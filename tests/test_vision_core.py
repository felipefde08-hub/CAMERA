from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

import cv2
import numpy as np
import pytest

from backend.cameras.frame_buffer import LatestFrameBuffer
from backend.cameras.manager import CameraManager
from backend.cameras.repository import CameraRepository
from backend.config import Settings
from backend.database.db import initialize_database
from backend.vision.detector import (
    DetectorUnavailable,
    RFDETRDetector,
    VisionDetector,
    create_detector,
    normalize_rfdetr_result,
)
from backend.vision.engine import VisionEngine, VisionSession
from backend.vision.models import BoundingBox, Detection, TrackedObject, VisionMetrics
from backend.vision.overlay import OverlayRenderer
from backend.vision.tracker import ByteTrackTracker, ObjectTracker
from tests.helpers import make_settings


class FakeDetector(VisionDetector):
    name = "FakeDetector"

    def __init__(self, class_names: list[str] | None = None) -> None:
        self._device = "CPU"
        self._class_names = class_names or ["person"]
        self.load_calls = 0
        self.detect_calls = 0

    def load(self) -> None:
        self.load_calls += 1

    def detect(self, frame: Any) -> tuple[list[Detection], float]:
        self.detect_calls += 1
        detections = [
            Detection(
                class_name="person",
                confidence=0.95,
                bounding_box=BoundingBox(x1=10, y1=10, x2=100, y2=200),
            ),
            Detection(
                class_name="car",
                confidence=0.80,
                bounding_box=BoundingBox(x1=200, y1=200, x2=400, y2=400),
            ),
        ]
        return detections, 12.5

    @property
    def device(self) -> str:
        return self._device


class FakeTracker(ObjectTracker):
    name = "FakeTracker"

    def __init__(self) -> None:
        self.updates: list[tuple[str, list[Detection], datetime]] = []

    def update(
        self, camera_id: str, detections: list[Detection], timestamp: datetime
    ) -> list[TrackedObject]:
        self.updates.append((camera_id, detections, timestamp))
        objects: list[TrackedObject] = []
        for index, detection in enumerate(detections):
            objects.append(
                TrackedObject(
                    track_id=index + 1,
                    camera_id=camera_id,
                    class_name=detection.class_name,
                    confidence=detection.confidence,
                    bounding_box=detection.bounding_box,
                    timestamp=timestamp,
                )
            )
        return objects


class FailingTracker(ObjectTracker):
    name = "FailingTracker"

    def update(
        self, camera_id: str, detections: list[Detection], timestamp: datetime
    ) -> list[TrackedObject]:
        raise RuntimeError("tracker offline")


class SupervisionLikeDetection:
    """Mimics a supervision.Detections object."""

    def __init__(
        self,
        xyxy: list[list[float]],
        confidence: list[float] | None = None,
        class_id: list[int] | None = None,
        class_names_in_data: list[str] | None = None,
    ) -> None:
        self.xyxy = np.array(xyxy, dtype=np.float32)
        self.confidence = (
            np.array(confidence, dtype=np.float32) if confidence else np.array([])
        )
        self.class_id = np.array(class_id, dtype=np.int64) if class_id else np.array([])
        self.data: dict[str, Any] = {}
        if class_names_in_data:
            self.data["class_name"] = np.array(class_names_in_data, dtype=object)
        self.data["source_shape"] = np.array([[480, 640]], dtype=np.int64)


class RawDetections:
    xyxy = [[10, 20, 110, 220], [0, 0, 5, 5]]
    confidence = [0.91, 0.2]
    class_name = ["person", "car"]


def _make_session(
    camera_id: str = "cam_1",
    settings: Settings | None = None,
    detector: VisionDetector | None = None,
    tracker: ObjectTracker | None = None,
) -> VisionSession:
    settings = settings or make_settings(Path("/tmp/test_vision.sqlite3"))
    detector = detector or FakeDetector()
    tracker = tracker or FakeTracker()
    return VisionSession(camera_id, settings, detector, tracker)


