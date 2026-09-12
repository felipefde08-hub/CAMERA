from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


@dataclass
class Event:
    """A structured operational event generated from observations.

    Events represent meaningful operational situations (e.g., a person
    entered a restricted zone) and feed the operator interface.
    """

    id: str
    type: str
    camera_id: str
    zone_id: str | None
    track_id: int | None
    severity: str  # "info", "attention", "critical"
    status: str  # "OPEN", "REVIEWED", "CLOSED"
    confidence: float | None
    started_at: str
    ended_at: str | None
    duration: float | None
    metadata: dict[str, Any]
    created_at: str
    updated_at: str

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "camera_id": self.camera_id,
            "zone_id": self.zone_id,
            "track_id": self.track_id,
            "severity": self.severity,
            "status": self.status,
            "confidence": self.confidence,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration": self.duration,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class EventRule:
    """A simple rule that maps an observation type + zone type to an event type.

    Rules evaluate deterministic conditions — no AI reasoning needed.
    """

    name: str
    observation_type: str  # e.g., "person_entered_zone"
    zone_type: str | None  # e.g., "restricted", or None for any
    event_type: str  # e.g., "person_restricted_zone"
    severity: str  # "info", "attention", "critical"
    duration_threshold_seconds: float = 0.0  # 0 = immediate
    cooldown_seconds: float = 10.0
    id: str | None = None
    camera_id: str | None = None
    zone_id: str | None = None
    enabled: bool = True

    def matches(
        self,
        observation_type: str,
        zone_type: str | None,
        camera_id: str | None = None,
        zone_id: str | None = None,
    ) -> bool:
        if not self.enabled:
            return False
        if self.observation_type != observation_type:
            return False
        if self.zone_type is not None and self.zone_type != zone_type:
            return False
        if self.camera_id is not None and self.camera_id != camera_id:
            return False
        if self.zone_id is not None and self.zone_id != zone_id:
            return False
        return True
