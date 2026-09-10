from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.cameras import router as cameras_router
from backend.api.health import router as health_router
from backend.api.vision import router as vision_router
from backend.cameras.manager import CameraManager
from backend.cameras.repository import CameraRepository
from backend.config import get_settings
from backend.database.db import initialize_database
from backend.logging_config import configure_logging
from backend.vision import VisionEngine


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
    description="CAMPEX Sprint 2 Vision Core API",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=startup_settings.frontend_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(cameras_router)
app.include_router(vision_router)
