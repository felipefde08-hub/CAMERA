from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Callable

from backend.cameras.manager import CameraManager
from backend.config import Settings
from backend.events import EventEngine, EventRepository
from backend.vision.detector import DetectorUnavailable, VisionDetector, create_detector
from backend.vision.models import TrackedObject, VisionMetrics
from backend.vision.motion import MotionEngine, MotionResult
from backend.vision.tracker import ByteTrackAdapter, ObjectTracker
from backend.zones import SpatialEngine, ZoneRepository
from backend.zones.models import Zone, Observation


logger = logging.getLogger("campex.vision.engine")


FrameProvider = Callable[[str], tuple[object | None, datetime | None]]


class VisionSession:
    def __init__(
        self,
        camera_id: str,
        settings: Settings,
        detector: VisionDetector,
        tracker: ObjectTracker | None = None,
        spatial_engine: SpatialEngine | None = None,
        event_engine: EventEngine | None = None,
        zone_repo: ZoneRepository | None = None,
        motion_engine: MotionEngine | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        utc_now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.camera_id = camera_id
        self.settings = settings
        self.detector = detector
        self.tracker = tracker or ByteTrackAdapter(
            lost_track_buffer=settings.vision_tracker_lost_buffer,
            frame_rate=settings.vision_fps,
        )
        self._motion = motion_engine or MotionEngine()
        self._spatial_engine = spatial_engine
        self._event_engine = event_engine
        self._zone_repo = zone_repo
        self._monotonic = monotonic
        self._utc_now = utc_now
        self._last_full_scan_at: float | None = None
        self.status = "STARTING"
        self.error: str | None = None
        self.started_at = self._monotonic()
        self._last_frame_at: datetime | None = None
        self._last_frame_id: int | None = None
        self._last_processed_at = 0.0
        self._last_inference_ms: float | None = None
        self._last_frame_age_ms: float | None = None
        self._last_motion_ms: float | None = None
        self._last_tracking_ms: float | None = None
        self._last_spatial_ms: float | None = None
        self._frames_processed = 0
        self._frames_dropped = 0
        self._motion_triggered_inferences = 0
        self._periodic_inferences = 0
        self._skipped_inferences = 0
        self._objects: list[TrackedObject] = []
        self._events: list = []
        self._component_errors: dict[str, str] = {}
        self._lock = threading.Lock()
        self._processing_lock = threading.Lock()

    def should_process(
        self,
        frame_at: datetime | None,
        frame_id: int | None = None,
    ) -> bool:
        if frame_at is None:
            return False
        with self._lock:
            if frame_id is not None:
                if self._last_frame_id is not None and frame_id <= self._last_frame_id:
                    return False
                unseen_frames = (
                    1
                    if self._last_frame_id is None
                    else max(1, frame_id - self._last_frame_id)
                )
            else:
                if self._last_frame_at is not None and frame_at <= self._last_frame_at:
                    return False
                unseen_frames = 1

        now = self._monotonic()
        if (now - self._last_processed_at) < (1 / self.settings.vision_fps):
            # Rate-limited: drop the frame but do NOT mark it as seen
            # so that the same frame can be reconsidered once the rate
            # window has elapsed.
            self._frames_dropped += unseen_frames
            return False
        self._frames_dropped += max(0, unseen_frames - 1)
        self._last_frame_id = frame_id
        self._last_frame_at = frame_at
        self._last_processed_at = now
        return True

    def process(self, frame: object, frame_at: datetime) -> None:
        if self.status == "ERROR":
            logger.info(
                "[CAMPEX][VISION] Session recovering",
                extra={"camera_id": self.camera_id, "state": "RECOVER"},
            )
            self.status = "RECOVER"

        frame_age_ms = max(
            0.0,
            (self._utc_now() - frame_at).total_seconds() * 1000,
        )
        now_monotonic = self._monotonic()
        motion_started = self._monotonic()
        try:
            if not self._motion.has_reference:
                self._motion.detect(frame)
                motion_result = MotionResult(True, 0, 0.0)
            else:
                motion_result = self._motion.detect(frame)
            self._component_errors.pop("motion", None)
        except Exception as exc:
            motion_result = MotionResult(True, 0, 0.0)
            self._component_errors["motion"] = str(exc)
            logger.exception(
                "[CAMPEX][VISION] Motion processing failed; running full inference",
                extra={"camera_id": self.camera_id},
            )
        self._last_motion_ms = (self._monotonic() - motion_started) * 1000

        periodic_due = (
            self._last_full_scan_at is None
            or now_monotonic - self._last_full_scan_at
            >= self.settings.vision_full_scan_seconds
        )
        inference_required = (
            motion_result.motion_detected
            or motion_result.global_change_detected
            or periodic_due
            or self.status == "RECOVER"
        )

        timestamp = self._utc_now()
        if not inference_required:
            tracking_started = self._monotonic()
            try:
                objects = self.tracker.update(self.camera_id, [], timestamp)
                self._component_errors.pop("tracker", None)
            except Exception as exc:
                self.fail(f"Tracker failure: {exc}", component="tracker")
                raise
            self._last_tracking_ms = (
                self._monotonic() - tracking_started
            ) * 1000
            with self._lock:
                self.status = "RUNNING"
                self.error = None
                self._last_frame_at = frame_at
                self._last_processed_at = self._monotonic()
                self._last_frame_age_ms = frame_age_ms
                self._frames_processed += 1
                self._skipped_inferences += 1
                self._objects = objects
                self._events = []
            return

        self._last_full_scan_at = now_monotonic
        if motion_result.motion_detected or motion_result.global_change_detected:
            self._motion_triggered_inferences += 1
        else:
            self._periodic_inferences += 1
        try:
            detections, inference_ms = self.detector.detect(frame)
            self._component_errors.pop("detector", None)
        except Exception as exc:
            self.fail(f"Detector failure: {exc}", component="detector")
            raise

        tracking_started = self._monotonic()
        try:
            objects = self.tracker.update(self.camera_id, detections, timestamp)
            self._component_errors.pop("tracker", None)
        except Exception as exc:
            self.fail(f"Tracker failure: {exc}", component="tracker")
            raise
        self._last_tracking_ms = (self._monotonic() - tracking_started) * 1000

        # Spatial evaluation (zones) — if configured
        observations: list[Observation] = []
        zones: list[Zone] = []
        spatial_started = self._monotonic()
        if self._spatial_engine and self._zone_repo:
            try:
                zones = self._zone_repo.list(self.camera_id)
                self._spatial_engine.update_zones(self.camera_id, zones)
                frame_height = frame.shape[0] if hasattr(frame, "shape") else 480
                frame_width = frame.shape[1] if hasattr(frame, "shape") else 640
                observations, _ = self._spatial_engine.evaluate(
                    self.camera_id, objects, frame_width, frame_height
                )
                self._component_errors.pop("spatial", None)
            except Exception as exc:
                self._component_errors["spatial"] = str(exc)
                logger.exception(
                    "[CAMPEX][VISION] Spatial processing failed",
                    extra={"camera_id": self.camera_id},
                )
        self._last_spatial_ms = (self._monotonic() - spatial_started) * 1000

        # Event generation from observations
        events: list = []
        if self._event_engine:
            try:
                events = self._event_engine.process(self.camera_id, observations, zones)
                self._component_errors.pop("event", None)
            except Exception as exc:
                self._component_errors["event"] = str(exc)
                logger.exception(
                    "[CAMPEX][VISION] Event processing failed",
                    extra={"camera_id": self.camera_id},
                )

        with self._lock:
            if self.status == "RECOVER":
                logger.info(
                    "[CAMPEX][VISION] Session recovered",
                    extra={"camera_id": self.camera_id, "state": "RUNNING"},
                )
            self.status = "RUNNING"
            self.error = None
            self._last_frame_at = frame_at
            self._last_processed_at = self._monotonic()
            self._last_inference_ms = inference_ms
            self._last_frame_age_ms = frame_age_ms
            self._frames_processed += 1
            self._objects = objects
            self._events = events

    def fail(self, error: str, component: str | None = None) -> None:
        with self._lock:
            self.status = "ERROR"
            self.error = error
            self._objects = []
            self._events = []
            if component:
                self._component_errors[component] = error

    def stop(self, reason: str = "vision_stopped") -> None:
        with self._processing_lock:
            if self._event_engine:
                self._event_engine.mark_camera_unknown(self.camera_id, reason)
            if self._spatial_engine:
                self._spatial_engine.reset(self.camera_id)
            reset_tracker = getattr(self.tracker, "reset", None)
            if callable(reset_tracker):
                reset_tracker()
            with self._lock:
                self.status = "STOPPED"
                self.error = None
                self._objects = []
                self._events = []

    @property
    def detector_ready(self) -> bool:
        """Whether the detector model has been loaded and is ready for inference."""
        return getattr(self.detector, "is_loaded", True)

    def restart(self) -> None:
        with self._processing_lock:
            if self._event_engine:
                self._event_engine.mark_camera_unknown(
                    self.camera_id, "vision_restarted"
                )
            if self._spatial_engine:
                self._spatial_engine.reset(self.camera_id)
            self._motion.reset()
            reset_tracker = getattr(self.tracker, "reset", None)
            if callable(reset_tracker):
                reset_tracker()
            with self._lock:
                self.status = "STARTING"
                self.error = None
                self._last_frame_at = None
                self._last_frame_id = None
                self._last_processed_at = 0.0
                self._last_full_scan_at = None
                self._last_inference_ms = None
                self._last_frame_age_ms = None
                self._last_motion_ms = None
                self._last_tracking_ms = None
                self._last_spatial_ms = None
                self._frames_processed = 0
                self._frames_dropped = 0
                self._motion_triggered_inferences = 0
                self._periodic_inferences = 0
                self._skipped_inferences = 0
                self._objects = []
                self._events = []
                self._component_errors.clear()

    def objects(self) -> list[TrackedObject]:
        with self._lock:
            return list(self._objects)

    def events(self) -> list:
        with self._lock:
            return list(self._events)

    def as_status(
        self,
        camera_fps: float = 0.0,
        frames_received: int = 0,
        frames_dropped: int = 0,
    ) -> dict:
        with self._lock:
            effective_dropped = max(frames_dropped, self._frames_dropped)
            tracker_backend = getattr(
                self.tracker, "backend", self.tracker.__class__.__name__
            )
            tracker_state = getattr(self.tracker, "state", "ACTIVE")
            metrics = VisionMetrics(
                camera_fps=camera_fps,
                vision_fps=self.settings.vision_fps if self.status == "RUNNING" else 0.0,
                inference_ms=self._last_inference_ms,
                objects_detected=len(self._objects),
                device=self.detector.device,
                detector=self.detector.name,
                tracker=self.tracker.name,
                uptime=max(0.0, self._monotonic() - self.started_at),
                frames_received=frames_received,
                frames_processed=self._frames_processed,
                frames_dropped=effective_dropped,
                frame_age_ms=self._last_frame_age_ms,
                motion_processing_ms=self._last_motion_ms,
                tracking_ms=self._last_tracking_ms,
                spatial_processing_ms=self._last_spatial_ms,
                motion_triggered_inferences=self._motion_triggered_inferences,
                periodic_inferences=self._periodic_inferences,
                skipped_inferences=self._skipped_inferences,
                tracker_backend=tracker_backend,
                tracker_state=tracker_state,
            )
            components = {
                "motion": {
                    "backend": self._motion.__class__.__name__,
                    "state": (
                        "ERROR"
                        if "motion" in self._component_errors
                        else "ACTIVE" if self._motion.has_reference else "CALIBRATING"
                    ),
                    "error": self._component_errors.get("motion"),
                },
                "detector": {
                    "backend": self.detector.__class__.__name__,
                    "state": (
                        "ERROR" if "detector" in self._component_errors
                        else "LOADING" if not self.detector_ready
                        else "ACTIVE"
                    ),
                    "error": self._component_errors.get("detector"),
                },
                "tracker": {
                    "type": getattr(self.tracker, "tracker_type", "custom"),
                    "backend": tracker_backend,
                    "state": (
                        "ERROR" if "tracker" in self._component_errors else tracker_state
                    ),
                    "error": self._component_errors.get("tracker"),
                },
                "spatial": {
                    "state": (
                        "NOT_CONFIGURED"
                        if self._spatial_engine is None
                        else "ERROR" if "spatial" in self._component_errors else "ACTIVE"
                    ),
                    "error": self._component_errors.get("spatial"),
                },
                "event": {
                    "state": (
                        "NOT_CONFIGURED"
                        if self._event_engine is None
                        else "ERROR" if "event" in self._component_errors else "ACTIVE"
                    ),
                    "error": self._component_errors.get("event"),
                },
            }
            return {
                "camera_id": self.camera_id,
                "status": self.status,
                "vision_status": self.status,
                "error": self.error,
                "metrics": metrics.as_dict(),
                "components": components,
            }


class VisionEngine:
    def __init__(self, settings: Settings, camera_manager: CameraManager) -> None:
        self.settings = settings
        self.camera_manager = camera_manager
        self._detector: VisionDetector | None = None
        self._detector_loaded = False
        self._detector_error: str | None = None
        self._detector_thread: threading.Thread | None = None
        self._sessions: dict[str, VisionSession] = {}
        self._spatial_engine = SpatialEngine()
        self._event_repo = EventRepository(settings)
        self._event_engine = EventEngine(self._event_repo)
        self._zone_repo = ZoneRepository.for_settings(settings)
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

            detector = self._get_detector()
            session = VisionSession(
                camera_id,
                self.settings,
                detector,
                spatial_engine=self._spatial_engine,
                event_engine=self._event_engine,
                zone_repo=self._zone_repo,
            )
            self._sessions[camera_id] = session

            # Kick off detector loading in a background thread so the
            # HTTP request returns immediately instead of blocking for
            # the model's load time (which can exceed the client timeout
            # and prevent the frontend from switching to the live MJPEG
            # stream).
            self._ensure_detector_loading_locked()

            logger.info(
                "[CAMPEX][VISION] Camera session started",
                extra={"camera_id": camera_id},
            )
            return session.as_status(camera_fps=0.0, frames_received=0, frames_dropped=0)

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
            if existing is not None:
                existing.restart()
                return existing.as_status()

            if not self.settings.vision_enabled:
                return self._disabled_status(camera_id)

            detector = self._get_detector()
            session = VisionSession(
                camera_id,
                self.settings,
                detector,
                spatial_engine=self._spatial_engine,
                event_engine=self._event_engine,
                zone_repo=self._zone_repo,
            )
            self._sessions[camera_id] = session
            self._ensure_detector_loading_locked()
            logger.info(
                "[CAMPEX][VISION] Camera session restarted",
                extra={"camera_id": camera_id},
            )
            return session.as_status(camera_fps=0.0, frames_received=0, frames_dropped=0)

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

    def events(self, camera_id: str) -> list:
        with self._lock:
            session = self._sessions.get(camera_id)
        return session.events() if session else []

    def _get_detector(self) -> VisionDetector:
        if self._detector is None:
            self._detector = create_detector(self.settings)
            logger.info(
                "[CAMPEX][VISION] Detector configured",
                extra={"detector": self._detector.name, "device": self._detector.device},
            )
        return self._detector

    def _ensure_detector_loading_locked(self) -> None:
        """Start a background thread to load the detector model.

        Must be called while holding ``self._lock``.  If the detector is
        already loaded or a loading thread is already in-flight this is a
        no-op, guaranteeing the model is loaded exactly once.
        """
        if self._detector_loaded or self._detector_error is not None:
            return
        if self._detector is None:
            return
        if self._detector_thread is not None and self._detector_thread.is_alive():
            return
        self._detector_thread = threading.Thread(
            target=self._load_detector_async,
            name="campex-vision-detector-load",
            daemon=True,
        )
        self._detector_thread.start()

    def _load_detector_async(self) -> None:
        """Background worker that loads the detector model.

        Updates ``_detector_loaded`` / ``_detector_error`` so that the
        VisionEngine poll-loop can start processing frames once loading
        completes, or mark sessions as ERROR on failure.
        """
        detector = self._detector
        if detector is None:
            return
        try:
            logger.info("[CAMPEX][VISION] Loading detector in background thread")
            detector.load()
            self._detector_loaded = True
            logger.info("[CAMPEX][VISION] Detector loaded")
        except Exception as exc:
            self._detector_error = str(exc)
            logger.exception(
                "[CAMPEX][VISION] Detector loading failed",
            )

    def _run(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                sessions = list(self._sessions.values())
                detector_error = self._detector_error
            for session in sessions:
                if session.status == "STOPPED":
                    continue
                if not session.detector_ready:
                    if detector_error and session.status != "ERROR":
                        session.fail(
                            f"Detector unavailable: {detector_error}",
                            component="detector",
                        )
                    continue
                if not self.camera_manager.is_running(session.camera_id):
                    if session.status != "ERROR":
                        logger.info(
                            "[CAMPEX][VISION] Camera offline, vision entering ERROR",
                            extra={"camera_id": session.camera_id},
                        )
                    session.fail("Camera is offline or not running.")
                    continue
                snapshot = self.camera_manager.latest_frame_snapshot(session.camera_id)
                if snapshot.frame is None or not session.should_process(
                    snapshot.frame_at, snapshot.frame_id
                ):
                    continue
                frame = snapshot.frame
                try:
                    session.process(frame, snapshot.frame_at)
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
