from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any

from backend.cameras.base import CameraConfig, CameraSource
from backend.cameras.factory import create_camera_source
from backend.cameras.health import CameraHealth, CameraStatus, utc_now
from backend.cameras.models import Camera
from backend.cameras.repository import CameraRepository
from backend.config import Settings


logger = logging.getLogger("campex.cameras.manager")


class CameraWorker:
    def __init__(
        self,
        camera: Camera,
        settings: Settings,
        source: CameraSource | None = None,
    ) -> None:
        self.camera = camera
        self.settings = settings
        self.source = source or create_camera_source(
            CameraConfig(
                id=camera.id,
                source_type=camera.source_type,
                source_uri=camera.source_uri,
            ),
            settings=self.settings,
        )
        self._stop = threading.Event()
        self._latest_frame: Any | None = None
        self._latest_frame_at: datetime | None = None
        self._frame_lock = threading.Lock()
        self._thread = threading.Thread(
            target=self._run,
            name=f"campex-camera-{camera.id}",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.source.close()
        if self._thread.is_alive():
            self._thread.join(timeout=2)

    def health(self) -> CameraHealth:
        health = self.source.health()
        if (
            health.status == CameraStatus.ONLINE
            and health.last_successful_frame is not None
            and (utc_now() - health.last_successful_frame).total_seconds()
            > self.settings.camera_stale_seconds
        ):
            health.status = CameraStatus.DEGRADED
            health.last_error = "No recent valid frame received."
        return health

    def latest_frame(self) -> tuple[Any | None, datetime | None]:
        with self._frame_lock:
            frame = self._latest_frame.copy() if self._latest_frame is not None else None
            return frame, self._latest_frame_at

    def _run(self) -> None:
        consecutive_failures = 0
        try:
            if not self.source.connect():
                time.sleep(self.settings.camera_reconnect_seconds)

            while not self._stop.is_set():
                result = self.source.read()
                if result.success:
                    with self._frame_lock:
                        self._latest_frame = (
                            result.frame.copy()
                            if hasattr(result.frame, "copy")
                            else result.frame
                        )
                        self._latest_frame_at = utc_now()
                    consecutive_failures = 0
                    time.sleep(0.02)
                    continue

                consecutive_failures += 1
                health = self.source.health()
                if consecutive_failures >= self.settings.camera_read_failure_limit:
                    health.status = CameraStatus.DEGRADED
                    logger.warning(
                        "Camera status transition",
                        extra={
                            "camera_id": self.camera.id,
                            "status": CameraStatus.DEGRADED.value,
                            "error": result.error,
                        },
                    )
                    self.source.reconnect()
                    consecutive_failures = 0
                    time.sleep(self.settings.camera_reconnect_seconds)
                else:
                    time.sleep(0.2)
        except Exception as exc:
            health = self.source.health()
            health.status = CameraStatus.OFFLINE
            health.last_error = str(exc)
            logger.exception("Camera worker failed", extra={"camera_id": self.camera.id})
        finally:
            self.source.close()


class CameraManager:
    def __init__(self, settings: Settings, repository: CameraRepository) -> None:
        self.settings = settings
        self.repository = repository
        self._workers: dict[str, CameraWorker] = {}
        self._lock = threading.Lock()

    def start_enabled_cameras(self) -> None:
        for camera in self.repository.list():
            if camera.enabled:
                self.start_camera(camera)

    def start_camera(self, camera: Camera) -> None:
        with self._lock:
            if camera.id in self._workers:
                return
            worker = CameraWorker(camera, self.settings)
            self._workers[camera.id] = worker
            worker.start()

    def stop_camera(self, camera_id: str) -> None:
        with self._lock:
            worker = self._workers.pop(camera_id, None)
        if worker:
            worker.stop()

    def restart_camera(self, camera: Camera) -> None:
        self.stop_camera(camera.id)
        if camera.enabled:
            self.start_camera(camera)

    def health(self, camera: Camera) -> CameraHealth:
        with self._lock:
            worker = self._workers.get(camera.id)
        if worker:
            return worker.health()
        return CameraHealth(camera_id=camera.id, status=CameraStatus.OFFLINE)

    def camera_health(self, camera_id: str) -> CameraHealth:
        with self._lock:
            worker = self._workers.get(camera_id)
        if worker:
            return worker.health()
        return CameraHealth(camera_id=camera_id, status=CameraStatus.OFFLINE)

    def latest_frame(self, camera_id: str) -> tuple[Any | None, datetime | None]:
        with self._lock:
            worker = self._workers.get(camera_id)
        if worker is None:
            return None, None
        return worker.latest_frame()

    def is_running(self, camera_id: str) -> bool:
        with self._lock:
            return camera_id in self._workers

    def shutdown(self) -> None:
        with self._lock:
            camera_ids = list(self._workers)
        for camera_id in camera_ids:
            self.stop_camera(camera_id)


def test_camera_connection(camera: Camera, settings: Settings) -> dict:
    source = create_camera_source(
        CameraConfig(
            id=camera.id,
            source_type=camera.source_type,
            source_uri=camera.source_uri,
        ),
        settings=settings,
    )
    deadline = time.monotonic() + settings.camera_test_timeout_seconds
    try:
        if not source.connect():
            health = source.health()
            return {
                "success": False,
                "status": health.status.value,
                "error": health.last_error or "Source could not provide a valid frame.",
                "resolution": None,
            }

        while time.monotonic() < deadline:
            result = source.read()
            if result.success:
                health = source.health()
                resolution = (
                    health.resolution
                    and {
                        "width": health.resolution.width,
                        "height": health.resolution.height,
                    }
                )
                return {
                    "success": True,
                    "status": CameraStatus.ONLINE.value,
                    "error": None,
                    "resolution": resolution,
                }
            time.sleep(0.05)

        health = source.health()
        return {
            "success": False,
            "status": CameraStatus.OFFLINE.value,
            "error": health.last_error or "No valid frame received before timeout.",
            "resolution": None,
        }
    except Exception as exc:
        logger.exception("Camera connection test failed", extra={"camera_id": camera.id})
        return {
            "success": False,
            "status": CameraStatus.OFFLINE.value,
            "error": str(exc),
            "resolution": None,
        }
    finally:
        source.close()
