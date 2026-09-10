from __future__ import annotations

import sqlite3
from pathlib import Path

from backend.config import Settings


SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS app_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cameras (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        area_id TEXT,
        source_type TEXT NOT NULL CHECK(source_type IN ('webcam', 'video_file', 'rtsp')),
        source_uri TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        vision_enabled INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'OFFLINE'
            CHECK(status IN ('CONNECTING', 'ONLINE', 'DEGRADED', 'OFFLINE')),
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
)


def connect(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database(settings: Settings) -> Path:
    database_path = settings.sqlite_path
    database_path.parent.mkdir(parents=True, exist_ok=True)

    with connect(database_path) as connection:
        for statement in SCHEMA_STATEMENTS:
            connection.execute(statement)
        connection.execute(
            """
            INSERT INTO app_meta (key, value, updated_at)
            VALUES ('schema_version', '1', CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = CURRENT_TIMESTAMP
            """
        )
        connection.commit()

    return database_path


def database_is_initialized(settings: Settings) -> bool:
    database_path = settings.sqlite_path
    if not database_path.exists():
        return False

    with connect(database_path) as connection:
        result = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'app_meta'"
        ).fetchone()
        return result is not None
