from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from fastapi.testclient import TestClient

from app.api import api
from app.auth import create_user
from app.database import connect, init_db
from app.machine_monitoring import MachineMonitorEngine, ReplayBuffer, calibrate_threshold, config_from_dict
from app.models import (
    classificar_evento,
    criar_camera,
    criar_cliente,
    criar_machine_monitor,
    criar_unidade,
    listar_eventos_filtrados,
    obter_machine_monitor,
    obter_evento,
)
from app.person_detection import Detection


def frame_with_square(x: int | None = None) -> np.ndarray:
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    if x is not None:
        cv2.rectangle(frame, (x, 40), (x + 20, 70), (255, 255, 255), -1)
    return frame


class OperationsV1Test(unittest.TestCase):
    def make_context(self, temp_dir: str):
        db_path = Path(temp_dir) / "operations.sqlite3"

        def test_connect(_db_path: object = None):
            return connect(db_path)

        with connect(db_path) as connection:
            init_db(connection)
            cliente_id = criar_cliente(connection, "Cliente")
            unidade_id = criar_unidade(connection, cliente_id, "Unidade")
            camera_id = criar_camera(connection, unidade_id, "Camera", cliente_id=cliente_id)
            monitor_id = criar_machine_monitor(
                connection,
                cliente_id,
                unidade_id,
                camera_id,
                "Prensa",
                [{"x": 0.0, "y": 0.0}, {"x": 0.8, "y": 0.0}, {"x": 0.8, "y": 1.0}, {"x": 0.0, "y": 1.0}],
                [{"x": 0.75, "y": 0.0}, {"x": 1.0, "y": 0.0}, {"x": 1.0, "y": 1.0}, {"x": 0.75, "y": 1.0}],
                motion_sensitivity=3.0,
                stop_seconds=0.05,
                recovery_seconds=0.05,
                replay_pre_seconds=0.2,
                replay_post_seconds=0.1,
            )
            monitor = obter_machine_monitor(connection, monitor_id)
        return test_connect, config_from_dict(monitor), camera_id, monitor_id, cliente_id

    def test_running_machine_does_not_create_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, config, *_ = self.make_context(temp_dir)
            with patch("app.machine_monitoring.connect", test_connect):
                engine = MachineMonitorEngine(config, ReplayBuffer(config.camera_id, fps=30))
                for i in range(10):
                    engine.update(frame_with_square((i * 7) % 80), [])
                    time.sleep(0.01)
                with test_connect() as connection:
                    events = listar_eventos_filtrados(connection, tipo="machine_stoppage")
        self.assertEqual(events, [])

    def test_short_absence_of_motion_does_not_create_stop(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, config, *_ = self.make_context(temp_dir)
            config.stop_seconds = 1.0
            with patch("app.machine_monitoring.connect", test_connect):
                engine = MachineMonitorEngine(config, ReplayBuffer(config.camera_id, fps=30))
                engine.update(frame_with_square(10), [])
                engine.update(frame_with_square(10), [])
                with test_connect() as connection:
                    events = listar_eventos_filtrados(connection, tipo="machine_stoppage")
        self.assertEqual(events, [])

    def test_confirmed_stop_creates_single_event_and_recovery_closes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, config, *_ = self.make_context(temp_dir)
            with patch("app.machine_monitoring.connect", test_connect), patch("app.machine_monitoring.ROOT", Path(temp_dir)):
                engine = MachineMonitorEngine(config, ReplayBuffer(config.camera_id, fps=30))
                engine.smoothing_seconds = 0.01
                engine.analysis_fps = 100
                engine.update(frame_with_square(10), [])
                time.sleep(0.06)
                engine.update(frame_with_square(10), [])
                engine.update(frame_with_square(10), [])
                time.sleep(0.06)
                engine.update(frame_with_square(10), [])
                time.sleep(0.06)
                for i in range(8):
                    engine.update(frame_with_square(20 + i * 8), [])
                    time.sleep(0.02)
                with test_connect() as connection:
                    events = listar_eventos_filtrados(connection, tipo="machine_stoppage")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["status"], "closed")
        self.assertIsNotNone(events[0]["midia_path"])

    def test_operator_present_and_absent_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, config, *_ = self.make_context(temp_dir)
            detection = Detection(130, 20, 150, 100, 0.9, track_id=4)
            with patch("app.machine_monitoring.connect", test_connect), patch("app.machine_monitoring.ROOT", Path(temp_dir)):
                engine = MachineMonitorEngine(config, ReplayBuffer(config.camera_id, fps=30))
                engine.smoothing_seconds = 0.01
                engine.analysis_fps = 100
                engine.update(frame_with_square(10), [detection])
                time.sleep(0.06)
                engine.update(frame_with_square(10), [detection])
                time.sleep(0.06)
                engine.update(frame_with_square(10), [detection])
                time.sleep(0.06)
                engine.update(frame_with_square(10), [detection])
                with test_connect() as connection:
                    events = listar_eventos_filtrados(connection, tipo="machine_stoppage")
        self.assertEqual(events[0]["operator_present_start"], 1)
        self.assertIn(4, events[0]["track_ids"])

    def test_replay_failure_does_not_remove_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, config, *_ = self.make_context(temp_dir)
            with patch("app.machine_monitoring.connect", test_connect), patch("app.machine_monitoring.write_replay", side_effect=RuntimeError("falha")):
                engine = MachineMonitorEngine(config, ReplayBuffer(config.camera_id, fps=30))
                engine.smoothing_seconds = 0.01
                engine.analysis_fps = 100
                engine.update(frame_with_square(10), [])
                time.sleep(0.06)
                engine.update(frame_with_square(10), [])
                time.sleep(0.06)
                engine.update(frame_with_square(10), [])
                time.sleep(0.06)
                engine.update(frame_with_square(10), [])
                with test_connect() as connection:
                    events = listar_eventos_filtrados(connection, tipo="machine_stoppage")
        self.assertEqual(len(events), 1)

    def test_classification_and_tenant_isolation_api(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, config, camera_id, monitor_id, cliente_id = self.make_context(temp_dir)
            with test_connect() as connection:
                user_id = create_user(connection, "gestor@example.com", "senha", "admin_cliente", cliente_id)
            with patch("app.api.connect", test_connect):
                client = TestClient(api)
                client.post("/auth/login", json={"email": "gestor@example.com", "senha": "senha"})
                monitors = client.get(f"/cameras/{camera_id}/machine-monitors")
                patched = client.patch(f"/machine-monitors/{monitor_id}", json={"motion_threshold": 5.0})
                operations = client.get("/operations")
            self.assertEqual(monitors.status_code, 200)
            self.assertEqual(patched.status_code, 200)
            self.assertEqual(len(operations.json()["machines"]), 1)

    def test_calibration_threshold(self) -> None:
        self.assertEqual(calibrate_threshold(20, 4), 12)


if __name__ == "__main__":
    unittest.main()