def test_vision_detector_is_abstract():
    assert issubclass(RFDETRDetector, VisionDetector)
    assert issubclass(ByteTrackTracker, ObjectTracker)
    with pytest.raises(TypeError):
        VisionDetector.__init__(object())
    with pytest.raises(TypeError):
        ObjectTracker.__init__(object())


def test_normalize_rfdetr_result_filters_and_maps_detections():
    detections = normalize_rfdetr_result(RawDetections(), confidence_threshold=0.5)

    assert len(detections) == 1
    assert detections[0].class_name == "person"
    assert detections[0].confidence == 0.91
    assert detections[0].bounding_box.as_list() == [10.0, 20.0, 110.0, 220.0]


def test_normalize_rfdetr_result_handles_supervision_detections():
    raw = SupervisionLikeDetection(
        xyxy=[[10, 20, 110, 220], [0, 0, 50, 50]],
        confidence=[0.95, 0.3],
        class_id=[0, 2],
        class_names_in_data=["person", "car"],
    )
    detections = normalize_rfdetr_result(raw, confidence_threshold=0.5)

    assert len(detections) == 1
    assert detections[0].class_name == "person"
    assert detections[0].confidence == 0.95
    assert detections[0].bounding_box.as_list() == [10.0, 20.0, 110.0, 220.0]


def test_normalize_rfdetr_result_falls_back_to_data_class_name():
    raw = SupervisionLikeDetection(
        xyxy=[[5, 5, 50, 50]],
        confidence=[0.8],
        class_id=[0],
        class_names_in_data=["person"],
    )
    detections = normalize_rfdetr_result(raw, confidence_threshold=0.5)
    assert len(detections) == 1
    assert detections[0].class_name == "person"


def test_normalize_rfdetr_result_resolves_class_from_class_id():
    raw = SupervisionLikeDetection(
        xyxy=[[5, 5, 50, 50]],
        confidence=[0.8],
        class_id=[0],
    )
    detections = normalize_rfdetr_result(
        raw, confidence_threshold=0.5, class_names=["person", "car", "truck"]
    )
    assert len(detections) == 1
    assert detections[0].class_name == "person"


def test_normalize_rfdetr_result_empty_result():
    raw = SupervisionLikeDetection(xyxy=[], confidence=[], class_id=[])
    detections = normalize_rfdetr_result(raw, confidence_threshold=0.5)
    assert detections == []


def test_normalize_rfdetr_result_handles_missing_confidence():
    raw = SupervisionLikeDetection(
        xyxy=[[10, 20, 110, 220]],
        confidence=None,
        class_id=[0],
        class_names_in_data=["person"],
    )
    detections = normalize_rfdetr_result(raw, confidence_threshold=0.0)
    assert len(detections) == 1
    assert detections[0].class_name == "person"


def test_tracker_keeps_track_id_for_overlapping_detection():
    tracker = ByteTrackTracker()
    timestamp = datetime.now(timezone.utc)

    first = tracker.update(
        "cam_1",
        [Detection("person", 0.9, BoundingBox(10, 10, 100, 200))],
        timestamp,
    )
    second = tracker.update(
        "cam_1",
        [Detection("person", 0.88, BoundingBox(14, 12, 104, 202))],
        timestamp,
    )

    assert first[0].track_id == second[0].track_id
    assert second[0].camera_id == "cam_1"


def test_tracker_assigns_new_ids_for_new_objects():
    tracker = ByteTrackTracker()
    timestamp = datetime.now(timezone.utc)

    first = tracker.update(
        "cam_1",
        [Detection("person", 0.9, BoundingBox(10, 10, 100, 200))],
        timestamp,
    )
    second = tracker.update(
        "cam_1",
        [
            Detection("person", 0.9, BoundingBox(100, 100, 200, 300)),
            Detection("person", 0.8, BoundingBox(300, 100, 400, 300)),
        ],
        timestamp,
    )

    assert len(first) == 1
    assert len(second) == 2
    assert second[0].track_id != second[1].track_id


