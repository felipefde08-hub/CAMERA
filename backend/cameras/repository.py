from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from backend.cameras.models import Camera
from backend.config import Settings
from backend.database.db import connect


def _row_to_camera(row) -> Camera:
    return Camera(
        id=row["id"],
        name=row["name"],
        area_id=row["area_id"],
        source_type=row["source_type"],
        source_uri=row["source_uri"],
        enabled=bool(row["enabled"]),
        vision_enabled=bool(row["vision_enabled"]),
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class CameraRepository:
    def __init__(self, settings: Settings) -> None:
        self.database_path: Path = settings.sqlite_path

    def list(self) -> list[Camera]:
        with connect(self.database_path) as connection:
            rows = connection.execute(
                "SELECT * FROM cameras ORDER BY created_at DESC"
            ).fetchall()
        return [_row_to_camera(row) for row in rows]

    def get(self, camera_id: str) -> Camera | None:
        with connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT * FROM cameras WHERE id = ?", (camera_id,)
            ).fetchone()
        return _row_to_camera(row) if row else None

    def create(
        self,
        *,
        name: str,
        area_id: str | None,
        source_type: str,
        source_uri: str,
        enabled: bool,
        vision_enabled: bool,
    ) -> Camera:
        camera_id = f"cam_{uuid4().hex[:12]}"
        with connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO cameras (
                    id, name, area_id, source_type, source_uri,
                    enabled, vision_enabled, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'OFFLINE')
                """,
                (
                    camera_id,
                    name,
                    area_id,
                    source_type,
                    source_uri,
                    int(enabled),
                    int(vision_enabled),
                ),
            )
            connection.commit()
        camera = self.get(camera_id)
        if camera is None:
            raise RuntimeError("Camera was not persisted.")
        return camera

    def update(self, camera_id: str, updates: dict) -> Camera | None:
        allowed = {
            "name",
            "area_id",
            "source_type",
            "source_uri",
            "enabled",
            "vision_enabled",
            "status",
        }
        fields = [key for key in updates if key in allowed]
        if not fields:
            return self.get(camera_id)

        values = [
            int(updates[field])
            if field in {"enabled", "vision_enabled"}
            else updates[field]
            for field in fields
        ]
        assignments = ", ".join(f"{field} = ?" for field in fields)
        with connect(self.database_path) as connection:
            connection.execute(
                f"""
                UPDATE cameras
                SET {assignments}, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (*values, camera_id),
            )
            connection.commit()
        return self.get(camera_id)

    def delete(self, camera_id: str) -> bool:
        with connect(self.database_path) as connection:
            cursor = connection.execute("DELETE FROM cameras WHERE id = ?", (camera_id,))
            connection.commit()
            return cursor.rowcount > 0
