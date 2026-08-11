from __future__ import annotations

import logging
import os
import signal
import shutil
import threading
import time
from pathlib import Path

import uvicorn

import app.alerts as alerts_module
import app.api as api_module
from app.config import API_HOST, API_PORT
from app.database import connect as db_connect, init_db
from app.models import atualizar_camera_operacao, registrar_edge_heartbeat
from edge_agent.health import mark_edge_contact
from edge_agent.sync_outbox import flush_sync_outbox, pending_sync_count
from shared.schemas import now_iso

logger = logging.getLogger("campex.edge_runtime")


class ProductionEdgeRuntime:
    def __init__(
        self,
        *,
        edge_id: str,
        db_path: Path,
        host: str = API_HOST,
        port: int = API_PORT,
        heartbeat_seconds: float = 10.0,
        sync_seconds: float = 10.0,
    ) -> None:
        self.edge_id = edge_id
        self.db_path = db_path
        self.host = host
        self.port = port
        self.heartbeat_seconds = heartbeat_seconds
        self.sync_seconds = sync_seconds
        self.stop_event = threading.Event()
        self.server: uvicorn.Server | None = None
        self.threads: list[threading.Thread] = []

    def _run_api(self) -> None:
        config = uvicorn.Config(api_module.api, host=self.host, port=self.port, log_level=os.getenv("CAMPEX_LOG_LEVEL", "info").lower())
        self.server = uvicorn.Server(config)
        self.server.run()

    def _run_camera_runtime(self) -> None:
        backoff = 1.0
        while not self.stop_event.is_set():
            try:
                result = api_module.bootstrap_production_streams()
                failed = result.get("failed") or []
                if failed:
                    logger.warning("Bootstrap de cameras com falhas: %s", failed)
                    backoff = min(backoff * 2, 30.0)
                else:
                    backoff = 1.0
                self._record_runtime_heartbeat()
            except Exception as exc:
                logger.exception("Falha no bootstrap/runtime de cameras: %s", exc)
                backoff = min(backoff * 2, 30.0)
            self.stop_event.wait(max(self.heartbeat_seconds, backoff))

    def _record_runtime_heartbeat(self) -> None:
        streams = api_module.live_streams.statuses()
        with db_connect(self.db_path) as connection:
            init_db(connection)
            mark_edge_contact(connection, self.edge_id, "online")
            pending = pending_sync_count(connection)
            disk = shutil.disk_usage(self.db_path.parent if self.db_path.parent.exists() else Path("."))
            online_count = 0
            last_frame = None
            capture_fps_values: list[float] = []
            inference_fps_values: list[float] = []
            frames_analyzed = 0
            for stream in streams:
                camera_id = str(stream.get("camera_id"))
                status = str(stream.get("status") or "offline")
                if status == "online":
                    online_count += 1
                if stream.get("last_frame_at"):
                    last_frame = max(last_frame or "", str(stream.get("last_frame_at")))
                if stream.get("fps") is not None:
                    capture_fps_values.append(float(stream.get("fps") or 0))
                if stream.get("analysis_fps") is not None:
                    inference_fps_values.append(float(stream.get("analysis_fps") or 0))
                frames = int(stream.get("analysis_frames") or stream.get("machine_frames_analyzed") or 0)
                frames_analyzed += frames
                atualizar_camera_operacao(
                    connection,
                    camera_id,
                    status,
                    ultimo_frame=str(stream.get("last_frame_at")) if stream.get("last_frame_at") else None,
                    ultimo_erro=str(stream.get("error")) if stream.get("error") else None,
                    frames_increment=0,
                )
            registrar_edge_heartbeat(
                connection,
                self.edge_id,
                heartbeat_at=now_iso(),
                camera_online=online_count > 0,
                last_frame_at=last_frame,
                capture_fps=round(sum(capture_fps_values) / len(capture_fps_values), 2) if capture_fps_values else None,
                inference_fps=round(sum(inference_fps_values) / len(inference_fps_values), 2) if inference_fps_values else None,
                frames_analyzed=frames_analyzed,
                outbox_pending=pending,
                disk_free_bytes=int(disk.free),
                disk_used_percent=round((disk.used / disk.total) * 100, 2) if disk.total else None,
            )

    def _run_outbox_sync(self) -> None:
        cloud_url = os.getenv("CAMPEX_CLOUD_URL")
        edge_secret = os.getenv("CAMPEX_EDGE_SECRET")
        if not cloud_url or not edge_secret:
            logger.info("Sincronizacao cloud desativada: CAMPEX_CLOUD_URL/CAMPEX_EDGE_SECRET ausentes.")
            return
        while not self.stop_event.is_set():
            try:
                with db_connect(self.db_path) as connection:
                    init_db(connection)
                    flush_sync_outbox(connection, cloud_url, self.edge_id, edge_secret)
            except Exception as exc:
                logger.warning("Falha temporaria ao sincronizar outbox: %s", exc)
            self.stop_event.wait(self.sync_seconds)

    def _run_alert_delivery_resume(self) -> None:
        while not self.stop_event.is_set():
            try:
                alerts_module.resume_pending_deliveries()
            except Exception as exc:
                logger.warning("Falha temporaria ao retomar entregas de alerta: %s", exc)
            self.stop_event.wait(self.sync_seconds)

    def _bind_runtime_database(self) -> None:
        def runtime_connect(_path: str | Path | None = None):
            return db_connect(self.db_path)

        api_module.connect = runtime_connect
        alerts_module.connect = runtime_connect

    def start(self) -> None:
        self._bind_runtime_database()
        with db_connect(self.db_path) as connection:
            init_db(connection)
        alerts_module.resume_pending_deliveries()
        jobs = [
            ("campex-api", self._run_api),
            ("campex-camera-runtime", self._run_camera_runtime),
            ("campex-outbox-sync", self._run_outbox_sync),
            ("campex-alert-delivery-resume", self._run_alert_delivery_resume),
        ]
        for name, target in jobs:
            thread = threading.Thread(target=target, name=name, daemon=True)
            self.threads.append(thread)
            thread.start()
        logger.info("Campex Edge disponivel em http://%s:%s", self.host, self.port)

    def wait(self) -> None:
        try:
            while not self.stop_event.is_set():
                time.sleep(0.5)
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        if self.stop_event.is_set():
            return
        logger.info("Encerrando Campex Edge com graceful shutdown.")
        self.stop_event.set()
        api_module.live_streams.stop_all()
        if self.server:
            self.server.should_exit = True
        for thread in self.threads:
            thread.join(timeout=8.0)


def run_production_edge(
    *,
    edge_id: str,
    db_path: Path,
    host: str = API_HOST,
    port: int = API_PORT,
    heartbeat_seconds: float = 10.0,
    sync_seconds: float = 10.0,
) -> None:
    runtime = ProductionEdgeRuntime(
        edge_id=edge_id,
        db_path=db_path,
        host=host,
        port=port,
        heartbeat_seconds=heartbeat_seconds,
        sync_seconds=sync_seconds,
    )

    def stop(_signum: int, _frame: object) -> None:
        runtime.shutdown()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    runtime.start()
    runtime.wait()