def test_tracker_different_classes_get_different_ids():
    tracker = ByteTrackTracker()
    timestamp = datetime.now(timezone.utc)

    results = tracker.update(
        "cam_1",
        [
            Detection("person", 0.9, BoundingBox(10, 10, 100, 200)),
            Detection("car", 0.9, BoundingBox(10, 10, 100, 200)),
        ],
        timestamp,
    )

    assert results[0].track_id != results[1].track_id
    assert results[0].class_name == "person"
    assert results[1].class_name == "car"


def test_tracker_expired_tracks_are_removed():
    tracker = ByteTrackTracker(max_missed=2)
    timestamp = datetime.now(timezone.utc)

    first = tracker.update(
        "cam_1",
        [Detection("person", 0.9, BoundingBox(10, 10, 100, 200))],
        timestamp,
    )
    track_id = first[0].track_id

    tracker.update("cam_1", [], timestamp)
    tracker.update("cam_1", [], timestamp)

    current = tracker.update(
        "cam_1",
        [Detection("person", 0.9, BoundingBox(10, 10, 100, 200))],
        timestamp,
    )
    assert current[0].track_id != track_id


def test_vision_session_processes_frame_and_tracks_objects():
    session = _make_session()

    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    timestamp = datetime.now(timezone.utc)

    session.process(frame, timestamp)

    assert session.status == "RUNNING"
    objects = session.objects()
    assert len(objects) == 2
    assert objects[0].track_id == 1
    assert objects[0].class_name == "person"
    assert objects[1].track_id == 2
    assert objects[1].class_name == "car"


def test_latest_frame_buffer_replaces_stale_frame():
    buffer = LatestFrameBuffer()
    first = np.zeros((8, 8, 3), dtype=np.uint8)
    second = np.ones((8, 8, 3), dtype=np.uint8)
    timestamp = datetime.now(timezone.utc)

    buffer.put(first, timestamp)
    buffer.put(second, timestamp)

    frame, frame_at = buffer.latest()
    stats = buffer.stats()

    assert frame_at == timestamp
    assert int(frame[0][0][0]) == 1
    assert stats.frames_received == 2
    assert stats.frames_replaced == 1


def test_latest_frame_buffer_does_not_accumulate_stale_frames():
    buffer = LatestFrameBuffer()
    timestamp = datetime.now(timezone.utc)

    for value in range(5):
        buffer.put(np.full((2, 2, 3), value, dtype=np.uint8), timestamp)

    snapshot = buffer.snapshot()

    assert int(snapshot.frame[0][0][0]) == 4
    assert snapshot.frames_received == 5
    assert snapshot.frames_replaced == 4


def test_vision_session_should_process_rate_limits():
    session = _make_session()
    timestamp = datetime.now(timezone.utc)

    assert session.should_process(timestamp) is True

    assert session.should_process(timestamp) is False

    new_timestamp = datetime.now(timezone.utc)
    assert session.should_process(new_timestamp) is False

    time.sleep(1 / session.settings.vision_fps + 0.05)
    assert session.should_process(new_timestamp) is True


def test_vision_session_stop():
    session = _make_session()
    session.stop()

    assert session.status == "STOPPED"


def test_vision_session_restart():
    session = _make_session()

    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    timestamp = datetime.now(timezone.utc)
    session.process(frame, timestamp)
    assert session.status == "RUNNING"
    assert session.error is None

    session.restart()
    assert session.status == "STARTING"
    assert session.objects() == []
    assert session.error is None


def test_vision_session_fail_sets_error():
    session = _make_session()

    session.fail("Detector not loaded")

    assert session.status == "ERROR"
    assert session.error == "Detector not loaded"


