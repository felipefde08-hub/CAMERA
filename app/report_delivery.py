from __future__ import annotations

import os
import smtplib
import sqlite3
import ssl
import threading
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any
from zoneinfo import ZoneInfo

from app.alerts import email_configuration_status
from app.database import connect, init_db
from app.operational_read_model import ReadModelFilters, daily_report


DEFAULT_TIMEZONE = "America/Sao_Paulo"
_scheduler_thread: threading.Thread | None = None
_scheduler_stop = threading.Event()


def ensure_report_delivery_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS report_schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL UNIQUE,
            enabled INTEGER NOT NULL DEFAULT 1,
            send_time TEXT NOT NULL DEFAULT '08:00',
            timezone TEXT NOT NULL DEFAULT 'America/Sao_Paulo',
            channel TEXT NOT NULL DEFAULT 'email',
            email TEXT,
            whatsapp_number TEXT,
            last_sent_local_date TEXT,
            last_sent_at TEXT,
            last_status TEXT,
            last_error TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.commit()


def get_report_schedule(connection: sqlite3.Connection, tenant_id: str) -> dict[str, Any] | None:
    ensure_report_delivery_schema(connection)
    row = connection.execute(
        "SELECT * FROM report_schedules WHERE tenant_id = ?",
        (tenant_id,),
    ).fetchone()
    return dict(row) if row else None


