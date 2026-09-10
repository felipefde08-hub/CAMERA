from __future__ import annotations

from typing import Any

import cv2

from backend.vision.models import TrackedObject


def draw_tracked_objects(frame: Any, objects: list[TrackedObject]) -> Any:
    output = frame.copy()
    for tracked in objects:
        box = tracked.bounding_box
        x1, y1, x2, y2 = [int(value) for value in box.as_list()]
        label = f"{tracked.class_name.upper()} #{tracked.track_id} {tracked.confidence:.0%}"
        cv2.rectangle(output, (x1, y1), (x2, y2), (0, 255, 128), 2)
        cv2.rectangle(output, (x1, max(0, y1 - 24)), (x1 + 220, y1), (0, 0, 0), -1)
        cv2.putText(
            output,
            label,
            (x1 + 6, max(16, y1 - 7)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
    return output
