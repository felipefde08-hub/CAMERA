from __future__ import annotations

import os
import threading

from app.config import DATABASE_PATH
from app.database import connect, init_db
from edge_agent.camera_worker import CameraWorker, CameraWorkerConfig


def main() -> None:
    camera_id = os.getenv("CAMERA_ID")
    source = os.getenv("RTSP_URL") or os.getenv("VIDEO_SOURCE")
    if not camera_id or not source:
        print("Defina CAMERA_ID e RTSP_URL ou VIDEO_SOURCE no ambiente.")
        return

    with connect(DATABASE_PATH) as connection:
        init_db(connection)

    worker = CameraWorker(CameraWorkerConfig(camera_id=camera_id, source=source), str(DATABASE_PATH))
    thread = threading.Thread(target=worker.run_forever, daemon=False)
    thread.start()
    thread.join()


if __name__ == "__main__":
    main()
