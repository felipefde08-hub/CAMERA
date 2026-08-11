from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import api as api_module
from app.api import api
from app.auth import create_user
from app.database import connect, init_db
from app.models import criar_camera, criar_cliente, criar_machine_monitor, criar_unidade


def _isolated_client(tmp_path: Path):
    db_path = tmp_path / "installable_mvp.sqlite3"

    def test_connect(_path=None):
        return connect(db_path)

    with test_connect() as connection:
        init_db(connection)
    patcher = patch.object(api_module, "connect", test_connect)
    patcher.start()
    return TestClient(api), db_path, patcher, test_connect


def _polygon():
    return [
        {"x": 0.2, "y": 0.2},
        {"x": 0.8, "y": 0.2},
        {"x": 0.8, "y": 0.8},
        {"x": 0.2, "y": 0.8},
    ]


def test_first_run_creates_admin_company_and_unit_on_empty_installation(tmp_path: Path) -> None:
    client, db_path, patcher, _test_connect = _isolated_client(tmp_path)
    try:
        status = client.get("/first-run/status")
        assert status.status_code == 200
        assert status.json()["available"] is True

        response = client.post(
            "/first-run/complete",
            json={
                "admin_nome": "Admin",
                "admin_email": "admin@cliente.test",
                "admin_senha": "senha-segura",
                "empresa_nome": "Cliente Novo",
                "empresa_documento": "dev",
                "unidade_nome": "Fábrica Principal",
            },
        )
        assert response.status_code == 201
        assert response.json()["cliente_id"].startswith("cli_")
        assert response.cookies.get("campex_session")

        locked = client.get("/first-run/status")
        assert locked.json()["available"] is False

        with connect(db_path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM clientes").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM unidades").fetchone()[0] == 1
    finally:
        patcher.stop()


def test_first_run_is_blocked_for_existing_installation(tmp_path: Path) -> None:
    client, _db_path, patcher, test_connect = _isolated_client(tmp_path)
    try:
        with test_connect() as connection:
            cliente_id = criar_cliente(connection, "Cliente Existente")
            create_user(connection, "admin@existente.test", "senha-segura", "admin_campex", cliente_id, "Admin")
        response = client.post(
            "/first-run/complete",
            json={
                "admin_nome": "Outro",
                "admin_email": "outro@cliente.test",
                "admin_senha": "senha-segura",
                "empresa_nome": "Outro Cliente",
                "unidade_nome": "Outra Fábrica",
            },
        )
        assert response.status_code == 403
    finally:
        patcher.stop()


def test_empty_installation_smoke_reaches_configured_monitor_without_physical_readiness(tmp_path: Path) -> None:
    client, db_path, patcher, _test_connect = _isolated_client(tmp_path)
    try:
        first_run = client.post(
            "/first-run/complete",
            json={
                "admin_nome": "Instalador",
                "admin_email": "instalador@cliente.test",
                "admin_senha": "senha-segura",
                "empresa_nome": "Indústria Nova",
                "unidade_nome": "Unidade 1",
            },
        ).json()
        cliente_id = first_run["cliente_id"]
        unidade_id = first_run["unidade_id"]

        area = client.post("/setup/areas", json={"unidade_id": unidade_id, "nome": "Corte"}).json()
        process = client.post(
            "/setup/processes",
            json={"unidade_id": unidade_id, "area_id": area["id"], "nome": "Linha A"},
        ).json()
        asset = client.post(
            "/setup/assets",
            json={"unidade_id": unidade_id, "area_id": area["id"], "process_id": process["id"], "nome": "A6"},
        ).json()
        camera = client.post(
            "/cameras/rtsp",
            json={
                "nome": "Câmera A6",
                "cliente_id": cliente_id,
                "unidade_id": unidade_id,
                "rtsp_url": "rtsp://usuario:senha@192.0.2.10:554/cam",
                "testar_conexao": False,
                "ativa": True,
            },
        ).json()["camera"]
        client.post(
            f"/setup/cameras/{camera['id']}/context",
            json={"area_context_id": area["id"], "process_id": process["id"], "asset_id": asset["id"]},
        )
        for area_type in ("machine_region", "operator_zone"):
            response = client.post(
                f"/cameras/{camera['id']}/areas",
                json={"name": area_type, "area_type": area_type, "polygon": _polygon(), "active": True},
            )
            assert response.status_code == 201
        monitor = client.post(
            f"/cameras/{camera['id']}/machine-monitors",
            json={
                "nome": "A6",
                "machine_polygon": _polygon(),
                "operator_polygon": _polygon(),
                "stop_seconds": 20,
                "operator_absence_seconds": 60,
                "stopped_with_operator_seconds": 90,
                "ativo": True,
            },
        )
        assert monitor.status_code == 200

        operation = client.get("/setup/operation").json()
        readiness = operation["readiness"]
        checks = {item["label"]: item["status"] for item in readiness["checks"]}
        assert checks["Empresa"] == "PASS"
        assert checks["Unidade"] == "PASS"
        assert checks["Contexto operacional"] == "PASS"
        assert checks["Câmera cadastrada"] == "PASS"
        assert checks["Machine region"] == "PASS"
        assert checks["Operator zone"] == "PASS"
        assert checks["Monitor"] == "PASS"
        assert checks["Câmera online"] == "PENDING"
        assert checks["Calibração"] == "PENDING"
        assert checks["Inference"] == "PENDING"

        with connect(db_path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM machine_monitors").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM monitored_areas").fetchone()[0] == 2
    finally:
        patcher.stop()


