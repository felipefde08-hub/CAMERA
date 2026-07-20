from __future__ import annotations

import time
import unittest

import cv2
import numpy as np
from fastapi.testclient import TestClient

from app.api import api, live_streams
from app.live_stream import LiveStreamManager
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


if __name__ == "__main__":
    unittest.main()
