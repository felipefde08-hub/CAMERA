from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import API_PORT, DATABASE_PATH, EVIDENCE_DIR, ROOT
from app.database import connect, init_db
from app.edge_config import EdgeConfigError, validate_edge_config
from app.edge_service import PLIST_PATH, service_status
from app.models import ultimo_edge_heartbeat
from app.security import mask_sensitive_error


READY = "READY"
NOT_READY = "NOT READY"
PASS = "PASS"
FAIL = "FAIL"
WARNING = "WARNING"
NOT_CONFIGURED = "NOT CONFIGURED"


@dataclass(frozen=True)
class DoctorCheck:
    label: str
    status: str
    detail: str = ""
    required: bool = True


@dataclass(frozen=True)
class DoctorReport:
    checks: list[DoctorCheck]
    result: str

    @property
    def exit_code(self) -> int:
        return 0 if self.result == READY else 1


def _safe(value: object) -> str:
    text = str(value or "")
    for name in ("CAMPEX_CREDENTIAL_KEY", "CAMPEX_EDGE_SECRET", "CAMPEX_SMTP_PASSWORD", "OPENAI_API_KEY"):
        secret = os.getenv(name)
        if secret:
            text = text.replace(secret, "***")
    return mask_sensitive_error(text)


def _parse_dt(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _recent(value: object, max_age_seconds: float) -> bool:
    parsed = _parse_dt(value)
    return bool(parsed and (datetime.now(timezone.utc) - parsed).total_seconds() <= max_age_seconds)


def _http_json(url: str, timeout: float) -> tuple[int, dict[str, Any] | None, str | None]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            if "application/json" not in response.headers.get("content-type", ""):
                return response.status, None, body[:160]
            import json

            return response.status, json.loads(body), None
    except urllib.error.HTTPError as exc:
        return exc.code, None, _safe(exc.reason)
    except Exception as exc:
        return 0, None, _safe(exc)


def _service_state() -> tuple[bool, bool, str]:
    result = service_status()
    message = _safe(result.message)
    lowered = message.lower()
    installed = PLIST_PATH.exists() or "state =" in lowered or "pid =" in lowered or "serviço carregado" in lowered
    if not result.ok:
        return installed, False, message
    if "state = running" in lowered or "pid =" in lowered or "serviço carregado" in lowered:
        return True, True, "serviço carregado"
    if "could not find service" in lowered or "not loaded" in lowered or "não carregado" in lowered:
        return installed, False, "serviço não carregado"
    return installed, False, message


def _stream_items(status_payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(status_payload, dict):
        return []
    cameras = status_payload.get("cameras")
    if isinstance(cameras, list):
        return [item for item in cameras if isinstance(item, dict)]
    streams = ((status_payload.get("workers") or {}).get("streams") or [])
    return [item for item in streams if isinstance(item, dict)]


def run_doctor(
    *,
    db_path: Path | None = None,
    api_url: str | None = None,
    min_free_gb: float = 5.0,
    frame_max_age_seconds: float = 30.0,
    timeout: float = 3.0,
    cloud_required: bool = False,
) -> DoctorReport:
    checks: list[DoctorCheck] = []
    database_path = Path(db_path or DATABASE_PATH)
    base_url = (api_url or f"http://127.0.0.1:{API_PORT}").rstrip("/")

    def add(label: str, status: str, detail: str = "", *, required: bool = True) -> None:
        checks.append(DoctorCheck(label=label, status=status, detail=_safe(detail), required=required))

    service_installed, service_running, service_detail = _service_state()
    add("Service installed", PASS if service_installed else FAIL, "" if service_installed else service_detail)
    add("Service running", PASS if service_running else FAIL, "" if service_running else service_detail)

    health_code, _health_payload, health_error = _http_json(f"{base_url}/health", timeout)
    add("API responding", PASS if health_code == 200 else FAIL, "" if health_code == 200 else (health_error or "API local indisponível"))

    ready_code, ready_payload, ready_error = _http_json(f"{base_url}/ready", timeout)
    status_code, status_payload, status_error = _http_json(f"{base_url}/edge/status", timeout)

    try:
        validate_edge_config(db_path=database_path)
        add("Edge configuration", PASS)
    except EdgeConfigError as exc:
        add("Edge configuration", FAIL, str(exc))

    connection: sqlite3.Connection | None = None
    try:
        connection = connect(database_path)
        init_db(connection)
        connection.execute("SELECT 1").fetchone()
        add("Database", PASS, str(database_path))

        try:
            database_path.parent.mkdir(parents=True, exist_ok=True)
            test_file = database_path.parent / ".campex_doctor_write"
            test_file.write_text("ok", encoding="utf-8")
            test_file.unlink(missing_ok=True)
            add("Database writable", PASS)
        except OSError as exc:
            add("Database writable", FAIL, str(exc))

        cameras_registered = connection.execute("SELECT COUNT(*) AS total FROM cameras WHERE ativa = 1").fetchone()["total"]
        add("Camera registered", PASS if cameras_registered else FAIL, f"{cameras_registered} ativa(s)")

        monitors = connection.execute("SELECT COUNT(*) AS total FROM machine_monitors WHERE ativo = 1").fetchone()["total"]
        monitors_ready = connection.execute(
            "SELECT COUNT(*) AS total FROM machine_monitors WHERE ativo = 1 AND calibration_result = 'READY'"
        ).fetchone()["total"]
        add("Machine monitor configured", PASS if monitors else FAIL, f"{monitors} ativo(s)")
        add("Machine monitor loaded/calibrated", PASS if monitors_ready else FAIL, "calibração ausente" if monitors and not monitors_ready else f"{monitors_ready} READY")

        outbox_pending = connection.execute("SELECT COUNT(*) AS total FROM sync_outbox WHERE status IN ('pending', 'failed')").fetchone()["total"]
        add("Outbox", PASS if outbox_pending == 0 else WARNING, f"{outbox_pending} pending", required=False)

        edge_id = os.getenv("CAMPEX_EDGE_ID")
        heartbeat = ultimo_edge_heartbeat(connection, edge_id)
        heartbeat_recent = bool(heartbeat and _recent(heartbeat.get("heartbeat_at"), max(frame_max_age_seconds * 3, 90)))
        add("Last edge heartbeat", PASS if heartbeat_recent else FAIL, "" if heartbeat_recent else "sem heartbeat recente")
    except sqlite3.Error as exc:
        add("Database", FAIL, str(exc))
    finally:
        if connection is not None:
            connection.close()

    disk = shutil.disk_usage(str(ROOT))
    free_gb = disk.free / (1024**3)
    add("Disk", PASS if free_gb >= min_free_gb else FAIL, f"{free_gb:.1f} GB livres")

    try:
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        test_file = EVIDENCE_DIR / ".campex_doctor_write"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink(missing_ok=True)
        add("Evidence storage", PASS)
    except OSError as exc:
        add("Evidence storage", FAIL, str(exc))

    streams = _stream_items(status_payload)
    frame_recent = any(_recent(item.get("last_frame_at") or item.get("ultimo_frame"), frame_max_age_seconds) for item in streams)
    stream_online = any(str(item.get("status") or item.get("camera_online") or "").lower() in {"online", "true", "ready"} for item in streams)
    add("RTSP/network reachability", PASS if stream_online or frame_recent else FAIL, status_error or "sem stream online")
    add("Frame freshness", PASS if frame_recent else FAIL, "sem frame recente")

    inference_ready = False
    for item in streams:
        fps = float(item.get("analysis_fps") or item.get("inference_fps") or 0)
        frames = int(item.get("analysis_frames") or item.get("frames_analyzed") or item.get("frames_processados") or 0)
        last = item.get("last_analysis_at") or item.get("last_inference_at")
        if fps > 0 or frames > 0 or _recent(last, frame_max_age_seconds):
            inference_ready = True
            break
    if isinstance(ready_payload, dict) and ready_payload.get("inference") == "ready":
        inference_ready = True
    add("Inference status", PASS if inference_ready else FAIL, ready_error or "inferência sem processamento recente")

    cloud_url = os.getenv("CAMPEX_CLOUD_URL")
    edge_secret = os.getenv("CAMPEX_EDGE_SECRET")
    if cloud_url and edge_secret:
        cloud_code, _cloud_payload, cloud_error = _http_json(f"{cloud_url.rstrip('/')}/health", timeout)
        add("Cloud configuration", PASS)
        add(
            "Cloud reachability",
            PASS if cloud_code == 200 else (FAIL if cloud_required else WARNING),
            cloud_error or f"HTTP {cloud_code}",
            required=cloud_required,
        )
    else:
        add(
            "Cloud configuration",
            NOT_CONFIGURED if not cloud_required else FAIL,
            "CAMPEX_CLOUD_URL/CAMPEX_EDGE_SECRET ausentes",
            required=cloud_required,
        )

    if ready_code == 200 and isinstance(ready_payload, dict):
        add("Readiness final", PASS if ready_payload.get("status") == "ready" else FAIL, str(ready_payload.get("status") or "not_ready"))
    else:
        add("Readiness final", FAIL, ready_error or "não foi possível consultar /ready")

    result = READY if all(item.status == PASS for item in checks if item.required) else NOT_READY
    return DoctorReport(checks=checks, result=result)


def format_doctor(report: DoctorReport) -> str:
    width = max([len(check.label) for check in report.checks] + [10])
    lines = ["CAMPEX EDGE DOCTOR", ""]
    for check in report.checks:
        dots = "." * max(2, width + 3 - len(check.label))
        suffix = f" ({check.detail})" if check.detail else ""
        lines.append(f"{check.label} {dots} {check.status}{suffix}")
    lines.extend(["", f"RESULT: {report.result}"])
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Diagnóstico do Campex Edge RC1.")
    parser.add_argument("--db", default=os.getenv("DATABASE_PATH") or str(DATABASE_PATH))
    parser.add_argument("--api-url", default=os.getenv("CAMPEX_API_URL") or f"http://127.0.0.1:{API_PORT}")
    parser.add_argument("--timeout", type=float, default=3.0)
    parser.add_argument("--min-free-gb", type=float, default=5.0)
    parser.add_argument("--frame-max-age-seconds", type=float, default=30.0)
    parser.add_argument("--require-cloud", action="store_true", help="Torna configuração e alcance Cloud obrigatórios.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_doctor(
        db_path=Path(args.db),
        api_url=args.api_url,
        timeout=args.timeout,
        min_free_gb=args.min_free_gb,
        frame_max_age_seconds=args.frame_max_age_seconds,
        cloud_required=args.require_cloud,
    )
    print(format_doctor(report))
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
