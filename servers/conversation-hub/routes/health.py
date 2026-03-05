from typing import Dict

from fastapi import APIRouter

router = APIRouter()


@router.get("/healthz")
async def health() -> Dict[str, str]:
    return {"status": "ok"}
