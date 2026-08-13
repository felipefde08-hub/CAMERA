from __future__ import annotations

import sqlite3
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.event_taxonomy import EVENT_FAMILY_ABSENCE, EVENT_FAMILY_FLOW, EVENT_FAMILY_INTERRUPTION, EVENT_FAMILY_UNKNOWN, EVENT_FAMILY_WAIT, OFFICIAL_EVENT_FAMILIES
from app.models import row_to_dict


LOSS_FAMILIES = {EVENT_FAMILY_INTERRUPTION, EVENT_FAMILY_WAIT, EVENT_FAMILY_ABSENCE}
FAMILY_LABELS = {
    EVENT_FAMILY_INTERRUPTION: "interrupções",
    EVENT_FAMILY_WAIT: "esperas",
    EVENT_FAMILY_FLOW: "fluxo/movimentação",
    EVENT_FAMILY_ABSENCE: "ausências",
}


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


def _family_label(family: str | None) -> str:
    return FAMILY_LABELS.get(str(family or ""), "eventos classificados")


def _seconds_label(value: float | int | None) -> str:
    total = max(0, int(round(float(value or 0))))
    hours = total // 3600
    minutes = (total % 3600) // 60
    seconds = total % 60
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


def _official_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [event for event in events if (event.get("event_family") or EVENT_FAMILY_UNKNOWN) in OFFICIAL_EVENT_FAMILIES]


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
    clauses = ["datetime(sample_at) >= datetime(?)", "datetime(sample_at) <= datetime(?)"]
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
        SELECT sample_at, camera_online, inference_fps, metadata_json
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
    for sample in samples:
        try:
            sample["metadata"] = json.loads(sample.get("metadata_json") or "{}")
        except json.JSONDecodeError:
            sample["metadata"] = {}
    inactive_count = sum(1 for sample in samples if not _sample_has_inference_signal(sample))
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


def _list_samples(connection: sqlite3.Connection, filters: ReadModelFilters) -> list[dict[str, Any]]:
    if not filters.start or not filters.end:
        return []
    clauses = ["datetime(sample_at) >= datetime(?)", "datetime(sample_at) <= datetime(?)"]
    params: list[Any] = [to_iso(filters.start), to_iso(filters.end)]
    for column, value in {
        "tenant_id": filters.cliente_id,
        "site_id": filters.site_id,
        "area_context_id": filters.area_context_id,
        "process_id": filters.process_id,
        "asset_id": filters.asset_id,
        "camera_id": filters.camera_id,
        "machine_id": filters.asset_id,
    }.items():
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    rows = connection.execute(
        f"""
        SELECT *
        FROM operational_samples
        WHERE {' AND '.join(clauses)}
        ORDER BY sample_at ASC, id ASC
        """,
        params,
    ).fetchall()
    samples = [row_to_dict(row) for row in rows]
    for sample in samples:
        raw = sample.get("metadata_json")
        try:
            sample["metadata"] = json.loads(raw or "{}")
        except json.JSONDecodeError:
            sample["metadata"] = {}
    return samples


def _sample_has_valid_observation(sample: dict[str, Any]) -> bool:
    metadata = sample.get("metadata") or {}
    observations = metadata.get("canonical_observations")
    if not isinstance(observations, list):
        return False
    for observation in observations:
        if not isinstance(observation, dict):
            continue
        if observation.get("observation_type") not in {"machine_activity", "person_presence", "zone_occupancy"}:
            continue
        if observation.get("data_quality") not in {"observed", "inferred"}:
            continue
        if str(observation.get("value") or "UNKNOWN").upper() == "UNKNOWN":
            continue
        return True
    return False


def _sample_has_inference_signal(sample: dict[str, Any]) -> bool:
    fps = sample.get("inference_fps")
    if fps is None:
        return _sample_has_valid_observation(sample)
    try:
        return float(fps) > 0
    except (TypeError, ValueError):
        return False


