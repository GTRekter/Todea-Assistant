from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import ALLOW_ORIGINS, PORT
from routes.conversations import router as conversations_router
from routes.health import router as health_router

app = FastAPI(title="Conversation Hub Service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(conversations_router)
app.include_router(health_router)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=PORT, reload=False)
