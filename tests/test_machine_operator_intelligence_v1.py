from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from app.database import connect, init_db
from app.live_stream import LiveCameraStream, calibration_separation, calibration_stats
from app.machine_monitoring import MachineMonitorConfig, MachineMonitorEngine, baseline_stats
from app.models import criar_area_monitorada, criar_camera, criar_cliente, criar_machine_monitor, criar_unidade, obter_machine_monitor
from app.models import criar_alert_recipient, listar_alert_deliveries
from app.machine_replay import evaluate_state_samples
from app.observation_engine import ObservationEngine
from app.person_detection import Detection
from app.restricted_area import AreaPoint


class MachineOperatorIntelligenceV1Test(unittest.TestCase):
    def make_context(self, temp_dir: str):
        db_path = Path(temp_dir) / "machine-v1.sqlite3"

        def test_connect():
            return connect(db_path)

        with test_connect() as connection:
            init_db(connection)
            cliente_id = criar_cliente(connection, "Cliente")
            unidade_id = criar_unidade(connection, cliente_id, "Unidade")
            camera_id = criar_camera(connection, unidade_id, "Camera", cliente_id=cliente_id)
            monitor_id = criar_machine_monitor(
                connection,
                cliente_id,
                unidade_id,
                camera_id,
                "Extrusora",
                [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1}, {"x": 0.9, "y": 0.9}],
                [{"x": 0.0, "y": 0.1}, {"x": 0.2, "y": 0.1}, {"x": 0.2, "y": 0.9}],
                stop_seconds=0.1,
                recovery_seconds=0.1,
                operator_absence_seconds=0.1,
                stopped_with_operator_seconds=0.1,
                loss_model="loss_per_minute",
                loss_per_minute=120.0,
            )
        return test_connect, cliente_id, unidade_id, camera_id, monitor_id

    def make_engine(self, cliente_id: str, unidade_id: str, camera_id: str, monitor_id: str) -> MachineMonitorEngine:
        config = MachineMonitorConfig(
            id=monitor_id,
            client_id=cliente_id,
            unit_id=unidade_id,
            camera_id=camera_id,
            nome="Extrusora",
            machine_polygon=[AreaPoint(0.1, 0.1), AreaPoint(0.9, 0.1), AreaPoint(0.9, 0.9)],
            operator_polygon=[AreaPoint(0.0, 0.1), AreaPoint(0.2, 0.1), AreaPoint(0.2, 0.9)],
            stop_seconds=0.1,
            recovery_seconds=0.1,
            operator_absence_seconds=0.1,
            stopped_with_operator_seconds=0.1,
            active_baseline=30.0,
            stopped_baseline=2.0,
            active_noise=1.0,
            stopped_noise=0.5,
            loss_model="loss_per_minute",
            loss_per_minute=120.0,
        )
        return MachineMonitorEngine(config)

    def wait_for_deliveries(self, test_connect, expected: int = 1):
        for _ in range(30):
            with test_connect() as connection:
                rows = listar_alert_deliveries(connection)
            if len(rows) >= expected and all(row["status"] != "pending" for row in rows):
                return rows
            time.sleep(0.05)
        with test_connect() as connection:
            return listar_alert_deliveries(connection)

    def test_baseline_stats_are_measurable(self) -> None:
        baseline, noise = baseline_stats([10, 12, 14])

        self.assertEqual(baseline, 12.0)
        self.assertGreater(noise, 0)

    def test_default_operator_presence_grace_is_conservative_for_factory_flow(self) -> None:
        config = MachineMonitorConfig(
            id="mon_1",
            client_id="tenant",
            unit_id="unit",
            camera_id="cam_1",
            nome="A6",
            machine_polygon=[AreaPoint(0.1, 0.1), AreaPoint(0.9, 0.1), AreaPoint(0.9, 0.9)],
            operator_polygon=[AreaPoint(0.0, 0.0), AreaPoint(0.2, 0.0), AreaPoint(0.2, 1.0)],
        )

        self.assertEqual(config.operator_presence_grace_seconds, 45.0)

    def test_evidence_window_keeps_only_recent_compressed_frames(self) -> None:
        stream = LiveCameraStream("cam_evidence", "fake.mp4")
        frame = np.zeros((60, 80, 3), dtype=np.uint8)

        with patch(
            "app.live_stream.time.monotonic",
            side_effect=[100.0, 101.0, 102.1, 133.0, 133.0],
        ), patch(
            "app.live_stream.now_iso",
            side_effect=[
                "2026-08-19T10:00:00+00:00",
                "2026-08-19T10:00:02+00:00",
                "2026-08-19T10:00:33+00:00",
            ],
        ):
            stream._buffer_evidence_frame(frame)
            stream._buffer_evidence_frame(frame)
            stream._buffer_evidence_frame(frame)
            stream._buffer_evidence_frame(frame)
            recent = stream.recent_evidence_frames(30)

        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["captured_at"], "2026-08-19T10:00:33+00:00")
        self.assertIsInstance(recent[0]["jpeg"], bytes)
        self.assertGreater(len(recent[0]["jpeg"]), 0)

    def test_assisted_calibration_collects_frame_samples_and_persists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, _cliente_id, _unidade_id, camera_id, monitor_id = self.make_context(temp_dir)
            with test_connect() as connection:
                criar_area_monitorada(
                    connection,
                    camera_id,
                    "Região da máquina",
                    [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 0.0}, {"x": 1.0, "y": 1.0}],
                    tipo="machine_region",
                    machine_id=monitor_id,
                )
                monitor = obter_machine_monitor(connection, monitor_id)
            stream = LiveCameraStream(camera_id, "fake.mp4")
            frame_a = np.zeros((60, 80, 3), dtype=np.uint8)
            frame_b = np.full((60, 80, 3), 255, dtype=np.uint8)

            with patch("app.live_stream.connect", test_connect):
                stream.start_machine_calibration(monitor, monitor["machine_polygon"], "active", duration_seconds=0.05)
                stream._update_calibration(frame_a)
                stream._update_calibration(frame_b)
                stream._update_calibration(frame_a)
                time.sleep(0.06)
                stream._update_calibration(frame_b)
            with test_connect() as connection:
                rows = connection.execute("SELECT phase, samples_json, stats_json FROM machine_calibrations WHERE machine_id = ?", (monitor_id,)).fetchall()
                updated = obter_machine_monitor(connection, monitor_id)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["phase"], "active")
        self.assertGreater(updated["active_calibration"]["samples_count"], 0)
        self.assertEqual(updated["calibration_algorithm_version"], "frame-diff-roi-temporal-v1")

    def test_live_people_count_uses_temporal_detection_consistent_with_overlay(self) -> None:
        stream = LiveCameraStream("cam_temporal", "fake.mp4")
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        temporal_person = Detection(10, 10, 30, 80, 0.9, track_id=7)

        class FakeEngine:
            analysis_fps = 5.0
            model_name = "fake"

            def analyze(self, _frame):
                return []

            def recent_detections(self):
                return [temporal_person]

            def draw(self, output, _detections):
                return output

        stream._analysis_enabled = True
        stream._last_analysis_seconds = 0
        stream._ensure_analysis_engine = lambda: FakeEngine()
        stream._load_active_areas = lambda: []
        stream._load_machine_engines = lambda: []

        stream._maybe_analyze(frame)

        self.assertEqual(stream.public_status()["people_count"], 1)

    def test_calibration_separation_ready_and_invalid(self) -> None:
        active = calibration_stats([30, 32, 31, 33, 29])
        stopped = calibration_stats([1, 2, 1, 3, 2])

        ready = calibration_separation(active, stopped)
        invalid = calibration_separation(stopped, active)

        self.assertEqual(ready["result"], "READY")
        self.assertGreater(ready["score"], 3)
        self.assertEqual(invalid["result"], "INVALID")

    def test_official_state_uses_baseline_hysteresis(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _connect, cliente_id, unidade_id, camera_id, monitor_id = self.make_context(temp_dir)
            engine = self.make_engine(cliente_id, unidade_id, camera_id, monitor_id)

        engine.state.smoothed_motion = 32.0
        active, active_confidence, _reason = engine._classify_state()
        engine.state.smoothed_motion = 1.0
        stopped, stopped_confidence, reason = engine._classify_state()

        self.assertEqual(active, "ACTIVE")
        self.assertEqual(stopped, "STOPPED")
        self.assertGreater(active_confidence, 0.5)
        self.assertGreater(stopped_confidence, 0.5)
        self.assertIn("atividade visual", reason)

    def test_stop_event_is_unique_closes_and_enters_outbox_with_estimated_loss(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, cliente_id, unidade_id, camera_id, monitor_id = self.make_context(temp_dir)
            engine = self.make_engine(cliente_id, unidade_id, camera_id, monitor_id)
            frame = np.zeros((80, 120, 3), dtype=np.uint8)
            now = time.monotonic()
            with patch("app.machine_monitoring.connect", test_connect), patch("app.alerts.connect", test_connect), patch("app.machine_monitoring.save_machine_evidence", return_value=("data/evidence/test.jpg", None)):
                engine.state.state = "STOPPED"
                engine.state.state_since = now - 120.0
                engine.state.confidence = 0.9
                engine.state.reason = "atividade visual abaixo do baseline por 120 segundos"
                engine._evaluate_official_events(now, frame)
                engine._evaluate_official_events(now + 1, frame)
                engine.state.state = "ACTIVE"
                engine._evaluate_official_events(now + 120, frame)
            with test_connect() as connection:
                events = connection.execute("SELECT tipo, status, duracao, midia_path, metadata_json FROM eventos").fetchall()
                outbox = connection.execute("SELECT COUNT(*) AS total FROM sync_outbox").fetchone()["total"]

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["tipo"], "machine_stoppage")
        self.assertEqual(events[0]["status"], "closed")
        self.assertGreaterEqual(events[0]["duracao"], 100)
        self.assertEqual(events[0]["midia_path"], "data/evidence/test.jpg")
        self.assertIn("Impacto operacional estimado", events[0]["metadata_json"])
        self.assertEqual(outbox, 1)

    def test_machine_stoppage_duration_uses_condition_start_not_new_state_start(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, cliente_id, unidade_id, camera_id, monitor_id = self.make_context(temp_dir)
            engine = self.make_engine(cliente_id, unidade_id, camera_id, monitor_id)
            frame = np.zeros((80, 120, 3), dtype=np.uint8)
            stopped_started = 1000.0
            opened_at = 1002.0
            closed_at = 1012.5
            with patch("app.machine_monitoring.connect", test_connect), patch("app.alerts.connect", test_connect), patch("app.machine_monitoring.save_machine_evidence", return_value=(None, None)):
                engine.state.state = "STOPPED"
                engine.state.state_since = stopped_started
                engine.state.confidence = 0.9
                engine._open_event(opened_at, frame, "machine_stoppage")
                engine.state.state = "ACTIVE"
                engine.state.state_since = closed_at
                engine._close_event_type("machine_stoppage", closed_at)
            with test_connect() as connection:
                event = connection.execute("SELECT duracao FROM eventos WHERE tipo = 'machine_stoppage'").fetchone()

        self.assertIsNotNone(event)
        self.assertAlmostEqual(event["duracao"], 12.5, delta=0.2)

    def test_active_without_operator_uses_single_open_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, cliente_id, unidade_id, camera_id, monitor_id = self.make_context(temp_dir)
            engine = self.make_engine(cliente_id, unidade_id, camera_id, monitor_id)
            frame = np.zeros((80, 120, 3), dtype=np.uint8)
            now = time.monotonic()
            with patch("app.machine_monitoring.connect", test_connect), patch("app.alerts.connect", test_connect), patch("app.machine_monitoring.save_machine_evidence", return_value=(None, None)):
                engine.state.state = "ACTIVE"
                engine.state.state_since = now - 30.0
                engine.state.operator_present = False
                engine._evaluate_official_events(now, frame)
                engine._evaluate_official_events(now + 0.2, frame)
                engine._evaluate_official_events(now + 0.4, frame)
                engine.state.operator_present = True
                engine._evaluate_official_events(now + 2.0, frame)
            with test_connect() as connection:
                rows = connection.execute("SELECT tipo, status FROM eventos WHERE tipo = 'machine_running_without_operator'").fetchall()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "closed")

    def test_active_with_operator_is_normal_without_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, cliente_id, unidade_id, camera_id, monitor_id = self.make_context(temp_dir)
            engine = self.make_engine(cliente_id, unidade_id, camera_id, monitor_id)
            frame = np.zeros((80, 120, 3), dtype=np.uint8)
            now = time.monotonic()
            with patch("app.machine_monitoring.connect", test_connect), patch("app.alerts.connect", test_connect), patch("app.machine_monitoring.save_machine_evidence", return_value=(None, None)):
                engine.state.state = "ACTIVE"
                engine.state.state_since = now - 10.0
                engine.state.operator_present = True
                engine._evaluate_official_events(now, frame)
                engine._evaluate_official_events(now + 6.0, frame)
            with test_connect() as connection:
                events = connection.execute("SELECT COUNT(*) AS total FROM eventos").fetchone()["total"]
                outbox = connection.execute("SELECT COUNT(*) AS total FROM sync_outbox").fetchone()["total"]

        self.assertEqual(events, 0)
        self.assertEqual(outbox, 0)

    def test_short_detector_loss_keeps_operator_present_during_grace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _test_connect, cliente_id, unidade_id, camera_id, monitor_id = self.make_context(temp_dir)
            engine = self.make_engine(cliente_id, unidade_id, camera_id, monitor_id)
            engine.config.operator_presence_grace_seconds = 10.0
            engine.config.operator_polygon = [
                AreaPoint(0.0, 0.0),
                AreaPoint(0.25, 0.0),
                AreaPoint(0.25, 1.0),
                AreaPoint(0.0, 1.0),
            ]
            frame = np.zeros((100, 100, 3), dtype=np.uint8)
            detection = Detection(5, 20, 15, 70, 0.91, track_id=7)

            engine._update_operator(frame, [detection], dt=0.1, now=100.0)
            engine._update_operator(frame, [], dt=1.0, now=105.0)

        self.assertTrue(engine.state.operator_present)
        self.assertFalse(engine.state.raw_operator_present)
        self.assertIn("graça temporal", engine.state.operator_presence_reason)

    def test_operation_area_presence_survives_leaving_small_operator_zone(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _test_connect, cliente_id, unidade_id, camera_id, monitor_id = self.make_context(temp_dir)
            engine = self.make_engine(cliente_id, unidade_id, camera_id, monitor_id)
            engine.config.presence_scope = "OPERATION_AREA"
            engine.config.operation_polygon = [
                AreaPoint(0.0, 0.0),
                AreaPoint(1.0, 0.0),
                AreaPoint(1.0, 1.0),
                AreaPoint(0.0, 1.0),
            ]
            frame = np.zeros((100, 100, 3), dtype=np.uint8)
            outside_operator_zone_inside_operation = Detection(65, 20, 75, 70, 0.88, track_id=8)

            engine._update_operator(frame, [outside_operator_zone_inside_operation], dt=0.1, now=100.0)

        self.assertTrue(engine.state.operator_present)
        self.assertTrue(engine.state.raw_operator_present)

    def test_active_machine_sustained_absence_opens_event_after_grace_and_tolerance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, cliente_id, unidade_id, camera_id, monitor_id = self.make_context(temp_dir)
            engine = self.make_engine(cliente_id, unidade_id, camera_id, monitor_id)
            engine.config.operator_presence_grace_seconds = 1.0
            frame = np.zeros((80, 120, 3), dtype=np.uint8)
            now = time.monotonic()
            with patch("app.machine_monitoring.connect", test_connect), patch("app.alerts.connect", test_connect), patch("app.machine_monitoring.save_machine_evidence", return_value=(None, None)):
                engine.state.state = "ACTIVE"
                engine.state.state_since = now - 30.0
                engine.state.confidence = 0.9
                engine.state.last_operator_seen_at = now - 2.0
                engine.state.operator_present = False
                engine._evaluate_official_events(now, frame)
                engine._evaluate_official_events(now + 0.2, frame)
            with test_connect() as connection:
                rows = connection.execute("SELECT tipo, status FROM eventos WHERE tipo = 'machine_running_without_operator'").fetchall()

        self.assertEqual(len(rows), 1)

    def test_running_without_operator_event_evidence_outbox_and_alert(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict("os.environ", {"CAMPEX_EMAIL_MODE": "console"}):
            test_connect, cliente_id, unidade_id, camera_id, monitor_id = self.make_context(temp_dir)
            engine = self.make_engine(cliente_id, unidade_id, camera_id, monitor_id)
            frame = np.zeros((80, 120, 3), dtype=np.uint8)
            now = time.monotonic()
            with patch("app.machine_monitoring.connect", test_connect), patch("app.alerts.connect", test_connect), patch("app.machine_monitoring.save_machine_evidence", return_value=("data/evidence/running_without_operator.jpg", None)), patch("builtins.print"):
                with test_connect() as connection:
                    criar_alert_recipient(connection, "Operacao", "operacao@example.com", camera_id=camera_id, cliente_id=cliente_id, event_types=["machine_running_without_operator"])
                engine.state.state = "ACTIVE"
                engine.state.state_since = now - 20.0
                engine.state.operator_present = False
                engine._evaluate_official_events(now, frame)
                engine._evaluate_official_events(now + 0.2, frame)
                engine.state.operator_present = True
                engine._evaluate_official_events(now + 1.0, frame)
                deliveries = self.wait_for_deliveries(test_connect)
            with test_connect() as connection:
                events = connection.execute("SELECT tipo, status, duracao, midia_path, operator_present_start FROM eventos WHERE tipo = 'machine_running_without_operator'").fetchall()
                outbox = connection.execute("SELECT COUNT(*) AS total FROM sync_outbox").fetchone()["total"]

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["tipo"], "machine_running_without_operator")
        self.assertEqual(events[0]["status"], "closed")
        self.assertGreaterEqual(events[0]["duracao"], 0.1)
        self.assertEqual(events[0]["midia_path"], "data/evidence/running_without_operator.jpg")
        self.assertEqual(events[0]["operator_present_start"], 0)
        self.assertGreaterEqual(outbox, 1)
        self.assertGreaterEqual(len(deliveries), 1)
        self.assertTrue(all(delivery["status"] == "sent" for delivery in deliveries))

    def test_stopped_with_operator_event_evidence_outbox_and_alert(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict("os.environ", {"CAMPEX_EMAIL_MODE": "console"}):
            test_connect, cliente_id, unidade_id, camera_id, monitor_id = self.make_context(temp_dir)
            engine = self.make_engine(cliente_id, unidade_id, camera_id, monitor_id)
            frame = np.zeros((80, 120, 3), dtype=np.uint8)
            now = time.monotonic()
            with patch("app.machine_monitoring.connect", test_connect), patch("app.alerts.connect", test_connect), patch("app.machine_monitoring.save_machine_evidence", return_value=("data/evidence/stopped_with_operator.jpg", None)), patch("builtins.print"):
                with test_connect() as connection:
                    criar_alert_recipient(connection, "Manutencao", "manutencao@example.com", camera_id=camera_id, cliente_id=cliente_id, event_types=["machine_stopped_with_operator"])
                engine.state.state = "STOPPED"
                engine.state.state_since = now - 20.0
                engine.state.operator_present = True
                engine._evaluate_official_events(now, frame)
                engine._evaluate_official_events(now + 0.2, frame)
                engine.state.state = "ACTIVE"
                engine._evaluate_official_events(now + 1.0, frame)
                deliveries = self.wait_for_deliveries(test_connect)
            with test_connect() as connection:
                events = connection.execute("SELECT tipo, status, duracao, midia_path, operator_present_start FROM eventos WHERE tipo = 'machine_stopped_with_operator'").fetchall()
                outbox = connection.execute("SELECT COUNT(*) AS total FROM sync_outbox").fetchone()["total"]

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["tipo"], "machine_stopped_with_operator")
        self.assertEqual(events[0]["status"], "closed")
        self.assertGreaterEqual(events[0]["duracao"], 0.1)
        self.assertEqual(events[0]["midia_path"], "data/evidence/stopped_with_operator.jpg")
        self.assertEqual(events[0]["operator_present_start"], 1)
        self.assertGreaterEqual(outbox, 1)
        self.assertGreaterEqual(len(deliveries), 1)
        self.assertTrue(all(delivery["status"] == "sent" for delivery in deliveries))

    def test_replay_metrics_compare_annotations_and_detected_states(self) -> None:
        metrics = evaluate_state_samples(
            [
                {"start": 0, "end": 10, "machine_state": "ACTIVE", "operator_present": True},
                {"start": 10, "end": 20, "machine_state": "STOPPED", "operator_present": True},
            ],
            [
                {"second": 1, "machine_state": "ACTIVE", "confidence": 0.8},
                {"second": 11, "machine_state": "STOPPED", "confidence": 0.9},
                {"second": 12, "machine_state": "ACTIVE", "confidence": 0.7},
            ],
        )

        self.assertEqual(metrics["samples"], 3)
        self.assertEqual(metrics["tempo_correto_percentual"], 66.67)
        self.assertEqual(metrics["transicoes_anotadas"], 1)
        self.assertGreater(metrics["confianca_media"], 0)

    def test_observation_engine_builds_central_frame_observation(self) -> None:
        engine = ObservationEngine("cam_1")

        observation = engine.build(
            machine_id="mach_1",
            machine_state="ACTIVE",
            machine_activity_score=28.5,
            machine_confidence=0.87,
            operator_present=True,
            zone_states=[
                {"tipo": "operator_zone", "pessoas_dentro": 1},
                {"tipo": "restricted_zone", "pessoas_dentro": 0},
                {"tipo": "work_area", "pessoas_dentro": 2},
            ],
        )

        self.assertEqual(observation["camera_id"], "cam_1")
        self.assertEqual(observation["machine_id"], "mach_1")
        self.assertEqual(observation["machine_state"], "ACTIVE")
        self.assertEqual(observation["people_in_operator_zone"], 1)
        self.assertEqual(observation["people_in_restricted_zone"], 0)
        self.assertEqual(observation["people_in_work_area"], 2)
        self.assertIn("seconds_in_machine_state", observation)


if __name__ == "__main__":
    unittest.main()
