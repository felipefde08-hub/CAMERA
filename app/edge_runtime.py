from __future__ import annotations

import logging
import json
import os
import signal
import shutil
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from datetime import datetime, timedelta, timezone

import uvicorn

import app.alerts as alerts_module
import app.api as api_module
import app.pilot as pilot_module
from app.config import API_HOST, API_PORT
from app.database import connect as db_connect, init_db
from app.models import atualizar_camera_operacao, fechar_eventos_machine_interrompidos, registrar_edge_heartbeat
from app.operational_alerting import evaluate_alert_decisions
from app.operational_read_model import ReadModelFilters
from app.security import encrypt_secret
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
        alert_decision_seconds: float = 60.0,
        latest_frame_seconds: float = 3.0,
    ) -> None:
        self.edge_id = edge_id
        self.db_path = db_path
        self.host = host
        self.port = port
        self.heartbeat_seconds = heartbeat_seconds
        self.sync_seconds = sync_seconds
        self.alert_decision_seconds = alert_decision_seconds
        self.latest_frame_seconds = latest_frame_seconds
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

    def _send_cloud_heartbeat(self, cloud_url: str, edge_secret: str) -> None:
        url = f"{cloud_url.rstrip('/')}/edge/heartbeat"
        request = urllib.request.Request(
            url,
            data=b"{}",
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Edge-Id": self.edge_id,
                "X-Edge-Secret": edge_secret,
            },
        )
        with urllib.request.urlopen(request, timeout=5.0) as response:
            if response.status < 200 or response.status >= 300:
                raise RuntimeError(f"Cloud heartbeat retornou HTTP {response.status}")

    def _upload_latest_frame(self, cloud_url: str, edge_secret: str, camera_id: str, jpeg: bytes) -> None:
        url = f"{cloud_url.rstrip('/')}/edge/cameras/{camera_id}/latest-frame"
        request = urllib.request.Request(
            url,
            data=jpeg,
            method="POST",
            headers={
                "Content-Type": "image/jpeg",
                "X-Edge-Id": self.edge_id,
                "X-Edge-Secret": edge_secret,
            },
        )
        with urllib.request.urlopen(request, timeout=8.0) as response:
            if response.status < 200 or response.status >= 300:
                raise RuntimeError(f"Cloud latest-frame retornou HTTP {response.status}")

    def _send_cloud_camera_statuses(self, cloud_url: str, edge_secret: str) -> None:
        items = []
        for status in api_module.live_streams.statuses():
            items.append(
                {
                    "camera_id": status.get("camera_id"),
                    "status": status.get("status"),
                    "last_frame_at": status.get("last_frame_at"),
                    "ai_status": status.get("ai_status"),
                    "people_count": status.get("people_count"),
                    "machine_state": status.get("machine_state"),
                    "machine_motion": status.get("machine_motion"),
                    "machine_confidence": status.get("machine_confidence"),
                    "machine_reason": status.get("machine_reason"),
                    "machine_seconds_in_state": status.get("machine_seconds_in_state"),
                    "machine_analysis_status": status.get("machine_analysis_status"),
                    "machine_monitor_id": status.get("machine_monitor_id"),
                }
            )
        if not items:
            return
        request = urllib.request.Request(
            f"{cloud_url.rstrip('/')}/edge/cameras/status",
            data=json.dumps({"cameras": items}).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Edge-Id": self.edge_id,
                "X-Edge-Secret": edge_secret,
            },
        )
        with urllib.request.urlopen(request, timeout=8.0) as response:
            if response.status < 200 or response.status >= 300:
                raise RuntimeError(f"Cloud camera status retornou HTTP {response.status}")

    def _run_latest_frame_upload(self) -> None:
        cloud_url = os.getenv("CAMPEX_CLOUD_URL")
        edge_secret = os.getenv("CAMPEX_EDGE_SECRET")
        if not cloud_url or not edge_secret:
            logger.info("Upload de latest-frame desativado: CAMPEX_CLOUD_URL/CAMPEX_EDGE_SECRET ausentes.")
            return
        while not self.stop_event.is_set():
            for stream_status in api_module.live_streams.statuses():
                if self.stop_event.is_set():
                    break
                camera_id = str(stream_status.get("camera_id") or "")
                if not camera_id or stream_status.get("status") != "online":
                    continue
                stream = api_module.live_streams.get(camera_id)
                jpeg = stream.latest_jpeg() if stream and hasattr(stream, "latest_jpeg") else None
                if not jpeg:
                    continue
                try:
                    self._upload_latest_frame(cloud_url, edge_secret, camera_id, jpeg)
                except Exception as exc:
                    logger.warning("Falha temporaria ao enviar latest-frame da camera %s: %s", camera_id, exc)
            self.stop_event.wait(self.latest_frame_seconds)

    def _fetch_cloud_edge_config(self, cloud_url: str, edge_secret: str) -> dict[str, object]:
        url = f"{cloud_url.rstrip('/')}/edge/config"
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Accept": "application/json",
                "X-Edge-Id": self.edge_id,
                "X-Edge-Secret": edge_secret,
            },
        )
        with urllib.request.urlopen(request, timeout=10.0) as response:
            if response.status < 200 or response.status >= 300:
                raise RuntimeError(f"Cloud config retornou HTTP {response.status}")
            return json.loads(response.read().decode("utf-8"))

    def sync_cloud_edge_config(self, cloud_url: str, edge_secret: str) -> dict[str, int]:
        payload = self._fetch_cloud_edge_config(cloud_url, edge_secret)
        cameras = payload.get("cameras") if isinstance(payload, dict) else []
        areas = payload.get("areas") if isinstance(payload, dict) else []
        monitors = payload.get("machine_monitors") if isinstance(payload, dict) else []
        if not isinstance(cameras, list):
            cameras = []
        if not isinstance(areas, list):
            areas = []
        if not isinstance(monitors, list):
            monitors = []
        active_ids: set[str] = set()
        area_ids: set[str] = set()
        monitor_ids: set[str] = set()
        created = 0
        updated = 0
        deactivated = 0
        areas_upserted = 0
        monitors_upserted = 0
        with db_connect(self.db_path) as connection:
            init_db(connection)
            for item in cameras:
                if not isinstance(item, dict):
                    continue
                camera_id = str(item.get("id") or "").strip()
                cliente_id = str(item.get("cliente_id") or "").strip()
                unidade_id = str(item.get("unidade_id") or "").strip()
                if not camera_id or not cliente_id or not unidade_id:
                    continue
                active_ids.add(camera_id)
                connection.execute(
                    "INSERT OR IGNORE INTO clientes (id, nome, status) VALUES (?, ?, 'ativo')",
                    (cliente_id, f"Cliente {cliente_id}"),
                )
                connection.execute(
                    "INSERT OR IGNORE INTO unidades (id, cliente_id, nome, timezone) VALUES (?, ?, ?, 'America/Sao_Paulo')",
                    (unidade_id, cliente_id, f"Unidade {unidade_id}"),
                )
                encrypted_password = encrypt_secret(str(item.get("password") or "")) if item.get("password") else None
                existing = connection.execute("SELECT id FROM cameras WHERE id = ?", (camera_id,)).fetchone()
                if existing:
                    connection.execute(
                        """
                        UPDATE cameras
                        SET cliente_id = ?, unidade_id = ?, edge_id = ?, nome = ?,
                            status = COALESCE(NULLIF(status, ''), 'nao_testada'),
                            config_ref = ?, source_type = 'rtsp', secure_ref = ?,
                            rtsp_host = ?, rtsp_port = ?, rtsp_path = ?,
                            rtsp_username = ?, rtsp_password = NULL,
                            rtsp_password_encrypted = COALESCE(?, rtsp_password_encrypted),
                            ativa = ?, site_id = ?, area_context_id = ?,
                            process_id = ?, asset_id = ?
                        WHERE id = ?
                        """,
                        (
                            cliente_id,
                            unidade_id,
                            self.edge_id,
                            str(item.get("nome") or camera_id),
                            item.get("secure_ref"),
                            item.get("secure_ref"),
                            item.get("host"),
                            item.get("porta") or 554,
                            item.get("path"),
                            item.get("username"),
                            encrypted_password,
                            1 if item.get("ativa", True) else 0,
                            unidade_id,
                            item.get("area_context_id"),
                            item.get("process_id"),
                            item.get("asset_id"),
                            camera_id,
                        ),
                    )
                    updated += 1
                else:
                    connection.execute(
                        """
                        INSERT INTO cameras (
                            id, cliente_id, unidade_id, edge_id, nome, status,
                            config_ref, source_type, secure_ref, rtsp_host,
                            rtsp_port, rtsp_path, rtsp_username, rtsp_password,
                            rtsp_password_encrypted, canal, ativa, site_id,
                            area_context_id, process_id, asset_id
                        )
                        VALUES (?, ?, ?, ?, ?, 'nao_testada', ?, 'rtsp', ?, ?, ?, ?, ?, NULL, ?, NULL, ?, ?, ?, ?, ?)
                        """,
                        (
                            camera_id,
                            cliente_id,
                            unidade_id,
                            self.edge_id,
                            str(item.get("nome") or camera_id),
                            item.get("secure_ref"),
                            item.get("secure_ref"),
                            item.get("host"),
                            item.get("porta") or 554,
                            item.get("path"),
                            item.get("username"),
                            encrypted_password,
                            1 if item.get("ativa", True) else 0,
                            unidade_id,
                            item.get("area_context_id"),
                            item.get("process_id"),
                            item.get("asset_id"),
                        ),
                    )
                    created += 1
            for item in areas:
                if not isinstance(item, dict):
                    continue
                area_id = str(item.get("id") or "").strip()
                camera_id = str(item.get("camera_id") or "").strip()
                if not area_id or not camera_id or camera_id not in active_ids:
                    continue
                area_ids.add(area_id)
                connection.execute(
                    """
                    INSERT INTO monitored_areas (
                        id, cliente_id, unidade_id, camera_id, machine_id, nome,
                        tipo, pontos_json, metadata_json, ativa, area_context_id,
                        process_id, asset_id, site_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        cliente_id = excluded.cliente_id,
                        unidade_id = excluded.unidade_id,
                        camera_id = excluded.camera_id,
                        machine_id = excluded.machine_id,
                        nome = excluded.nome,
                        tipo = excluded.tipo,
                        pontos_json = excluded.pontos_json,
                        ativa = excluded.ativa,
                        area_context_id = excluded.area_context_id,
                        process_id = excluded.process_id,
                        asset_id = excluded.asset_id,
                        site_id = excluded.site_id,
                        atualizado_em = CURRENT_TIMESTAMP
                    """,
                    (
                        area_id,
                        str(payload.get("cliente_id") or ""),
                        str(payload.get("unidade_id") or ""),
                        camera_id,
                        item.get("machine_id"),
                        str(item.get("nome") or "Zona operacional"),
                        str(item.get("tipo") or "operator_zone"),
                        json.dumps(item.get("pontos") or [], ensure_ascii=False),
                        1 if item.get("ativa", True) else 0,
                        item.get("area_context_id"),
                        item.get("process_id"),
                        item.get("asset_id"),
                        str(payload.get("unidade_id") or ""),
                    ),
                )
                areas_upserted += 1
            for item in monitors:
                if not isinstance(item, dict):
                    continue
                monitor_id = str(item.get("id") or "").strip()
                camera_id = str(item.get("camera_id") or "").strip()
                if not monitor_id or not camera_id or camera_id not in active_ids:
                    continue
                monitor_ids.add(monitor_id)
                connection.execute(
                    """
                    INSERT INTO machine_monitors (
                        id, client_id, unit_id, camera_id, nome, machine_polygon_json,
                        operator_polygon_json, operation_polygon_json, presence_scope,
                        ativo, motion_sensitivity, stop_seconds, recovery_seconds,
                        replay_pre_seconds, replay_post_seconds,
                        operator_absence_seconds, stopped_with_operator_seconds,
                        area_context_id, process_id, asset_id, site_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 3.0, 60.0, 30.0, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        client_id = excluded.client_id,
                        unit_id = excluded.unit_id,
                        camera_id = excluded.camera_id,
                        nome = excluded.nome,
                        machine_polygon_json = excluded.machine_polygon_json,
                        operator_polygon_json = excluded.operator_polygon_json,
                        operation_polygon_json = excluded.operation_polygon_json,
                        presence_scope = excluded.presence_scope,
                        ativo = excluded.ativo,
                        motion_sensitivity = excluded.motion_sensitivity,
                        stop_seconds = excluded.stop_seconds,
                        operator_absence_seconds = excluded.operator_absence_seconds,
                        stopped_with_operator_seconds = excluded.stopped_with_operator_seconds,
                        area_context_id = excluded.area_context_id,
                        process_id = excluded.process_id,
                        asset_id = excluded.asset_id,
                        site_id = excluded.site_id,
                        atualizado_em = CURRENT_TIMESTAMP
                    """,
                    (
                        monitor_id,
                        str(item.get("client_id") or item.get("cliente_id") or payload.get("cliente_id") or ""),
                        str(item.get("unit_id") or item.get("unidade_id") or payload.get("unidade_id") or ""),
                        camera_id,
                        str(item.get("nome") or "Monitor operacional"),
                        json.dumps(item.get("machine_polygon") or [], ensure_ascii=False),
                        json.dumps(item.get("operator_polygon") or [], ensure_ascii=False),
                        json.dumps(item.get("operation_polygon"), ensure_ascii=False) if item.get("operation_polygon") is not None else None,
                        str(item.get("presence_scope") or "OPERATOR_ZONE"),
                        1 if item.get("ativo", True) else 0,
                        float(item.get("motion_sensitivity") or 25.0),
                        float(item.get("stop_seconds") or 30.0),
                        float(item.get("operator_absence_seconds") or 300.0),
                        float(item.get("stopped_with_operator_seconds") or 120.0),
                        item.get("area_context_id"),
                        item.get("process_id"),
                        item.get("asset_id"),
                        str(item.get("unit_id") or item.get("unidade_id") or payload.get("unidade_id") or ""),
                    ),
                )
                monitors_upserted += 1
            if active_ids:
                placeholders = ",".join("?" for _ in active_ids)
                cursor = connection.execute(
                    f"UPDATE cameras SET ativa = 0 WHERE edge_id = ? AND id NOT IN ({placeholders}) AND source_type = 'rtsp'",
                    (self.edge_id, *sorted(active_ids)),
                )
            else:
                cursor = connection.execute(
                    "UPDATE cameras SET ativa = 0 WHERE edge_id = ? AND source_type = 'rtsp'",
                    (self.edge_id,),
                )
            deactivated = int(cursor.rowcount or 0)
            if area_ids:
                placeholders = ",".join("?" for _ in area_ids)
                connection.execute(
                    f"UPDATE monitored_areas SET ativa = 0 WHERE camera_id IN ({','.join('?' for _ in active_ids)}) AND id NOT IN ({placeholders})",
                    (*sorted(active_ids), *sorted(area_ids)),
                )
            elif active_ids:
                connection.execute(
                    f"UPDATE monitored_areas SET ativa = 0 WHERE camera_id IN ({','.join('?' for _ in active_ids)})",
                    tuple(sorted(active_ids)),
                )
            if monitor_ids:
                placeholders = ",".join("?" for _ in monitor_ids)
                connection.execute(
                    f"UPDATE machine_monitors SET ativo = 0 WHERE camera_id IN ({','.join('?' for _ in active_ids)}) AND id NOT IN ({placeholders})",
                    (*sorted(active_ids), *sorted(monitor_ids)),
                )
            elif active_ids:
                connection.execute(
                    f"UPDATE machine_monitors SET ativo = 0 WHERE camera_id IN ({','.join('?' for _ in active_ids)})",
                    tuple(sorted(active_ids)),
                )
            connection.commit()
        return {
            "created": created,
            "updated": updated,
            "deactivated": deactivated,
            "areas_upserted": areas_upserted,
            "monitors_upserted": monitors_upserted,
        }

    def _run_outbox_sync(self) -> None:
        cloud_url = os.getenv("CAMPEX_CLOUD_URL")
        edge_secret = os.getenv("CAMPEX_EDGE_SECRET")
        if not cloud_url or not edge_secret:
            logger.info("Sincronizacao cloud desativada: CAMPEX_CLOUD_URL/CAMPEX_EDGE_SECRET ausentes.")
            return
        while not self.stop_event.is_set():
            try:
                self._send_cloud_heartbeat(cloud_url, edge_secret)
            except Exception as exc:
                logger.warning("Falha temporaria no heartbeat com Cloud: %s", exc)

            try:
                self.sync_cloud_edge_config(cloud_url, edge_secret)
            except Exception as exc:
                logger.warning("Falha temporaria ao sincronizar configuracao do Edge: %s", exc)

            try:
                self._send_cloud_camera_statuses(cloud_url, edge_secret)
            except Exception as exc:
                logger.warning("Falha temporaria ao sincronizar status das cameras: %s", exc)

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

    def _run_alert_decisioning(self) -> None:
        while not self.stop_event.is_set():
            try:
                now = datetime.now(timezone.utc)
                with db_connect(self.db_path) as connection:
                    init_db(connection)
                    tenants = [
                        row["cliente_id"]
                        for row in connection.execute(
                            """
                            SELECT DISTINCT cliente_id
                            FROM cameras
                            WHERE cliente_id IS NOT NULL AND ativa = 1
                            """
                        ).fetchall()
                    ]
                    for tenant_id in tenants:
                        payload = evaluate_alert_decisions(
                            connection,
                            ReadModelFilters(
                                cliente_id=tenant_id,
                                start=now - timedelta(hours=2),
                                end=now,
                            ),
                            now=now,
                        )
                        alerts_module.enqueue_alert_decisions(payload.get("decisions") or [])
            except Exception as exc:
                logger.warning("Falha temporaria no decisioning de alertas: %s", exc)
            self.stop_event.wait(self.alert_decision_seconds)

    def _bind_runtime_database(self) -> None:
        def runtime_connect(_path: str | Path | None = None):
            return db_connect(self.db_path)

        api_module.connect = runtime_connect
        alerts_module.connect = runtime_connect
        pilot_module.connect = runtime_connect

    def start(self) -> None:
        self._bind_runtime_database()
        with db_connect(self.db_path) as connection:
            init_db(connection)
            interrupted = fechar_eventos_machine_interrompidos(connection)
            if interrupted:
                logger.warning("Eventos de máquina órfãos fechados no startup: %s", interrupted)
        alerts_module.resume_pending_deliveries()
        jobs = [
            ("campex-api", self._run_api),
            ("campex-camera-runtime", self._run_camera_runtime),
            ("campex-outbox-sync", self._run_outbox_sync),
            ("campex-latest-frame-upload", self._run_latest_frame_upload),
            ("campex-alert-decisioning", self._run_alert_decisioning),
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
    alert_decision_seconds: float = 60.0,
) -> None:
    runtime = ProductionEdgeRuntime(
        edge_id=edge_id,
        db_path=db_path,
        host=host,
        port=port,
        heartbeat_seconds=heartbeat_seconds,
        sync_seconds=sync_seconds,
        alert_decision_seconds=alert_decision_seconds,
    )

    def stop(_signum: int, _frame: object) -> None:
        runtime.shutdown()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    runtime.start()
    runtime.wait()
