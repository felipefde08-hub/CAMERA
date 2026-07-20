from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.camera_rtsp import build_rtsp_url
from app.database import connect, init_db
from app.models import criar_camera, criar_cliente, criar_unidade, listar, obter_camera


class CameraRtspStage1Test(unittest.TestCase):
    def test_build_rtsp_url_masks_credentials(self) -> None:
        connection = build_rtsp_url(
            host="192.168.1.50",
            port=554,
            path="live/channel1",
            username="admin",
            password="senha-secreta",
        )

        self.assertEqual(connection.url, "rtsp://admin:senha-secreta@192.168.1.50:554/live/channel1")
        self.assertEqual(connection.safe_url, "rtsp://***:***@192.168.1.50:554/live/channel1")
        self.assertNotIn("senha-secreta", connection.safe_url)

    def test_camera_credentials_stay_out_of_public_listing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "stage1.sqlite3"
            with connect(db_path) as connection:
                init_db(connection)
                cliente_id = criar_cliente(connection, "Cliente RTSP")
                unidade_id = criar_unidade(connection, cliente_id, "Unidade RTSP")
                rtsp = build_rtsp_url(
                    host="camera.local",
                    port=554,
                    path="/stream",
                    username="operador",
                    password="muito-secreta",
                )
                camera_id = criar_camera(
                    connection,
                    unidade_id,
                    "Camera RTSP",
                    config_ref=rtsp.url,
                    status="offline",
                    cliente_id=cliente_id,
                    source_type="rtsp",
                    secure_ref=rtsp.safe_url,
                    rtsp_host=rtsp.host,
                    rtsp_port=rtsp.port,
                    rtsp_path=rtsp.path,
                    rtsp_username=rtsp.username,
                    rtsp_password=rtsp.password,
                )
                private_camera = obter_camera(connection, camera_id, include_secret=True)
                public_camera = listar(connection, "cameras")[0]

        self.assertEqual(private_camera["rtsp_password"], "muito-secreta")
        self.assertNotIn("rtsp_password", public_camera)
        self.assertNotIn("rtsp_username", public_camera)
        self.assertNotIn("muito-secreta", str(public_camera))
        self.assertIn("***:***", public_camera["config_ref"])


if __name__ == "__main__":
    unittest.main()
