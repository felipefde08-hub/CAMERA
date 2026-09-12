from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import hypot

from backend.vision.models import BoundingBox, TrackedObject


PERSON_CLASSES = {"person"}
PHONE_CLASSES = {"cell phone", "mobile phone", "phone", "smartphone"}
MACHINE_CLASSES = {
    "forklift",
    "truck",
    "car",
    "bus",
    "motorcycle",
    "bicycle",
    "train",
    "boat",
    "airplane",
    "tractor",
    "excavator",
    "crane",
    "loader",
    "bulldozer",
    "machine",
    "industrial machine",
}


@dataclass
class TrackState:
    center: tuple[float, float]
    first_seen: datetime
    last_seen: datetime
    still_since: datetime


class ProductivityEngine:
    def __init__(
        self,
        idle_seconds: float = 30.0,
        still_distance_px: float = 18.0,
        machine_proximity_px: float = 140.0,
    ) -> None:
        self.idle_seconds = idle_seconds
        self.still_distance_px = still_distance_px
        self.machine_proximity_px = machine_proximity_px
        self._tracks: dict[tuple[str, int], TrackState] = {}

    def analyze(self, camera_id: str, objects: list[TrackedObject], timestamp: datetime) -> dict:
        people = [obj for obj in objects if classify_object(obj.class_name) == "person"]
        machines = [obj for obj in objects if classify_object(obj.class_name) == "machine"]
        phones = [obj for obj in objects if classify_object(obj.class_name) == "phone"]
        signals: list[dict] = []

        for person in people:
            state = self._update_track(camera_id, person, timestamp)
            idle_for = max(0.0, (timestamp - state.still_since).total_seconds())
            if idle_for >= self.idle_seconds:
                signals.append(
                    {
                        "type": "person_idle",
                        "severity": "attention",
                        "label": "Pessoa parada por tempo prolongado",
                        "track_id": person.track_id,
                        "duration_seconds": round(idle_for, 1),
                        "confidence": person.confidence,
                    }
                )

            if any(_boxes_near(person.bounding_box, phone.bounding_box, 80.0) for phone in phones):
                signals.append(
                    {
                        "type": "possible_phone_use",
                        "severity": "attention",
                        "label": "Possível uso de celular",
                        "track_id": person.track_id,
                        "confidence": person.confidence,
                    }
                )

            near_machine = [
                machine for machine in machines
                if _boxes_near(person.bounding_box, machine.bounding_box, self.machine_proximity_px)
            ]
            if near_machine:
                signals.append(
                    {
                        "type": "person_near_machine",
                        "severity": "info",
                        "label": "Pessoa próxima de máquina",
                        "track_id": person.track_id,
                        "machine_track_id": near_machine[0].track_id,
                        "confidence": min(person.confidence, near_machine[0].confidence),
                    }
                )

        for machine in machines:
            state = self._update_track(camera_id, machine, timestamp)
            still_for = max(0.0, (timestamp - state.still_since).total_seconds())
            if still_for >= self.idle_seconds:
                signals.append(
                    {
                        "type": "machine_stationary",
                        "severity": "info",
                        "label": "Máquina parada por tempo prolongado",
                        "track_id": machine.track_id,
                        "class_name": machine.class_name,
                        "duration_seconds": round(still_for, 1),
                        "confidence": machine.confidence,
                    }
                )

        active_people = max(0, len(people) - len([s for s in signals if s["type"] == "person_idle"]))
        score = 100
        score -= 18 * len([s for s in signals if s["type"] == "person_idle"])
        score -= 12 * len([s for s in signals if s["type"] == "possible_phone_use"])
        score = max(0, min(100, score))

        return {
            "camera_id": camera_id,
            "timestamp": timestamp.isoformat(),
            "score": score,
            "counts": {
                "people": len(people),
                "active_people": active_people,
                "idle_people": len([s for s in signals if s["type"] == "person_idle"]),
                "machines": len(machines),
                "phones": len(phones),
            },
            "signals": signals,
            "machines": [machine.as_dict() | {"category": "machine"} for machine in machines],
            "people": [person.as_dict() | {"category": "person"} for person in people],
            "limitations": [
                "Celular e máquinas específicas dependem das classes reconhecidas pelo detector.",
                "Produtividade é inferida por sinais objetivos; revisão humana continua recomendada.",
            ],
        }

    def reset(self, camera_id: str | None = None) -> None:
        if camera_id is None:
            self._tracks.clear()
            return
        for key in list(self._tracks):
            if key[0] == camera_id:
                self._tracks.pop(key, None)

    def _update_track(self, camera_id: str, obj: TrackedObject, timestamp: datetime) -> TrackState:
        key = (camera_id, obj.track_id)
        center = _center(obj.bounding_box)
        previous = self._tracks.get(key)
        if previous is None:
            state = TrackState(center, timestamp, timestamp, timestamp)
            self._tracks[key] = state
            return state

        moved = hypot(center[0] - previous.center[0], center[1] - previous.center[1])
        still_since = previous.still_since if moved <= self.still_distance_px else timestamp
        state = TrackState(center, previous.first_seen, timestamp, still_since)
        self._tracks[key] = state
        return state


def classify_object(class_name: str) -> str:
    normalized = class_name.strip().lower().replace("_", " ")
    if normalized in PERSON_CLASSES:
        return "person"
    if normalized in PHONE_CLASSES:
        return "phone"
    if normalized in MACHINE_CLASSES:
        return "machine"
    return "object"


def _center(box: BoundingBox) -> tuple[float, float]:
    return ((box.x1 + box.x2) / 2, (box.y1 + box.y2) / 2)


def _boxes_near(first: BoundingBox, second: BoundingBox, max_distance: float) -> bool:
    a = _center(first)
    b = _center(second)
    return hypot(a[0] - b[0], a[1] - b[1]) <= max_distance
