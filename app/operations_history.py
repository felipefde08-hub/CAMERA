from __future__ import annotations

import logging
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.config import ROOT
from app.database import connect, init_db
from shared.schemas import now_iso

LOGGER = logging.getLogger(__name__)

SNAPSHOT_EVENT_STATES = {
    ("machine_state", "PARADA"),
    ("machine_state", "ATIVA"),
    ("operator_presence", "PRESENTE"),
    ("camera_status", "offline"),
}


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    if len(normalized) >= 6 and normalized[-6] == " " and normalized[-3] == ":":
        normalized = f"{normalized[:-6]}+{normalized[-5:]}"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso_at(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def row_to_event(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    return data


def init_operations_db(connection: sqlite3.Connection) -> None:
    init_db(connection)


def insert_operational_event(
    connection: sqlite3.Connection,
    session_id: str,
    camera_id: str | None,
    machine_name: str | None,
    event_type: str,
    previous_state: str | None,
    new_state: str,
    started_at: str,
    confidence: float | None = None,
    activity_score: float | None = None,
    people_count: int = 0,
    snapshot_path: str | None = None,
) -> str:
    event_id = new_id("op")
    connection.execute(
        """
        INSERT INTO operational_events (
            id, session_id, camera_id, machine_name, event_type, previous_state,
            new_state, started_at, confidence, activity_score, people_count,
            snapshot_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            session_id,
            camera_id,
            machine_name,
            event_type,
            previous_state,
            new_state,
            started_at,
            confidence,
            activity_score,
            int(people_count or 0),
            snapshot_path,
        ),
    )
    connection.commit()
    return event_id


def close_open_operational_event(
    connection: sqlite3.Connection,
    session_id: str,
    event_type: str,
    ended_at: str,
) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT *
        FROM operational_events
        WHERE session_id = ? AND event_type = ? AND ended_at IS NULL
        ORDER BY started_at DESC
        LIMIT 1
        """,
        (session_id, event_type),
    ).fetchone()
    if row is None:
        return None
    started = parse_iso(row["started_at"])
    ended = parse_iso(ended_at)
    duration = max(0.0, (ended - started).total_seconds()) if started and ended else None
    connection.execute(
        """
        UPDATE operational_events
        SET ended_at = ?, duration_seconds = ?
        WHERE id = ?
        """,
        (ended_at, duration, row["id"]),
    )
    connection.commit()
    updated = dict(row)
    updated["ended_at"] = ended_at
    updated["duration_seconds"] = duration
    return updated


def list_operational_events(
    connection: sqlite3.Connection,
    start: str | None = None,
    end: str | None = None,
    camera_id: str | None = None,
    machine_name: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    values: list[Any] = []
    if start:
        clauses.append("COALESCE(ended_at, ?) >= ?")
        values.extend([now_iso(), start])
    if end:
        clauses.append("started_at <= ?")
        values.append(end)
    if camera_id:
        clauses.append("camera_id = ?")
        values.append(camera_id)
    if machine_name:
        clauses.append("machine_name = ?")
        values.append(machine_name)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = connection.execute(
        f"""
        SELECT *
        FROM operational_events
        {where}
        ORDER BY started_at DESC, created_at DESC, rowid DESC
        LIMIT ? OFFSET ?
        """,
        [*values, max(1, min(limit, 200)), max(0, offset)],
    ).fetchall()
    return [row_to_event(row) for row in rows]


@dataclass
class OperationalSnapshot:
    session_id: str
    camera_id: str
    machine_name: str | None
    machine_state: str
    operator_state: str
    camera_status: str
    calibration_status: str
    confidence: float | None
    activity_score: float | None
    people_count: int


class OperationsRecorder:
    def __init__(self, session_id: str, camera_id: str | None = None, evidence_root: Path | None = None) -> None:
        self.session_id = session_id
        self.camera_id = self._persistent_camera_id(camera_id)
        self.evidence_root = evidence_root or (ROOT / "data" / "operations_snapshots")
        self._states: dict[str, str] = {}

    @staticmethod
    def _persistent_camera_id(camera_id: str | None) -> str | None:
        if not camera_id or camera_id.startswith("live_"):
            return None
        return camera_id

    def update_status(
        self,
        camera_status: str,
        ops_state: dict[str, Any] | None,
        frame: np.ndarray | None = None,
    ) -> None:
        machine = (ops_state or {}).get("machine") if ops_state else None
        snapshot = OperationalSnapshot(
            session_id=self.session_id,
            camera_id=self.camera_id or self.session_id,
            machine_name=machine.get("nome") if machine else None,
            machine_state=str((ops_state or {}).get("machine_state") or "NAO_CONFIGURADA"),
            operator_state="PRESENTE" if (ops_state or {}).get("operator_present") else "AUSENTE",
            camera_status="online" if camera_status == "online" else "offline",
            calibration_status=str((ops_state or {}).get("calibration_status") or "não calibrada"),
            confidence=(ops_state or {}).get("visual_confidence"),
            activity_score=(ops_state or {}).get("machine_motion"),
            people_count=int((ops_state or {}).get("people_count") or 0),
        )
        self._transition("camera_status", snapshot.camera_status, snapshot, frame)
        if machine:
            self._transition("machine_state", snapshot.machine_state, snapshot, frame)
            self._transition("operator_presence", snapshot.operator_state, snapshot, frame)
            self._transition("calibration", snapshot.calibration_status, snapshot, frame)
            relation_state = "ATIVA_SEM_OPERADOR" if snapshot.machine_state == "ATIVA" and snapshot.operator_state == "AUSENTE" else "NORMAL"
            self._transition("active_without_operator", relation_state, snapshot, frame)

    def _transition(
        self,
        event_type: str,
        new_state: str,
        snapshot: OperationalSnapshot,
        frame: np.ndarray | None,
    ) -> None:
        previous = self._states.get(event_type)
        if previous is None:
            previous = self._latest_state(event_type)
            if previous is not None:
                self._states[event_type] = previous
        if previous == new_state:
            return
        now = now_iso()
        snapshot_path = self._save_snapshot(event_type, new_state, frame) if self._should_snapshot(event_type, new_state, previous) else None
        try:
            with connect() as connection:
                init_operations_db(connection)
                if self._is_redundant_open_event(connection, event_type, new_state):
                    self._states[event_type] = new_state
                    return
                close_open_operational_event(connection, self.session_id, event_type, now)
                insert_operational_event(
                    connection,
                    self.session_id,
                    self.camera_id,
                    snapshot.machine_name,
                    event_type,
                    previous,
                    new_state,
                    now,
                    confidence=snapshot.confidence,
                    activity_score=snapshot.activity_score,
                    people_count=snapshot.people_count,
                    snapshot_path=snapshot_path,
                )
            self._states[event_type] = new_state
        except Exception:
            LOGGER.exception("Falha ao persistir evento operacional.")

    def _is_redundant_open_event(self, connection: sqlite3.Connection, event_type: str, new_state: str) -> bool:
        row = connection.execute(
            """
            SELECT new_state
            FROM operational_events
            WHERE session_id = ? AND event_type = ? AND ended_at IS NULL
            ORDER BY started_at DESC, created_at DESC, rowid DESC
            LIMIT 1
            """,
            (self.session_id, event_type),
        ).fetchone()
        return bool(row and row["new_state"] == new_state)

    def _latest_state(self, event_type: str) -> str | None:
        try:
            with connect() as connection:
                init_operations_db(connection)
                row = connection.execute(
                    """
                    SELECT new_state
                    FROM operational_events
                    WHERE session_id = ? AND event_type = ?
                    ORDER BY started_at DESC, created_at DESC, rowid DESC
                    LIMIT 1
                    """,
                    (self.session_id, event_type),
                ).fetchone()
                return str(row["new_state"]) if row else None
        except Exception:
            LOGGER.exception("Falha ao recuperar ultimo estado operacional.")
            return None

    def _should_snapshot(self, event_type: str, new_state: str, previous: str | None) -> bool:
        if (event_type, new_state) in SNAPSHOT_EVENT_STATES:
            return True
        return event_type == "active_without_operator" and new_state == "ATIVA_SEM_OPERADOR"

    def _save_snapshot(self, event_type: str, new_state: str, frame: np.ndarray | None) -> str | None:
        if frame is None:
            return None
        try:
            now = datetime.now(timezone.utc).astimezone()
            folder = self.evidence_root / (self.camera_id or self.session_id) / f"{now:%Y}" / f"{now:%m}" / f"{now:%d}"
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{now:%H%M%S}_{event_type}_{new_state}_{uuid.uuid4().hex[:6]}.jpg"
            if not cv2.imwrite(str(path), frame):
                return None
            try:
                return str(path.relative_to(ROOT))
            except ValueError:
                return str(path)
        except Exception:
            LOGGER.exception("Falha ao salvar snapshot operacional.")
            return None


def _overlap_seconds(event: dict[str, Any], start: datetime, end: datetime, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    event_start = parse_iso(event.get("started_at"))
    event_end = parse_iso(event.get("ended_at")) or now
    if event_start is None:
        return 0.0
    left = max(event_start, start)
    right = min(event_end, end)
    return max(0.0, (right - left).total_seconds())


def operations_summary(
    connection: sqlite3.Connection,
    start: str | None,
    end: str | None,
    camera_id: str | None = None,
    machine_name: str | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    end_dt = parse_iso(end) or now
    start_dt = parse_iso(start) or (end_dt - timedelta(days=1))
    events = list_operational_events(connection, iso_at(start_dt), iso_at(end_dt), camera_id, machine_name, limit=200, offset=0)
    events = events + _older_open_events(connection, start_dt, camera_id, machine_name)

    total_monitored = max(0.0, (end_dt - start_dt).total_seconds())
    active = sum(_overlap_seconds(e, start_dt, end_dt, now) for e in events if e["event_type"] == "machine_state" and e["new_state"] == "ATIVA")
    stopped_events = [e for e in events if e["event_type"] == "machine_state" and e["new_state"] == "PARADA"]
    stopped = sum(_overlap_seconds(e, start_dt, end_dt, now) for e in stopped_events)
    active_without_operator = sum(_overlap_seconds(e, start_dt, end_dt, now) for e in events if e["event_type"] == "active_without_operator" and e["new_state"] == "ATIVA_SEM_OPERADOR")
    offline = sum(_overlap_seconds(e, start_dt, end_dt, now) for e in events if e["event_type"] == "camera_status" and e["new_state"] == "offline")
    stop_durations = [_overlap_seconds(e, start_dt, end_dt, now) for e in stopped_events]
    operator_absences = [e for e in events if e["event_type"] == "operator_presence" and e["new_state"] == "AUSENTE"]
    current = current_status(connection, camera_id, machine_name)
    return {
        "period": {"start": iso_at(start_dt), "end": iso_at(end_dt)},
        "tempo_total_monitorado": round(total_monitored, 2),
        "tempo_maquina_ativa": round(active, 2),
        "tempo_maquina_parada": round(stopped, 2),
        "percentual_atividade_estimada": round((active / total_monitored) * 100, 2) if total_monitored else 0,
        "quantidade_paradas": len(stopped_events),
        "duracao_media_paradas": round(sum(stop_durations) / len(stop_durations), 2) if stop_durations else 0,
        "maior_parada": round(max(stop_durations, default=0), 2),
        "tempo_ativa_sem_operador": round(active_without_operator, 2),
        "quantidade_ausencias_operador": len(operator_absences),
        "disponibilidade_camera": round(((total_monitored - offline) / total_monitored) * 100, 2) if total_monitored else 0,
        "situacao_atual_maquina": current.get("machine_state", "NAO_CONFIGURADA"),
        "situacao_atual_operador": current.get("operator_state", "AUSENTE"),
    }


def _older_open_events(
    connection: sqlite3.Connection,
    start_dt: datetime,
    camera_id: str | None,
    machine_name: str | None,
) -> list[dict[str, Any]]:
    clauses = ["started_at < ?", "ended_at IS NULL"]
    values: list[Any] = [iso_at(start_dt)]
    if camera_id:
        clauses.append("camera_id = ?")
        values.append(camera_id)
    if machine_name:
        clauses.append("machine_name = ?")
        values.append(machine_name)
    rows = connection.execute(
        f"SELECT * FROM operational_events WHERE {' AND '.join(clauses)}",
        values,
    ).fetchall()
    return [row_to_event(row) for row in rows]


def current_status(connection: sqlite3.Connection, camera_id: str | None = None, machine_name: str | None = None) -> dict[str, Any]:
    clauses: list[str] = []
    values: list[Any] = []
    if camera_id:
        clauses.append("camera_id = ?")
        values.append(camera_id)
    if machine_name:
        clauses.append("machine_name = ?")
        values.append(machine_name)
    where = f"AND {' AND '.join(clauses)}" if clauses else ""
    status: dict[str, Any] = {
        "machine_state": "NAO_CONFIGURADA",
        "operator_state": "AUSENTE",
        "camera_status": "desconhecida",
        "people_count": 0,
        "machine_name": machine_name,
        "last_update": None,
    }
    mapping = {
        "machine_state": "machine_state",
        "operator_presence": "operator_state",
        "camera_status": "camera_status",
    }
    for event_type, key in mapping.items():
        row = connection.execute(
            f"""
            SELECT *
            FROM operational_events
            WHERE event_type = ? {where}
            ORDER BY started_at DESC, created_at DESC, rowid DESC
            LIMIT 1
            """,
            [event_type, *values],
        ).fetchone()
        if row:
            status[key] = row["new_state"]
            status["people_count"] = max(int(status["people_count"]), int(row["people_count"] or 0))
            status["machine_name"] = row["machine_name"] or status["machine_name"]
            status["last_update"] = row["started_at"]
    return status


def operations_timeline(
    connection: sqlite3.Connection,
    start: str | None,
    end: str | None,
    camera_id: str | None = None,
    machine_name: str | None = None,
) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    end_dt = parse_iso(end) or now
    start_dt = parse_iso(start) or (end_dt - timedelta(days=1))
    events = list_operational_events(connection, iso_at(start_dt), iso_at(end_dt), camera_id, machine_name, limit=200, offset=0)
    items = []
    for event in sorted(events, key=lambda item: item["started_at"]):
        if event["event_type"] == "machine_state" and event["new_state"] not in {"ATIVA", "PARADA", "CALIBRANDO", "SEM SINAL"}:
            continue
        if event["event_type"] == "active_without_operator" and event["new_state"] != "ATIVA_SEM_OPERADOR":
            continue
        if event["event_type"] not in {"machine_state", "active_without_operator", "calibration"}:
            continue
        state = "CALIBRANDO" if event["event_type"] == "calibration" else event["new_state"]
        items.append({
            "event_type": event["event_type"],
            "state": state,
            "start": max(parse_iso(event["started_at"]) or start_dt, start_dt).isoformat(),
            "end": min(parse_iso(event["ended_at"]) or now, end_dt).isoformat(),
            "duration_seconds": round(_overlap_seconds(event, start_dt, end_dt, now), 2),
            "machine_name": event.get("machine_name"),
        })
    return items


def prune_operation_snapshots(days: int | None = None) -> list[Path]:
    retention_days = days if days is not None else int(os.getenv("CAMPEX_OPERATION_SNAPSHOT_RETENTION_DAYS", "30"))
    root = ROOT / "data" / "operations_snapshots"
    if not root.exists():
        return []
    cutoff = datetime.now(timezone.utc).timestamp() - (retention_days * 86400)
    removed: list[Path] = []
    for path in root.rglob("*.jpg"):
        if path.stat().st_mtime < cutoff:
            path.unlink()
            removed.append(path)
    return removed