def test_disabled_camera_is_not_started_by_production_bootstrap(tmp_path: Path) -> None:
    client, _db_path, patcher, test_connect = _isolated_client(tmp_path)
    try:
        with test_connect() as connection:
            cliente_id = criar_cliente(connection, "Cliente")
            unidade_id = criar_unidade(connection, cliente_id, "Unidade")
            active = criar_camera(connection, unidade_id, "Ativa", cliente_id=cliente_id, config_ref="video.mp4")
            inactive = criar_camera(connection, unidade_id, "Inativa", cliente_id=cliente_id, config_ref="video.mp4", ativa=False)
            criar_machine_monitor(connection, cliente_id, unidade_id, active, "Monitor", _polygon(), _polygon())

        class FakeStream:
            def __init__(self, camera_id: str, source: str) -> None:
                self.camera_id = camera_id
                self.source = source
                self.analysis = False

            def start(self) -> None:
                return None

            def set_analysis(self, enabled: bool):
                self.analysis = enabled
                return self.public_status()

            def public_status(self):
                return {"camera_id": self.camera_id, "status": "online"}

        class FakeStreams:
            def __init__(self) -> None:
                self.started: dict[str, FakeStream] = {}

            def get_or_create(self, camera_id: str, source: str):
                self.started[camera_id] = FakeStream(camera_id, source)
                return self.started[camera_id]

        fake = FakeStreams()
        with patch.object(api_module, "live_streams", fake):
            result = api_module.bootstrap_production_streams()
        assert [item["camera_id"] for item in result["started"]] == [active]
        assert inactive not in fake.started
    finally:
        patcher.stop()


def test_camera_can_be_deactivated_without_deletion(tmp_path: Path) -> None:
    client, _db_path, patcher, _test_connect = _isolated_client(tmp_path)
    try:
        first_run = client.post(
            "/first-run/complete",
            json={
                "admin_nome": "Instalador",
                "admin_email": "admin-toggle@cliente.test",
                "admin_senha": "senha-segura",
                "empresa_nome": "Indústria",
                "unidade_nome": "Unidade",
            },
        ).json()
        camera = client.post(
            "/cameras/rtsp",
            json={
                "nome": "Câmera",
                "cliente_id": first_run["cliente_id"],
                "unidade_id": first_run["unidade_id"],
                "rtsp_url": "rtsp://usuario:senha@192.0.2.11:554/cam",
                "testar_conexao": False,
                "ativa": True,
            },
        ).json()["camera"]
        updated = client.patch(f"/cameras/{camera['id']}", json={"ativa": False})
        assert updated.status_code == 200
        assert updated.json()["ativa"] is False
        cameras = client.get("/cameras/estado").json()
        stored = next(item for item in cameras if item["id"] == camera["id"])
        assert stored["ativa"] is False
    finally:
        patcher.stop()


def test_windows_start_script_uses_edge_production_runtime() -> None:
    script = Path("scripts/start_factory_windows.ps1").read_text(encoding="utf-8")
    assert "manage.py run-edge-production" in script
    assert "-m app.main" not in script
    assert "CAMPEX_EDGE_ID" in script


def test_setup_frontend_uses_assisted_calibration_flow() -> None:
    script = Path("frontend/app.js").read_text(encoding="utf-8")
    assert "/calibration/${phase}/start" in script
    assert "/calibration/status" in script
    assert "Movimento com máquina funcionando" not in script
