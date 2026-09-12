from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from backend.api.cameras import router as cameras_router
from backend.api.health import router as health_router
from backend.api.machines import router as machines_router
from backend.api.operations import router as operations_router
from backend.api.vision import router as vision_router
from backend.api.zones import router as zones_router
from backend.api.events import router as events_router
from backend.cameras.manager import CameraManager
from backend.cameras.repository import CameraRepository
from backend.config import get_settings
from backend.database.db import initialize_database
from backend.logging_config import configure_logging
from backend.vision.engine import VisionEngine


startup_settings = get_settings()
configure_logging(startup_settings)
logger = logging.getLogger("campex")



@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    settings = get_settings()
    app_instance.state.settings = settings
    database_path = initialize_database(settings)
    repository = CameraRepository(settings)
    manager = CameraManager(settings, repository)
    vision_engine = VisionEngine(settings, manager)
    app_instance.state.camera_manager = manager
    app_instance.state.vision_engine = vision_engine
    logger.info(
        "CAMPEX started",
        extra={
            "environment": settings.environment,
            "database_path": str(database_path),
        },
    )
    manager.start_enabled_cameras()
    try:
        yield
    finally:
        vision_engine.shutdown()
        manager.shutdown()


app = FastAPI(
    title="CAMPEX",
    version=startup_settings.version,
    description="CAMPEX Sprint 3 Foundation API",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=startup_settings.frontend_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)


@app.middleware("http")
async def api_token_guard(request: Request, call_next):
    settings = getattr(request.app.state, "settings", startup_settings)
    token = settings.api_token
    if (
        token
        and request.url.path.startswith("/api/v1")
        and request.url.path != "/api/v1/health"
        and request.headers.get("X-CAMPEX-Token") != token
    ):
        return JSONResponse(
            {"detail": "Token de API ausente ou inválido."},
            status_code=401,
        )
    return await call_next(request)

app.include_router(health_router)
app.include_router(cameras_router)
app.include_router(vision_router)
app.include_router(zones_router)
app.include_router(machines_router)
app.include_router(events_router)
app.include_router(operations_router)
