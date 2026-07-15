from __future__ import annotations

import sqlite3
from pathlib import Path

from app.config import DATABASE_PATH


def connect(db_path: str | Path = DATABASE_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS clientes (
            id TEXT PRIMARY KEY,
            nome TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'ativo',
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS unidades (
            id TEXT PRIMARY KEY,
            cliente_id TEXT NOT NULL,
            nome TEXT NOT NULL,
            localizacao TEXT,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (cliente_id) REFERENCES clientes (id)
        );

        CREATE TABLE IF NOT EXISTS dispositivos (
            id TEXT PRIMARY KEY,
            unidade_id TEXT NOT NULL,
            nome TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'offline',
            ultimo_contato TEXT,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (unidade_id) REFERENCES unidades (id)
        );

        CREATE TABLE IF NOT EXISTS cameras (
            id TEXT PRIMARY KEY,
            cliente_id TEXT,
            unidade_id TEXT NOT NULL,
            dispositivo_id TEXT,
            edge_id TEXT,
            nome TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'nao_conectada',
            config_ref TEXT,
            source_type TEXT,
            secure_ref TEXT,
            ultimo_frame TEXT,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (cliente_id) REFERENCES clientes (id),
            FOREIGN KEY (unidade_id) REFERENCES unidades (id),
            FOREIGN KEY (dispositivo_id) REFERENCES dispositivos (id)
        );

        CREATE TABLE IF NOT EXISTS regras (
            id TEXT PRIMARY KEY,
            camera_id TEXT NOT NULL,
            tipo_evento TEXT NOT NULL,
            tempo_minimo REAL NOT NULL DEFAULT 0,
            ativo INTEGER NOT NULL DEFAULT 1,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (camera_id) REFERENCES cameras (id)
        );

        CREATE TABLE IF NOT EXISTS eventos (
            id TEXT PRIMARY KEY,
            cliente_id TEXT NOT NULL,
            unidade_id TEXT NOT NULL,
            camera_id TEXT NOT NULL,
            tipo TEXT NOT NULL,
            inicio TEXT NOT NULL,
            fim TEXT,
            duracao REAL,
            operador_presente INTEGER,
            confianca REAL,
            midia_path TEXT,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (cliente_id) REFERENCES clientes (id),
            FOREIGN KEY (unidade_id) REFERENCES unidades (id),
            FOREIGN KEY (camera_id) REFERENCES cameras (id)
        );

        CREATE TABLE IF NOT EXISTS alertas (
            id TEXT PRIMARY KEY,
            evento_id TEXT NOT NULL,
            canal TEXT NOT NULL,
            destinatario TEXT,
            status TEXT NOT NULL DEFAULT 'pendente',
            horario TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (evento_id) REFERENCES eventos (id)
        );

        CREATE TABLE IF NOT EXISTS edge_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            edge_id TEXT NOT NULL,
            recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            uptime_seconds REAL NOT NULL,
            cpu_percent REAL,
            memory_percent REAL,
            active_cameras INTEGER NOT NULL DEFAULT 0,
            frames_processed INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    _ensure_column(connection, "cameras", "cliente_id", "TEXT")
    _ensure_column(connection, "cameras", "edge_id", "TEXT")
    _ensure_column(connection, "cameras", "source_type", "TEXT")
    _ensure_column(connection, "cameras", "secure_ref", "TEXT")
    _ensure_column(connection, "cameras", "ultimo_frame", "TEXT")
    _ensure_column(connection, "cameras", "ultimo_erro", "TEXT")
    _ensure_column(connection, "cameras", "reconexoes", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(connection, "cameras", "frames_processados", "INTEGER NOT NULL DEFAULT 0")
    connection.commit()


def _ensure_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
