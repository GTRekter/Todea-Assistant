import asyncio
import json
import os
import subprocess
import time
from typing import Any, Dict, List, Optional
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import APIRouter, Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator
from google.adk.agents import Agent as GoogleAgent
from google.adk.runners import Runner as GoogleRunner
from google.adk.sessions.in_memory_session_service import InMemorySessionService as GoogleInMemorySessionService
from google.adk.tools.mcp_tool import MCPToolset as GoogleMCPToolset
from google.adk.tools.mcp_tool import StreamableHTTPConnectionParams as GoogleStreamableHTTPConnectionParams
from google.genai import types

load_dotenv()

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:3002/mcp")
KUBE_NAMESPACE = os.getenv("KUBE_NAMESPACE", "todea")
KUBE_SECRET_NAME = os.getenv("KUBE_SECRET_NAME", "todea-api-keys")

# Runtime-mutable Kubernetes server URL. Empty string = use default kubeconfig (local cluster).
_kube_server: str = os.getenv("KUBE_SERVER", "")
PORT = int(os.environ.get("PORT", "3100"))
GOOGLE_MODEL = os.getenv("AGENT_MODEL_GOOGLE", "gemini-2.5-flash")
GOOGLE_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
]
PROVIDER_ID = "google"
APP_NAME = "todea-google"
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GOOGLE_GENAI_API_KEY")
GOOGLE_VERTEX_PROJECT = os.getenv("GOOGLE_VERTEX_PROJECT") or os.getenv("VERTEX_PROJECT")
GOOGLE_VERTEX_LOCATION = os.getenv("GOOGLE_VERTEX_LOCATION") or os.getenv("VERTEX_LOCATION")

DEFAULT_INSTRUCTION = (
    "You are the todea workspace assistant. Think out loud, then call MCP tools "
    "to answer the user's request about channels, hot topics, and workspace settings. "
    "Return a concise final answer after tools complete."
)

app = FastAPI(title="Agent Hub Service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
            # Keep model in sync with latest selection.
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


session_service: Optional[Any] = None
_runners: Dict[str, Any] = {}
lock = asyncio.Lock()
conversation_lock = asyncio.Lock()
conversation_store = ConversationStore()


def ensure_google_credentials() -> None:
    # The Google GenAI client requires either an API key or Vertex AI project + location.
    if not GOOGLE_API_KEY and not (GOOGLE_VERTEX_PROJECT and GOOGLE_VERTEX_LOCATION):
        raise RuntimeError(
            "Google credentials are missing. Set GOOGLE_API_KEY (or GOOGLE_GENAI_API_KEY) "
            "or configure GOOGLE_VERTEX_PROJECT and GOOGLE_VERTEX_LOCATION."
        )


def build_agent(model: str) -> Any:
    ensure_google_credentials()
    tool_set = GoogleMCPToolset(
        connection_params=GoogleStreamableHTTPConnectionParams(url=MCP_SERVER_URL.rstrip("/"))
    )
    return GoogleAgent(
        name=f"{PROVIDER_ID}_agent",
        model=model,
        description="Google agent that calls MCP tools",
        instruction=DEFAULT_INSTRUCTION,
        tools=[tool_set],
    )


def get_runner(model: str) -> Any:
    global session_service, _runners
    if session_service is None:
        session_service = GoogleInMemorySessionService()
    if model not in _runners:
        agent = build_agent(model)
        _runners[model] = GoogleRunner(
            app_name=APP_NAME,
            agent=agent,
            session_service=session_service,
        )
    return _runners[model]


async def ensure_session(session_id: str) -> None:
    existing = await session_service.get_session(
        app_name=APP_NAME,
        user_id="web-ui",
        session_id=session_id,
    )
    if existing:
        return
    await session_service.create_session(
        app_name=APP_NAME,
        user_id="web-ui",
        session_id=session_id,
    )


def content_to_text(content: Optional[types.Content]) -> str:
    if not content:
        return ""
    parts = []
    if content.parts:
        for part in content.parts:
            if getattr(part, "text", None):
                parts.append(part.text)
            elif getattr(part, "function_call", None):
                parts.append(f"[function call] {part.function_call.name}")
            elif getattr(part, "function_response", None):
                fn = part.function_response
                parts.append(f"[function response] {fn.name}: {fn.response}")
            elif getattr(part, "code_execution_result", None):
                result = part.code_execution_result
                output = getattr(result, "output", None) or getattr(result, "stdout", None)
                if output:
                    parts.append(str(output))
    return "\n".join([p for p in parts if p]) or (getattr(content, "text", "") or "")


async def run_agent_chat(message: str, session_id: str, model: str) -> str:
    runner = get_runner(model)
    await ensure_session(session_id)

    final_response = ""
    user_message = types.Content(role="user", parts=[types.Part(text=message)])

    async for event in runner.run_async(
        user_id="web-ui",
        session_id=session_id,
        new_message=user_message,
    ):
        if event.author != "web-ui" and event.is_final_response():
            final_response = content_to_text(event.content) or final_response

    return final_response or "The agent did not return any text."


@app.get("/models")
async def list_models() -> Dict[str, Any]:
    return {"models": GOOGLE_MODELS, "default": GOOGLE_MODEL}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    message = (request.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="A message is required.")

    model = (request.model or GOOGLE_MODEL).strip() or GOOGLE_MODEL
    if model not in GOOGLE_MODELS:
        raise HTTPException(status_code=400, detail=f"Unknown model '{model}'. Available: {GOOGLE_MODELS}")

    session_id = (request.session_id or f"default-{PROVIDER_ID}").strip() or f"default-{PROVIDER_ID}"

    async with conversation_lock:
        conversation_store.ensure(session_id, model=model, title=None)

    try:
        get_runner(model)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    async with lock:
        content = await run_agent_chat(message, session_id, model)

    async with conversation_lock:
        conversation_store.append_message(session_id, "user", message)
        conversation_store.append_message(session_id, "assistant", content)

    return ChatResponse(content=content, provider=PROVIDER_ID, session_id=session_id)


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------


def _conversation_not_found(conversation_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"Conversation '{conversation_id}' not found.")


@app.get("/conversations", response_model=ConversationListResponse)
async def list_conversations() -> ConversationListResponse:
    async with conversation_lock:
        summaries = [
            ConversationSummary(**c)
            for c in conversation_store.list()
        ]
    return ConversationListResponse(conversations=summaries)


@app.post("/conversations", response_model=Conversation)
async def create_conversation(request: ConversationCreateRequest) -> Conversation:
    model = (request.model or GOOGLE_MODEL).strip() or GOOGLE_MODEL
    if model not in GOOGLE_MODELS:
        raise HTTPException(status_code=400, detail=f"Unknown model '{model}'. Available: {GOOGLE_MODELS}")

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


@app.get("/healthz")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Settings — write/read Kubernetes secrets
# ---------------------------------------------------------------------------

class SettingsRequest(BaseModel):
    google_api_key: str = Field(..., min_length=1)


class SettingsResponse(BaseModel):
    status: str
    message: str


def _kubectl(*args: str, stdin: Optional[str] = None, timeout: int = 30) -> subprocess.CompletedProcess:
    cmd = ["kubectl"]
    if _kube_server:
        cmd += ["--server", _kube_server]
    cmd += list(args)
    try:
        return subprocess.run(
            cmd,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="kubectl not found. Ensure it is installed and on $PATH.")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="kubectl command timed out.")


