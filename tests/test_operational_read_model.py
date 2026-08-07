from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import api
from app.auth import create_user
from app.database import connect, init_db
from app.models import criar_camera, criar_cliente, criar_unidade, obter_evento, registrar_evento, registrar_operational_sample
from app.operational_context import criar_operational_area, criar_operational_asset, criar_operational_process
from app.operational_read_model import ReadModelFilters, comparison, current_operation, losses, parse_datetime, period_summary


NOW = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)
START = parse_datetime("2026-08-07T08:00:00+00:00")
END = parse_datetime("2026-08-07T12:00:00+00:00")


def make_context():
    temp_dir = tempfile.TemporaryDirectory()
    db_path = Path(temp_dir.name) / "read-model.sqlite3"
    connection = connect(db_path)
    init_db(connection)
    cliente_id = criar_cliente(connection, "Cliente")
    site_id = criar_unidade(connection, cliente_id, "Fabrica")
    area_id = criar_operational_area(connection, cliente_id=cliente_id, unidade_id=site_id, nome="Corte")
    process_id = criar_operational_process(connection, cliente_id=cliente_id, unidade_id=site_id, area_id=area_id, nome="Linha A6")
    asset_id = criar_operational_asset(connection, cliente_id=cliente_id, unidade_id=site_id, area_id=area_id, process_id=process_id, nome="A6")
    camera_id = criar_camera(connection, site_id, "Camera A6", cliente_id=cliente_id, area_context_id=area_id, process_id=process_id, asset_id=asset_id)
    return temp_dir, db_path, connection, cliente_id, site_id, area_id, process_id, asset_id, camera_id


def add_event(
    connection,
    cliente_id: str,
    site_id: str,
    camera_id: str,
    tipo: str,
    *,
    start: str,
    end: str | None = None,
    duration: float | None = None,
    event_uuid: str,
    workflow_status: str = "new",
    confirmed_cause: str | None = None,
    action_taken: str | None = None,
) -> str:
    event_id = registrar_evento(
        connection,
        cliente_id,
        site_id,
        camera_id,
        tipo,
        inicio=start,
        fim=end,
        duracao=duration,
        event_uuid=event_uuid,
    )
    connection.execute(
        """
        UPDATE eventos
        SET status = ?,
            workflow_status = ?,
            confirmed_cause = ?,
            action_taken = ?
        WHERE id = ?
        """,
        ("closed" if end else "open", workflow_status, confirmed_cause, action_taken, event_id),
    )
    connection.commit()
    return event_id


def test_summary_separates_families_unknown_and_traceability() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, area_id, process_id, asset_id, camera_id = make_context()
    with temp_dir, connection:
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T09:00:00+00:00", end="2026-08-07T09:10:00+00:00", duration=600, event_uuid="evt-int-1")
        add_event(connection, cliente_id, site_id, camera_id, "workstation_unattended", start="2026-08-07T10:00:00+00:00", end="2026-08-07T10:05:00+00:00", duration=300, event_uuid="evt-abs-1")
        add_event(connection, cliente_id, site_id, camera_id, "restricted_area_occupied", start="2026-08-07T11:00:00+00:00", end="2026-08-07T11:02:00+00:00", duration=120, event_uuid="evt-unk-1")
        summary = period_summary(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=NOW)

    families = {item["key"]: item for item in summary["events_by_family"]}
    assert families["interruption"]["total_duration_seconds"] == 600
    assert families["absence"]["total_duration_seconds"] == 300
    assert families["unknown"]["total_duration_seconds"] == 120
    assert set(summary["event_uuids"]) == {"evt-int-1", "evt-abs-1", "evt-unk-1"}
    assert summary["events_pending_human_analysis"]["total"] == 3
    assert area_id in {item["key"] for item in summary["events_by_area"]}
    assert process_id in {item["key"] for item in summary["events_by_process"]}
    assert asset_id in {item["key"] for item in summary["events_by_asset"]}


def test_open_event_duration_uses_now_without_modifying_record() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, _asset_id, camera_id = make_context()
    with temp_dir, connection:
        event_id = add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T11:30:00+00:00", event_uuid="evt-open-1")
        current = current_operation(connection, ReadModelFilters(cliente_id=cliente_id), now=NOW)
        event_after = obter_evento(connection, event_id)

    assert current["total_open_events"] == 1
    assert current["open_events"][0]["current_duration_seconds"] == 1800
    assert event_after["fim"] is None
    assert event_after["duracao"] is None


def test_filters_by_site_area_process_asset_family_and_workflow() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, area_id, process_id, asset_id, camera_id = make_context()
    with temp_dir, connection:
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T09:00:00+00:00", end="2026-08-07T09:10:00+00:00", duration=600, event_uuid="evt-filter-1", workflow_status="acknowledged")
        filters = ReadModelFilters(
            cliente_id=cliente_id,
            site_id=site_id,
            area_context_id=area_id,
            process_id=process_id,
            asset_id=asset_id,
            event_family="interruption",
            workflow_status="acknowledged",
            start=START,
            end=END,
        )
        summary = period_summary(connection, filters, now=NOW)

    assert summary["total_events"] == 1
    assert summary["event_uuids"] == ["evt-filter-1"]


