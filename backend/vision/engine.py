from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Callable

from backend.cameras.manager import CameraManager
from backend.config import Settings
from backend.vision.detector import DetectorUnavailable, VisionDetector, create_detector
from backend.vision.models import TrackedObject, VisionMetrics
from backend.vision.motion import MotionDetector, MotionResult
from backend.vision.tracker import ByteTrackTracker, ObjectTracker


logger = logging.getLogger("campex.vision.engine")


FrameProvider = Callable[[str], tuple[object | None, datetime | None]]


class VisionSession:
    def __init__(
        self,
        camera_id: str,
        settings: Settings,
        detector: VisionDetector,
        tracker: ObjectTracker | None = None,
    ) -> None:
        self.camera_id = camera_id
        self.settings = settings
        self.detector = detector
        self.tracker = tracker or ByteTrackTracker()
        self._motion = MotionDetector()
        self._frames_since_motion_skip = 0
        self._motion_full_scan_interval = 30
        self.status = "STARTING"
        self.error: str | None = None
        self.started_at = time.monotonic()
        self._last_frame_at: datetime | None = None
        self._last_processed_at = 0.0
        self._last_inference_ms: float | None = None
        self._last_frame_age_ms: float | None = None
        self._frames_processed = 0
        self._frames_dropped = 0
        self._objects: list[TrackedObject] = []
        self._lock = threading.Lock()

    def should_process(self, frame_at: datetime | None) -> bool:
        if frame_at is None:
            return False
        with self._lock:
            now = time.monotonic()
            if (now - self._last_processed_at) < (1 / self.settings.vision_fps):
                self._frames_dropped += 1
                return False
            self._last_frame_at = frame_at
            self._last_processed_at = now
            return True

    def process(self, frame: object, frame_at: datetime) -> None:
        frame_age_ms = max(
            0.0,
            (datetime.now(timezone.utc) - frame_at).total_seconds() * 1000,
        )
        if not self._motion.has_reference:
            self._motion.detect(frame)
            motion_result = MotionResult(True, 0, 0.0)
        else:
            motion_result = self._motion.detect(frame)
        if not motion_result.motion_detected:
            self._frames_since_motion_skip += 1
            if self._frames_since_motion_skip < self._motion_full_scan_interval:
                timestamp = datetime.now(timezone.utc)
                try:
                    objects = self.tracker.update(self.camera_id, [], timestamp)
                except Exception as exc:
                    self.fail(f"Tracker failure: {exc}")
                    raise
                with self._lock:
                    self.status = "RUNNING"
                    self.error = None
                    self._last_frame_at = frame_at
                    self._last_processed_at = time.monotonic()
                    self._last_frame_age_ms = frame_age_ms
                    self._frames_processed += 1
                    self._objects = objects
                return
            self._motion.reset()
            self._frames_since_motion_skip = 0

        timestamp = datetime.now(timezone.utc)
        try:
            detections, inference_ms = self.detector.detect(frame)
        except Exception as exc:
            self.fail(f"Detector failure: {exc}")
            raise

        try:
            objects = self.tracker.update(self.camera_id, detections, timestamp)
        except Exception as exc:
            self.fail(f"Tracker failure: {exc}")
            raise

        with self._lock:
            self.status = "RUNNING"
            self.error = None
            self._last_frame_at = frame_at
            self._last_processed_at = time.monotonic()
            self._last_inference_ms = inference_ms
            self._last_frame_age_ms = frame_age_ms
            self._frames_processed += 1
            self._objects = objects

    def fail(self, error: str) -> None:
        with self._lock:
            self.status = "ERROR"
            self.error = error

    def stop(self) -> None:
        with self._lock:
            self.status = "STOPPED"

    def restart(self) -> None:
        with self._lock:
            self.status = "STARTING"
            self.error = None
            self._last_frame_at = None
            self._last_processed_at = 0.0
            self._last_inference_ms = None
            self._last_frame_age_ms = None
            self._frames_processed = 0
            self._frames_dropped = 0
            self._objects = []
            self._frames_since_motion_skip = 0
            self._motion.reset()

    def objects(self) -> list[TrackedObject]:
        with self._lock:
            return list(self._objects)

    def as_status(
        self,
        camera_fps: float = 0.0,
        frames_received: int = 0,
        frames_dropped: int = 0,
    ) -> dict:
        with self._lock:
            effective_dropped = max(frames_dropped, self._frames_dropped)
            metrics = VisionMetrics(
                camera_fps=camera_fps,
                vision_fps=self.settings.vision_fps if self.status == "RUNNING" else 0.0,
                inference_ms=self._last_inference_ms,
                objects_detected=len(self._objects),
                device=self.detector.device,
                detector=self.detector.name,
                tracker=self.tracker.name,
                uptime=max(0.0, time.monotonic() - self.started_at),
                frames_received=frames_received,
                frames_processed=self._frames_processed,
                frames_dropped=effective_dropped,
                frame_age_ms=self._last_frame_age_ms,
            )
            return {
                "camera_id": self.camera_id,
                "status": self.status,
                "vision_status": self.status,
                "error": self.error,
                "metrics": metrics.as_dict(),
            }