def _coverage_from_sample_seconds(known_seconds: float, total_seconds: float, sample_count: int, unknown_seconds: float) -> dict[str, Any]:
    if total_seconds <= 0:
        return {"status": "INSUFFICIENT", "valid_percent": 0.0, "unknown_percent": 100.0, "sample_count": sample_count}
    valid_percent = round((known_seconds / total_seconds) * 100, 2)
    unknown_percent = round((unknown_seconds / total_seconds) * 100, 2)
    if sample_count == 0 or valid_percent < 50:
        status = "INSUFFICIENT"
    elif valid_percent < 90:
        status = "PARTIAL"
    else:
        status = "GOOD"
    return {
        "status": status,
        "valid_percent": valid_percent,
        "unknown_percent": unknown_percent,
        "sample_count": sample_count,
    }


def _sample_rollup(samples: list[dict[str, Any]], start: datetime, end: datetime) -> dict[str, Any]:
    total_seconds = max(0.0, (end - start).total_seconds())
    machine = {"ACTIVE": 0.0, "STOPPED": 0.0, "UNKNOWN": 0.0}
    human = {"PRESENT": 0.0, "ABSENT": 0.0, "UNKNOWN": 0.0}
    if not samples:
        machine["UNKNOWN"] = total_seconds
        human["UNKNOWN"] = total_seconds
        coverage = _coverage_from_sample_seconds(0.0, total_seconds, 0, total_seconds)
        return {"machine": machine, "human": human, "coverage": coverage}
    first_at = parse_datetime(samples[0]["sample_at"], start)
    if first_at > start:
        gap = min(total_seconds, (first_at - start).total_seconds())
        machine["UNKNOWN"] += gap
        human["UNKNOWN"] += gap
    for index, sample in enumerate(samples):
        current_at = parse_datetime(sample["sample_at"], start)
        next_at = parse_datetime(samples[index + 1]["sample_at"], end) if index + 1 < len(samples) else end
        segment_seconds = _overlap_seconds({"inicio": to_iso(current_at), "fim": to_iso(next_at)}, start, end, end)
        if segment_seconds <= 0:
            continue
        sensor_ok = sample.get("camera_online") == 1 and _sample_has_inference_signal(sample)
        state = str(sample.get("machine_state") or "UNKNOWN").upper()
        if not sensor_ok or state not in {"ACTIVE", "STOPPED"}:
            machine["UNKNOWN"] += segment_seconds
        else:
            machine[state] += segment_seconds
        operator_value = sample.get("operator_present")
        if not sensor_ok or operator_value is None:
            human["UNKNOWN"] += segment_seconds
        elif int(operator_value) == 1:
            human["PRESENT"] += segment_seconds
        else:
            human["ABSENT"] += segment_seconds
    known_seconds = machine["ACTIVE"] + machine["STOPPED"]
    coverage = _coverage_from_sample_seconds(known_seconds, total_seconds, len(samples), machine["UNKNOWN"])
    return {"machine": machine, "human": human, "coverage": coverage}


