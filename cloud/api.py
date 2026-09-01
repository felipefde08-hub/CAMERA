from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import ROOT
from cloud.database import connect, init_cloud_db, is_postgres_url
from cloud.security import hash_edge_secret, verify_edge_secret
from shared.schemas import now_iso

LOGGER = logging.getLogger(__name__)

api = FastAPI(title="Campex Cloud")
FRONTEND_DIR = ROOT / "frontend"

if FRONTEND_DIR.exists():
    api.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


class EdgeDeviceIn(BaseModel):
    id: str
    tenant_id: str
    cliente_id: str
    unidade_id: str
    nome: str = "Edge Device"
    secret: str = Field(min_length=12)


class EdgeEventIn(BaseModel):
    event_uuid: str
    tenant_id: str
    cliente_id: str
    unidade_id: str
    camera_id: str
    tipo: str
    inicio: Optional[str] = None
    fim: Optional[str] = None
    duracao: Optional[float] = None
    operador_presente: Optional[bool] = None
    confianca: Optional[float] = None
    severidade: Optional[str] = None
    status: Optional[str] = None
    midia_path: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class ReportDeliveryIn(BaseModel):
    delivery_id: str = Field(min_length=8)
    cliente_id: str
    recipient: str
    subject: str
    text_body: str
    html_body: str



@api.on_event("startup")
def startup() -> None:
    init_cloud_db()


@api.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "database": "postgresql" if is_postgres_url() else "sqlite-dev"}


@api.get("/")
def root() -> RedirectResponse:
    return RedirectResponse(url="/dashboard", status_code=307)


INTERNAL_ROUTES = {
    "/dashboard": "dashboard.html",
    "/overview": "dashboard.html",
    "/events": "workspace.html",
    "/evidence": "workspace.html",
}


for internal_route, html_file in INTERNAL_ROUTES.items():
    async def serve_internal(file_name: str = html_file) -> FileResponse:
        return FileResponse(FRONTEND_DIR / file_name)

    api.add_api_route(internal_route, serve_internal, methods=["GET"], include_in_schema=False)


@api.get("/auth/status")
def cloud_auth_status() -> dict[str, Any]:
    return {
        "authenticated": True,
        "bootstrap": True,
        "user": {"nome": "Campex Cloud", "role": "admin_campex"},
    }


@api.post("/admin/edge-devices")
def create_edge_device(payload: EdgeDeviceIn) -> dict[str, Any]:
    with connect() as db:
        init_cloud_db(db)
        existing = db.fetchone("SELECT id FROM edge_devices WHERE id = ?", (payload.id,))
        if existing:
            raise HTTPException(status_code=409, detail="Edge ja cadastrado.")
        db.execute(
            """
            INSERT INTO edge_devices (
                id, tenant_id, cliente_id, unidade_id, nome, secret_hash, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)
            """,
            (
                payload.id,
                payload.tenant_id,
                payload.cliente_id,
                payload.unidade_id,
                payload.nome,
                hash_edge_secret(payload.secret),
                now_iso(),
                now_iso(),
            ),
        )
        db.commit()
    return {"id": payload.id, "tenant_id": payload.tenant_id, "status": "active"}


