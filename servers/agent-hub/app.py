"""Unified Hub — routes chat requests to Google (ADK), Ollama, or Azure OpenAI.

The provider is selected per-request via the `provider` field.
All three providers share the same conversation storage (conversation-hub).

Environment variables
---------------------
Common:
  MCP_SERVER_URL         MCP endpoint (default http://localhost:3002/mcp)
  CONVERSATION_HUB_URL   conversation-hub base URL (default http://localhost:3300)
  DEFAULT_INSTRUCTION    system prompt override
  MAX_TOOL_ITERATIONS    max tool-call rounds (default 10)
  TOOL_REFRESH_SECONDS   MCP tool cache TTL (default 300)
  ALLOW_ORIGINS          CORS origins (default *)
  PORT                   listen port (default 3100)

Google:
  GOOGLE_API_KEY / GOOGLE_GENAI_API_KEY
  GOOGLE_VERTEX_PROJECT / VERTEX_PROJECT
  GOOGLE_VERTEX_LOCATION / VERTEX_LOCATION
  AGENT_MODEL_GOOGLE     default Google model (default gemini-2.5-flash)

Ollama:
  OLLAMA_HOST            Ollama base URL (default http://localhost:11434)
  AGENT_MODEL_OLLAMA     default Ollama model (default llama3.1:8b)
  MODEL_REFRESH_SECONDS  Ollama model list cache TTL (default 60)

Azure:
  AZURE_OPENAI_ENDPOINT
  AZURE_OPENAI_API_KEY
  AZURE_OPENAI_DEPLOYMENT  deployment name (default gpt-4o)
  AZURE_OPENAI_API_VERSION (default 2024-12-01-preview)
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import ALLOW_ORIGINS, PORT
from routes.chat import router as chat_router
from routes.conversations import router as conversations_router
from routes.health import router as health_router
from routes.settings import router as settings_router

app = FastAPI(title="Todea Hub")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)
app.include_router(conversations_router)
app.include_router(settings_router)
app.include_router(health_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=PORT, reload=False)
