from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent


def _env_list(name: str, default: str) -> list[str]:
    raw_value = os.getenv(name, default)
    return [item.strip() for item in raw_value.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    environment: str
    service_name: str
    version: str
    log_level: str
    database_url: str
    frontend_origins: list[str]
    camera_reconnect_seconds: float
    camera_stale_seconds: float
    camera_read_failure_limit: int
    camera_test_timeout_seconds: float
    vision_enabled: bool
    vision_detector: str
    vision_device: str
    vision_fps: float
    vision_confidence: float
    vision_video_loop: bool
    api_token: str | None = None
    vision_full_scan_seconds: float = 6.0
    vision_tracker_lost_buffer: int = 30

    def __post_init__(self) -> None:
        if self.camera_reconnect_seconds < 0:
            raise ValueError("CAMERA_RECONNECT_SECONDS must be non-negative.")
        if self.camera_stale_seconds <= 0:
            raise ValueError("CAMERA_STALE_SECONDS must be greater than zero.")
        if self.camera_read_failure_limit < 1:
            raise ValueError("CAMERA_READ_FAILURE_LIMIT must be at least 1.")
        if self.camera_test_timeout_seconds <= 0:
            raise ValueError("CAMERA_TEST_TIMEOUT_SECONDS must be greater than zero.")
        if self.vision_fps <= 0:
            raise ValueError("VISION_FPS must be greater than zero.")
        if not 0.0 <= self.vision_confidence <= 1.0:
            raise ValueError("VISION_CONFIDENCE must be between 0 and 1.")
        if self.vision_full_scan_seconds <= 0:
            raise ValueError("VISION_FULL_SCAN_SECONDS must be greater than zero.")
        if self.vision_tracker_lost_buffer < 1:
            raise ValueError("VISION_TRACKER_LOST_BUFFER must be at least 1.")

    @property
    def sqlite_path(self) -> Path:
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix):
            raise ValueError("Sprint 0 supports only sqlite:/// DATABASE_URL values.")

        raw_path = self.database_url.removeprefix(prefix)
        db_path = Path(raw_path)
        if not db_path.is_absolute():
            db_path = ROOT_DIR / db_path
        return db_path.resolve()

    @classmethod









    def from_env(cls) -> "Settings":
        return cls(
            environment=os.getenv("CAMPEX_ENV", "development"),
            service_name=os.getenv("CAMPEX_SERVICE_NAME", "campex"),
            version=os.getenv("CAMPEX_VERSION", "0.1.0"),
            log_level=os.getenv("CAMPEX_LOG_LEVEL", "INFO").upper(),
            database_url=os.getenv(
                "DATABASE_URL", "sqlite:///./storage/campex_dev.sqlite3"
            ),
            frontend_origins=_env_list(
                "CAMPEX_FRONTEND_ORIGINS",
                "*",
            ),
            camera_reconnect_seconds=float(os.getenv("CAMERA_RECONNECT_SECONDS", "5")),
            camera_stale_seconds=float(os.getenv("CAMERA_STALE_SECONDS", "10")),
            camera_read_failure_limit=int(os.getenv("CAMERA_READ_FAILURE_LIMIT", "3")),
            camera_test_timeout_seconds=float(
                os.getenv("CAMERA_TEST_TIMEOUT_SECONDS", "5")
            ),
            vision_enabled=os.getenv("VISION_ENABLED", "true").lower()
            in {"1", "true", "yes", "on"},
            vision_detector=os.getenv("VISION_DETECTOR", "rfdetr").lower(),
            vision_device=os.getenv("VISION_DEVICE", "auto").lower(),
            vision_fps=float(os.getenv("VISION_FPS", "5")),
            vision_confidence=float(os.getenv("VISION_CONFIDENCE", "0.50")),
            vision_video_loop=os.getenv("VISION_VIDEO_LOOP", "true").lower()
            in {"1", "true", "yes", "on"},
            api_token=os.getenv("CAMPEX_API_TOKEN") or None,
            vision_full_scan_seconds=float(
                os.getenv("VISION_FULL_SCAN_SECONDS", "6")
            ),
            vision_tracker_lost_buffer=int(
                os.getenv("VISION_TRACKER_LOST_BUFFER", "30")
            ),
        )


def get_settings() -> Settings:
    return Settings.from_env()
