from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.event_taxonomy import EVENT_FAMILY_ABSENCE, EVENT_FAMILY_INTERRUPTION, EVENT_FAMILY_UNKNOWN, EVENT_FAMILY_WAIT
from app.models import row_to_dict


LOSS_FAMILIES = {EVENT_FAMILY_INTERRUPTION, EVENT_FAMILY_WAIT, EVENT_FAMILY_ABSENCE}


@dataclass(frozen=True)
class ReadModelFilters:
    cliente_id: str | None = None
    site_id: str | None = None
    area_context_id: str | None = None
    process_id: str | None = None
    asset_id: str | None = None
    camera_id: str | None = None
    event_family: str | None = None
    tipo: str | None = None
    workflow_status: str | None = None
    start: datetime | None = None
    end: datetime | None = None


def parse_datetime(value: str | None, default: datetime | None = None) -> datetime:
    if not value:
        if default is not None:
            return default
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def to_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def period_bounds(period: str = "day", start: str | None = None, end: str | None = None, now: datetime | None = None) -> tuple[datetime, datetime]:
    reference = now or datetime.now(timezone.utc)
    if start or end:
        return parse_datetime(start, reference - timedelta(days=1)), parse_datetime(end, reference)
    period = period or "day"
    if period == "turno":
        return reference - timedelta(hours=8), reference
    if period == "week":
        return reference - timedelta(days=7), reference
    if period == "month":
        return reference - timedelta(days=30), reference
    if period == "custom":
        return reference - timedelta(days=1), reference
    return reference - timedelta(days=1), reference


