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

        CREATE TABLE IF NOT EXISTS monitored_areas (
            id TEXT PRIMARY KEY,
            camera_id TEXT NOT NULL,
            nome TEXT NOT NULL,
            tipo TEXT NOT NULL DEFAULT 'restricted_area',
            pontos_json TEXT NOT NULL,
            ativa INTEGER NOT NULL DEFAULT 1,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (camera_id) REFERENCES cameras (id)
        );

        CREATE TABLE IF NOT EXISTS alert_recipients (
            id TEXT PRIMARY KEY,
            nome TEXT NOT NULL,
            email TEXT NOT NULL,
            ativo INTEGER NOT NULL DEFAULT 1,
            camera_id TEXT,
            area_id TEXT,
            severidade_minima TEXT NOT NULL DEFAULT 'low',
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (camera_id) REFERENCES cameras (id),
            FOREIGN KEY (area_id) REFERENCES monitored_areas (id)
        );

        CREATE TABLE IF NOT EXISTS alert_deliveries (
            id TEXT PRIMARY KEY,
            evento_id TEXT,
            recipient_id TEXT NOT NULL,
            canal TEXT NOT NULL DEFAULT 'email',
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            last_attempt_at TEXT,
            next_attempt_at TEXT,
            sent_at TEXT,
            erro TEXT,
            is_test INTEGER NOT NULL DEFAULT 0,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (evento_id, recipient_id, canal),
            FOREIGN KEY (evento_id) REFERENCES eventos (id),
            FOREIGN KEY (recipient_id) REFERENCES alert_recipients (id)
        );

        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            cliente_id TEXT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            ativo INTEGER NOT NULL DEFAULT 1,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (cliente_id) REFERENCES clientes (id)
        );

        CREATE TABLE IF NOT EXISTS user_sessions (
            token_hash TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS technical_notices (
            id TEXT PRIMARY KEY,
            cliente_id TEXT,
            camera_id TEXT,
            component TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            inicio TEXT NOT NULL,
            fim TEXT,
            erro TEXT,
            email_sent INTEGER NOT NULL DEFAULT 0,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (cliente_id) REFERENCES clientes (id),
            FOREIGN KEY (camera_id) REFERENCES cameras (id)
        );

        CREATE TABLE IF NOT EXISTS installation_state (
            key TEXT PRIMARY KEY,
            value TEXT,
            atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS machine_monitors (
            id TEXT PRIMARY KEY,
            client_id TEXT NOT NULL,
            unit_id TEXT NOT NULL,
            camera_id TEXT NOT NULL,
            nome TEXT NOT NULL,
            machine_polygon_json TEXT NOT NULL,
            operator_polygon_json TEXT NOT NULL,
            ativo INTEGER NOT NULL DEFAULT 1,
            motion_sensitivity REAL NOT NULL DEFAULT 25.0,
            motion_threshold REAL,
            stop_seconds REAL NOT NULL DEFAULT 10.0,
            recovery_seconds REAL NOT NULL DEFAULT 3.0,
            replay_pre_seconds REAL NOT NULL DEFAULT 60.0,
            replay_post_seconds REAL NOT NULL DEFAULT 30.0,
            calibration_status TEXT NOT NULL DEFAULT 'not_calibrated',
            running_motion REAL,
            stopped_motion REAL,
            current_state TEXT NOT NULL DEFAULT 'unavailable',
            current_motion REAL,
            operator_present INTEGER NOT NULL DEFAULT 0,
            last_state_change TEXT,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (client_id) REFERENCES clientes (id),
            FOREIGN KEY (unit_id) REFERENCES unidades (id),
            FOREIGN KEY (camera_id) REFERENCES cameras (id)
        );

        CREATE TABLE IF NOT EXISTS operational_events (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            camera_id TEXT,
            machine_name TEXT,
            event_type TEXT NOT NULL,
            previous_state TEXT,
            new_state TEXT NOT NULL,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            duration_seconds REAL,
            confidence REAL,
            activity_score REAL,
            people_count INTEGER NOT NULL DEFAULT 0,
            snapshot_path TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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
    _ensure_column(connection, "cameras", "rtsp_host", "TEXT")
    _ensure_column(connection, "cameras", "rtsp_port", "INTEGER")
    _ensure_column(connection, "cameras", "rtsp_path", "TEXT")
    _ensure_column(connection, "cameras", "rtsp_username", "TEXT")
    _ensure_column(connection, "cameras", "rtsp_password", "TEXT")
    _ensure_column(connection, "cameras", "rtsp_password_encrypted", "TEXT")
    _ensure_column(connection, "cameras", "monitoring_enabled", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(connection, "cameras", "analysis_enabled", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(connection, "cameras", "resolucao", "TEXT")
    _ensure_column(connection, "cameras", "fps", "REAL")
    _ensure_column(connection, "eventos", "area_id", "TEXT")
    _ensure_column(connection, "eventos", "regra_id", "TEXT")
    _ensure_column(connection, "eventos", "severidade", "TEXT NOT NULL DEFAULT 'high'")
    _ensure_column(connection, "eventos", "status", "TEXT NOT NULL DEFAULT 'closed'")
    _ensure_column(connection, "eventos", "quantidade_inicial", "INTEGER")
    _ensure_column(connection, "eventos", "quantidade_atual", "INTEGER")
    _ensure_column(connection, "eventos", "quantidade_maxima", "INTEGER")
    _ensure_column(connection, "eventos", "track_ids_json", "TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(connection, "eventos", "observacao", "TEXT")
    _ensure_column(connection, "eventos", "acknowledged_at", "TEXT")
    _ensure_column(connection, "eventos", "acknowledged_by", "TEXT")
    _ensure_column(connection, "eventos", "ultimo_ocupado_em", "TEXT")
    _ensure_column(connection, "eventos", "evidence_error", "TEXT")
    _ensure_column(connection, "eventos", "atualizado_em", "TEXT")
    _ensure_column(connection, "eventos", "machine_monitor_id", "TEXT")
    _ensure_column(connection, "eventos", "motion_level", "REAL")
    _ensure_column(connection, "eventos", "operator_present_start", "INTEGER")
    _ensure_column(connection, "eventos", "operator_present_seconds", "REAL")
    _ensure_column(connection, "eventos", "operator_absent_seconds", "REAL")
    _ensure_column(connection, "eventos", "max_people", "INTEGER")
    _ensure_column(connection, "eventos", "replay_path", "TEXT")
    _ensure_column(connection, "eventos", "replay_error", "TEXT")
    _ensure_column(connection, "eventos", "cause_category", "TEXT")
    _ensure_column(connection, "eventos", "cause_notes", "TEXT")
    _ensure_column(connection, "eventos", "classified_at", "TEXT")
    _ensure_column(connection, "eventos", "classified_by", "TEXT")
    _ensure_column(connection, "operational_events", "activity_score", "REAL")
    _ensure_column(connection, "operational_events", "snapshot_path", "TEXT")
    connection.commit()


def _ensure_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
