import asyncio
import os
import time
from typing import Any, Dict, List, Optional
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from ollama import AsyncClient, ResponseError

load_dotenv()

# Configuration ---------------------------------------------------------------
ALLOW_ORIGINS = [origin.strip() for origin in os.getenv("ALLOW_ORIGINS", "*").split(",") if origin.strip()]
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("AGENT_MODEL_OLLAMA", os.getenv("OLLAMA_MODEL", "llama3.2"))
PORT = int(os.getenv("PORT", "3200"))
MODEL_REFRESH_SECONDS = int(os.getenv("MODEL_REFRESH_SECONDS", "60"))
PROVIDER_ID = "ollama"
DEFAULT_INSTRUCTION = os.getenv(
    "DEFAULT_INSTRUCTION",
    (
        "You are the todea workspace assistant. Think out loud, then answer concisely. "
        "If the user asks about Linkerd or Kubernetes, give actionable steps and sample commands."
    ),
)

app = FastAPI(title="Ollama Hub Service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Models ---------------------------------------------------------------------
class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    model: Optional[str] = None


class ChatResponse(BaseModel):
    content: str
    provider: str
    session_id: str


class ConversationMessage(BaseModel):
    role: str
    content: str
    timestamp: float


class Conversation(BaseModel):
    id: str
    title: str
    model: str
    created_at: float
    updated_at: float
    message_count: int = 0
    messages: List[ConversationMessage] = Field(default_factory=list)


class ConversationSummary(BaseModel):
    id: str
    title: str
    model: str
    created_at: float
    updated_at: float
    message_count: int = 0


class ConversationListResponse(BaseModel):
    conversations: List[ConversationSummary]


class ConversationCreateRequest(BaseModel):
    title: Optional[str] = None
    model: Optional[str] = None


class ConversationUpdateRequest(BaseModel):
    title: str = Field(..., min_length=1)


class SettingsResponse(BaseModel):
    status: str
    message: str


class ClusterSettingsRequest(BaseModel):
    kube_server: str = ""


class ClusterSettingsResponse(BaseModel):
    kube_server: str


# State ----------------------------------------------------------------------
class ConversationStore:
    """
    In-memory store for chat conversations and their message history.
    Keeps lightweight metadata and full message lists for retrieval.
    """

    def __init__(self) -> None:
        self.conversations: Dict[str, Dict[str, Any]] = {}
        self.messages: Dict[str, List[Dict[str, Any]]] = {}
        self._counter = 1

    def _now(self) -> float:
        return time.time()

    def _default_title(self) -> str:
        title = f"Conversation {self._counter}"
        self._counter += 1
        return title

    def create(self, title: Optional[str], model: str, conversation_id: Optional[str] = None) -> Dict[str, Any]:
        conv_id = conversation_id or str(uuid4())
        now = self._now()
        conversation = {
            "id": conv_id,
            "title": (title or "").strip() or self._default_title(),
            "model": model,
            "created_at": now,
            "updated_at": now,
            "message_count": 0,
        }
        self.conversations[conv_id] = conversation
        self.messages[conv_id] = []
        return conversation

    def ensure(self, conversation_id: str, model: str, title: Optional[str] = None) -> Dict[str, Any]:
        existing = self.conversations.get(conversation_id)
        if existing:
            existing["model"] = model
            return existing
        return self.create(title=title, model=model, conversation_id=conversation_id)

    def list(self) -> List[Dict[str, Any]]:
        return sorted(self.conversations.values(), key=lambda c: c["updated_at"], reverse=True)

    def get(self, conversation_id: str) -> Dict[str, Any]:
        conversation = self.conversations.get(conversation_id)
        if not conversation:
            raise KeyError(conversation_id)
        return conversation

    def update_title(self, conversation_id: str, title: str) -> Dict[str, Any]:
        conversation = self.get(conversation_id)
        conversation["title"] = title.strip() or conversation["title"]
        conversation["updated_at"] = self._now()
        return conversation

    def delete(self, conversation_id: str) -> None:
        self.conversations.pop(conversation_id, None)
        self.messages.pop(conversation_id, None)

    def append_message(self, conversation_id: str, role: str, content: str) -> Dict[str, Any]:
        conversation = self.get(conversation_id)
        entry = {
            "role": role,
            "content": content,
            "timestamp": self._now(),
        }
        self.messages.setdefault(conversation_id, []).append(entry)
        conversation["updated_at"] = entry["timestamp"]
        conversation["message_count"] = len(self.messages.get(conversation_id, []))
        return entry

    def detail(self, conversation_id: str) -> Dict[str, Any]:
        conversation = self.get(conversation_id)
        return {
            **conversation,
            "messages": list(self.messages.get(conversation_id, [])),
        }


conversation_store = ConversationStore()
conversation_lock = asyncio.Lock()
chat_lock = asyncio.Lock()
_model_cache: Dict[str, Any] = {"names": [], "ts": 0.0}


# Helpers --------------------------------------------------------------------
async def _list_models(force: bool = False) -> List[str]:
    now = time.time()
    if not _model_cache["names"] or force or (now - _model_cache["ts"] > MODEL_REFRESH_SECONDS):
        try:
            async with AsyncClient(host=OLLAMA_HOST) as client:
                response = await client.list()
        except ResponseError as exc:  # type: ignore
            raise HTTPException(status_code=502, detail=f"Ollama list failed: {exc}") from exc
        except Exception as exc:  # pragma: no cover - defensive
            raise HTTPException(status_code=502, detail=f"Failed to reach Ollama at {OLLAMA_HOST}: {exc}") from exc

        models = response.get("models", []) if isinstance(response, dict) else []
        names = []
        for item in models:
            name = item.get("name") or item.get("model")
            if name:
                names.append(name)
        if not names:
            raise HTTPException(status_code=400, detail="No models installed on the Ollama host. Use 'ollama pull <model>'.")
        _model_cache["names"] = names
        _model_cache["ts"] = now
    return _model_cache["names"]


def _history_for_session(session_id: str) -> List[Dict[str, str]]:
    messages = conversation_store.messages.get(session_id, [])
    return [{"role": m["role"], "content": m["content"]} for m in messages]


async def run_ollama_chat(message: str, session_id: str, model: str) -> str:
    history = _history_for_session(session_id)
    payload = [{"role": "system", "content": DEFAULT_INSTRUCTION}] + history + [
        {"role": "user", "content": message}
    ]

    try:
        async with AsyncClient(host=OLLAMA_HOST) as client:
            result = await client.chat(
                model=model,
                messages=payload,
                stream=False,
            )
    except ResponseError as exc:  # type: ignore
        raise HTTPException(status_code=502, detail=f"Ollama chat failed: {exc}") from exc
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=502, detail=f"Failed to reach Ollama at {OLLAMA_HOST}: {exc}") from exc

    if not isinstance(result, dict) or "message" not in result:
        raise HTTPException(status_code=500, detail="Unexpected response from Ollama.")

    content = result.get("message", {}).get("content", "")
    if not content:
        raise HTTPException(status_code=500, detail="The Ollama model did not return any text.")
    return str(content)