def operational_data(connection: sqlite3.Connection, filters: ReadModelFilters, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    if not filters.start or not filters.end:
        raise ValueError("Dados operacionais requerem início e fim.")
    events = list_events(connection, filters, now=now)
    samples = _list_samples(connection, filters)
    rollup = _sample_rollup(samples, filters.start, filters.end)
    classified_events = _official_events(events)
    stoppages = [event for event in classified_events if event.get("tipo") == "machine_stoppage"]
    absences = [event for event in classified_events if event.get("tipo") in {"workstation_unattended", "machine_running_without_operator"}]
    zone_events = [event for event in events if event.get("area_id") or event.get("tipo") in {"restricted_zone_occupied", "restricted_area_occupied", "excessive_zone_dwell"}]
    proximity_observations = []
    for sample in samples:
        metadata = sample.get("metadata") or {}
        for observation in metadata.get("canonical_observations", []) if isinstance(metadata.get("canonical_observations"), list) else []:
            if observation.get("observation_type") == "person_vehicle_proximity":
                proximity_observations.append(observation)
    stopped_total = sum(float(event.get("read_duration_seconds") or 0) for event in stoppages)
    absence_total = sum(float(event.get("read_duration_seconds") or 0) for event in absences)
    return {
        "period": {"start": to_iso(filters.start), "end": to_iso(filters.end)},
        "filters": {key: value for key, value in filters.__dict__.items() if value is not None and key not in {"start", "end"}},
        "coverage": rollup["coverage"],
        "machine_data": {
            "observed_total_seconds": round(sum(rollup["machine"].values()), 3),
            "active_seconds": round(rollup["machine"]["ACTIVE"], 3),
            "stopped_seconds": round(rollup["machine"]["STOPPED"], 3),
            "unknown_seconds": round(rollup["machine"]["UNKNOWN"], 3),
            "visual_availability_percent": round((rollup["machine"]["ACTIVE"] / max(1.0, rollup["machine"]["ACTIVE"] + rollup["machine"]["STOPPED"])) * 100, 2) if (rollup["machine"]["ACTIVE"] + rollup["machine"]["STOPPED"]) else None,
            "stoppage_count": len(stoppages),
            "stoppage_total_seconds": round(stopped_total, 3),
            "average_stoppage_seconds": round(stopped_total / len(stoppages), 3) if stoppages else 0,
            "max_stoppage_seconds": round(max((float(event.get("read_duration_seconds") or 0) for event in stoppages), default=0), 3),
            "critical_times": [{"started_at": event.get("inicio"), "duration_seconds": event.get("read_duration_seconds"), "event_uuid": _event_uuid(event)} for event in stoppages],
            "traceability": {"event_uuids": [_event_uuid(event) for event in stoppages], "observation_types": ["machine_activity"]},
        },
        "human_operation_data": {
            "presence_seconds": round(rollup["human"]["PRESENT"], 3),
            "absence_seconds": round(rollup["human"]["ABSENT"], 3),
            "unknown_seconds": round(rollup["human"]["UNKNOWN"], 3),
            "absence_count": len(absences),
            "absence_total_seconds": round(absence_total, 3),
            "absence_periods": [{"started_at": event.get("inicio"), "ended_at": event.get("fim"), "duration_seconds": event.get("read_duration_seconds"), "event_uuid": _event_uuid(event)} for event in absences],
            "traceability": {"event_uuids": [_event_uuid(event) for event in absences], "observation_types": ["person_presence", "zone_occupancy"]},
        },
        "zone_safety_data": {
            "occupancy_event_count": len(zone_events),
            "occupancy_total_seconds": round(sum(float(event.get("read_duration_seconds") or 0) for event in zone_events), 3),
            "occupancies": [{"event_uuid": _event_uuid(event), "tipo": event.get("tipo"), "area_id": event.get("area_id"), "duration_seconds": event.get("read_duration_seconds"), "evidence": event.get("midia_path")} for event in zone_events],
            "person_vehicle_proximity": {
                "observations_count": len(proximity_observations),
                "near_count": sum(1 for item in proximity_observations if item.get("value") == "NEAR"),
                "candidate_count": sum(1 for item in proximity_observations if item.get("value") == "CANDIDATE"),
                "vehicle_classes": sorted({str((item.get("metadata") or {}).get("vehicle_class")) for item in proximity_observations if (item.get("metadata") or {}).get("vehicle_class")}),
                "status": "OBSERVATION_SUPPORTED_EVENT_NOT_YET_DEFINED",
            },
            "traceability": {"event_uuids": [_event_uuid(event) for event in zone_events], "observation_types": ["zone_occupancy", "person_vehicle_proximity"]},
        },
        "data_quality": {
            "unknown_seconds": round(rollup["machine"]["UNKNOWN"], 3),
            "unknown_is_not_counted_as_active_or_stopped": True,
            "sample_count": len(samples),
        },
    }


def daily_report(connection: sqlite3.Connection, filters: ReadModelFilters, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    data = operational_data(connection, filters, now=now)
    summary = period_summary(connection, filters, now=now)
    intel = intelligence(connection, filters, now=now)
    events = list_events(connection, filters, now=now)
    main_events = sorted(events, key=lambda event: float(event.get("read_duration_seconds") or 0), reverse=True)[:10]
    return {
        "report_type": "daily_operational_report_v1",
        "period": data["period"],
        "coverage": data["coverage"],
        "summary": {
            "machines": data["machine_data"],
            "human_operation": data["human_operation_data"],
            "zones_safety": data["zone_safety_data"],
        },
        "main_events": [
            {
                "event_uuid": _event_uuid(event),
                "tipo": event.get("tipo"),
                "event_family": event.get("event_family") or EVENT_FAMILY_UNKNOWN,
                "started_at": event.get("inicio"),
                "ended_at": event.get("fim"),
                "duration_seconds": event.get("read_duration_seconds"),
                "context": {
                    "site_id": event.get("site_id"),
                    "area_id": event.get("area_context_id") or event.get("area_id"),
                    "process_id": event.get("process_id"),
                    "asset_id": event.get("asset_id") or event.get("machine_monitor_id"),
                    "camera_id": event.get("camera_id"),
                },
                "evidence": event.get("midia_path"),
            }
            for event in main_events
        ],
        "intelligence": {
            "briefing": intel["briefing"],
            "attention": intel["attention"],
            "patterns": intel["patterns"],
            "confirmed_causes": intel["confirmed_causes"],
        },
        "traceability": {
            "event_uuids": summary["event_uuids"],
            "why": "Cada métrica referencia events/event_uuids e observation_types usados no cálculo.",
        },
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


def _insight(
    *,
    insight_id: str,
    statement: str,
    number: str,
    why: str,
    event_uuids: list[str],
    severity: str = "info",
    rule_id: str,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "insight_id": insight_id,
        "statement": statement,
        "number": number,
        "why": why,
        "severity": severity,
        "event_uuids": event_uuids,
        "rule_id": rule_id,
        "rule_version": "intelligence_v0",
        "metrics_used": metrics or {},
        "recommended_action": "Investigar os eventos relacionados e confirmar causa ou ação quando necessário.",
    }


def _top(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    return items[0] if items else None


def _current_previous_text(metric: dict[str, Any]) -> str:
    if metric.get("percent_change") is None:
        return "sem base anterior suficiente"
    sign = "+" if float(metric["percent_change"]) > 0 else ""
    return f"{sign}{metric['percent_change']}% vs período anterior"


def _metric_from_values(current_value: float, previous_value: float) -> dict[str, Any]:
    diff = current_value - previous_value
    percent = None if previous_value == 0 else round((diff / previous_value) * 100, 3)
    return {"current": round(current_value, 3), "previous": round(previous_value, 3), "absolute_difference": round(diff, 3), "percent_change": percent}


def _hour_bucket(event: dict[str, Any]) -> str | None:
    value = event.get("inicio")
    if not value:
        return None
    hour = parse_datetime(value).hour
    return f"{hour:02d}h-{(hour + 1) % 24:02d}h"


def _events_with_operator_absence(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    related: list[dict[str, Any]] = []
    for event in events:
        observed = event.get("observed_context") or event.get("metadata") or ""
        text = str(observed).lower()
        if "operator_absent" in text or "operador ausente" in text or event.get("operator_present") == 0:
            related.append(event)
    return related


def intelligence(connection: sqlite3.Connection, filters: ReadModelFilters, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    events = list_events(connection, filters, now=now)
    classified_events = _official_events(events)
    summary = period_summary(connection, filters, now=now)
    loss_summary = losses(connection, filters, now=now)
    comparison_payload = comparison(connection, filters, now=now) if filters.start and filters.end else None
    official_comparison = None
    previous_classified_events: list[dict[str, Any]] = []
    if filters.start and filters.end:
        previous_start, previous_end = previous_period(filters.start, filters.end)
        previous_filters = ReadModelFilters(**{**filters.__dict__, "start": previous_start, "end": previous_end})
        previous_classified_events = _official_events(list_events(connection, previous_filters, now=now))
        current_duration = sum(float(event.get("read_duration_seconds") or 0) for event in classified_events)
        previous_duration = sum(float(event.get("read_duration_seconds") or 0) for event in previous_classified_events)
        current_avg = current_duration / len(classified_events) if classified_events else 0
        previous_avg = previous_duration / len(previous_classified_events) if previous_classified_events else 0
        official_comparison = {
            "metrics": {
                "total_events": _metric_from_values(float(len(classified_events)), float(len(previous_classified_events))),
                "total_duration_seconds": _metric_from_values(current_duration, previous_duration),
                "average_duration_seconds": _metric_from_values(current_avg, previous_avg),
            },
            "current_event_uuids": [_event_uuid(event) for event in classified_events],
            "previous_event_uuids": [_event_uuid(event) for event in previous_classified_events],
        }
    unknown_events = [event for event in events if (event.get("event_family") or EVENT_FAMILY_UNKNOWN) not in OFFICIAL_EVENT_FAMILIES]

    insights: list[dict[str, Any]] = []
    patterns: list[dict[str, Any]] = []
    briefing: list[str] = []

    if not classified_events:
        briefing.append("Ainda não existem eventos operacionais classificados suficientes neste período.")
    else:
        top_family = _top([item for item in summary["events_by_family"] if item["key"] in OFFICIAL_EVENT_FAMILIES])
        top_asset = _top([item for item in loss_summary["by_asset"] if item["key"] != "não informado"])
        if top_family:
            briefing.append(f"{_family_label(top_family['key']).capitalize()} somaram {_seconds_label(top_family['total_duration_seconds'])} no período.")
            insights.append(
                _insight(
                    insight_id=f"family_concentration:{top_family['key']}",
                    statement=f"{_family_label(top_family['key']).capitalize()} concentraram a maior duração classificada do período.",
                    number=_seconds_label(top_family["total_duration_seconds"]),
                    why=f"{top_family['total_events']} evento(s) classificados como {_family_label(top_family['key'])}.",
                    event_uuids=top_family["event_uuids"],
                    rule_id="top_family_duration",
                    metrics={"event_family": top_family["key"], "duration_seconds": top_family["total_duration_seconds"], "events": top_family["total_events"]},
                )
            )
        if top_asset and float(top_asset.get("total_duration_seconds") or 0) > 0:
            total_loss_duration = sum(float(item.get("total_duration_seconds") or 0) for item in loss_summary["by_family"])
            share = round((float(top_asset["total_duration_seconds"]) / total_loss_duration) * 100, 1) if total_loss_duration else 0
            briefing.append(f"{top_asset['key']} concentrou {share}% do tempo classificado como perda operacional.")
            insights.append(
                _insight(
                    insight_id=f"asset_loss_concentration:{top_asset['key']}",
                    statement=f"{top_asset['key']} concentrou {share}% das perdas monitoradas.",
                    number=_seconds_label(top_asset["total_duration_seconds"]),
                    why=f"{top_asset['total_events']} evento(s) em famílias classificadas como perda operacional.",
                    event_uuids=top_asset["event_uuids"],
                    severity="warning" if share >= 40 else "info",
                    rule_id="top_asset_loss_share",
                    metrics={"asset_id": top_asset["key"], "share_percent": share, "duration_seconds": top_asset["total_duration_seconds"]},
                )
            )

        if official_comparison:
            duration_metric = official_comparison["metrics"]["total_duration_seconds"]
            if duration_metric["percent_change"] is not None and abs(float(duration_metric["percent_change"])) >= 10:
                direction = "aumentou" if float(duration_metric["absolute_difference"]) > 0 else "reduziu"
                insights.append(
                    _insight(
                        insight_id="period_duration_change",
                        statement=f"A duração total dos eventos {direction} no período.",
                        number=_current_previous_text(duration_metric),
                        why=f"{_seconds_label(duration_metric['current'])} no período atual contra {_seconds_label(duration_metric['previous'])} no período anterior.",
                        event_uuids=official_comparison["current_event_uuids"],
                        severity="warning" if float(duration_metric["absolute_difference"]) > 0 else "info",
                        rule_id="period_over_period_duration",
                        metrics=duration_metric,
                    )
                )

        by_asset = [item for item in summary["events_by_asset"] if item["key"] != "não informado"]
        repeated_asset = next((item for item in by_asset if int(item["total_events"]) >= 3), None)
        if repeated_asset:
            patterns.append(
                _insight(
                    insight_id=f"asset_recurrence:{repeated_asset['key']}",
                    statement=f"{repeated_asset['total_events']} ocorrências foram registradas no ativo {repeated_asset['key']}.",
                    number=f"{repeated_asset['total_events']} eventos",
                    why="A recorrência é matemática: mesmo ativo com três ou mais eventos classificados no período.",
                    event_uuids=repeated_asset["event_uuids"],
                    rule_id="asset_recurrence_count",
                    metrics={"asset_id": repeated_asset["key"], "events": repeated_asset["total_events"]},
                )
            )

        by_hour: dict[str, dict[str, Any]] = {}
        for event in classified_events:
            bucket = _hour_bucket(event)
            if not bucket:
                continue
            item = by_hour.setdefault(bucket, {"key": bucket, "total_events": 0, "event_uuids": []})
            item["total_events"] += 1
            item["event_uuids"].append(_event_uuid(event))
        top_hour = sorted(by_hour.values(), key=lambda item: (-item["total_events"], item["key"]))[:1]
        if top_hour and top_hour[0]["total_events"] >= 2:
            item = top_hour[0]
            patterns.append(
                _insight(
                    insight_id=f"hour_concentration:{item['key']}",
                    statement=f"{item['total_events']} eventos classificados ocorreram entre {item['key']}.",
                    number=f"{item['total_events']} eventos",
                    why="A concentração temporal foi identificada por contagem de eventos no mesmo intervalo de uma hora.",
                    event_uuids=item["event_uuids"],
                    rule_id="hourly_event_concentration",
                    metrics={"hour_bucket": item["key"], "events": item["total_events"]},
                )
            )

        absence_related = _events_with_operator_absence(classified_events)
        interruption_events = [event for event in classified_events if event.get("event_family") == EVENT_FAMILY_INTERRUPTION]
        if interruption_events and absence_related:
            patterns.append(
                _insight(
                    insight_id="interruption_with_observed_absence",
                    statement=f"Em {len(absence_related)} de {len(interruption_events)} interrupções havia ausência observada no contexto.",
                    number=f"{len(absence_related)}/{len(interruption_events)}",
                    why="A Campex relata apenas a simultaneidade observada; isso não é causa confirmada.",
                    event_uuids=[_event_uuid(event) for event in absence_related],
                    rule_id="observed_absence_overlap",
                    metrics={"interruption_events": len(interruption_events), "events_with_observed_absence": len(absence_related)},
                )
            )

    family_groups = {item["key"]: item for item in summary["events_by_family"] if item["key"] in OFFICIAL_EVENT_FAMILIES}
    kpis = [
        {"key": "interruption_duration", "label": "Duração de interrupções", "value_seconds": float(family_groups.get(EVENT_FAMILY_INTERRUPTION, {}).get("total_duration_seconds") or 0), "event_uuids": family_groups.get(EVENT_FAMILY_INTERRUPTION, {}).get("event_uuids", [])},
        {"key": "interruption_frequency", "label": "Frequência de interrupções", "value": int(family_groups.get(EVENT_FAMILY_INTERRUPTION, {}).get("total_events") or 0), "event_uuids": family_groups.get(EVENT_FAMILY_INTERRUPTION, {}).get("event_uuids", [])},
        {"key": "average_duration", "label": "Duração média", "value_seconds": (sum(float(event.get("read_duration_seconds") or 0) for event in classified_events) / len(classified_events)) if classified_events else 0, "event_uuids": [_event_uuid(event) for event in classified_events]},
        {"key": "wait_duration", "label": "Espera", "value_seconds": float(family_groups.get(EVENT_FAMILY_WAIT, {}).get("total_duration_seconds") or 0), "event_uuids": family_groups.get(EVENT_FAMILY_WAIT, {}).get("event_uuids", [])},
        {"key": "absence_duration", "label": "Ausência", "value_seconds": float(family_groups.get(EVENT_FAMILY_ABSENCE, {}).get("total_duration_seconds") or 0), "event_uuids": family_groups.get(EVENT_FAMILY_ABSENCE, {}).get("event_uuids", [])},
        {"key": "recurrence", "label": "Recorrência", "value": max((int(item["total_events"]) for item in summary["events_by_asset"]), default=0), "event_uuids": (_top(summary["events_by_asset"]) or {}).get("event_uuids", [])},
    ]

    causes = _group_events(classified_events, "confirmed_cause")
    for cause in causes:
        if cause["key"] == "não informado":
            cause["key"] = "causa não informada"
    return {
        "period": summary["period"],
        "filters": summary["filters"],
        "coverage": summary["coverage"],
        "briefing": briefing,
        "attention": insights[:5],
        "patterns": patterns[:5],
        "kpis": kpis,
        "confirmed_causes": causes,
        "comparison": official_comparison or comparison_payload,
        "traceability": {"event_uuids": [_event_uuid(event) for event in classified_events]},
        "data_quality": {
            "classified_events": len(classified_events),
            "unknown_events": len(unknown_events),
            "unknown_event_uuids": [_event_uuid(event) for event in unknown_events],
        },
    }
