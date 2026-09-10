from __future__ import annotations

from typing import Any

import cv2

from backend.vision.models import TrackedObject


class OverlayRenderer:
    box_color = (0, 255, 128)
    label_background = (0, 0, 0)
    label_color = (255, 255, 255)

    def render(self, frame: Any, objects: list[TrackedObject]) -> Any:
        output = frame.copy()
        for tracked in objects:
            self._draw_tracked_object(output, tracked)
        return output

    def _draw_tracked_object(self, frame: Any, tracked: TrackedObject) -> None:
        box = tracked.bounding_box
        x1, y1, x2, y2 = [int(value) for value in box.as_list()]
        label = f"{tracked.class_name.upper()} #{tracked.track_id} {tracked.confidence:.0%}"
        label_width = max(140, min(260, 10 + len(label) * 10))
        cv2.rectangle(frame, (x1, y1), (x2, y2), self.box_color, 2)
        cv2.rectangle(
            frame,
            (x1, max(0, y1 - 24)),
            (x1 + label_width, y1),
            self.label_background,
            -1,
        )
        cv2.putText(
            frame,
            label,
            (x1 + 6, max(16, y1 - 7)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            self.label_color,
            1,
            cv2.LINE_AA,
        )


def draw_tracked_objects(frame: Any, objects: list[TrackedObject]) -> Any:
    return OverlayRenderer().render(frame, objects)
