from __future__ import annotations

from fastapi import APIRouter

from backend.config import get_settings


router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ok",
        "service": settings.service_name,
        "version": settings.version,
    }
