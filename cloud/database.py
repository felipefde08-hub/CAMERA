from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.config import ROOT


DATABASE_URL = os.getenv("DATABASE_URL", "")
SQLITE_CLOUD_PATH = Path(os.getenv("CLOUD_SQLITE_PATH", str(ROOT / "data" / "campex_cloud.sqlite3")))


def is_postgres_url(url: str | None = None) -> bool:
    value = url if url is not None else DATABASE_URL
    return value.startswith("postgres://") or value.startswith("postgresql://")


@contextmanager
def connect():
    if is_postgres_url():
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("psycopg precisa estar instalado para usar PostgreSQL.") from exc
        with psycopg.connect(DATABASE_URL, row_factory=dict_row) as connection:
            yield PostgresConnection(connection)
        return
    SQLITE_CLOUD_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(SQLITE_CLOUD_PATH) as connection:
        connection.row_factory = sqlite3.Row
        yield SQLiteConnection(connection)


class SQLiteConnection:
    param = "?"

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def execute(self, sql: str, values: tuple = ()):
        return self.connection.execute(sql, values)

    def fetchone(self, sql: str, values: tuple = ()):
        row = self.connection.execute(sql, values).fetchone()
        return dict(row) if row else None

    def fetchall(self, sql: str, values: tuple = ()):
        return [dict(row) for row in self.connection.execute(sql, values).fetchall()]

    def commit(self) -> None:
        self.connection.commit()


class PostgresConnection:
    param = "%s"

    def __init__(self, connection) -> None:
        self.connection = connection

    def _sql(self, sql: str) -> str:
        return sql.replace("?", "%s")

    def execute(self, sql: str, values: tuple = ()):
        return self.connection.execute(self._sql(sql), values)

    def fetchone(self, sql: str, values: tuple = ()):
        cursor = self.connection.execute(self._sql(sql), values)
        return cursor.fetchone()

    def fetchall(self, sql: str, values: tuple = ()):
        cursor = self.connection.execute(self._sql(sql), values)
        return list(cursor.fetchall())

    def commit(self) -> None:
        self.connection.commit()


def init_cloud_db(db=None) -> None:
    if db is None:
        with connect() as connection:
            init_cloud_db(connection)
        return
    if isinstance(db, PostgresConnection):
        _init_postgres(db)
    else:
        _init_sqlite(db)
    db.commit()


def _init_sqlite(db: SQLiteConnection) -> None:
    db.connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS edge_devices (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            cliente_id TEXT NOT NULL,
            unidade_id TEXT NOT NULL,
            nome TEXT NOT NULL,
            secret_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            revoked_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS edge_events (
            id TEXT PRIMARY KEY,
            event_uuid TEXT NOT NULL UNIQUE,
            tenant_id TEXT NOT NULL,
            cliente_id TEXT NOT NULL,
            unidade_id TEXT NOT NULL,
            edge_id TEXT NOT NULL,
            camera_id TEXT NOT NULL,
            tipo TEXT NOT NULL,
            inicio TEXT,
            fim TEXT,
            duracao REAL,
            operador_presente INTEGER,
            confianca REAL,
            severidade TEXT,
            status TEXT,
            midia_path TEXT,
            payload_json TEXT NOT NULL,
            received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    _ensure_sqlite_column(db, "edge_events", "severidade", "TEXT")
    _ensure_sqlite_column(db, "edge_events", "status", "TEXT")


def _init_postgres(db: PostgresConnection) -> None:
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS edge_devices (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            cliente_id TEXT NOT NULL,
            unidade_id TEXT NOT NULL,
            nome TEXT NOT NULL,
            secret_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            revoked_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS edge_events (
            id TEXT PRIMARY KEY,
            event_uuid TEXT NOT NULL UNIQUE,
            tenant_id TEXT NOT NULL,
            cliente_id TEXT NOT NULL,
            unidade_id TEXT NOT NULL,
            edge_id TEXT NOT NULL REFERENCES edge_devices(id),
            camera_id TEXT NOT NULL,
            tipo TEXT NOT NULL,
            inicio TIMESTAMPTZ,
            fim TIMESTAMPTZ,
            duracao DOUBLE PRECISION,
            operador_presente BOOLEAN,
            confianca DOUBLE PRECISION,
            severidade TEXT,
            status TEXT,
            midia_path TEXT,
            payload_json TEXT NOT NULL,
            received_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    db.execute("ALTER TABLE edge_events ADD COLUMN IF NOT EXISTS severidade TEXT")
    db.execute("ALTER TABLE edge_events ADD COLUMN IF NOT EXISTS status TEXT")


def _ensure_sqlite_column(db: SQLiteConnection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in db.connection.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        db.connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