def test_vision_session_status_contains_metrics():
    session = _make_session()
    status = session.as_status(camera_fps=30.0, frames_received=8, frames_dropped=3)

    assert status["camera_id"] == "cam_1"
    assert status["status"] in {"STARTING", "RUNNING", "ERROR", "STOPPED"}
    assert status["vision_status"] == status["status"]
    assert status["metrics"] is not None
    assert status["metrics"]["detector"] == "FakeDetector"
    assert status["metrics"]["device"] == "CPU"
    assert status["metrics"]["camera_fps"] == 30.0
    assert status["metrics"]["frames_received"] == 8
    assert status["metrics"]["frames_dropped"] == 3


def test_vision_engine_disabled_status(tmp_path: Path):
    settings = make_settings(tmp_path / "vision-disabled.sqlite3")
    settings = settings.__class__(**{**settings.__dict__, "vision_enabled": False})
    initialize_database(settings)

    repository = CameraRepository(settings)
    manager = CameraManager(settings, repository)
    engine = VisionEngine(settings, manager)
    try:
        status = engine.start_session("cam_missing")
    finally:
        engine.shutdown()
        manager.shutdown()

    assert status["status"] == "DISABLED"


def test_vision_session_duplicate_start_reuses_session(tmp_path: Path):
    settings = make_settings(tmp_path / "vision.sqlite3")
    initialize_database(settings)
    repository = CameraRepository(settings)
    camera = repository.create(
        name="Video",
        area_id=None,
        source_type="video_file",
        source_uri=str(tmp_path / "missing.mp4"),
        enabled=False,
        vision_enabled=True,
    )
    manager = CameraManager(settings, repository)
    engine = VisionEngine(settings, manager)
    try:
        first = engine.start_session(camera.id)
        second = engine.start_session(camera.id)
    finally:
        engine.shutdown()
        manager.shutdown()

    assert first["camera_id"] == camera.id
    assert second["camera_id"] == camera.id
    assert first["status"] in {"STARTING", "ERROR"}
    assert second["status"] in {"STARTING", "ERROR"}


def test_vision_engine_stop_session(tmp_path: Path):
    settings = make_settings(tmp_path / "vision-stop.sqlite3")
    initialize_database(settings)
    repository = CameraRepository(settings)
    camera = repository.create(
        name="Video",
        area_id=None,
        source_type="video_file",
        source_uri=str(tmp_path / "missing.mp4"),
        enabled=False,
        vision_enabled=True,
    )
    manager = CameraManager(settings, repository)
    engine = VisionEngine(settings, manager)

    with patch("backend.vision.engine.create_detector", return_value=FakeDetector()):
        engine.start_session(camera.id)
        status = engine.status(camera.id)
        assert status["status"] in {"STARTING", "ERROR", "RUNNING"}

        stop_status = engine.stop_session(camera.id)
        assert stop_status["status"] == "STOPPED"

        after_stop = engine.status(camera.id)
        assert after_stop["status"] == "STOPPED"
    engine.shutdown()
    manager.shutdown()


def test_vision_engine_restart_session(tmp_path: Path):
    settings = make_settings(tmp_path / "vision-restart.sqlite3")
    initialize_database(settings)
    repository = CameraRepository(settings)
    camera = repository.create(
        name="Video",
        area_id=None,
        source_type="video_file",
        source_uri=str(tmp_path / "missing.mp4"),
        enabled=False,
        vision_enabled=True,
    )
    manager = CameraManager(settings, repository)
    engine = VisionEngine(settings, manager)

    with patch("backend.vision.engine.create_detector", return_value=FakeDetector()):
        start_status = engine.start_session(camera.id)
        assert start_status["status"] in {"STARTING", "ERROR", "RUNNING"}

        restart_status = engine.restart_session(camera.id)
        assert restart_status["camera_id"] == camera.id
        assert restart_status["status"] in {"STARTING", "ERROR", "RUNNING"}
    engine.shutdown()
    manager.shutdown()


