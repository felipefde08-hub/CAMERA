from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from shared.schemas import now_iso


@dataclass
class MachineObservationTracker:
    state_since: float = field(default_factory=time.monotonic)
    last_state: str = "UNKNOWN"

    def duration(self, state: str, now: float) -> float:
        if state != self.last_state:
            self.last_state = state
            self.state_since = now
        return max(0.0, now - self.state_since)


class ObservationEngine:
    def __init__(self, camera_id: str) -> None:
        self.camera_id = camera_id
        self._trackers: dict[str, MachineObservationTracker] = {}

    def build(
        self,
        *,
        machine_id: str | None,
        machine_state: str,
        machine_activity_score: float | None,
        machine_confidence: float | None,
        operator_present: bool,
        zone_states: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        now = time.monotonic()
        machine_key = machine_id or self.camera_id
        tracker = self._trackers.setdefault(machine_key, MachineObservationTracker())
        counts = self._zone_counts(zone_states or [])
        return {
            "timestamp": now_iso(),
            "camera_id": self.camera_id,
            "machine_id": machine_id,
            "machine_state": machine_state if machine_state in {"ACTIVE", "STOPPED", "UNKNOWN"} else "UNKNOWN",
            "machine_activity_score": round(float(machine_activity_score or 0.0), 3),
            "machine_confidence": round(float(machine_confidence or 0.0), 3),
            "operator_present": bool(operator_present),
            "people_in_operator_zone": counts["operator_zone"],
            "people_in_restricted_zone": counts["restricted_zone"],
            "people_in_work_area": counts["work_area"],
            "seconds_in_machine_state": round(tracker.duration(machine_state, now), 2),
        }

    def _zone_counts(self, zone_states: list[dict[str, Any]]) -> dict[str, int]:
        counts = {"operator_zone": 0, "restricted_zone": 0, "work_area": 0}
        for zone in zone_states:
            zone_type = normalize_zone_type(str(zone.get("tipo") or ""))
            if zone_type in counts:
                counts[zone_type] += int(zone.get("pessoas_dentro") or 0)
        return counts


def normalize_zone_type(zone_type: str) -> str:
    aliases = {
        "restricted_area": "restricted_zone",
        "workstation": "operator_zone",
        "dwell_area": "work_area",
    }
    return aliases.get(zone_type, zone_type)
