from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api import api
from app.config import ROOT


def _workspace_script() -> str:
    return Path(ROOT / "frontend" / "workspace.js").read_text(encoding="utf-8")


def test_events_route_serves_product_shell() -> None:
    client = TestClient(api)

    response = client.get("/events")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "workspace.js" in response.text


def test_events_v0_uses_canonical_events_and_detail_endpoint() -> None:
    script = _workspace_script()
    start = script.index('"/events":')
    end = script.index('"/alerts":')
    route_block = script[start:end]

    assert 'endpoint: "/eventos"' in route_block
    assert 'title: "Events"' in route_block
    assert "Memória operacional verificável" in route_block
    assert "Não classificados" in route_block
    assert "camera_id" not in route_block.lower()
    assert "/eventos/${row.id}/detail" in script


def test_events_v0_separates_physical_status_from_workflow() -> None:
    script = _workspace_script()

    assert "function eventPhysicalStatus" in script
    assert "function eventWorkflow" in script
    assert "workflow_status || \"new\"" in script
    assert "Status físico" in script
    assert "Workflow" in script
    assert "/acknowledge" in script
    assert "/human-context" in script
    assert "/resolve" in script


def test_events_v0_keeps_unknown_in_audit_tab_only() -> None:
    script = _workspace_script()

    assert 'currentTab === "não classificados"' in script
    assert 'eventFamily(row) === "unknown"' in script
    assert 'eventFamily(row) !== "unknown"' in script


def test_events_v0_deep_links_by_event_uuid() -> None:
    script = _workspace_script()

    assert "/events?event_uuid=" in script
    assert 'params.get("event_uuid")' in script
    assert "item.event_uuid === eventUuid" in script


def test_events_v0_removes_technical_shell_cards_from_events() -> None:
    script = _workspace_script()

    assert 'path === "/operations-view" || path === "/events" || path === "/insights"' in script
    assert "cx-events-mode" in script
    assert "cx-event-card" in Path(ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