def _send_cloud_report_email(payload: ReportDeliveryIn) -> str:
    import os
    import urllib.error
    import urllib.request

    provider = os.getenv("CAMPEX_CLOUD_EMAIL_PROVIDER", "").strip().lower()

    if provider != "resend":
        raise RuntimeError(
            "CLOUD_EMAIL_NOT_CONFIGURED: CAMPEX_CLOUD_EMAIL_PROVIDER deve ser 'resend'."
        )

    api_key = os.getenv("CAMPEX_RESEND_API_KEY", "").strip()
    from_address = os.getenv("CAMPEX_EMAIL_FROM", "").strip()

    if not api_key or not from_address:
        missing = []
        if not api_key:
            missing.append("CAMPEX_RESEND_API_KEY")
        if not from_address:
            missing.append("CAMPEX_EMAIL_FROM")
        raise RuntimeError(
            f"CLOUD_EMAIL_NOT_CONFIGURED: faltam {', '.join(missing)}."
        )

    body = json.dumps(
        {
            "from": from_address,
            "to": [payload.recipient],
            "subject": payload.subject,
            "text": payload.text_body,
            "html": payload.html_body,
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        "https://api.resend.com/emails",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Idempotency-Key": payload.delivery_id,
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(
            f"EMAIL_PROVIDER_ERROR: HTTP {exc.code}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"EMAIL_PROVIDER_UNAVAILABLE: {exc.reason}"
        ) from exc

    provider_message_id = str(response_payload.get("id") or "").strip()
    if not provider_message_id:
        raise RuntimeError("EMAIL_PROVIDER_INVALID_RESPONSE: id ausente.")

    return provider_message_id


@api.post("/edge/report-delivery")
def receive_report_delivery(
    payload: ReportDeliveryIn,
    x_edge_id: Optional[str] = Header(default=None, alias="X-Edge-Id"),
    x_edge_secret: Optional[str] = Header(default=None, alias="X-Edge-Secret"),
) -> dict[str, Any]:
    if not x_edge_id or not x_edge_secret:
        raise HTTPException(status_code=401, detail="Credenciais do Edge ausentes.")

    payload_json = json.dumps(
        payload.model_dump(),
        ensure_ascii=False,
        sort_keys=True,
    )

    with connect() as db:
        init_cloud_db(db)

        device = db.fetchone(
            "SELECT * FROM edge_devices WHERE id = ?",
            (x_edge_id,),
        )

        if not device or not verify_edge_secret(
            x_edge_secret,
            device["secret_hash"],
        ):
            LOGGER.warning(
                "Tentativa de report delivery com credencial invalida para edge_id=%s",
                x_edge_id,
            )
            raise HTTPException(status_code=401, detail="Edge nao autorizado.")

        if device["status"] != "active" or device.get("revoked_at"):
            raise HTTPException(
                status_code=403,
                detail="Edge revogado ou inativo.",
            )

        if payload.cliente_id != device["cliente_id"]:
            raise HTTPException(
                status_code=403,
                detail="Relatorio pertence a outro cliente.",
            )

        existing = db.fetchone(
            """
            SELECT *
            FROM report_deliveries
            WHERE id = ?
            """,
            (payload.delivery_id,),
        )

        if existing:
            if (
                existing["cliente_id"] != payload.cliente_id
                or existing["edge_id"] != x_edge_id
                or existing["payload_json"] != payload_json
            ):
                raise HTTPException(
                    status_code=409,
                    detail="delivery_id ja utilizado com outro payload.",
                )

            if existing["status"] == "sent":
                return {
                    "delivery_id": payload.delivery_id,
                    "status": "sent",
                    "idempotent": True,
                    "provider_message_id": existing.get("provider_message_id"),
                }
        else:
            db.execute(
                """
                INSERT INTO report_deliveries (
                    id,
                    tenant_id,
                    cliente_id,
                    unidade_id,
                    edge_id,
                    recipient,
                    subject,
                    status,
                    attempts,
                    payload_json,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?)
                """,
                (
                    payload.delivery_id,
                    device["tenant_id"],
                    payload.cliente_id,
                    device["unidade_id"],
                    x_edge_id,
                    payload.recipient,
                    payload.subject,
                    payload_json,
                    now_iso(),
                    now_iso(),
                ),
            )
            db.commit()

        db.execute(
            """
            UPDATE report_deliveries
            SET
                status = 'pending',
                attempts = attempts + 1,
                last_error = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (now_iso(), payload.delivery_id),
        )
        db.commit()

        try:
            provider_message_id = _send_cloud_report_email(payload)
        except Exception as exc:
            db.execute(
                """
                UPDATE report_deliveries
                SET
                    status = 'failed',
                    last_error = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    str(exc)[:2000],
                    now_iso(),
                    payload.delivery_id,
                ),
            )
            db.commit()
            raise HTTPException(
                status_code=502,
                detail=str(exc),
            ) from exc

        sent_at = now_iso()

        db.execute(
            """
            UPDATE report_deliveries
            SET
                status = 'sent',
                provider_message_id = ?,
                last_error = NULL,
                sent_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                provider_message_id,
                sent_at,
                sent_at,
                payload.delivery_id,
            ),
        )
        db.commit()

        return {
            "delivery_id": payload.delivery_id,
            "status": "sent",
            "idempotent": False,
            "provider_message_id": provider_message_id,
        }



@api.post("/edge/events")
def receive_edge_event(
    payload: EdgeEventIn,
    request: Request,
    x_edge_id: Optional[str] = Header(default=None, alias="X-Edge-Id"),
    x_edge_secret: Optional[str] = Header(default=None, alias="X-Edge-Secret"),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    if not x_edge_id or not x_edge_secret:
        raise HTTPException(status_code=401, detail="Credenciais do Edge ausentes.")
    if idempotency_key and idempotency_key != payload.event_uuid:
        raise HTTPException(status_code=400, detail="Idempotency-Key diferente do event_uuid.")
    with connect() as db:
        init_cloud_db(db)
        device = db.fetchone("SELECT * FROM edge_devices WHERE id = ?", (x_edge_id,))
        if not device or not verify_edge_secret(x_edge_secret, device["secret_hash"]):
            LOGGER.warning("Tentativa de evento com credencial invalida para edge_id=%s", x_edge_id)
            raise HTTPException(status_code=401, detail="Edge nao autorizado.")
        if device["status"] != "active" or device.get("revoked_at"):
            raise HTTPException(status_code=403, detail="Edge revogado ou inativo.")
        if payload.tenant_id != device["tenant_id"] or payload.cliente_id != device["cliente_id"] or payload.unidade_id != device["unidade_id"]:
            raise HTTPException(status_code=403, detail="Evento pertence a outro tenant, cliente ou unidade.")
        existing = db.fetchone("SELECT id, received_at FROM edge_events WHERE event_uuid = ?", (payload.event_uuid,))
        if existing:
            payload_json = json.dumps(payload.model_dump())
            db.execute(
                """
                UPDATE edge_events
                SET fim = COALESCE(?, fim),
                    duracao = COALESCE(?, duracao),
                    operador_presente = COALESCE(?, operador_presente),
                    confianca = COALESCE(?, confianca),
                    severidade = COALESCE(?, severidade),
                    status = COALESCE(?, status),
                    midia_path = COALESCE(?, midia_path),
                    payload_json = ?
                WHERE event_uuid = ?
                """,
                (
                    payload.fim,
                    payload.duracao,
                    payload.operador_presente,
                    payload.confianca,
                    payload.severidade,
                    payload.status,
                    payload.midia_path,
                    payload_json,
                    payload.event_uuid,
                ),
            )
            db.commit()
            return {"status": "duplicate_updated", "event_uuid": payload.event_uuid, "id": existing["id"], "received_at": existing["received_at"]}
        event_id = f"cevt_{uuid.uuid4().hex[:12]}"
        received_at = now_iso()
        payload_json = json.dumps(payload.model_dump())
        db.execute(
            """
            INSERT INTO edge_events (
                id, event_uuid, tenant_id, cliente_id, unidade_id, edge_id, camera_id, tipo,
                inicio, fim, duracao, operador_presente, confianca, severidade, status, midia_path,
                payload_json, received_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                payload.event_uuid,
                payload.tenant_id,
                payload.cliente_id,
                payload.unidade_id,
                x_edge_id,
                payload.camera_id,
                payload.tipo,
                payload.inicio,
                payload.fim,
                payload.duracao,
                payload.operador_presente,
                payload.confianca,
                payload.severidade,
                payload.status,
                payload.midia_path,
                payload_json,
                received_at,
            ),
        )
        db.commit()
    LOGGER.info("Evento recebido do Edge edge_id=%s event_uuid=%s", x_edge_id, payload.event_uuid)
    return {"status": "received", "event_uuid": payload.event_uuid, "id": event_id, "received_at": received_at}


@api.get("/eventos")
def list_cloud_events() -> list[dict[str, Any]]:
    with connect() as db:
        init_cloud_db(db)
        rows = db.fetchall("SELECT * FROM edge_events ORDER BY received_at DESC LIMIT 200")
    return [
        _event_row_public(row)
        for row in rows
    ]


@api.get("/cameras/estado")
def list_cloud_camera_state() -> list[dict[str, Any]]:
    with connect() as db:
        init_cloud_db(db)
        rows = db.fetchall(
            """
            SELECT camera_id, edge_id, unidade_id, MAX(received_at) AS ultimo_frame, COUNT(*) AS eventos
            FROM edge_events
            GROUP BY camera_id, edge_id, unidade_id
            ORDER BY MAX(received_at) DESC
            LIMIT 200
            """
        )
    return [
        {
            "id": row["camera_id"],
            "nome": row["camera_id"],
            "camera_id": row["camera_id"],
            "edge_id": row["edge_id"],
            "unidade_id": row["unidade_id"],
            "status": "online",
            "ultimo_frame": row["ultimo_frame"],
            "eventos_recebidos": row["eventos"],
        }
        for row in rows
    ]


@api.get("/visual-rules")
def list_cloud_visual_rules() -> list[dict[str, Any]]:
    return []


@api.get("/alert-deliveries")
def list_cloud_alert_deliveries() -> list[dict[str, Any]]:
    return []


@api.get("/operations/events")
def list_cloud_operational_events(limit: int = 30, offset: int = 0) -> dict[str, Any]:
    with connect() as db:
        init_cloud_db(db)
        rows = db.fetchall(
            """
            SELECT *
            FROM edge_events
            ORDER BY COALESCE(inicio, received_at) DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
    events = [_event_row_operation(row) for row in rows]
    return {"events": events, "limit": limit, "offset": offset}


@api.get("/operations/summary")
def cloud_operations_summary() -> dict[str, Any]:
    with connect() as db:
        init_cloud_db(db)
        rows = db.fetchall("SELECT * FROM edge_events ORDER BY COALESCE(inicio, received_at)")
    durations = [float(row["duracao"] or 0) for row in rows if row["tipo"] == "machine_stoppage"]
    total_stopped = sum(durations)
    return {
        "tempo_total_monitorado": 0,
        "tempo_maquina_ativa": 0,
        "tempo_maquina_parada": total_stopped,
        "percentual_atividade_estimada": 0,
        "quantidade_paradas": len(durations),
        "duracao_media_paradas": (total_stopped / len(durations)) if durations else 0,
        "maior_parada": max(durations) if durations else 0,
        "tempo_ativa_sem_operador": 0,
        "quantidade_ausencias_operador": 0,
        "disponibilidade_camera": 100 if rows else 0,
        "period": {"start": rows[0]["inicio"] if rows else now_iso(), "end": rows[-1]["fim"] or rows[-1]["received_at"] if rows else now_iso()},
    }


@api.get("/operations/timeline")
def cloud_operations_timeline() -> list[dict[str, Any]]:
    with connect() as db:
        init_cloud_db(db)
        rows = db.fetchall(
            """
            SELECT *
            FROM edge_events
            WHERE tipo IN ('machine_stoppage', 'restricted_area_occupied')
            ORDER BY COALESCE(inicio, received_at)
            LIMIT 200
            """
        )
    return [_event_row_timeline(row) for row in rows]


@api.get("/operations/current-status")
def cloud_current_status() -> dict[str, Any]:
    with connect() as db:
        init_cloud_db(db)
        row = db.fetchone("SELECT * FROM edge_events ORDER BY received_at DESC LIMIT 1")
    return {
        "machine_name": _metadata_value(row, "machine_name") if row else None,
        "machine_state": "NAO_CONFIGURADA",
        "operator_state": "AUSENTE",
        "people_count": 0,
        "camera_status": "online" if row else "unknown",
        "last_event": _event_row_public(row) if row else None,
    }


@api.get("/operations")
def cloud_operations() -> dict[str, Any]:
    return {"machines": []}


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(row.get("payload_json") or "{}")
    except json.JSONDecodeError:
        return {}


def _metadata_value(row: dict[str, Any] | None, key: str) -> Any:
    if not row:
        return None
    metadata = _payload(row).get("metadata") or {}
    return metadata.get(key)


def _event_row_public(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "event_uuid": row["event_uuid"],
        "cliente_id": row["cliente_id"],
        "unidade_id": row["unidade_id"],
        "camera_id": row["camera_id"],
        "tipo": row["tipo"],
        "inicio": row["inicio"],
        "fim": row["fim"],
        "duracao": row["duracao"],
        "confianca": row["confianca"],
        "severidade": row.get("severidade"),
        "status": row.get("status") or ("closed" if row.get("fim") else "open"),
        "criado_em": row["received_at"],
        "machine_name": _metadata_value(row, "machine_name"),
    }


def _event_row_operation(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "event_uuid": row["event_uuid"],
        "session_id": row["edge_id"],
        "camera_id": row["camera_id"],
        "machine_name": _metadata_value(row, "machine_name") or _metadata_value(row, "machine_monitor_id"),
        "event_type": row["tipo"],
        "previous_state": None,
        "new_state": _state_for_type(row["tipo"]),
        "started_at": row["inicio"] or row["received_at"],
        "ended_at": row["fim"],
        "duration_seconds": row["duracao"] or 0,
        "confidence": row["confianca"],
        "severidade": row.get("severidade"),
        "status": row.get("status") or ("closed" if row.get("fim") else "open"),
        "people_count": 0,
        "snapshot_path": row["midia_path"],
        "created_at": row["received_at"],
    }


def _event_row_timeline(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_type": row["tipo"],
        "state": _state_for_type(row["tipo"]),
        "start": row["inicio"] or row["received_at"],
        "end": row["fim"] or row["received_at"],
        "duration_seconds": row["duracao"] or 0,
    }


def _state_for_type(event_type: str) -> str:
    if event_type == "machine_stoppage":
        return "PARADA"
    if event_type == "active_without_operator":
        return "ATIVA_SEM_OPERADOR"
    if event_type == "restricted_area_occupied":
        return "OCUPADA"
    return event_type