def test_vision_engine_start_stop_start_without_restart(tmp_path: Path):
    settings = make_settings(tmp_path / "vision-cycle.sqlite3")
    initialize_database(settings)
    repository = CameraRepository(settings)
    camera = repository.create(
        name="Video",
        area_id=None,
        source_type="video_file",
        source_uri=str(tmp_path / "missing.mp4"),
        enabled=False,
        vision_enabled=True,
    )
    manager = CameraManager(settings, repository)
    engine = VisionEngine(settings, manager)

    with patch("backend.vision.engine.create_detector", return_value=FakeDetector()):
        first_start = engine.start_session(camera.id)
        assert first_start["camera_id"] == camera.id

        engine.stop_session(camera.id)
        assert engine.status(camera.id)["status"] == "STOPPED"

        second_start = engine.start_session(camera.id)
        assert second_start["camera_id"] == camera.id
        assert second_start["status"] in {"STARTING", "ERROR", "RUNNING"}
    engine.shutdown()
    manager.shutdown()


def test_vision_engine_camera_offline_sets_error(tmp_path: Path):
    settings = make_settings(tmp_path / "vision-offline.sqlite3")
    initialize_database(settings)
    repository = CameraRepository(settings)
    manager = CameraManager(settings, repository)
    engine = VisionEngine(settings, manager)

    with patch("backend.vision.engine.create_detector", return_value=FakeDetector()):
        engine.start_session("cam_nonexistent")
        time.sleep(0.3)
        status = engine.status("cam_nonexistent")
    engine.shutdown()
    manager.shutdown()

    assert status["status"] == "ERROR"
    assert "offline" in (status.get("error") or "").lower()


def test_vision_engine_detectors_singleton(tmp_path: Path):
    settings = make_settings(tmp_path / "vision-singleton.sqlite3")
    initialize_database(settings)
    repository = CameraRepository(settings, )
    manager = CameraManager(settings, repository)
    engine = VisionEngine(settings, manager)

    fake = FakeDetector()
    with patch("backend.vision.engine.create_detector", return_value=fake):
        engine.start_session("cam_1")
        engine.start_session("cam_2")
        time.sleep(0.2)

    assert fake.load_calls == 1
    engine.shutdown()
    manager.shutdown()


def test_vision_engine_error_does_not_crash(tmp_path: Path):
    settings = make_settings(tmp_path / "vision-crash.sqlite3")
    initialize_database(settings)
    repository = CameraRepository(settings)
    manager = CameraManager(settings, repository)
    engine = VisionEngine(settings, manager)
    started = False
    try:
        with patch("backend.vision.engine.create_detector", return_value=FakeDetector()):
            engine.start_session("cam_no_camera")
            time.sleep(0.3)
            status = engine.status("cam_no_camera")
            assert status["status"] in {"ERROR", "RUNNING", "STARTING"}
            assert engine._thread.is_alive()
            started = True
    finally:
        engine.shutdown()
        manager.shutdown()

    assert started
    assert not engine._thread.is_alive()


def test_tracker_failure_sets_vision_error_without_crashing_session():
    session = _make_session(tracker=FailingTracker())
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    timestamp = datetime.now(timezone.utc)

    with pytest.raises(RuntimeError):
        session.process(frame, timestamp)

    assert session.status == "ERROR"
    assert "tracker" in (session.error or "").lower()


