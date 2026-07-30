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
from app.machine_replay import evaluate_state_samples
from app.observation_engine import ObservationEngine
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
            active_baseline=30.0,
            stopped_baseline=2.0,
            active_noise=1.0,
            stopped_noise=0.5,
            loss_model="loss_per_minute",
            loss_per_minute=120.0,
        )
        return MachineMonitorEngine(config)

    def test_baseline_stats_are_measurable(self) -> None:
        baseline, noise = baseline_stats([10, 12, 14])

        self.assertEqual(baseline, 12.0)
        self.assertGreater(noise, 0)

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
        self.assertEqual(updated["calibration_algorithm_version"], "frame-diff-roi-v1")

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