class VisionEngine:
    def __init__(self, settings: Settings, camera_manager: CameraManager) -> None:
        self.settings = settings
        self.camera_manager = camera_manager
        self._detector: VisionDetector | None = None
        self._detector_loaded = False
        self._sessions: dict[str, VisionSession] = {}
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread = threading.Thread(
            target=self._run,
            name="campex-vision-engine",
            daemon=True,
        )
        self._thread.start()
        logger.info("[CAMPEX][VISION] Engine initialized")

    def shutdown(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2)
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            session.stop()

    def start_session(self, camera_id: str) -> dict:
        if not self.settings.vision_enabled:
            return self._disabled_status(camera_id)

        with self._lock:
            existing = self._sessions.get(camera_id)
            if existing is not None and existing.status != "STOPPED":
                return existing.as_status()

            try:
                detector = self._get_detector()
                self._ensure_detector_loaded(detector)
            except DetectorUnavailable as exc:
                detector = self._detector or create_detector(self.settings)
                session = VisionSession(camera_id, self.settings, detector)
                session.fail(str(exc))
                self._sessions[camera_id] = session
                return session.as_status()

            session = VisionSession(camera_id, self.settings, detector)
            self._sessions[camera_id] = session
            logger.info("[CAMPEX][VISION] Camera session started", extra={"camera_id": camera_id})
            return session.as_status()

    def stop_session(self, camera_id: str) -> dict:
        with self._lock:
            session = self._sessions.pop(camera_id, None)
        if session is None:
            return {"camera_id": camera_id, "status": "STOPPED", "error": None, "metrics": None}
        session.stop()
        logger.info("[CAMPEX][VISION] Camera session stopped", extra={"camera_id": camera_id})
        return session.as_status()

    def restart_session(self, camera_id: str) -> dict:
        with self._lock:
            existing = self._sessions.get(camera_id)
            if existing is None:
                self._sessions.pop(camera_id, None)
            else:
                existing.restart()
                return existing.as_status()

            if not self.settings.vision_enabled:
                return self._disabled_status(camera_id)

            try:
                detector = self._get_detector()
                self._ensure_detector_loaded(detector)
            except DetectorUnavailable as exc:
                detector = self._detector or create_detector(self.settings)
                session = VisionSession(camera_id, self.settings, detector)
                session.fail(str(exc))
                self._sessions[camera_id] = session
                return session.as_status()

            session = VisionSession(camera_id, self.settings, detector)
            self._sessions[camera_id] = session
            logger.info(
                "[CAMPEX][VISION] Camera session restarted",
                extra={"camera_id": camera_id},
            )
            return session.as_status()

    def status(self, camera_id: str) -> dict:
        if not self.settings.vision_enabled:
            return self._disabled_status(camera_id)
        with self._lock:
            session = self._sessions.get(camera_id)
        if session is None:
            return {"camera_id": camera_id, "status": "STOPPED", "error": None, "metrics": None}
        camera_fps = 0.0
        health = self.camera_manager.camera_health(camera_id)
        frame_stats = self.camera_manager.frame_stats(camera_id)
        if health.approximate_fps:
            camera_fps = health.approximate_fps
        status = session.as_status(
            camera_fps=camera_fps,
            frames_received=frame_stats.frames_received,
            frames_dropped=frame_stats.frames_replaced,
        )
        status["camera_status"] = health.status.value
        metrics = status.get("metrics") or {}
        status.update(
            {
                "detector": metrics.get("detector"),
                "tracker": metrics.get("tracker"),
                "device": metrics.get("device"),
                "capture_fps": metrics.get("camera_fps"),
                "vision_fps": metrics.get("vision_fps"),
                "inference_ms": metrics.get("inference_ms"),
                "frame_age_ms": metrics.get("frame_age_ms"),
                "frames_dropped": metrics.get("frames_dropped"),
                "objects": metrics.get("objects_detected"),
            }
        )
        return status

    def objects(self, camera_id: str) -> list[TrackedObject]:
        with self._lock:
            session = self._sessions.get(camera_id)
        return session.objects() if session else []

    def _get_detector(self) -> VisionDetector:
        if self._detector is None:
            self._detector = create_detector(self.settings)
            logger.info(
                "[CAMPEX][VISION] Detector configured",
                extra={"detector": self._detector.name, "device": self._detector.device},
            )
        return self._detector

    def _ensure_detector_loaded(self, detector: VisionDetector) -> None:
        if self._detector_loaded:
            return
        detector.load()
        self._detector_loaded = True

    def _run(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                sessions = list(self._sessions.values())
            for session in sessions:
                if session.status == "STOPPED":
                    continue
                if not self.camera_manager.is_running(session.camera_id):
                    session.fail("Camera is offline or not running.")
                    continue
                frame, frame_at = self.camera_manager.latest_frame(session.camera_id)
                if frame is None or not session.should_process(frame_at):
                    continue
                try:
                    session.process(frame, frame_at)
                except DetectorUnavailable as exc:
                    session.fail(str(exc))
                except Exception as exc:
                    logger.exception(
                        "[CAMPEX][VISION] Camera vision processing failed",
                        extra={"camera_id": session.camera_id},
                    )
                    if session.error is None:
                        session.fail(str(exc))
            time.sleep(0.02)

    @staticmethod
    def _disabled_status(camera_id: str) -> dict:
        return {
            "camera_id": camera_id,
            "status": "DISABLED",
            "error": "Vision is disabled by configuration.",
            "metrics": None,
        }
