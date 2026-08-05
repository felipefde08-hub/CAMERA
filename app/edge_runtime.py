from __future__ import annotations

import logging
import os
import signal
import threading
import time
from pathlib import Path

import uvicorn

from app.alerts import resume_pending_deliveries
from app.api import api
from app.config import API_HOST, API_PORT
from app.database import connect, init_db
from edge_agent.service import EdgeSupervisor
from edge_agent.sync_outbox import flush_sync_outbox

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
        self.supervisor = EdgeSupervisor(edge_id=edge_id, db_path=db_path, heartbeat_seconds=heartbeat_seconds)
        self.server: uvicorn.Server | None = None
        self.threads: list[threading.Thread] = []

    def _run_api(self) -> None:
        config = uvicorn.Config(api, host=self.host, port=self.port, log_level=os.getenv("CAMPEX_LOG_LEVEL", "info").lower())
        self.server = uvicorn.Server(config)
        self.server.run()

    def _run_supervisor(self) -> None:
        self.supervisor.run_forever()

    def _run_outbox_sync(self) -> None:
        cloud_url = os.getenv("CAMPEX_CLOUD_URL")
        edge_secret = os.getenv("CAMPEX_EDGE_SECRET")
        if not cloud_url or not edge_secret:
            logger.info("Sincronizacao cloud desativada: CAMPEX_CLOUD_URL/CAMPEX_EDGE_SECRET ausentes.")
            return
        while not self.stop_event.is_set():
            try:
                with connect(self.db_path) as connection:
                    init_db(connection)
                    flush_sync_outbox(connection, cloud_url, self.edge_id, edge_secret)
            except Exception as exc:
                logger.warning("Falha temporaria ao sincronizar outbox: %s", exc)
            self.stop_event.wait(self.sync_seconds)

    def start(self) -> None:
        with connect(self.db_path) as connection:
            init_db(connection)
        resume_pending_deliveries()
        jobs = [
            ("campex-api", self._run_api),
            ("campex-edge-supervisor", self._run_supervisor),
            ("campex-outbox-sync", self._run_outbox_sync),
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
        self.supervisor.shutdown()
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
