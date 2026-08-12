from __future__ import annotations

import sqlite3
from typing import Any

from app.models import obter_evento
from shared.schemas import now_iso


WORKFLOW_NEW = "new"
WORKFLOW_ACKNOWLEDGED = "acknowledged"
WORKFLOW_RESOLVED = "resolved"
OUTCOME_RESOLVED = "resolved"
OUTCOME_NOT_RESOLVED = "not_resolved"
OUTCOME_UNKNOWN = "unknown"


def _actor_value(actor: dict[str, Any] | str | None) -> str | None:
    if actor is None:
        return None
    if isinstance(actor, str):
        return actor
    return actor.get("email") or actor.get("id") or actor.get("nome")


def acknowledge_event(
    connection: sqlite3.Connection,
    event_id: str,
    *,
    actor: dict[str, Any] | str | None = None,
    human_notes: str | None = None,
    at: str | None = None,
) -> dict[str, Any] | None:
    event = obter_evento(connection, event_id)
    if event is None:
        return None
    timestamp = at or now_iso()
    connection.execute(
        """
        UPDATE eventos
        SET workflow_status = CASE
                WHEN workflow_status = 'resolved' THEN workflow_status
                ELSE 'acknowledged'
            END,
            acknowledged_at = COALESCE(acknowledged_at, ?),
            acknowledged_by = COALESCE(acknowledged_by, ?),
            human_notes = COALESCE(?, human_notes),
            observacao = COALESCE(?, observacao),
            atualizado_em = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (timestamp, _actor_value(actor), human_notes, human_notes, event_id),
    )
    connection.commit()
    return obter_evento(connection, event_id)


def update_human_context(
    connection: sqlite3.Connection,
    event_id: str,
    *,
    confirmed_cause: str | None = None,
    action_taken: str | None = None,
    human_notes: str | None = None,
    actor: dict[str, Any] | str | None = None,
    at: str | None = None,
) -> dict[str, Any] | None:
    event = obter_evento(connection, event_id)
    if event is None:
        return None
    connection.execute(
        """
        UPDATE eventos
        SET confirmed_cause = COALESCE(?, confirmed_cause),
            confirmed_by = CASE WHEN ? IS NOT NULL THEN COALESCE(confirmed_by, ?) ELSE confirmed_by END,
            confirmed_at = CASE WHEN ? IS NOT NULL THEN COALESCE(confirmed_at, ?) ELSE confirmed_at END,
            action_taken = COALESCE(?, action_taken),
            action_at = CASE WHEN ? IS NOT NULL THEN COALESCE(action_at, ?) ELSE action_at END,
            human_notes = COALESCE(?, human_notes),
            cause_category = COALESCE(?, cause_category),
            cause_notes = COALESCE(?, cause_notes),
            classified_by = COALESCE(?, classified_by),
            classified_at = COALESCE(?, classified_at),
            atualizado_em = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            confirmed_cause,
            confirmed_cause,
            _actor_value(actor),
            confirmed_cause,
            at or now_iso(),
            action_taken,
            action_taken,
            at or now_iso(),
            human_notes,
            confirmed_cause,
            human_notes,
            _actor_value(actor),
            at or now_iso(),
            event_id,
        ),
    )
    connection.commit()
    return obter_evento(connection, event_id)


def update_operational_memory(
    connection: sqlite3.Connection,
    event_id: str,
    *,
    actor: dict[str, Any] | str | None = None,
    confirmed_cause: str | None = None,
    action_taken: str | None = None,
    recommendation_id: str | None = None,
    recommendation_accepted: bool | None = None,
    outcome_status: str | None = None,
    outcome_notes: str | None = None,
    human_notes: str | None = None,
    at: str | None = None,
) -> dict[str, Any] | None:
    event = obter_evento(connection, event_id)
    if event is None:
        return None
    if outcome_status not in {None, OUTCOME_RESOLVED, OUTCOME_NOT_RESOLVED, OUTCOME_UNKNOWN}:
        raise ValueError("outcome_status invalido.")
    timestamp = at or now_iso()
    resolution_time_seconds = _resolution_time_seconds(event, timestamp) if outcome_status == OUTCOME_RESOLVED else None
    if confirmed_cause or action_taken or human_notes:
        update_human_context(
            connection,
            event_id,
            confirmed_cause=confirmed_cause,
            action_taken=action_taken,
            human_notes=human_notes,
            actor=actor,
            at=timestamp,
        )
    connection.execute(
        """
        UPDATE eventos
        SET recommendation_id = COALESCE(?, recommendation_id),
            recommendation_accepted = COALESCE(?, recommendation_accepted),
            outcome_status = COALESCE(?, outcome_status),
            outcome_notes = COALESCE(?, outcome_notes),
            resolution_time_seconds = COALESCE(?, resolution_time_seconds),
            atualizado_em = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            recommendation_id,
            None if recommendation_accepted is None else int(recommendation_accepted),
            outcome_status,
            outcome_notes,
            resolution_time_seconds,
            event_id,
        ),
    )
    _record_memory_audit(
        connection,
        event_id,
        actor=actor,
        metadata={
            "confirmed_cause": bool(confirmed_cause),
            "action_taken": bool(action_taken),
            "recommendation_id": recommendation_id,
            "recommendation_accepted": recommendation_accepted,
            "outcome_status": outcome_status,
        },
    )
    connection.commit()
    return obter_evento(connection, event_id)


def resolve_event(
    connection: sqlite3.Connection,
    event_id: str,
    *,
    actor: dict[str, Any] | str | None = None,
    confirmed_cause: str | None = None,
    action_taken: str | None = None,
    human_notes: str | None = None,
    at: str | None = None,
) -> dict[str, Any] | None:
    event = obter_evento(connection, event_id)
    if event is None:
        return None
    timestamp = at or now_iso()
    if event.get("workflow_status") == WORKFLOW_NEW:
        acknowledge_event(connection, event_id, actor=actor, human_notes=human_notes, at=timestamp)
    if confirmed_cause or action_taken or human_notes:
        update_human_context(
            connection,
            event_id,
            confirmed_cause=confirmed_cause,
            action_taken=action_taken,
            human_notes=human_notes,
            actor=actor,
            at=timestamp,
        )
    connection.execute(
        """
        UPDATE eventos
        SET workflow_status = 'resolved',
            resolved_at = COALESCE(resolved_at, ?),
            resolved_by = COALESCE(resolved_by, ?),
            atualizado_em = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (timestamp, _actor_value(actor), event_id),
    )
    connection.commit()
    return obter_evento(connection, event_id)


