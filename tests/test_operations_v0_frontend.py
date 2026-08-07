from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api import api
from app.config import ROOT


def test_operations_view_route_serves_workspace_shell() -> None:
    client = TestClient(api)

    response = client.get("/operations-view")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "workspace.js" in response.text


def test_operations_view_uses_read_model_endpoints_for_aggregations() -> None:
    script = Path(ROOT / "frontend" / "workspace.js").read_text(encoding="utf-8")
    start = script.index("async function renderOperationsReadModelPage")
    end = script.index("async function loadAlertsWorkspace")
    operations_block = script[start:end]

    assert "/operations/read-model/current" in operations_block
    assert "/operations/read-model/summary" in operations_block
    assert "/operations/read-model/losses" in operations_block
    assert "/operations/read-model/comparison" in operations_block
    assert "/operations/summary" not in operations_block
    assert "/operations/events" not in operations_block


def test_operations_view_replaces_legacy_dashboard_content() -> None:
    script = Path(ROOT / "frontend" / "workspace.js").read_text(encoding="utf-8")
    start = script.index("async function renderOperationsReadModelPage")
    end = script.index("async function loadAlertsWorkspace")
    operations_block = script[start:end]

    for expected in [
        "Operations",
        "Como está sua operação?",
        "Briefing operacional",
        "O que merece atenção",
        "Operação agora",
        "Principais perdas",
        "Comparação",
        "Sem dados operacionais suficientes neste período.",
    ]:
        assert expected in operations_block

    for legacy_label in [
        "Adicionar câmera",
        "Revisar eventos",
        "Configurar alerta",
        "Gerar relatório",
        "Status das câmeras",
        "SQLite persistente",
        "credenciais",
        "cards de implantação",
    ]:
        assert legacy_label not in operations_block

    for family_label in ["Interrupções", "Esperas", "Ausências", "Fluxo", "Eventos abertos"]:
        assert family_label in script


def test_operations_formats_period_and_keeps_unknown_secondary() -> None:
    script = Path(ROOT / "frontend" / "workspace.js").read_text(encoding="utf-8")

    assert "function formatOperationsPeriod" in script
    assert "toLocaleDateString" in script
    assert "toLocaleTimeString" in script
    assert "function officialFamilyRows" in script
    assert "function unknownEventCount" in script
    assert "function renderUnknownQualityNote" in script
    assert "não entram nos indicadores oficiais da Operations" in script
    assert "Sem eventos operacionais classificados suficientes neste período." in script
    assert "officialFamilyRows(summary)[0]" in script
    assert "...officialFamilyRows(summary).map" in script


def test_operations_current_uses_canonical_context_labels() -> None:
    script = Path(ROOT / "frontend" / "workspace.js").read_text(encoding="utf-8")

    assert "function eventContextLabel" in script
    assert "asset_name || event.asset_id" in script
    assert "process_name || event.process_id" in script
    assert "area_name || event.area_context_id" in script
    assert "camera_name || event.camera_id" in script
    assert "Contexto operacional não informado" in script
    assert "Ativo operacional" not in script[
        script.index("function renderOperationsCurrent"):
        script.index("function renderOperationsRanking")
    ]
    assert "Sem classificação" not in script[
        script.index("function renderOperationsCurrent"):
        script.index("function renderOperationsRanking")
    ]


def test_operations_load_page_does_not_inject_legacy_shell_cards() -> None:
    script = Path(ROOT / "frontend" / "workspace.js").read_text(encoding="utf-8")

    assert 'cards.innerHTML = path === "/operations-view" ? ""' in script
    assert "renderOperationsAuthState" in script
    assert "Entre para acessar os dados da operação." in script
    assert "/settings/cameras?next=%2Foperations-view#login" in script

    for legacy_label in [
        "Registros",
        "SQLite persistente",
        "Sem credenciais no navegador",
        "Adicionar câmera",
        "Gerar relatório",
        "Status das câmeras",
    ]:
        assert legacy_label not in script[
            script.index("function renderOperationsAuthState"):
            script.index("function renderRows")
        ]


def test_login_redirect_can_return_to_operations_view() -> None:
    app_script = Path(ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert 'new URLSearchParams(window.location.search).get("next")' in app_script
    assert 'next.startsWith("/")' in app_script
    assert 'window.location.href = next' in app_script


def test_operations_view_is_not_rendered_from_dashboard_html() -> None:
    client = TestClient(api)

    response = client.get("/operations-view")

    assert response.status_code == 200
    assert "workspace.js" in response.text
    assert "operations-dashboard.js" not in response.text
    assert "dashboard.html" not in response.text


def test_operations_traceability_keeps_event_uuid_links() -> None:
    script = Path(ROOT / "frontend" / "workspace.js").read_text(encoding="utf-8")

    assert "data-event-uuids" in script
    assert "renderTraceDrawer" in script
    assert "event_uuids" in script