# Routes ---------------------------------------------------------------------
@app.get("/models")
async def list_models() -> Dict[str, Any]:
    names = await _list_models()
    default = OLLAMA_MODEL if OLLAMA_MODEL in names else names[0]
    return {"models": names, "default": default}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    message = (request.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="A message is required.")

    available_models = await _list_models()
    model = (request.model or OLLAMA_MODEL).strip() or OLLAMA_MODEL
    if available_models and model not in available_models:
        raise HTTPException(status_code=400, detail=f"Unknown model '{model}'. Available: {available_models}")

    session_id = (request.session_id or f"default-{PROVIDER_ID}").strip() or f"default-{PROVIDER_ID}"

    async with conversation_lock:
        conversation_store.ensure(session_id, model=model, title=None)

    async with chat_lock:
        content = await run_ollama_chat(message, session_id, model)

    async with conversation_lock:
        conversation_store.append_message(session_id, "user", message)
        conversation_store.append_message(session_id, "assistant", content)

    return ChatResponse(content=content, provider=PROVIDER_ID, session_id=session_id)


# Conversations --------------------------------------------------------------

def _conversation_not_found(conversation_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"Conversation '{conversation_id}' not found.")


@app.get("/conversations", response_model=ConversationListResponse)
async def list_conversations() -> ConversationListResponse:
    async with conversation_lock:
        summaries = [ConversationSummary(**c) for c in conversation_store.list()]
    return ConversationListResponse(conversations=summaries)


@app.post("/conversations", response_model=Conversation)
async def create_conversation(request: ConversationCreateRequest) -> Conversation:
    available_models = await _list_models()
    model = (request.model or OLLAMA_MODEL).strip() or OLLAMA_MODEL
    if available_models and model not in available_models:
        raise HTTPException(status_code=400, detail=f"Unknown model '{model}'. Available: {available_models}")

    async with conversation_lock:
        conversation = conversation_store.create(request.title, model=model)
        detail = conversation_store.detail(conversation["id"])
    return Conversation(**detail)


@app.get("/conversations/{conversation_id}", response_model=Conversation)
async def get_conversation(conversation_id: str) -> Conversation:
    async with conversation_lock:
        try:
            detail = conversation_store.detail(conversation_id)
        except KeyError:
            raise _conversation_not_found(conversation_id) from None
    return Conversation(**detail)


@app.patch("/conversations/{conversation_id}", response_model=Conversation)
async def update_conversation(conversation_id: str, request: ConversationUpdateRequest) -> Conversation:
    async with conversation_lock:
        try:
            conversation_store.update_title(conversation_id, request.title)
            detail = conversation_store.detail(conversation_id)
        except KeyError:
            raise _conversation_not_found(conversation_id) from None
    return Conversation(**detail)


@app.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str) -> Dict[str, str]:
    async with conversation_lock:
        if conversation_id not in conversation_store.conversations:
            raise _conversation_not_found(conversation_id)
        conversation_store.delete(conversation_id)
    return {"status": "deleted", "id": conversation_id}


# Health ---------------------------------------------------------------------
@app.get("/healthz")
async def health() -> Dict[str, Any]:
    try:
        names = await _list_models()
    except HTTPException as exc:
        raise exc
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok", "models": len(names)}


# Settings stubs (keeps the React settings page working) ---------------------
@app.post("/settings", response_model=SettingsResponse)
async def save_settings() -> SettingsResponse:
    return SettingsResponse(status="noop", message="No API key required for Ollama.")


@app.get("/settings/status")
async def settings_status() -> Dict[str, Any]:
    return {"exists": True}


@app.get("/settings/cluster", response_model=ClusterSettingsResponse)
async def get_cluster_settings() -> ClusterSettingsResponse:
    # Cluster settings are not used for the Ollama hub.
    return ClusterSettingsResponse(kube_server="")


@app.post("/settings/cluster", response_model=ClusterSettingsResponse)
async def save_cluster_settings(request: ClusterSettingsRequest = Body(...)) -> ClusterSettingsResponse:
    # Accept and echo the value to satisfy the UI; it is not used by the service.
    return ClusterSettingsResponse(kube_server=(request.kube_server or "").strip())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=PORT, reload=False)
