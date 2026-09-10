from fastapi.testclient import TestClient

from backend.config import Settings
from backend.database.db import initialize_database
from backend.main import app


def test_camera_crud_and_sanitized_response(monkeypatch, tmp_path):
    database_path = tmp_path / "api.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    initialize_database(Settings.from_env())

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/cameras",
            json={
                "name": "RTSP teste",
                "source_type": "rtsp",
                "source_uri": "rtsp://example-user:example-pass@192.168.1.50/stream",
                "enabled": False,
                "vision_enabled": False,
            },
        )
        assert response.status_code == 201
        camera = response.json()
        assert camera["source_uri"] == "rtsp://***:***@192.168.1.50/stream"

        camera_id = camera["id"]
        assert client.get(f"/api/v1/cameras/{camera_id}").status_code == 200
        assert len(client.get("/api/v1/cameras").json()) == 1

        patch = client.patch(f"/api/v1/cameras/{camera_id}", json={"name": "RTSP teste 2"})
        assert patch.status_code == 200
        assert patch.json()["name"] == "RTSP teste 2"

        health = client.get(f"/api/v1/cameras/{camera_id}/health")
        assert health.status_code == 200
        assert health.json()["status"] in {
            "CONNECTING",
            "ONLINE",
            "DEGRADED",
            "OFFLINE",
        }

        delete = client.delete(f"/api/v1/cameras/{camera_id}")
        assert delete.status_code == 204
        assert client.get(f"/api/v1/cameras/{camera_id}").status_code == 404


def test_test_connection_failure_is_reported(monkeypatch, tmp_path):
    database_path = tmp_path / "api-failure.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    initialize_database(Settings.from_env())

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/cameras",
            json={
                "name": "Arquivo ausente",
                "source_type": "video_file",
                "source_uri": str(tmp_path / "missing.mp4"),
                "enabled": False,
                "vision_enabled": False,
            },
        )
        camera_id = response.json()["id"]

        test_result = client.post(f"/api/v1/cameras/{camera_id}/test")

    assert test_result.status_code == 200
    assert test_result.json()["success"] is False
    assert test_result.json()["status"] == "OFFLINE"