def upsert_report_schedule(
    connection: sqlite3.Connection,
    *,
    tenant_id: str,
    enabled: bool,
    send_time: str,
    timezone_name: str = DEFAULT_TIMEZONE,
    channel: str = "email",
    email: str | None = None,
    whatsapp_number: str | None = None,
) -> dict[str, Any]:
    ensure_report_delivery_schema(connection)

    try:
        hour_text, minute_text = send_time.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValueError
    except Exception as exc:
        raise ValueError("Horário inválido. Use HH:MM.") from exc

    try:
        ZoneInfo(timezone_name)
    except Exception as exc:
        raise ValueError("Fuso horário inválido.") from exc

    channel = str(channel or "email").strip().lower()
    if channel not in {"email", "whatsapp", "both"}:
        raise ValueError("Canal inválido.")

    if channel in {"email", "both"} and not email:
        raise ValueError("Email é obrigatório para este canal.")

    connection.execute(
        """
        INSERT INTO report_schedules (
            tenant_id, enabled, send_time, timezone, channel,
            email, whatsapp_number, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(tenant_id) DO UPDATE SET
            enabled = excluded.enabled,
            send_time = excluded.send_time,
            timezone = excluded.timezone,
            channel = excluded.channel,
            email = excluded.email,
            whatsapp_number = excluded.whatsapp_number,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            tenant_id,
            int(enabled),
            send_time,
            timezone_name,
            channel,
            email,
            whatsapp_number,
        ),
    )
    connection.commit()
    return get_report_schedule(connection, tenant_id) or {}


def _tenant_name(connection: sqlite3.Connection, tenant_id: str) -> str:
    row = connection.execute(
        "SELECT nome FROM clientes WHERE id = ?",
        (tenant_id,),
    ).fetchone()
    return str(row["nome"]) if row and row["nome"] else "Operação"


def build_report_for_tenant(
    connection: sqlite3.Connection,
    *,
    tenant_id: str,
    end_at: datetime,
) -> dict[str, Any]:
    start_at = end_at - timedelta(hours=24)

    filters = ReadModelFilters(
        cliente_id=tenant_id,
        start=start_at.astimezone(timezone.utc),
        end=end_at.astimezone(timezone.utc),
    )

    report = daily_report(
        connection,
        filters,
        now=end_at.astimezone(timezone.utc),
    )

    return {
        "tenant_id": tenant_id,
        "tenant_name": _tenant_name(connection, tenant_id),
        "generated_at": end_at.isoformat(),
        "period": {
            "start": start_at.isoformat(),
            "end": end_at.isoformat(),
        },
        "report": report,
    }


def _seconds_label(value: Any) -> str:
    total = max(0, int(float(value or 0)))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}min"
    if minutes:
        return f"{minutes}min {seconds:02d}s"
    return f"{seconds}s"


def build_report_email(payload: dict[str, Any], recipient: str) -> EmailMessage:
    report = payload["report"]
    summary = report.get("summary") or {}
    machines = summary.get("machines") or {}
    events = report.get("main_events") or []

    tenant_name = payload.get("tenant_name") or "Operação"
    period = payload.get("period") or {}

    message = EmailMessage()
    message["From"] = os.getenv("CAMPEX_EMAIL_FROM", "campex@localhost")
    message["To"] = recipient
    message["Subject"] = f"[Campex] Relatório operacional — {tenant_name}"

    lines = [
        f"Relatório Operacional Campex — {tenant_name}",
        "",
        f"Período: {period.get('start')} até {period.get('end')}",
        "",
        "Resumo",
        f"- Acontecimentos relevantes: {len(events)}",
        f"- Tempo ativo: {_seconds_label(machines.get('active_seconds'))}",
        f"- Tempo parado: {_seconds_label(machines.get('stopped_seconds'))}",
        f"- Tempo sem leitura confiável: {_seconds_label(machines.get('unknown_seconds'))}",
        "",
        "Principais acontecimentos",
    ]

    if not events:
        lines.append("- Nenhum acontecimento relevante registrado no período.")
    else:
        for event in events[:7]:
            lines.append(
                f"- {event.get('started_at') or 'Horário não informado'} — "
                f"{event.get('tipo') or 'Ocorrência operacional'} — "
                f"{_seconds_label(event.get('duration_seconds'))}"
            )

    app_url = os.getenv("CAMPEX_APP_URL", "http://127.0.0.1:8000")
    lines.extend(["", f"Ver relatório completo: {app_url}/reports"])

    message.set_content("\n".join(lines))
    return message


def send_report_email(payload: dict[str, Any], recipient: str) -> None:
    config = email_configuration_status()

    if config["status"] != "CONFIGURED":
        if config["status"] == "NOT_CONFIGURED":
            raise RuntimeError(
                f"EMAIL_NOT_CONFIGURED: faltam {', '.join(config.get('missing') or [])}."
            )
        raise RuntimeError(str(config.get("error") or "CAMPEX_EMAIL_MODE inválido."))

    if config["mode"] == "console":
        print(
            f"Campex relatório console: "
            f"{payload.get('tenant_name')} -> {recipient}"
        )
        return

    message = build_report_email(payload, recipient)

    host = os.getenv("CAMPEX_SMTP_HOST")
    port = int(os.getenv("CAMPEX_SMTP_PORT", "587"))
    username = os.getenv("CAMPEX_SMTP_USERNAME")
    password = os.getenv("CAMPEX_SMTP_PASSWORD")
    use_tls = os.getenv("CAMPEX_SMTP_USE_TLS", "true").lower() == "true"

    if not host or not username or not password:
        raise RuntimeError("SMTP não configurado.")

    with smtplib.SMTP(host, port, timeout=15) as smtp:
        if use_tls:
            smtp.starttls(context=ssl.create_default_context())
        smtp.login(username, password)
        smtp.send_message(message)


def _schedule_is_due(schedule: dict[str, Any], now_utc: datetime) -> tuple[bool, datetime]:
    tz = ZoneInfo(str(schedule.get("timezone") or DEFAULT_TIMEZONE))
    local_now = now_utc.astimezone(tz)

    hour, minute = [int(part) for part in str(schedule["send_time"]).split(":", 1)]
    scheduled_local = local_now.replace(
        hour=hour,
        minute=minute,
        second=0,
        microsecond=0,
    )

    already_sent_today = (
        str(schedule.get("last_sent_local_date") or "")
        == local_now.date().isoformat()
    )

    return local_now >= scheduled_local and not already_sent_today, local_now


def send_due_reports_once(now_utc: datetime | None = None) -> list[dict[str, Any]]:
    now_utc = now_utc or datetime.now(timezone.utc)
    results: list[dict[str, Any]] = []

    with connect() as connection:
        init_db(connection)
        ensure_report_delivery_schema(connection)

        schedules = [
            dict(row)
            for row in connection.execute(
                """
                SELECT *
                FROM report_schedules
                WHERE enabled = 1
                ORDER BY tenant_id
                """
            ).fetchall()
        ]

        for schedule in schedules:
            due, local_now = _schedule_is_due(schedule, now_utc)
            if not due:
                continue

            tenant_id = str(schedule["tenant_id"])

            try:
                payload = build_report_for_tenant(
                    connection,
                    tenant_id=tenant_id,
                    end_at=local_now,
                )

                channel = str(schedule.get("channel") or "email")

                if channel in {"email", "both"}:
                    send_report_email(payload, str(schedule["email"]))

                if channel in {"whatsapp", "both"}:
                    raise RuntimeError(
                        "WHATSAPP_PROVIDER_NOT_CONFIGURED"
                    )

                connection.execute(
                    """
                    UPDATE report_schedules
                    SET
                        last_sent_local_date = ?,
                        last_sent_at = ?,
                        last_status = 'sent',
                        last_error = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE tenant_id = ?
                    """,
                    (
                        local_now.date().isoformat(),
                        now_utc.isoformat(),
                        tenant_id,
                    ),
                )
                connection.commit()

                results.append(
                    {
                        "tenant_id": tenant_id,
                        "status": "sent",
                    }
                )

            except Exception as exc:
                connection.execute(
                    """
                    UPDATE report_schedules
                    SET
                        last_status = 'failed',
                        last_error = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE tenant_id = ?
                    """,
                    (str(exc), tenant_id),
                )
                connection.commit()

                results.append(
                    {
                        "tenant_id": tenant_id,
                        "status": "failed",
                        "error": str(exc),
                    }
                )

    return results


def _scheduler_loop() -> None:
    while not _scheduler_stop.is_set():
        try:
            send_due_reports_once()
        except Exception:
            pass
        _scheduler_stop.wait(20.0)


def start_report_scheduler() -> None:
    global _scheduler_thread

    if _scheduler_thread and _scheduler_thread.is_alive():
        return

    _scheduler_stop.clear()
    _scheduler_thread = threading.Thread(
        target=_scheduler_loop,
        name="campex-report-scheduler",
        daemon=True,
    )
    _scheduler_thread.start()


def stop_report_scheduler() -> None:
    _scheduler_stop.set()
    thread = _scheduler_thread
    if thread:
        thread.join(timeout=3.0)