def test_losses_rank_by_asset_and_exclude_unknown() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, asset_id, camera_id = make_context()
    with temp_dir, connection:
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T09:00:00+00:00", end="2026-08-07T09:10:00+00:00", duration=600, event_uuid="evt-loss-1")
        add_event(connection, cliente_id, site_id, camera_id, "restricted_area_occupied", start="2026-08-07T10:00:00+00:00", end="2026-08-07T10:10:00+00:00", duration=600, event_uuid="evt-unknown-1")
        ranked = losses(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=NOW)

    assert ranked["by_asset"][0]["key"] == asset_id
    assert ranked["by_asset"][0]["event_uuids"] == ["evt-loss-1"]
    assert ranked["excluded_unknown_or_non_loss_event_uuids"] == ["evt-unknown-1"]


def test_confirmed_causes_and_actions_are_human_only() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, _asset_id, camera_id = make_context()
    with temp_dir, connection:
        add_event(
            connection,
            cliente_id,
            site_id,
            camera_id,
            "machine_stoppage",
            start="2026-08-07T09:00:00+00:00",
            end="2026-08-07T09:20:00+00:00",
            duration=1200,
            event_uuid="evt-cause-1",
            confirmed_cause="falta de material",
            action_taken="abastecimento solicitado",
        )
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T10:00:00+00:00", end="2026-08-07T10:10:00+00:00", duration=600, event_uuid="evt-no-cause-1")
        summary = period_summary(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=NOW)

    causes = {item["key"]: item for item in summary["confirmed_causes"]}
    assert causes["falta de material"]["total_duration_seconds"] == 1200
    assert causes["causa não informada"]["total_duration_seconds"] == 600
    assert summary["actions_taken"][0]["key"] == "abastecimento solicitado"


def test_comparison_handles_zero_previous_period_safely() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, _asset_id, camera_id = make_context()
    with temp_dir, connection:
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T09:00:00+00:00", end="2026-08-07T09:10:00+00:00", duration=600, event_uuid="evt-current-1")
        result = comparison(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=NOW)

    assert result["metrics"]["total_events"]["current"] == 1
    assert result["metrics"]["total_events"]["previous"] == 0
    assert result["metrics"]["total_events"]["percent_change"] is None
    assert result["current_event_uuids"] == ["evt-current-1"]
    assert result["previous_event_uuids"] == []


def test_workflow_status_does_not_change_physical_duration() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, _asset_id, camera_id = make_context()
    with temp_dir, connection:
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T09:00:00+00:00", end="2026-08-07T09:10:00+00:00", duration=600, event_uuid="evt-workflow-1", workflow_status="resolved")
        new_only = period_summary(connection, ReadModelFilters(cliente_id=cliente_id, workflow_status="new", start=START, end=END), now=NOW)
        resolved = period_summary(connection, ReadModelFilters(cliente_id=cliente_id, workflow_status="resolved", start=START, end=END), now=NOW)

    assert new_only["total_events"] == 0
    assert resolved["total_duration_seconds"] == 600


def test_coverage_unknown_when_no_samples_and_observed_when_samples_exist() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, _asset_id, camera_id = make_context()
    with temp_dir, connection:
        empty = period_summary(connection, ReadModelFilters(cliente_id=cliente_id, camera_id=camera_id, start=START, end=END), now=NOW)
        registrar_operational_sample(
            connection,
            sample_uuid="sample-read-1",
            tenant_id=cliente_id,
            unit_id=site_id,
            camera_id=camera_id,
            machine_id="machine_a6",
            machine_state="ACTIVE",
            operator_present=True,
            activity_score=10,
            confidence=0.9,
            capture_fps=15,
            inference_fps=5,
            frames_analyzed=100,
            camera_online=True,
            sample_at="2026-08-07T09:00:00+00:00",
        )
        observed = period_summary(connection, ReadModelFilters(cliente_id=cliente_id, camera_id=camera_id, start=START, end=END), now=NOW)

    assert empty["coverage"]["status"] == "unknown"
    assert observed["coverage"]["sample_count"] == 1
    assert observed["coverage"]["status"] == "partial"


def test_read_model_api_summary_endpoint() -> None:
    temp_dir, db_path, connection, cliente_id, site_id, _area_id, _process_id, _asset_id, camera_id = make_context()
    with temp_dir:
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T09:00:00+00:00", end="2026-08-07T09:10:00+00:00", duration=600, event_uuid="evt-api-1")
        create_user(connection, "gestor@example.com", "senha", "admin_cliente", cliente_id)
        connection.close()

        def test_connect(_path=None):
            return connect(db_path)

        with patch("app.api.connect", test_connect):
            client = TestClient(api)
            client.post("/auth/login", json={"email": "gestor@example.com", "senha": "senha"})
            response = client.get("/operations/read-model/summary", params={"start": "2026-08-07T08:00:00+00:00", "end": "2026-08-07T12:00:00+00:00", "camera_id": camera_id})

    assert response.status_code == 200
    assert response.json()["event_uuids"] == ["evt-api-1"]
