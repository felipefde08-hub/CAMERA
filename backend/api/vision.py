from __future__ import annotations

import asyncio

import cv2
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from backend.cameras.manager import CameraManager
from backend.cameras.repository import CameraRepository
from backend.config import get_settings
from backend.vision.engine import VisionEngine
from backend.vision.overlay import draw_tracked_objects


router = APIRouter(prefix="/api/v1/cameras", tags=["vision"])


def get_repository() -> CameraRepository:
    return CameraRepository(get_settings())


def get_camera_manager(request: Request) -> CameraManager:
    return request.app.state.camera_manager


def get_vision_engine(request: Request) -> VisionEngine:
    return request.app.state.vision_engine


def ensure_camera(camera_id: str, repository: CameraRepository) -> None:
    if repository.get(camera_id) is None:
        raise HTTPException(status_code=404, detail="Camera not found.")


@router.post("/{camera_id}/vision/start")
def start_vision(
    camera_id: str,
    repository: CameraRepository = Depends(get_repository),
    engine: VisionEngine = Depends(get_vision_engine),
) -> dict:
    ensure_camera(camera_id, repository)
    return engine.start_session(camera_id)


@router.post("/{camera_id}/vision/restart")
def restart_vision(
    camera_id: str,
    repository: CameraRepository = Depends(get_repository),
    engine: VisionEngine = Depends(get_vision_engine),
) -> dict:
    ensure_camera(camera_id, repository)
    return engine.restart_session(camera_id)


@router.post("/{camera_id}/vision/stop")
def stop_vision(
    camera_id: str,
    repository: CameraRepository = Depends(get_repository),
    engine: VisionEngine = Depends(get_vision_engine),
) -> dict:
    ensure_camera(camera_id, repository)
    return engine.stop_session(camera_id)


@router.get("/{camera_id}/vision/status")
def vision_status(
    camera_id: str,
    repository: CameraRepository = Depends(get_repository),
    engine: VisionEngine = Depends(get_vision_engine),
) -> dict:
    ensure_camera(camera_id, repository)
    return engine.status(camera_id)


@router.get("/{camera_id}/vision/objects")
def vision_objects(
    camera_id: str,
    repository: CameraRepository = Depends(get_repository),
    engine: VisionEngine = Depends(get_vision_engine),
) -> list[dict]:
    ensure_camera(camera_id, repository)
    return [tracked.as_dict() for tracked in engine.objects(camera_id)]


@router.get("/{camera_id}/stream")
async def camera_stream(
    request: Request,
    camera_id: str,
    repository: CameraRepository = Depends(get_repository),
    manager: CameraManager = Depends(get_camera_manager),
    engine: VisionEngine = Depends(get_vision_engine),
) -> StreamingResponse:
    ensure_camera(camera_id, repository)

    async def generate():
        while True:
            if await request.is_disconnected():
                break
            frame, _ = manager.latest_frame(camera_id)
            if frame is None:
                frame = _blank_frame("Aguardando frame da camera")
            objects = engine.objects(camera_id)
            if objects:
                frame = draw_tracked_objects(frame, objects)
            ok, encoded = cv2.imencode(".jpg", frame)
            if ok:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n"
                    + encoded.tobytes()
                    + b"\r\n"
                )
            await asyncio.sleep(0.05)

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


def _blank_frame(message: str):
    import numpy as np

    frame = np.zeros((480, 854, 3), dtype=np.uint8)
    cv2.putText(
        frame,
        message,
        (32, 240),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (220, 220, 220),
        2,
        cv2.LINE_AA,
    )
    return frame
