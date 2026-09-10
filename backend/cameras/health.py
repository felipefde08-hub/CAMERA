from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class CameraStatus(StrEnum):
    CONNECTING = "CONNECTING"
    ONLINE = "ONLINE"
    DEGRADED = "DEGRADED"
    OFFLINE = "OFFLINE"


@dataclass
class Resolution:
    width: int
    height: int


@dataclass
class CameraHealth:
    camera_id: str
    status: CameraStatus
    last_successful_frame: datetime | None = None
    last_error: str | None = None
    resolution: Resolution | None = None
    approximate_fps: float | None = None
    reconnect_attempts: int = 0
    frames_received: int = 0

    def as_dict(self) -> dict:
        return {
            "camera_id": self.camera_id,
            "status": self.status.value,
            "last_successful_frame": (
                self.last_successful_frame.isoformat()
                if self.last_successful_frame
                else None
            ),
            "last_error": self.last_error,
            "resolution": (
                {
                    "width": self.resolution.width,
                    "height": self.resolution.height,
                }
                if self.resolution
                else None
            ),
            "approximate_fps": self.approximate_fps,
            "reconnect_attempts": self.reconnect_attempts,
            "frames_received": self.frames_received,
        }


def utc_now() -> datetime:
    return datetime.now(UTC)
