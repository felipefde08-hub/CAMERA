from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from backend.vision.models import BoundingBox, Detection, TrackedObject


class ObjectTracker(ABC):
    name = "abstract"

    def __init__(self) -> None:
        if self.__class__ is object:
            raise TypeError("ObjectTracker cannot initialize a plain object.")

    @abstractmethod
    def update(
        self, camera_id: str, detections: list[Detection], timestamp: datetime
    ) -> list[TrackedObject]:
        raise NotImplementedError


@dataclass
class _Track:
    track_id: int
    class_name: str
    bounding_box: BoundingBox
    confidence: float
    missed: int = 0


class ByteTrackTracker(ObjectTracker):
    name = "ByteTrack"

    def __init__(self, iou_threshold: float = 0.25, max_missed: int = 10) -> None:
        self.iou_threshold = iou_threshold
        self.max_missed = max_missed
        self._next_id = 1
        self._tracks: dict[int, _Track] = {}

    def update(
        self, camera_id: str, detections: list[Detection], timestamp: datetime
    ) -> list[TrackedObject]:
        assigned_tracks: set[int] = set()
        objects: list[TrackedObject] = []

        for detection in detections:
            best_track_id: int | None = None
            best_score = 0.0
            for track_id, track in self._tracks.items():
                if track_id in assigned_tracks or track.class_name != detection.class_name:
                    continue
                score = _iou(track.bounding_box, detection.bounding_box)
                if score > best_score:
                    best_score = score
                    best_track_id = track_id

            if best_track_id is None or best_score < self.iou_threshold:
                best_track_id = self._next_id
                self._next_id += 1

            self._tracks[best_track_id] = _Track(
                track_id=best_track_id,
                class_name=detection.class_name,
                bounding_box=detection.bounding_box,
                confidence=detection.confidence,
                missed=0,
            )
            assigned_tracks.add(best_track_id)
            objects.append(
                TrackedObject(
                    track_id=best_track_id,
                    camera_id=camera_id,
                    class_name=detection.class_name,
                    confidence=detection.confidence,
                    bounding_box=detection.bounding_box,
                    timestamp=timestamp,
                )
            )

        for track_id in list(self._tracks):
            if track_id in assigned_tracks:
                continue
            self._tracks[track_id].missed += 1
            if self._tracks[track_id].missed >= self.max_missed:
                del self._tracks[track_id]

        return objects


def _iou(first: BoundingBox, second: BoundingBox) -> float:
    x1 = max(first.x1, second.x1)
    y1 = max(first.y1, second.y1)
    x2 = min(first.x2, second.x2)
    y2 = min(first.y2, second.y2)
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if intersection == 0:
        return 0.0

    first_area = max(0.0, first.x2 - first.x1) * max(0.0, first.y2 - first.y1)
    second_area = max(0.0, second.x2 - second.x1) * max(0.0, second.y2 - second.y1)
    union = first_area + second_area - intersection
    return intersection / union if union else 0.0
