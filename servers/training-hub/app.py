"""
training-hub — FastAPI service that manages the training pipeline on Kubernetes.

Endpoints:
  GET  /healthz                   — health check
  GET  /settings                  — models, repos, websites, github token status
  POST /settings/github-token     — save GitHub token as K8s Secret
  POST /scrape                    — create a scraper Job
  POST /train                     — create a trainer Job
  GET  /jobs                      — list active/recent training Jobs
  GET  /logs/{job_name}           — SSE stream of pod logs
  DELETE /jobs/{job_name}         — cancel a running Job
"""

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import ALLOW_ORIGINS, PORT
from routes.health import router as health_router
from routes.jobs import router as jobs_router
from routes.settings import router as settings_router

app = FastAPI(title="Training Hub")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(settings_router)
app.include_router(jobs_router)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
