from __future__ import annotations

import time
import unittest

import cv2
import numpy as np
from fastapi.testclient import TestClient

from app import api as api_module
from app.api import api, live_streams
from app.live_stream import LiveStreamManager
from app.person_detection import PersonAnalysisEngine
from edge_agent.camera_connector import CameraSource


class FakeCapture:
    opened_count = 0

    def __init__(self, frames: list[np.ndarray], opened: bool = True) -> None:
        self.frames = frames
        self.opened = opened
        self.released = False

    def isOpened(self) -> bool:
        return self.opened and not self.released

    def read(self) -> tuple[bool, np.ndarray | None]:
        if not self.frames:
            self.opened = False
            return False, None
        time.sleep(0.01)
        return True, self.frames.pop(0)

    def get(self, prop: int) -> float:
        if prop == cv2.CAP_PROP_FRAME_WIDTH:
            return 64
        if prop == cv2.CAP_PROP_FRAME_HEIGHT:
            return 48
        if prop == cv2.CAP_PROP_FPS:
            return 12
        return 0

    def release(self) -> None:
        self.released = True


class FakeConnector:
    opened = 0

    def __init__(self, camera: CameraSource) -> None:
        self.camera = camera
        self.info = type(
            "Info",
            (),
            {"width": 64, "height": 48, "fps": 12.0, "error": None},
        )()
        self.capture: FakeCapture | None = None

    def open(self) -> bool:
        FakeConnector.opened += 1
        frame = np.zeros((48, 64, 3), dtype=np.uint8)
        self.capture = FakeCapture([frame.copy() for _ in range(200)])
        return True

    def stop(self) -> None:
        if self.capture:
            self.capture.release()

    def close(self) -> None:
        if self.capture:
            self.capture.release()


class FailingThenWorkingConnector(FakeConnector):
    attempts = 0

    def open(self) -> bool:
        FailingThenWorkingConnector.attempts += 1
        if FailingThenWorkingConnector.attempts == 1:
            self.info.error = "falha simulada"
            return False
        return super().open()


class FailingDetector:
    model_name = "fake-person-detector"

    def detect(self, frame):
        raise RuntimeError("falha IA simulada")


class LiveStreamStage2Test(unittest.TestCase):
    def tearDown(self) -> None:
        live_streams.stop_all()

    def test_live_stream_reuses_one_connection_for_same_camera(self) -> None:
        FakeConnector.opened = 0
        manager = LiveStreamManager(connector_factory=lambda camera: FakeConnector(camera))
        stream_a = manager.get_or_create("cam_1", "rtsp://user:pass@camera/stream")
        stream_b = manager.get_or_create("cam_1", "rtsp://user:pass@camera/stream")
        stream_a.start()
        stream_b.start()
        time.sleep(0.2)
        status = stream_a.public_status()
        manager.stop_all()

        self.assertIs(stream_a, stream_b)
        self.assertEqual(FakeConnector.opened, 1)
        self.assertNotIn("pass", str(status))

    def test_live_stream_reconnects_after_initial_failure(self) -> None:
        FailingThenWorkingConnector.attempts = 0
        manager = LiveStreamManager(connector_factory=lambda camera: FailingThenWorkingConnector(camera))
        stream = manager.get_or_create("cam_2", "rtsp://user:pass@camera/stream")
        stream.start()
        time.sleep(1.4)
        status = stream.public_status()
        manager.stop_all()

        self.assertGreaterEqual(FailingThenWorkingConnector.attempts, 2)
        self.assertIn(status["status"], {"online", "reconectando", "offline"})
        self.assertNotIn("pass", str(status))

    def test_status_endpoint_does_not_return_credentials_for_missing_stream(self) -> None:
        client = TestClient(api)
        response = client.get("/cameras/cam_inexistente/status")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("senha", response.text.lower())

    def test_live_view_starts_without_camera_registration(self) -> None:
        original_manager = api_module.live_streams
        original_sessions = dict(api_module.live_view_sessions)
        try:
            api_module.live_streams = LiveStreamManager(connector_factory=lambda camera: FakeConnector(camera))
            api_module.live_view_sessions.clear()
            client = TestClient(api)
            response = client.post(
                "/live-view/start",
                json={
                    "nome": "Intelbras Teste",
                    "host": "192.168.15.2",
                    "porta_rtsp": 554,
                    "usuario": "admin",
                    "senha": "segredo",
                    "caminho_rtsp": "/stream",
                },
            )
            payload = response.json()
            status = client.get(f"/live-view/{payload['session_id']}/status")
        finally:
            api_module.live_streams.stop_all()
            api_module.live_streams = original_manager
            api_module.live_view_sessions.clear()
            api_module.live_view_sessions.update(original_sessions)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["nome"], "Intelbras Teste")
        self.assertNotIn("segredo", response.text + status.text)
        self.assertIn(status.status_code, {200})

    def test_live_view_ops_endpoints_do_not_expose_credentials(self) -> None:
        original_manager = api_module.live_streams
        original_sessions = dict(api_module.live_view_sessions)
        try:
            api_module.live_streams = LiveStreamManager(connector_factory=lambda camera: FakeConnector(camera))
            api_module.live_view_sessions.clear()
            client = TestClient(api)
            response = client.post(
                "/live-view/start",
                json={
                    "nome": "Intelbras Operacional",
                    "host": "192.168.15.2",
                    "usuario": "admin",
                    "senha": "segredo",
                    "caminho_rtsp": "/cam/realmonitor",
                },
            )
            session_id = response.json()["session_id"]
            ai = client.post(f"/live-view/{session_id}/ai/start")
            machine = client.post(
                f"/live-view/{session_id}/machine",
                json={
                    "nome": "Extrusora principal",
                    "machine_polygon": [
                        {"x": 0.2, "y": 0.2},
                        {"x": 0.8, "y": 0.2},
                        {"x": 0.8, "y": 0.8},
                        {"x": 0.2, "y": 0.8},
                    ],
                },
            )
            calibration = client.post(f"/live-view/{session_id}/machine/calibrate-active")
            status = client.get(f"/live-view/{session_id}/status")
        finally:
            api_module.live_streams.stop_all()
            api_module.live_streams = original_manager
            api_module.live_view_sessions.clear()
            api_module.live_view_sessions.update(original_sessions)

        combined = response.text + ai.text + machine.text + calibration.text + status.text
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ai.status_code, 200)
        self.assertEqual(machine.status_code, 200)
        self.assertEqual(calibration.status_code, 200)
        self.assertEqual(status.status_code, 200)
        self.assertTrue(ai.json()["ai_enabled"])
        self.assertEqual(machine.json()["machine"]["nome"], "Extrusora principal")
        self.assertEqual(calibration.json()["calibration_status"], "calibrada")
        self.assertIn("ops", status.json())
        self.assertNotIn("segredo", combined)

    def test_live_view_stream_stays_online_when_ai_fails(self) -> None:
        manager = LiveStreamManager(connector_factory=lambda camera: FakeConnector(camera))
        stream = manager.get_or_create("live_fail", "rtsp://user:pass@camera/stream")
        stream.enable_live_view_ops()
        stream._analysis_engine = PersonAnalysisEngine(detector=FailingDetector(), tracking_enabled=False)
        stream.start()
        stream.set_analysis(True)
        time.sleep(0.4)
        status = stream.public_status()
        manager.stop_all()

        self.assertIn(status["status"], {"online", "reconectando", "offline"})
        self.assertEqual(status["ai_status"], "indisponivel")
        self.assertIn("falha IA simulada", status["analysis_error"])
        self.assertNotIn("pass", str(status))


if __name__ == "__main__":
    unittest.main()