def previous_period(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    delta = end - start
    return start - delta, start


def _overlap_seconds(event: dict[str, Any], start: datetime, end: datetime, now: datetime) -> float:
    event_start = parse_datetime(event.get("inicio"), start)
    raw_end = event.get("fim")
    event_end = parse_datetime(raw_end, now) if raw_end else now
    effective_start = max(start, event_start)
    effective_end = min(end, event_end)
    return max(0.0, (effective_end - effective_start).total_seconds())


def _event_uuid(event: dict[str, Any]) -> str:
    return str(event.get("event_uuid") or event.get("id"))


def _build_event_query(filters: ReadModelFilters) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if filters.start and filters.end:
        clauses.append("inicio <= ?")
        params.append(to_iso(filters.end))
        clauses.append("COALESCE(fim, ?) >= ?")
        params.extend([to_iso(filters.end), to_iso(filters.start)])
    column_filters = {
        "cliente_id": filters.cliente_id,
        "site_id": filters.site_id,
        "area_context_id": filters.area_context_id,
        "process_id": filters.process_id,
        "asset_id": filters.asset_id,
        "camera_id": filters.camera_id,
        "event_family": filters.event_family,
        "tipo": filters.tipo,
        "workflow_status": filters.workflow_status,
    }
    for column, value in column_filters.items():
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


def list_events(connection: sqlite3.Connection, filters: ReadModelFilters, *, now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    where, params = _build_event_query(filters)
    rows = connection.execute(
        f"""
        SELECT *
        FROM eventos
        {where}
        ORDER BY inicio ASC, criado_em ASC
        """,
        params,
    ).fetchall()
    events = [row_to_dict(row) for row in rows]
    for event in events:
        if filters.start and filters.end:
            event["read_duration_seconds"] = _overlap_seconds(event, filters.start, filters.end, now)
        elif event.get("fim"):
            event["read_duration_seconds"] = float(event.get("duracao") or 0)
        else:
            event["read_duration_seconds"] = _overlap_seconds(event, parse_datetime(event.get("inicio"), now), now, now)
        event["event_family"] = event.get("event_family") or EVENT_FAMILY_UNKNOWN
    return events


def _group_events(events: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for event in events:
        label = str(event.get(key) or "não informado")
        item = grouped.setdefault(label, {"key": label, "total_events": 0, "total_duration_seconds": 0.0, "event_uuids": []})
        item["total_events"] += 1
        item["total_duration_seconds"] += float(event.get("read_duration_seconds") or 0)
        item["event_uuids"].append(_event_uuid(event))
    return sorted(grouped.values(), key=lambda item: (-item["total_duration_seconds"], -item["total_events"], item["key"]))


def _coverage(connection: sqlite3.Connection, filters: ReadModelFilters) -> dict[str, Any]:
    if not filters.start or not filters.end:
        return {"status": "unknown", "reason": "Período não informado para cobertura."}
    clauses = ["sample_at >= ?", "sample_at <= ?"]
    params: list[Any] = [to_iso(filters.start), to_iso(filters.end)]
    for column, value in {
        "unit_id": filters.site_id,
        "area_context_id": filters.area_context_id,
        "process_id": filters.process_id,
        "asset_id": filters.asset_id,
        "camera_id": filters.camera_id,
    }.items():
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    rows = connection.execute(
        f"""
        SELECT sample_at, camera_online, inference_fps
        FROM operational_samples
        WHERE {' AND '.join(clauses)}
        ORDER BY sample_at ASC
        """,
        params,
    ).fetchall()
    samples = [row_to_dict(row) for row in rows]
    if not samples:
        return {
            "status": "unknown",
            "requested_start": to_iso(filters.start),
            "requested_end": to_iso(filters.end),
            "reason": "Sem amostras operacionais suficientes para estimar cobertura.",
            "sample_count": 0,
            "gaps": [],
        }
    gaps: list[dict[str, Any]] = []
    previous = parse_datetime(samples[0]["sample_at"])
    if (previous - filters.start).total_seconds() > 120:
        gaps.append({"type": "no_samples", "start": to_iso(filters.start), "end": to_iso(previous)})
    for sample in samples[1:]:
        current = parse_datetime(sample["sample_at"])
        if (current - previous).total_seconds() > 120:
            gaps.append({"type": "no_samples", "start": to_iso(previous), "end": to_iso(current)})
        previous = current
    if (filters.end - previous).total_seconds() > 120:
        gaps.append({"type": "no_samples", "start": to_iso(previous), "end": to_iso(filters.end)})
    offline_count = sum(1 for sample in samples if sample.get("camera_online") == 0)
    inactive_count = sum(1 for sample in samples if not sample.get("inference_fps"))
    return {
        "status": "partial" if gaps or offline_count or inactive_count else "observed",
        "requested_start": to_iso(filters.start),
        "requested_end": to_iso(filters.end),
        "covered_start": samples[0]["sample_at"],
        "covered_end": samples[-1]["sample_at"],
        "sample_count": len(samples),
        "offline_samples": offline_count,
        "inference_inactive_samples": inactive_count,
        "gaps": gaps,
    }


def current_operation(connection: sqlite3.Connection, filters: ReadModelFilters | None = None, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    filters = filters or ReadModelFilters()
    current_filters = ReadModelFilters(**{**filters.__dict__, "start": None, "end": None})
    where, params = _build_event_query(current_filters)
    open_clause = "status = 'open'"
    where = f"{where} AND {open_clause}" if where else f"WHERE {open_clause}"
    rows = connection.execute(
        f"""
        SELECT *
        FROM eventos
        {where}
        ORDER BY inicio ASC, criado_em ASC
        """,
        params,
    ).fetchall()
    events = [row_to_dict(row) for row in rows]
    for event in events:
        event["event_family"] = event.get("event_family") or EVENT_FAMILY_UNKNOWN
        event["current_duration_seconds"] = _overlap_seconds(event, parse_datetime(event.get("inicio"), now), now, now)
        event["event_uuid"] = _event_uuid(event)
    return {"as_of": to_iso(now), "open_events": events, "total_open_events": len(events)}


def period_summary(connection: sqlite3.Connection, filters: ReadModelFilters, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    events = list_events(connection, filters, now=now)
    total_duration = sum(float(event.get("read_duration_seconds") or 0) for event in events)
    unresolved = [event for event in events if (event.get("workflow_status") or "new") == "new"]
    causes = _group_events(events, "confirmed_cause")
    for cause in causes:
        if cause["key"] == "não informado":
            cause["key"] = "causa não informada"
    return {
        "period": {"start": to_iso(filters.start) if filters.start else None, "end": to_iso(filters.end) if filters.end else None},
        "filters": {key: value for key, value in filters.__dict__.items() if value is not None and key not in {"start", "end"}},
        "total_events": len(events),
        "total_duration_seconds": round(total_duration, 3),
        "average_duration_seconds": round(total_duration / len(events), 3) if events else 0,
        "events_by_family": _group_events(events, "event_family"),
        "duration_by_family": _group_events(events, "event_family"),
        "events_by_area": _group_events(events, "area_context_id"),
        "events_by_process": _group_events(events, "process_id"),
        "events_by_asset": _group_events(events, "asset_id"),
        "events_pending_human_analysis": {"total": len(unresolved), "event_uuids": [_event_uuid(event) for event in unresolved]},
        "confirmed_causes": causes,
        "actions_taken": _group_events([event for event in events if event.get("action_taken")], "action_taken"),
        "event_uuids": [_event_uuid(event) for event in events],
        "coverage": _coverage(connection, filters),
    }


def losses(connection: sqlite3.Connection, filters: ReadModelFilters, *, now: datetime | None = None) -> dict[str, Any]:
    events = [event for event in list_events(connection, filters, now=now) if (event.get("event_family") or EVENT_FAMILY_UNKNOWN) in LOSS_FAMILIES]
    return {
        "period": {"start": to_iso(filters.start) if filters.start else None, "end": to_iso(filters.end) if filters.end else None},
        "loss_families": sorted(LOSS_FAMILIES),
        "by_asset": _group_events(events, "asset_id"),
        "by_process": _group_events(events, "process_id"),
        "by_area": _group_events(events, "area_context_id"),
        "by_family": _group_events(events, "event_family"),
        "excluded_unknown_or_non_loss_event_uuids": [
            _event_uuid(event)
            for event in list_events(connection, filters, now=now)
            if (event.get("event_family") or EVENT_FAMILY_UNKNOWN) not in LOSS_FAMILIES
        ],
    }


def _comparison_metric(current: dict[str, Any], previous: dict[str, Any], key: str) -> dict[str, Any]:
    current_value = float(current.get(key) or 0)
    previous_value = float(previous.get(key) or 0)
    diff = current_value - previous_value
    percent = None if previous_value == 0 else round((diff / previous_value) * 100, 3)
    return {"current": current_value, "previous": previous_value, "absolute_difference": round(diff, 3), "percent_change": percent}


def comparison(connection: sqlite3.Connection, filters: ReadModelFilters, *, now: datetime | None = None) -> dict[str, Any]:
    if not filters.start or not filters.end:
        raise ValueError("Comparação requer início e fim.")
    previous_start, previous_end = previous_period(filters.start, filters.end)
    current_summary = period_summary(connection, filters, now=now)
    previous_filters = ReadModelFilters(**{**filters.__dict__, "start": previous_start, "end": previous_end})
    previous_summary = period_summary(connection, previous_filters, now=now)
    return {
        "current_period": current_summary["period"],
        "previous_period": previous_summary["period"],
        "metrics": {
            "total_events": _comparison_metric(current_summary, previous_summary, "total_events"),
            "total_duration_seconds": _comparison_metric(current_summary, previous_summary, "total_duration_seconds"),
            "average_duration_seconds": _comparison_metric(current_summary, previous_summary, "average_duration_seconds"),
        },
        "current_event_uuids": current_summary["event_uuids"],
        "previous_event_uuids": previous_summary["event_uuids"],
    }
