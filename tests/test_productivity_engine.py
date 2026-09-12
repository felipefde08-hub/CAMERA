from datetime import datetime, timedelta, timezone

from backend.productivity.engine import ProductivityEngine, classify_object
from backend.vision.models import BoundingBox, TrackedObject


def _obj(track_id, class_name, box, timestamp):
    return TrackedObject(
        track_id=track_id,
        camera_id="cam_1",
        class_name=class_name,
        confidence=0.9,
        bounding_box=BoundingBox(*box),
        timestamp=timestamp,
    )


def test_classifies_machine_and_phone_classes():
    assert classify_object("person") == "person"
    assert classify_object("forklift") == "machine"
    assert classify_object("cell phone") == "phone"


def test_productivity_flags_idle_person_and_machine_presence():
    engine = ProductivityEngine(idle_seconds=2, still_distance_px=5)
    first = datetime.now(timezone.utc)
    later = first + timedelta(seconds=3)

    engine.analyze("cam_1", [_obj(1, "person", (10, 10, 80, 160), first)], first)
    snapshot = engine.analyze(
        "cam_1",
        [
            _obj(1, "person", (11, 10, 81, 160), later),
            _obj(2, "forklift", (200, 80, 360, 260), later),
        ],
        later,
    )

    assert snapshot["counts"]["people"] == 1
    assert snapshot["counts"]["machines"] == 1
    assert any(signal["type"] == "person_idle" for signal in snapshot["signals"])


def test_productivity_flags_possible_phone_use():
    engine = ProductivityEngine(idle_seconds=60)
    now = datetime.now(timezone.utc)
    snapshot = engine.analyze(
        "cam_1",
        [
            _obj(1, "person", (10, 10, 80, 160), now),
            _obj(2, "cell phone", (50, 50, 70, 80), now),
        ],
        now,
    )

    assert snapshot["counts"]["phones"] == 1
    assert any(signal["type"] == "possible_phone_use" for signal in snapshot["signals"])
