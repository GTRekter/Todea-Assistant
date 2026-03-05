"""
Kubernetes Agent — HTTP wrapper around kubectl diagnostics.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import ALLOW_ORIGINS, PORT
from routes.health import router as health_router
from routes.kubernetes import router as kubernetes_router

app = FastAPI(title="Kubernetes Agent")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(kubernetes_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