@app.post("/settings", response_model=SettingsResponse)
async def save_settings(request: SettingsRequest) -> SettingsResponse:
    ns_result = _kubectl("get", "namespace", KUBE_NAMESPACE, "--ignore-not-found", "-o", "name")
    if not ns_result.stdout.strip():
        create_result = _kubectl("create", "namespace", KUBE_NAMESPACE)
        if create_result.returncode != 0:
            raise HTTPException(status_code=500, detail=create_result.stderr.strip() or "Failed to create namespace.")
    manifest = json.dumps({
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": KUBE_SECRET_NAME, "namespace": KUBE_NAMESPACE},
        "stringData": {"GOOGLE_API_KEY": request.google_api_key},
    })
    result = _kubectl("apply", "-f", "-", stdin=manifest)
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=result.stderr.strip() or "kubectl apply failed.")
    return SettingsResponse(status="ok", message=result.stdout.strip())


@app.get("/settings/status")
async def settings_status() -> Dict[str, Any]:
    result = _kubectl(
        "get", "secret", KUBE_SECRET_NAME,
        "-n", KUBE_NAMESPACE,
        "--ignore-not-found", "-o", "name",
    )
    return {"exists": bool(result.stdout.strip())}


class ClusterSettingsRequest(BaseModel):
    kube_server: str = ""


class ClusterSettingsResponse(BaseModel):
    kube_server: str


@app.get("/settings/cluster", response_model=ClusterSettingsResponse)
async def get_cluster_settings() -> ClusterSettingsResponse:
    return ClusterSettingsResponse(kube_server=_kube_server)


@app.post("/settings/cluster", response_model=ClusterSettingsResponse)
async def save_cluster_settings(request: ClusterSettingsRequest) -> ClusterSettingsResponse:
    global _kube_server
    _kube_server = (request.kube_server or "").strip()
    return ClusterSettingsResponse(kube_server=_kube_server)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("servers.agent-hub.app:app", host="0.0.0.0", port=PORT, reload=False)
