"""
OpenSSL Agent — HTTP wrapper around certificate generation and inspection tools.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import PORT, ALLOW_ORIGINS
from routes.health import router as health_router
from routes.certificates import router as certificates_router

app = FastAPI(title="OpenSSL Agent")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(certificates_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