def test_vision_metrics_has_all_required_fields():
    metrics = VisionMetrics(
        camera_fps=30.0,
        vision_fps=5.0,
        inference_ms=45.0,
        objects_detected=2,
        device="CPU",
        detector="RF-DETR Nano",
        tracker="ByteTrack",
        uptime=120.0,
        frames_received=100,
        frames_processed=20,
        frames_dropped=80,
        frame_age_ms=41.0,
    )
    data = metrics.as_dict()

    assert data["camera_fps"] == 30.0
    assert data["vision_fps"] == 5.0
    assert data["inference_ms"] == 45.0
    assert data["objects_detected"] == 2
    assert data["device"] == "CPU"
    assert data["detector"] == "RF-DETR Nano"
    assert data["tracker"] == "ByteTrack"
    assert data["uptime"] == 120.0
    assert data["frames_received"] == 100
    assert data["frames_processed"] == 20
    assert data["frames_dropped"] == 80
    assert data["frame_age_ms"] == 41.0


def test_tracked_object_as_dict():
    timestamp = datetime.now(timezone.utc)
    obj = TrackedObject(
        track_id=12,
        camera_id="cam_1",
        class_name="person",
        confidence=0.96,
        bounding_box=BoundingBox(x1=10, y1=20, x2=100, y2=200),
        timestamp=timestamp,
    )
    data = obj.as_dict()

    assert data["track_id"] == 12
    assert data["camera_id"] == "cam_1"
    assert data["class_name"] == "person"
    assert data["confidence"] == 0.96
    assert data["bounding_box"] == [10.0, 20.0, 100.0, 200.0]
    assert data["timestamp"] == timestamp.isoformat()


def test_detection_as_dict():
    detection = Detection(
        class_name="person",
        confidence=0.91,
        bounding_box=BoundingBox(x1=10, y1=20, x2=110, y2=220),
    )
    data = detection.as_dict()

    assert data["class_name"] == "person"
    assert data["confidence"] == 0.91
    assert data["bounding_box"] == [10.0, 20.0, 110.0, 220.0]


def test_overlay_renderer_accepts_tracked_objects():
    renderer = OverlayRenderer()
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    obj = TrackedObject(
        track_id=12,
        camera_id="cam_1",
        class_name="person",
        confidence=0.94,
        bounding_box=BoundingBox(10, 20, 80, 100),
        timestamp=datetime.now(timezone.utc),
    )

    rendered = renderer.render(frame, [obj])

    assert rendered.shape == frame.shape
    assert int(rendered.sum()) > 0


def test_create_detector_unsupported_type():
    settings = make_settings(Path("/tmp/test_unsupported.sqlite3"))
    fields = {**settings.__dict__, "vision_detector": "yolox"}
    settings = settings.__class__(**fields)
    with pytest.raises(DetectorUnavailable):
        create_detector(settings)


def test_motion_detector_no_motion_on_blank_frame():
    from backend.vision.motion import MotionDetector, MotionResult

    detector = MotionDetector()
    frame = np.zeros((480, 640, 3), dtype=np.uint8)

    assert detector.has_reference is False
    result = detector.detect(frame)
    assert result.motion_detected is False
    assert detector.has_reference is True


def test_motion_detector_detects_frame_change():
    from backend.vision.motion import MotionDetector

    detector = MotionDetector()
    base = np.zeros((480, 640, 3), dtype=np.uint8)
    detector.detect(base)

    changed = base.copy()
    cv2.rectangle(changed, (100, 100), (200, 200), (255, 255, 255), -1)

    result = detector.detect(changed)
    assert result.motion_detected is True
    assert result.motion_pixels > 0
    assert len(result.regions) > 0


def test_motion_detector_reset_clears_reference():
    from backend.vision.motion import MotionDetector

    detector = MotionDetector()
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    detector.detect(frame)
    assert detector.has_reference is True

    detector.reset()
    assert detector.has_reference is False


def test_motion_detector_skips_detection_when_no_motion():
    session = _make_session()
    frame_a = np.zeros((480, 640, 3), dtype=np.uint8)
    frame_b = np.zeros((480, 640, 3), dtype=np.uint8)
    timestamp = datetime.now(timezone.utc)

    session.process(frame_a, timestamp)
    assert session.status == "RUNNING"

    session.process(frame_b, timestamp)
    objects = session.objects()
    assert len(objects) == 0
