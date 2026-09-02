from __future__ import annotations

import base64
import re
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.auth import create_user
from cloud import database as cloud_database
from cloud.api import api as cloud_api


def make_client(temp_dir: str) -> TestClient:
    cloud_database.DATABASE_URL = ""
    cloud_database.SQLITE_CLOUD_PATH = Path(temp_dir) / "cloud-installer.sqlite3"
    return TestClient(cloud_api)


def bootstrap_account(client: TestClient) -> tuple[str, str]:
    with cloud_database.connect() as db:
        cloud_database.init_cloud_db(db)

        create_user(
            db,
            email="felipe@campex.test",
            password="SenhaCampex123",
            role="admin_campex",
            nome="Felipe",
        )

    login = client.post(
        "/auth/login",
        json={
            "email": "felipe@campex.test",
            "senha": "SenhaCampex123",
        },
    )
    assert login.status_code == 200

    cliente = client.post(
        "/clientes",
        json={
            "nome": "Cliente Piloto",
            "status": "ativo",
        },
    )
    assert cliente.status_code == 200
    cliente_id = cliente.json()["id"]

    unidade = client.post(
        "/unidades",
        json={
            "cliente_id": cliente_id,
            "nome": "Producao",
            "localizacao": "Sao Jose do Rio Preto",
            "timezone": "America/Sao_Paulo",
        },
    )
    assert unidade.status_code == 200
    unidade_id = unidade.json()["id"]

    return cliente_id, unidade_id


def decode_installer_powershell(cmd_text: str) -> str:
    match = re.search(
        r"-EncodedCommand\s+([A-Za-z0-9+/=]+)",
        cmd_text,
    )
    assert match is not None

    encoded = match.group(1)
    return base64.b64decode(encoded).decode("utf-16le")


def extract_variable(script: str, name: str) -> str:
    match = re.search(
        rf'^\${re.escape(name)}\s*=\s*"([^"]+)"',
        script,
        flags=re.MULTILINE,
    )
    assert match is not None
    return match.group(1)


def test_installer_creates_offline_edge_then_heartbeat_makes_it_online() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        client = make_client(temp_dir)
        cliente_id, unidade_id = bootstrap_account(client)

        download = client.get(
            "/edge-installer/windows",
            params={"unidade_id": unidade_id},
        )

        assert download.status_code == 200
        assert "Instalar-Campex.cmd" in download.headers.get(
            "content-disposition",
            "",
        )

        cmd_text = download.text
        powershell = decode_installer_powershell(cmd_text)

        edge_id = extract_variable(powershell, "EdgeId")
        edge_secret = extract_variable(powershell, "EdgeSecret")
        cloud_url = extract_variable(powershell, "CloudUrl")

        assert edge_id.startswith("edge_")
        assert len(edge_secret) >= 12
        assert cloud_url.startswith("http://testserver")
        assert "/edge-package/windows" in powershell

        with cloud_database.connect() as db:
            cloud_database.init_cloud_db(db)
            edge = db.fetchone(
                "SELECT * FROM edge_devices WHERE id = ?",
                (edge_id,),
            )

        assert edge is not None
        assert edge["cliente_id"] == cliente_id
        assert edge["tenant_id"] == cliente_id
        assert edge["unidade_id"] == unidade_id
        assert edge["last_seen_at"] is None

        before = client.get("/edge-devices")
        assert before.status_code == 200

        edge_before = next(
            item for item in before.json()
            if item["id"] == edge_id
        )
        assert edge_before["online"] is False
        assert edge_before["connection_status"] == "offline"

        heartbeat = client.post(
            "/edge/heartbeat",
            headers={
                "X-Edge-Id": edge_id,
                "X-Edge-Secret": edge_secret,
            },
        )

        assert heartbeat.status_code == 200
        assert heartbeat.json()["status"] == "online"

        after = client.get("/edge-devices")
        assert after.status_code == 200

        edge_after = next(
            item for item in after.json()
            if item["id"] == edge_id
        )
        assert edge_after["online"] is True
        assert edge_after["connection_status"] == "online"
        assert edge_after["last_seen_at"] is not None
