from backend.cameras.repository import CameraRepository
from backend.database.db import initialize_database
from tests.helpers import make_settings


def test_camera_model_persists_minimum_fields(tmp_path):
    settings = make_settings(tmp_path / "repo.sqlite3")
    initialize_database(settings)
    repository = CameraRepository(settings)

    camera = repository.create(
        name="Entrada",
        area_id=None,
        source_type="webcam",
        source_uri="0",
        enabled=True,
        vision_enabled=False,
    )

    assert camera.id.startswith("cam_")
    assert camera.name == "Entrada"
    assert camera.source_type == "webcam"
    assert camera.status == "OFFLINE"

    updated = repository.update(camera.id, {"enabled": False, "name": "Entrada 2"})

    assert updated is not None
    assert updated.enabled is False
    assert updated.name == "Entrada 2"
    assert repository.delete(camera.id) is True
    assert repository.get(camera.id) is None
