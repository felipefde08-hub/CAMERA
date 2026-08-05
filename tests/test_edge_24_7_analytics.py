from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import api as api_module
from app.analytics import aggregate_period, compute_summary, data_quality, generate_insights, parse_dt
from app.api import api
from app.database import connect, init_db
from app.models import (
    criar_camera,
    criar_cliente,
    criar_machine_monitor,
    criar_unidade,
    registrar_edge_heartbeat,
    registrar_evento,
    registrar_operational_sample,
)
from shared.schemas import now_iso


class Edge24x7AnalyticsTest(unittest.TestCase):
    def make_db(self, temp_dir: str):
        db_path = Path(temp_dir) / "edge24.sqlite3"
        connection = connect(db_path)
        init_db(connection)
        cliente_id = criar_cliente(connection, "Cliente Teste")
        unidade_id = criar_unidade(connection, cliente_id, "Unidade Teste")
        camera_id = criar_camera(connection, unidade_id, "Camera Teste", cliente_id=cliente_id, edge_id="edge_test")
        machine_id = criar_machine_monitor(
            connection,
            client_id=cliente_id,
            unit_id=unidade_id,
            camera_id=camera_id,
            nome="Extrusora Teste",
            machine_polygon=[{"x": 0.1, "y": 0.1}, {"x": 0.8, "y": 0.1}, {"x": 0.8, "y": 0.8}],
            operator_polygon=[{"x": 0.1, "y": 0.1}, {"x": 0.5, "y": 0.1}, {"x": 0.5, "y": 0.5}],
        )
        return connection, db_path, cliente_id, unidade_id, camera_id, machine_id

    def test_edge_heartbeat_is_persisted_and_exposed_in_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            connection, db_path, _cliente_id, _unidade_id, _camera_id, _machine_id = self.make_db(temp_dir)
            registrar_edge_heartbeat(
                connection,
                "edge_test",
                heartbeat_at=now_iso(),
                camera_online=True,
                last_frame_at="2026-08-05T10:00:00+00:00",
                capture_fps=15.0,
                inference_fps=4.0,
                frames_analyzed=40,
                outbox_pending=2,
                disk_free_bytes=123456,
                disk_used_percent=42.0,
            )

            def patched_connect(_path=None):
                return connect(db_path)

            with patch.object(api_module, "connect", patched_connect):
                client = TestClient(api)
                response = client.get("/edge/status?edge_id=edge_test")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["heartbeat"]["edge_id"], "edge_test")
        self.assertEqual(response.json()["heartbeat"]["frames_analyzed"], 40)

    def test_analytics_counts_event_once_and_persists_idempotent_hourly_aggregation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            connection, _db_path, cliente_id, unidade_id, camera_id, machine_id = self.make_db(temp_dir)
            event_id = registrar_evento(
                connection,
                cliente_id,
                unidade_id,
                camera_id,
                "machine_stoppage",
                inicio="2026-08-05T10:10:00+00:00",
                fim="2026-08-05T10:20:00+00:00",
                duracao=600,
            )
            connection.execute("UPDATE eventos SET machine_monitor_id = ? WHERE id = ?", (machine_id, event_id))
            connection.commit()
            start = parse_dt("2026-08-05T10:00:00+00:00")
            end = parse_dt("2026-08-05T11:00:00+00:00")

            first = aggregate_period(connection, machine_id=machine_id, camera_id=camera_id, start=start, end=end, aggregation="hour")
            second = aggregate_period(connection, machine_id=machine_id, camera_id=camera_id, start=start, end=end, aggregation="hour")
            rows = connection.execute("SELECT COUNT(*) AS total FROM hourly_machine_metrics").fetchone()["total"]

        self.assertEqual(first["stoppage_count"], 1)
        self.assertEqual(first["stopped_seconds"], 600)
        self.assertEqual(second["stoppage_count"], 1)
        self.assertEqual(rows, 1)

    def test_data_quality_reports_missing_samples_and_insights_are_traceable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            connection, _db_path, cliente_id, unidade_id, camera_id, machine_id = self.make_db(temp_dir)
            event_id = registrar_evento(
                connection,
                cliente_id,
                unidade_id,
                camera_id,
                "machine_running_without_operator",
                inicio="2026-08-05T12:00:00+00:00",
                fim="2026-08-05T12:03:00+00:00",
                duracao=180,
            )
            connection.execute("UPDATE eventos SET machine_monitor_id = ? WHERE id = ?", (machine_id, event_id))
            registrar_operational_sample(
                connection,
                sample_uuid="sample-1",
                tenant_id=cliente_id,
                unit_id=unidade_id,
                camera_id=camera_id,
                machine_id=machine_id,
                machine_state="ACTIVE",
                operator_present=False,
                activity_score=12.0,
                confidence=0.8,
                capture_fps=15.0,
                inference_fps=5.0,
                frames_analyzed=10,
                camera_online=True,
                sample_at="2026-08-05T12:00:00+00:00",
            )
            start = parse_dt("2026-08-05T12:00:00+00:00")
            end = parse_dt("2026-08-05T13:00:00+00:00")
            summary = compute_summary(connection, machine_id=machine_id, camera_id=camera_id, start=start, end=end)
            quality = data_quality(connection, machine_id=machine_id, camera_id=camera_id, start=start, end=end)
            insights = generate_insights(connection, machine_id=machine_id, camera_id=camera_id, start=start, end=end)

        self.assertEqual(summary["running_without_operator_seconds"], 180)
        self.assertTrue(quality["periods"])
        self.assertTrue(any(item["rule_id"] == "running_without_operator_v1" for item in insights))


if __name__ == "__main__":
    unittest.main()