def observed_context(event: dict[str, Any]) -> dict[str, Any]:
    metadata = event.get("metadata") or {}
    return {
        "tipo": event.get("tipo"),
        "inicio": event.get("inicio"),
        "fim": event.get("fim"),
        "duracao": event.get("duracao"),
        "operador_presente": event.get("operador_presente"),
        "confianca": event.get("confianca"),
        "quantidade_inicial": event.get("quantidade_inicial"),
        "quantidade_maxima": event.get("quantidade_maxima"),
        "motion_level": event.get("motion_level"),
        "operator_present_seconds": event.get("operator_present_seconds"),
        "operator_absent_seconds": event.get("operator_absent_seconds"),
        "metadata": metadata,
    }


def event_detail(connection: sqlite3.Connection, event_id: str) -> dict[str, Any] | None:
    event = obter_evento(connection, event_id)
    if event is None:
        return None
    return {
        **event,
        "technical_type": event.get("tipo"),
        "business_taxonomy": {
            "event_family": event.get("event_family") or "unknown",
            "event_subtype": event.get("event_subtype"),
        },
        "physical_context": {
            "cliente_id": event.get("cliente_id"),
            "unidade_id": event.get("unidade_id"),
            "site_id": event.get("site_id"),
            "area_context_id": event.get("area_context_id"),
            "process_id": event.get("process_id"),
            "asset_id": event.get("asset_id"),
            "camera_id": event.get("camera_id"),
            "machine_monitor_id": event.get("machine_monitor_id"),
            "area_id": event.get("area_id"),
        },
        "physical_status": event.get("status"),
        "workflow_status": event.get("workflow_status") or WORKFLOW_NEW,
        "observed_context": observed_context(event),
        "human_context": {
            "confirmed_cause": event.get("confirmed_cause") or event.get("cause_category"),
            "confirmed_by": event.get("confirmed_by") or event.get("classified_by"),
            "confirmed_at": event.get("confirmed_at") or event.get("classified_at"),
            "action_taken": event.get("action_taken"),
            "action_at": event.get("action_at"),
            "recommendation_id": event.get("recommendation_id"),
            "recommendation_accepted": None if event.get("recommendation_accepted") is None else bool(event.get("recommendation_accepted")),
            "outcome_status": event.get("outcome_status"),
            "outcome_notes": event.get("outcome_notes"),
            "resolution_time_seconds": event.get("resolution_time_seconds"),
            "human_notes": event.get("human_notes") or event.get("observacao") or event.get("cause_notes"),
            "acknowledged_at": event.get("acknowledged_at"),
            "acknowledged_by": event.get("acknowledged_by"),
            "resolved_at": event.get("resolved_at"),
            "resolved_by": event.get("resolved_by"),
        },
    }


def group_events_by_confirmed_cause(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT COALESCE(confirmed_cause, cause_category, 'sem causa confirmada') AS confirmed_cause,
               COUNT(*) AS total,
               SUM(COALESCE(duracao, 0)) AS total_duration_seconds
        FROM eventos
        GROUP BY COALESCE(confirmed_cause, cause_category, 'sem causa confirmada')
        ORDER BY total DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def _resolution_time_seconds(event: dict[str, Any], resolved_at: str) -> float | None:
    from app.operational_read_model import parse_datetime

    start = event.get("inicio")
    if not start:
        return None
    end_dt = parse_datetime(resolved_at)
    start_dt = parse_datetime(start, end_dt)
    return max(0.0, (end_dt - start_dt).total_seconds())


def _record_memory_audit(connection: sqlite3.Connection, event_id: str, *, actor: dict[str, Any] | str | None, metadata: dict[str, Any]) -> None:
    try:
        from app.models import registrar_audit_log

        event = obter_evento(connection, event_id)
        registrar_audit_log(
            connection,
            action="event.operational_memory.update",
            actor=actor if isinstance(actor, dict) else {"email": _actor_value(actor)},
            entity_type="evento",
            entity_id=event_id,
            tenant_id=event.get("cliente_id") if event else None,
            metadata=metadata,
        )
    except Exception:
        return
