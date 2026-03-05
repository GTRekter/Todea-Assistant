"""
Helm Agent — HTTP wrapper around the helm and kubectl CLIs.

All domain-specific knowledge (chart names, release names, values) lives in
the callers. This service is purely a subprocess bridge.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import PORT, ALLOW_ORIGINS
from routes.health import router as health_router
from routes.helm import router as helm_router
from routes.kubectl import router as kubectl_router

app = FastAPI(title="Helm Agent")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(helm_router)
app.include_router(kubectl_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
