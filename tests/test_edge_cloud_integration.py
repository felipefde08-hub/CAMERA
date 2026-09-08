from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from app.auth import create_user
from app.database import connect as edge_connect
from app.database import init_db
from app.models import criar_camera, criar_cliente, criar_unidade, registrar_evento
from app.edge_runtime import ProductionEdgeRuntime
from cloud import database as cloud_database
from cloud.api import api as cloud_api
from edge_agent.sync_outbox import flush_sync_outbox, pending_sync_count


EDGE_ID = "edge_fl_plasticos_01"
EDGE_SECRET = "secret-local-com-mais-de-12"


class EdgeCloudIntegrationTest(unittest.TestCase):
    def make_cloud_client(self, temp_dir: str) -> TestClient:
        cloud_database.DATABASE_URL = ""
        cloud_database.SQLITE_CLOUD_PATH = Path(temp_dir) / "cloud.sqlite3"
        client = TestClient(cloud_api)

        with cloud_database.connect() as db:
            cloud_database.init_cloud_db(db)
            create_user(
                db,
                email="admin@campex.test",
                password="SenhaCampex123",
                role="admin_campex",
                nome="Admin Campex",
            )

        response = client.post(
            "/auth/login",
            json={
                "email": "admin@campex.test",
                "senha": "SenhaCampex123",
            },
        )
        assert response.status_code == 200

        return client

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
        self.assertIn('id="workspaceTitle"', dashboard.text)
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

    def test_edge_heartbeat_accepts_legacy_payload_without_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = self.make_cloud_client(temp_dir)
            self.register_edge(client)
            response = client.post(
                "/edge/heartbeat",
                json={},
                headers={"X-Edge-Id": EDGE_ID, "X-Edge-Secret": EDGE_SECRET},
            )
            diagnostics = client.get(f"/edges/{EDGE_ID}/diagnostics")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["diagnostics"], "not_provided")
        self.assertEqual(diagnostics.status_code, 200)
        self.assertEqual(diagnostics.json()["edge_id"], EDGE_ID)
        self.assertIsNone(diagnostics.json()["diagnostics"])

    def test_edge_heartbeat_persists_latest_diagnostics_snapshot_without_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = self.make_cloud_client(temp_dir)
            self.register_edge(client)
            first = {
                "diagnostics": {
                    "generated_at": "2026-09-03T10:00:00+00:00",
                    "edge": {
                        "version": "rc1",
                        "process_uptime_seconds": 12.5,
                        "python_version": "3.11.9",
                        "platform": "Windows",
                        "local_api_healthy": True,
                        "last_local_health_check_at": "2026-09-03T10:00:00+00:00",
                    },
                    "cameras": {
                        "total": 1,
                        "online": 1,
                        "offline": 0,
                        "items": [{
                            "camera_id": "cam_01",
                            "status": "online",
                            "last_frame_at": "2026-09-03T10:00:00+00:00",
                            "reconnect_attempts": 0,
                            "analysis_status": "ANALYZING",
                            "analysis_error": "rtsp://user:password@10.0.0.10/live",
                        }],
                    },
                    "machines": {
                        "total": 1,
                        "items": [{
                            "monitor_id": "mon_01",
                            "camera_id": "cam_01",
                            "machine_state": "STOPPED",
                            "analysis_status": "ANALYZING",
                            "signal_quality": 0.87,
                            "calibration_result": "PASS",
                            "frames_analyzed": 42,
                            "confidence": 0.91,
                            "reason": "motion below baseline",
                        }],
                    },
                    "edge_secret": "should-not-persist",
                }
            }
            second = {
                "diagnostics": {
                    **first["diagnostics"],
                    "generated_at": "2026-09-03T10:01:00+00:00",
                    "cameras": {**first["diagnostics"]["cameras"], "online": 0, "offline": 1},
                }
            }
            self.assertEqual(client.post("/edge/heartbeat", json=first, headers={"X-Edge-Id": EDGE_ID, "X-Edge-Secret": EDGE_SECRET}).status_code, 200)
            self.assertEqual(client.post("/edge/heartbeat", json=second, headers={"X-Edge-Id": EDGE_ID, "X-Edge-Secret": EDGE_SECRET}).status_code, 200)
            payload = client.get(f"/edges/{EDGE_ID}/diagnostics").json()
            with cloud_database.connect() as db:
                row = db.fetchone("SELECT last_diagnostics_json FROM edge_devices WHERE id = ?", (EDGE_ID,))

        self.assertEqual(payload["generated_at"], "2026-09-03T10:01:00+00:00")
        self.assertIsNotNone(payload["received_at"])
        self.assertEqual(payload["diagnostics"]["cameras"]["online"], 0)
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("should-not-persist", serialized)
        self.assertNotIn("rtsp://user:password", serialized)
        self.assertIn("[redacted]", serialized)
        self.assertIn("received_at", row["last_diagnostics_json"])

    def test_edge_diagnostics_auth_and_tenant_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = self.make_cloud_client(temp_dir)
            self.register_edge(client, tenant_id="cli_fl", unidade_id="uni_fl")
            client.post(
                "/edge/heartbeat",
                json={"diagnostics": {"generated_at": "2026-09-03T10:00:00+00:00", "edge": {}, "cameras": {}, "machines": {}}},
                headers={"X-Edge-Id": EDGE_ID, "X-Edge-Secret": EDGE_SECRET},
            )
            self.assertEqual(
                client.post("/edge/heartbeat", json={}, headers={"X-Edge-Id": EDGE_ID, "X-Edge-Secret": "wrong"}).status_code,
                401,
            )
            with cloud_database.connect() as db:
                cloud_database.init_cloud_db(db)
                create_user(
                    db,
                    email="tenant@campex.test",
                    password="SenhaCampex123",
                    role="admin_cliente",
                    nome="Tenant",
                    cliente_id="cli_other",
                )
            other = TestClient(cloud_api)
            self.assertEqual(other.post("/auth/login", json={"email": "tenant@campex.test", "senha": "SenhaCampex123"}).status_code, 200)
            forbidden = other.get(f"/edges/{EDGE_ID}/diagnostics")

        self.assertEqual(forbidden.status_code, 403)

    def test_edge_diagnostics_offline_is_not_reported_healthy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = self.make_cloud_client(temp_dir)
            self.register_edge(client)
            with cloud_database.connect() as db:
                db.execute(
                    "UPDATE edge_devices SET last_seen_at = ?, last_diagnostics_json = ? WHERE id = ?",
                    (
                        "2026-09-03T10:00:00+00:00",
                        json.dumps({
                            "received_at": "2026-09-03T10:00:00+00:00",
                            "diagnostics": {"generated_at": "2026-09-03T10:00:00+00:00", "edge": {}, "cameras": {}, "machines": {}},
                        }),
                        EDGE_ID,
                    ),
                )
                db.commit()
            payload = client.get(f"/edges/{EDGE_ID}/diagnostics").json()

        self.assertFalse(payload["online"])
        self.assertEqual(payload["status"], "offline")
        self.assertTrue(payload["stale"])

    def test_edge_diagnostics_old_generated_at_is_stale_even_when_received_now(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = self.make_cloud_client(temp_dir)
            self.register_edge(client)
            old_generated_at = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
            response = client.post(
                "/edge/heartbeat",
                json={"diagnostics": {"generated_at": old_generated_at, "edge": {}, "cameras": {}, "machines": {}}},
                headers={"X-Edge-Id": EDGE_ID, "X-Edge-Secret": EDGE_SECRET},
            )
            payload = client.get(f"/edges/{EDGE_ID}/diagnostics").json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["online"])
        self.assertTrue(payload["stale"])

    def test_edge_diagnostics_recent_online_snapshot_is_not_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = self.make_cloud_client(temp_dir)
            self.register_edge(client)
            generated_at = datetime.now(timezone.utc).isoformat()
            response = client.post(
                "/edge/heartbeat",
                json={"diagnostics": {"generated_at": generated_at, "edge": {}, "cameras": {}, "machines": {}}},
                headers={"X-Edge-Id": EDGE_ID, "X-Edge-Secret": EDGE_SECRET},
            )
            payload = client.get(f"/edges/{EDGE_ID}/diagnostics").json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["online"])
        self.assertFalse(payload["stale"])

    def test_runtime_collects_partial_diagnostics_and_heartbeat_continues_when_collection_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = ProductionEdgeRuntime(edge_id=EDGE_ID, db_path=Path(temp_dir) / "edge.sqlite3")
            with patch("app.edge_runtime.api_module.live_streams.statuses", return_value=[
                {
                    "camera_id": "cam_01",
                    "status": "online",
                    "last_frame_at": "2026-09-03T10:00:00+00:00",
                    "analysis_error": "failed with rtsp://user:password@10.0.0.10/live and token=abc",
                    "machine_monitor_id": "mon_01",
                    "machine_state": "ACTIVE",
                    "machine_analysis_status": "ANALYZING",
                    "machine_frames_analyzed": 10,
                    "machine_confidence": 0.88,
                    "machine_reason": "secret leaked in local reason",
                }
            ]), patch.object(runtime, "_check_local_api_health", return_value=None), patch("app.edge_runtime.db_connect", side_effect=RuntimeError("credential .env rtsp://secret")):
                diagnostics = runtime._collect_cloud_diagnostics()

            calls = []

            class FakeResponse:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

            def fake_urlopen(request, timeout):
                calls.append(json.loads(request.data.decode("utf-8")))
                return FakeResponse()

            with patch.object(runtime, "_collect_cloud_diagnostics", side_effect=RuntimeError("partial failure")), patch("app.edge_runtime.urllib.request.urlopen", side_effect=fake_urlopen):
                runtime._send_cloud_heartbeat("https://cloud.campex.test", EDGE_SECRET)

        self.assertEqual(diagnostics["cameras"]["online"], 1)
        serialized = json.dumps(diagnostics, ensure_ascii=False)
        self.assertNotIn("rtsp://user:password", serialized)
        self.assertNotIn("token=abc", serialized)
        self.assertNotIn("credential .env", serialized)
        self.assertIn("diagnostic_redacted", serialized)
        self.assertIn("monitor_query_failed", serialized)
        self.assertEqual(diagnostics["machines"]["items"][0]["machine_state"], "ACTIVE")
        self.assertEqual(calls, [{}])


if __name__ == "__main__":
    unittest.main()
