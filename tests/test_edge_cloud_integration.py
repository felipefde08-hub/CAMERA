from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from app.database import connect as edge_connect
from app.database import init_db
from app.models import criar_camera, criar_cliente, criar_unidade, registrar_evento
from cloud import database as cloud_database
from cloud.api import api as cloud_api
from edge_agent.sync_outbox import flush_sync_outbox, pending_sync_count


EDGE_ID = "edge_fl_plasticos_01"
EDGE_SECRET = "secret-local-com-mais-de-12"


class EdgeCloudIntegrationTest(unittest.TestCase):
    def make_cloud_client(self, temp_dir: str) -> TestClient:
        cloud_database.DATABASE_URL = ""
        cloud_database.SQLITE_CLOUD_PATH = Path(temp_dir) / "cloud.sqlite3"
        return TestClient(cloud_api)

    def register_edge(self, client: TestClient, tenant_id: str = "cli_fl", unidade_id: str = "uni_fl") -> None:
        response = client.post(
            "/admin/edge-devices",
            json={
                "id": EDGE_ID,
                "tenant_id": tenant_id,
                "cliente_id": tenant_id,
                "unidade_id": unidade_id,
                "nome": "Edge FL Plasticos",
                "secret": EDGE_SECRET,
            },
        )
        self.assertEqual(response.status_code, 200)

    def sample_event(self, tenant_id: str = "cli_fl", unidade_id: str = "uni_fl") -> dict:
        return {
            "event_uuid": "evt-uuid-001",
            "tenant_id": tenant_id,
            "cliente_id": tenant_id,
            "unidade_id": unidade_id,
            "camera_id": "cam_01",
            "tipo": "machine_stoppage",
            "inicio": "2026-07-28T08:00:00-03:00",
            "fim": "2026-07-28T08:05:00-03:00",
            "duracao": 300,
            "operador_presente": False,
            "confianca": 0.91,
            "metadata": {"machine_name": "Extrusora principal"},
        }

    def test_cloud_receives_new_event_and_lists_for_dashboard(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = self.make_cloud_client(temp_dir)
            health = client.get("/health")
            dashboard = client.get("/dashboard")
            self.register_edge(client)
            response = client.post(
                "/edge/events",
                json=self.sample_event(),
                headers={"X-Edge-Id": EDGE_ID, "X-Edge-Secret": EDGE_SECRET, "Idempotency-Key": "evt-uuid-001"},
            )
            events = client.get("/eventos").json()
            operations = client.get("/operations/events").json()
            cameras = client.get("/cameras/estado").json()

        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn("Campex Operations", dashboard.text)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "received")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_uuid"], "evt-uuid-001")
        self.assertEqual(len(operations["events"]), 1)
        self.assertEqual(operations["events"][0]["event_uuid"], "evt-uuid-001")
        self.assertEqual(cameras[0]["camera_id"], "cam_01")

    def test_duplicate_event_uuid_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = self.make_cloud_client(temp_dir)
            self.register_edge(client)
            headers = {"X-Edge-Id": EDGE_ID, "X-Edge-Secret": EDGE_SECRET, "Idempotency-Key": "evt-uuid-001"}
            first = client.post("/edge/events", json=self.sample_event(), headers=headers)
            updated_payload = {**self.sample_event(), "fim": "2026-07-28T08:07:00-03:00", "duracao": 420, "status": "closed", "severidade": "high"}
            second = client.post("/edge/events", json=updated_payload, headers=headers)
            events = client.get("/eventos").json()

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["status"], "duplicate_updated")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["duracao"], 420)
        self.assertEqual(events[0]["status"], "closed")
        self.assertEqual(events[0]["severidade"], "high")

    def test_invalid_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = self.make_cloud_client(temp_dir)
            self.register_edge(client)
            response = client.post(
                "/edge/events",
                json=self.sample_event(),
                headers={"X-Edge-Id": EDGE_ID, "X-Edge-Secret": "senha-errada"},
            )

        self.assertEqual(response.status_code, 401)

    def test_revoked_device_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = self.make_cloud_client(temp_dir)
            self.register_edge(client)
            with cloud_database.connect() as db:
                db.execute("UPDATE edge_devices SET status = 'revoked', revoked_at = ? WHERE id = ?", ("2026-07-28T09:00:00-03:00", EDGE_ID))
                db.commit()
            response = client.post(
                "/edge/events",
                json=self.sample_event(),
                headers={"X-Edge-Id": EDGE_ID, "X-Edge-Secret": EDGE_SECRET},
            )

        self.assertEqual(response.status_code, 403)

    def test_other_tenant_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = self.make_cloud_client(temp_dir)
            self.register_edge(client, tenant_id="cli_fl", unidade_id="uni_fl")
            response = client.post(
                "/edge/events",
                json=self.sample_event(tenant_id="cli_outro", unidade_id="uni_fl"),
                headers={"X-Edge-Id": EDGE_ID, "X-Edge-Secret": EDGE_SECRET},
            )

        self.assertEqual(response.status_code, 403)

    def test_edge_outbox_survives_failure_and_syncs_later(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "edge.sqlite3"
            with edge_connect(db_path) as connection:
                init_db(connection)
                cliente_id = criar_cliente(connection, "FL Plasticos")
                unidade_id = criar_unidade(connection, cliente_id, "Unidade")
                camera_id = criar_camera(connection, unidade_id, "Camera", cliente_id=cliente_id)
                registrar_evento(connection, cliente_id, unidade_id, camera_id, "machine_stoppage", event_uuid="evt-sync-001")
                self.assertEqual(pending_sync_count(connection), 1)
                with patch("edge_agent.sync_outbox.httpx.post", side_effect=httpx.ConnectError("offline")):
                    self.assertEqual(flush_sync_outbox(connection, "https://cloud.campex.test", EDGE_ID, EDGE_SECRET), 0)
                failed = connection.execute("SELECT status, attempts FROM sync_outbox WHERE event_uuid = ?", ("evt-sync-001",)).fetchone()

            reopened = sqlite3.connect(db_path)
            reopened.row_factory = sqlite3.Row
            try:
                reopened.execute("UPDATE sync_outbox SET next_attempt_at = NULL WHERE event_uuid = ?", ("evt-sync-001",))
                reopened.commit()

                class FakeResponse:
                    def raise_for_status(self) -> None:
                        return None

                with patch("edge_agent.sync_outbox.httpx.post", return_value=FakeResponse()) as poster:
                    synced = flush_sync_outbox(reopened, "https://cloud.campex.test", EDGE_ID, EDGE_SECRET)
                row = reopened.execute("SELECT status FROM sync_outbox WHERE event_uuid = ?", ("evt-sync-001",)).fetchone()
            finally:
                reopened.close()

        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["attempts"], 1)
        self.assertEqual(synced, 1)
        self.assertEqual(row["status"], "synced")
        poster.assert_called_once()

    def test_sync_failures_keep_outbox_for_retry_without_leaking_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "edge.sqlite3"
            cloud_url = "https://cloud.campex.test"
            edge_secret = "secret-local-com-mais-de-12"
            with edge_connect(db_path) as connection:
                init_db(connection)
                cliente_id = criar_cliente(connection, "FL Plasticos")
                unidade_id = criar_unidade(connection, cliente_id, "Unidade")
                camera_id = criar_camera(connection, unidade_id, "Camera", cliente_id=cliente_id)
                registrar_evento(connection, cliente_id, unidade_id, camera_id, "machine_stoppage", event_uuid="evt-sync-secret")

                with patch("edge_agent.sync_outbox.httpx.post", side_effect=httpx.ConnectError(f"offline {cloud_url} {edge_secret}")):
                    synced = flush_sync_outbox(connection, cloud_url, EDGE_ID, edge_secret)
                row = connection.execute("SELECT status, attempts, last_error FROM sync_outbox WHERE event_uuid = ?", ("evt-sync-secret",)).fetchone()

        self.assertEqual(synced, 0)
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["attempts"], 1)
        self.assertNotIn(edge_secret, row["last_error"])
        self.assertNotIn(cloud_url, row["last_error"])

    def test_timeout_and_http_5xx_keep_outbox_pending_for_later_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "edge.sqlite3"
            with edge_connect(db_path) as connection:
                init_db(connection)
                cliente_id = criar_cliente(connection, "FL Plasticos")
                unidade_id = criar_unidade(connection, cliente_id, "Unidade")
                camera_id = criar_camera(connection, unidade_id, "Camera", cliente_id=cliente_id)
                registrar_evento(connection, cliente_id, unidade_id, camera_id, "machine_stoppage", event_uuid="evt-timeout")
                registrar_evento(connection, cliente_id, unidade_id, camera_id, "machine_stoppage", event_uuid="evt-5xx")

                with patch("edge_agent.sync_outbox.httpx.post", side_effect=httpx.TimeoutException("timeout")):
                    self.assertEqual(flush_sync_outbox(connection, "https://cloud.campex.test", EDGE_ID, EDGE_SECRET, limit=1), 0)
                connection.execute("UPDATE sync_outbox SET next_attempt_at = '2999-01-01T00:00:00+00:00' WHERE event_uuid = ?", ("evt-timeout",))
                connection.commit()

                request = httpx.Request("POST", "https://cloud.campex.test/edge/events")
                response = httpx.Response(503, request=request, text="temporarily unavailable")
                with patch("edge_agent.sync_outbox.httpx.post", return_value=response):
                    self.assertEqual(flush_sync_outbox(connection, "https://cloud.campex.test", EDGE_ID, EDGE_SECRET, limit=1), 0)

                statuses = {
                    row["event_uuid"]: row["status"]
                    for row in connection.execute("SELECT event_uuid, status FROM sync_outbox WHERE event_uuid IN (?, ?)", ("evt-timeout", "evt-5xx")).fetchall()
                }

        self.assertEqual(statuses["evt-timeout"], "failed")
        self.assertEqual(statuses["evt-5xx"], "failed")

    def test_lost_ack_retry_is_idempotent_in_cloud_and_drains_outbox(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = self.make_cloud_client(temp_dir)
            db_path = Path(temp_dir) / "edge.sqlite3"
            with edge_connect(db_path) as connection:
                init_db(connection)
                cliente_id = criar_cliente(connection, "FL Plasticos")
                unidade_id = criar_unidade(connection, cliente_id, "Unidade")
                camera_id = criar_camera(connection, unidade_id, "Camera", cliente_id=cliente_id)
                self.register_edge(client, tenant_id=cliente_id, unidade_id=unidade_id)
                registrar_evento(connection, cliente_id, unidade_id, camera_id, "machine_stoppage", event_uuid="evt-lost-ack")
                payload = connection.execute("SELECT payload_json FROM sync_outbox WHERE event_uuid = ?", ("evt-lost-ack",)).fetchone()["payload_json"]

                accepted = client.post(
                    "/edge/events",
                    json=__import__("json").loads(payload),
                    headers={"X-Edge-Id": EDGE_ID, "X-Edge-Secret": EDGE_SECRET, "Idempotency-Key": "evt-lost-ack"},
                )
                self.assertEqual(accepted.status_code, 200)
                self.assertEqual(pending_sync_count(connection), 1)

                def local_post(url, json=None, headers=None, timeout=None):
                    return httpx.Response(
                        200,
                        json=client.post("/edge/events", json=json, headers=headers).json(),
                        request=httpx.Request("POST", url),
                    )

                with patch("edge_agent.sync_outbox.httpx.post", side_effect=local_post):
                    synced = flush_sync_outbox(connection, "https://cloud.campex.test", EDGE_ID, EDGE_SECRET)
                row = connection.execute("SELECT status FROM sync_outbox WHERE event_uuid = ?", ("evt-lost-ack",)).fetchone()
                events = client.get("/eventos").json()

        self.assertEqual(synced, 1)
        self.assertEqual(row["status"], "synced")
        self.assertEqual(len([item for item in events if item["event_uuid"] == "evt-lost-ack"]), 1)

    def test_invalid_cloud_secret_keeps_outbox_unsynced(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = self.make_cloud_client(temp_dir)
            self.register_edge(client)
            db_path = Path(temp_dir) / "edge.sqlite3"
            with edge_connect(db_path) as connection:
                init_db(connection)
                cliente_id = criar_cliente(connection, "FL Plasticos")
                unidade_id = criar_unidade(connection, cliente_id, "Unidade")
                camera_id = criar_camera(connection, unidade_id, "Camera", cliente_id=cliente_id)
                registrar_evento(connection, cliente_id, unidade_id, camera_id, "machine_stoppage", event_uuid="evt-invalid-secret")

                def local_post(url, json=None, headers=None, timeout=None):
                    return httpx.Response(
                        401,
                        json=client.post("/edge/events", json=json, headers=headers).json(),
                        request=httpx.Request("POST", url),
                    )

                with patch("edge_agent.sync_outbox.httpx.post", side_effect=local_post):
                    synced = flush_sync_outbox(connection, "https://cloud.campex.test", EDGE_ID, "wrong-secret")
                row = connection.execute("SELECT status, attempts FROM sync_outbox WHERE event_uuid = ?", ("evt-invalid-secret",)).fetchone()

        self.assertEqual(synced, 0)
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["attempts"], 1)

    def test_report_delivery_is_authenticated_persisted_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = self.make_cloud_client(temp_dir)
            with cloud_database.connect() as db:
                cloud_database.init_cloud_db(db)
                from cloud.security import hash_edge_secret
                db.execute(
                    """
                    INSERT INTO edge_devices (
                        id, tenant_id, cliente_id, unidade_id,
                        nome, secret_hash, status
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 'active')
                    """,
                    (
                        EDGE_ID,
                        "cli_fl",
                        "cli_fl",
                        "uni_fl",
                        "Edge FL Plasticos",
                        hash_edge_secret(EDGE_SECRET),
                    ),
                )
                db.commit()

            payload = {
                "delivery_id": "report-2026-09-02-cli-fl",
                "cliente_id": "cli_fl",
                "recipient": "gestor@example.com",
                "subject": "Campex | Relatório Operacional — 02/09/2026",
                "text_body": "Resumo operacional Campex.",
                "html_body": "<html><body>Resumo operacional Campex.</body></html>",
            }
            headers = {
                "X-Edge-Id": EDGE_ID,
                "X-Edge-Secret": EDGE_SECRET,
            }

            with patch(
                "cloud.api._send_cloud_report_email",
                return_value="provider-msg-001",
            ) as send_mock:
                first = client.post(
                    "/edge/report-delivery",
                    json=payload,
                    headers=headers,
                )
                second = client.post(
                    "/edge/report-delivery",
                    json=payload,
                    headers=headers,
                )

                conflict = client.post(
                    "/edge/report-delivery",
                    json={**payload, "subject": "Outro relatório"},
                    headers=headers,
                )

            with cloud_database.connect() as db:
                row = db.fetchone(
                    "SELECT * FROM report_deliveries WHERE id = ?",
                    (payload["delivery_id"],),
                )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["status"], "sent")
        self.assertFalse(first.json()["idempotent"])

        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["status"], "sent")
        self.assertTrue(second.json()["idempotent"])

        self.assertEqual(conflict.status_code, 409)

        self.assertEqual(send_mock.call_count, 1)
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "sent")
        self.assertEqual(row["attempts"], 1)
        self.assertEqual(row["provider_message_id"], "provider-msg-001")

    def test_postgresql_url_detection(self) -> None:
        self.assertTrue(cloud_database.is_postgres_url("postgresql://user:pass@host/db"))
        self.assertTrue(cloud_database.is_postgres_url("postgres://user:pass@host/db"))
        self.assertFalse(cloud_database.is_postgres_url("sqlite:///local.db"))


if __name__ == "__main__":
    unittest.main()
