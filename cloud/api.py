from __future__ import annotations

import json
import logging
import os
import uuid
from urllib.parse import quote
from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import ROOT
from app.auth import (
    ADMIN_ROLES,
    authenticate,
    create_session,
    create_user,
    delete_session,
    get_request_user,
    users_exist,
)
from cloud.database import connect, init_cloud_db, is_postgres_url
from cloud.security import hash_edge_secret, verify_edge_secret
from shared.schemas import now_iso

LOGGER = logging.getLogger(__name__)

api = FastAPI(title="Campex Cloud")
FRONTEND_DIR = ROOT / "frontend"

if FRONTEND_DIR.exists():
    api.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


class LoginIn(BaseModel):
    email: str
    senha: str


class CloudClienteIn(BaseModel):
    nome: str = Field(min_length=1)
    documento: Optional[str] = None
    status: str = "ativo"


class CloudUnidadeIn(BaseModel):
    cliente_id: Optional[str] = None
    nome: str = Field(min_length=1)
    localizacao: Optional[str] = None
    timezone: str = "America/Sao_Paulo"


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


def _cookie_secure() -> bool:
    return os.getenv("CAMPEX_COOKIE_SECURE", "").strip().lower() in {"1", "true", "yes", "on"}


def _bootstrap_cloud_admin() -> None:
    email = os.getenv("CAMPEX_CLOUD_ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("CAMPEX_CLOUD_ADMIN_PASSWORD", "")
    if not email or not password:
        LOGGER.warning("Cloud sem credenciais bootstrap configuradas.")
        return
    if len(password) < 8:
        raise RuntimeError("CAMPEX_CLOUD_ADMIN_PASSWORD deve ter pelo menos 8 caracteres.")

    with connect() as db:
        init_cloud_db(db)
        if users_exist(db):
            return
        create_user(
            db,
            email=email,
            password=password,
            role="admin_campex",
            nome="Administrador Campex",
        )
        LOGGER.info("Administrador inicial do Campex Cloud criado.")


@api.on_event("startup")
def startup() -> None:
    init_cloud_db()
    _bootstrap_cloud_admin()


@api.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "database": "postgresql" if is_postgres_url() else "sqlite-dev"}


@api.get("/")
def root() -> RedirectResponse:
    return RedirectResponse(url="/operations-view", status_code=307)


INTERNAL_ROUTES = {
    "/dashboard": "workspace.html",
    "/overview": "workspace.html",
    "/operations-view": "workspace.html",
    "/cameras": "workspace.html",
    "/events": "workspace.html",
    "/alerts": "workspace.html",
    "/evidence": "workspace.html",
    "/rules": "workspace.html",
    "/reports": "workspace.html",
    "/insights": "workspace.html",
    "/history": "workspace.html",
    "/integrations": "workspace.html",
    "/users": "workspace.html",
    "/edges": "workspace.html",
    "/settings": "workspace.html",
    "/settings/cameras": "index.html",
    "/settings/notifications": "workspace.html",
    "/settings/account": "workspace.html",
    "/help": "workspace.html",
}


def _cloud_user(request: Request) -> dict[str, Any] | None:
    with connect() as db:
        init_cloud_db(db)
        return get_request_user(request, db)


def _require_cloud_user(request: Request) -> dict[str, Any]:
    user = _cloud_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Login necessario.")
    return user


def _login_redirect(request: Request) -> RedirectResponse:
    next_path = request.url.path
    if request.url.query:
        next_path = f"{next_path}?{request.url.query}"
    return RedirectResponse(
        url=f"/login?next={quote(next_path, safe='')}",
        status_code=303,
    )


@api.get("/login", include_in_schema=False)
def cloud_login_page() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "login.html")


@api.get("/login/", include_in_schema=False)
def cloud_login_page_slash() -> FileResponse:
    return cloud_login_page()


async def serve_internal(request: Request):
    if _cloud_user(request) is None:
        return _login_redirect(request)
    file_name = INTERNAL_ROUTES.get(request.url.path)
    if file_name is None:
        raise HTTPException(status_code=404, detail="Pagina nao encontrada.")
    return FileResponse(FRONTEND_DIR / file_name)


for internal_route in INTERNAL_ROUTES:
    api.add_api_route(
        internal_route,
        serve_internal,
        methods=["GET"],
        include_in_schema=False,
    )


@api.post("/auth/login")
def cloud_post_login(payload: LoginIn, response: Response) -> dict[str, Any]:
    with connect() as db:
        init_cloud_db(db)
        user = authenticate(db, payload.email, payload.senha)
        if user is None:
            raise HTTPException(status_code=401, detail="E-mail ou senha invalidos.")
        token = create_session(db, user["id"])

    response.set_cookie(
        "campex_session",
        token,
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(),
        max_age=60 * 60 * 12,
    )
    return {"user": user, "next": "/operations-view?view=home"}


@api.post("/auth/logout")
def cloud_post_logout(request: Request, response: Response) -> dict[str, bool]:
    token = request.cookies.get("campex_session")
    if token:
        with connect() as db:
            init_cloud_db(db)
            delete_session(db, token)
    response.delete_cookie("campex_session")
    return {"ok": True}


@api.get("/auth/me")
def cloud_auth_me(request: Request) -> dict[str, Any]:
    return {"user": _require_cloud_user(request)}


@api.get("/auth/status")
def cloud_auth_status(request: Request) -> dict[str, Any]:
    user = _cloud_user(request)
    return {
        "authenticated": user is not None,
        "bootstrap": False,
        "user": user,
    }



def _cloud_new_id(prefix: str) -> str:
    import uuid
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


@api.get("/clientes")
def cloud_get_clientes(request: Request) -> list[dict[str, Any]]:
    user = _require_cloud_user(request)

    with connect() as db:
        init_cloud_db(db)

        if user.get("role") == "admin_campex":
            rows = db.fetchall(
                "SELECT * FROM clientes ORDER BY nome"
            )
        else:
            cliente_id = user.get("cliente_id")
            if not cliente_id:
                return []
            rows = db.fetchall(
                "SELECT * FROM clientes WHERE id = ? ORDER BY nome",
                (cliente_id,),
            )

    return [dict(row) for row in rows]


@api.post("/clientes")
def cloud_post_cliente(
    payload: CloudClienteIn,
    request: Request,
) -> dict[str, Any]:
    user = _require_cloud_user(request)

    if user.get("role") != "admin_campex":
        raise HTTPException(
            status_code=403,
            detail="Somente admin Campex cria clientes.",
        )

    cliente_id = _cloud_new_id("cli")

    with connect() as db:
        init_cloud_db(db)
        db.execute(
            """
            INSERT INTO clientes (
                id,
                nome,
                documento,
                status
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                cliente_id,
                payload.nome.strip(),
                payload.documento,
                payload.status.strip() or "ativo",
            ),
        )
        db.commit()

        row = db.fetchone(
            "SELECT * FROM clientes WHERE id = ?",
            (cliente_id,),
        )

    return dict(row)


@api.get("/unidades")
def cloud_get_unidades(
    request: Request,
    cliente_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    user = _require_cloud_user(request)

    effective_cliente_id = cliente_id

    if user.get("role") != "admin_campex":
        effective_cliente_id = user.get("cliente_id")

    with connect() as db:
        init_cloud_db(db)

        if effective_cliente_id:
            rows = db.fetchall(
                """
                SELECT *
                FROM unidades
                WHERE cliente_id = ?
                ORDER BY nome
                """,
                (effective_cliente_id,),
            )
        elif user.get("role") == "admin_campex":
            rows = db.fetchall(
                "SELECT * FROM unidades ORDER BY nome"
            )
        else:
            rows = []

    return [dict(row) for row in rows]


@api.post("/unidades")
def cloud_post_unidade(
    payload: CloudUnidadeIn,
    request: Request,
) -> dict[str, Any]:
    user = _require_cloud_user(request)

    if user.get("role") not in ADMIN_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Permissao insuficiente.",
        )

    if user.get("role") == "admin_campex":
        cliente_id = (payload.cliente_id or "").strip()
        if not cliente_id:
            raise HTTPException(
                status_code=400,
                detail="Informe o cliente da unidade.",
            )
    else:
        cliente_id = str(user.get("cliente_id") or "").strip()
        if not cliente_id:
            raise HTTPException(
                status_code=403,
                detail="Usuario sem cliente vinculado.",
            )

    with connect() as db:
        init_cloud_db(db)

        cliente = db.fetchone(
            "SELECT id FROM clientes WHERE id = ?",
            (cliente_id,),
        )
        if not cliente:
            raise HTTPException(
                status_code=404,
                detail="Cliente nao encontrado.",
            )

        unidade_id = _cloud_new_id("uni")

        db.execute(
            """
            INSERT INTO unidades (
                id,
                cliente_id,
                nome,
                localizacao,
                timezone
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                unidade_id,
                cliente_id,
                payload.nome.strip(),
                payload.localizacao,
                payload.timezone,
            ),
        )
        db.commit()

        row = db.fetchone(
            "SELECT * FROM unidades WHERE id = ?",
            (unidade_id,),
        )

    return dict(row)


@api.post("/admin/edge-devices")
def create_edge_device(payload: EdgeDeviceIn, request: Request) -> dict[str, Any]:
    user = _require_cloud_user(request)
    if user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Permissao insuficiente.")
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





@api.get("/edge-installer/windows")
def download_windows_edge_installer(
    request: Request,
    unidade_id: str,
) -> Response:
    import base64
    import os
    import secrets

    from cloud.edge_installer import build_windows_installer_cmd

    user = _require_cloud_user(request)

    if user.get("role") not in ADMIN_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Permissao insuficiente para instalar Edge.",
        )

    with connect() as db:
        init_cloud_db(db)

        unidade = db.fetchone(
            "SELECT * FROM unidades WHERE id = ?",
            (unidade_id,),
        )

        if not unidade:
            raise HTTPException(
                status_code=404,
                detail="Unidade nao encontrada.",
            )

        cliente_id = str(unidade["cliente_id"])

        if (
            user.get("role") != "admin_campex"
            and str(user.get("cliente_id") or "") != cliente_id
        ):
            raise HTTPException(
                status_code=403,
                detail="Unidade pertence a outro cliente.",
            )

        edge_id = _cloud_new_id("edge")
        edge_secret = secrets.token_urlsafe(32)
        credential_key = base64.urlsafe_b64encode(
            os.urandom(32)
        ).decode("ascii")

        created_at = now_iso()

        db.execute(
            """
            INSERT INTO edge_devices (
                id,
                tenant_id,
                cliente_id,
                unidade_id,
                nome,
                secret_hash,
                status,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)
            """,
            (
                edge_id,
                cliente_id,
                cliente_id,
                unidade_id,
                f"Campex Edge - {unidade['nome']}",
                hash_edge_secret(edge_secret),
                created_at,
                created_at,
            ),
        )
        db.commit()

    cloud_url = str(request.base_url).rstrip("/")

    installer = build_windows_installer_cmd(
        cloud_url=cloud_url,
        edge_id=edge_id,
        edge_secret=edge_secret,
        credential_key=credential_key,
    )

    return Response(
        content=installer,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": 'attachment; filename="Instalar-Campex.cmd"',
            "Cache-Control": "no-store",
        },
    )


@api.get("/edge-package/windows")
def download_windows_edge_package(
    x_edge_id: Optional[str] = Header(default=None, alias="X-Edge-Id"),
    x_edge_secret: Optional[str] = Header(default=None, alias="X-Edge-Secret"),
):
    import os

    from starlette.background import BackgroundTask
    from cloud.edge_installer import create_windows_edge_package

    if not x_edge_id or not x_edge_secret:
        raise HTTPException(
            status_code=401,
            detail="Credenciais do Edge ausentes.",
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
            raise HTTPException(
                status_code=401,
                detail="Edge nao autorizado.",
            )

        if device["status"] != "active" or device.get("revoked_at"):
            raise HTTPException(
                status_code=403,
                detail="Edge revogado ou inativo.",
            )

    project_root = Path(__file__).resolve().parents[1]
    zip_path = create_windows_edge_package(project_root)

    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename="campex-edge-package.zip",
        background=BackgroundTask(
            lambda: os.unlink(zip_path)
            if os.path.exists(zip_path)
            else None
        ),
    )


@api.get("/edge-devices")
def list_edge_devices(
    request: Request,
    cliente_id: Optional[str] = None,
    unidade_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    from datetime import datetime, timezone

    user = _require_cloud_user(request)

    effective_cliente_id = cliente_id
    if user.get("role") != "admin_campex":
        effective_cliente_id = user.get("cliente_id")

    clauses = []
    params: list[Any] = []

    if effective_cliente_id:
        clauses.append("cliente_id = ?")
        params.append(effective_cliente_id)

    if unidade_id:
        clauses.append("unidade_id = ?")
        params.append(unidade_id)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with connect() as db:
        init_cloud_db(db)
        rows = db.fetchall(
            f"""
            SELECT
                id,
                tenant_id,
                cliente_id,
                unidade_id,
                nome,
                status,
                revoked_at,
                created_at,
                updated_at,
                last_seen_at
            FROM edge_devices
            {where}
            ORDER BY nome
            """,
            tuple(params),
        )

    now = datetime.now(timezone.utc)
    result = []

    for row in rows:
        item = dict(row)
        last_seen = item.get("last_seen_at")
        online = False

        if last_seen and item.get("status") == "active" and not item.get("revoked_at"):
            try:
                parsed = datetime.fromisoformat(str(last_seen).replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                online = (
                    now - parsed.astimezone(timezone.utc)
                ).total_seconds() <= 90
            except Exception:
                online = False

        item["online"] = online
        item["connection_status"] = "online" if online else "offline"
        item["last_seen_at"] = last_seen
        result.append(item)

    return result


@api.post("/edge/heartbeat")
def edge_heartbeat(
    x_edge_id: Optional[str] = Header(default=None, alias="X-Edge-Id"),
    x_edge_secret: Optional[str] = Header(default=None, alias="X-Edge-Secret"),
) -> dict[str, Any]:
    if not x_edge_id or not x_edge_secret:
        raise HTTPException(
            status_code=401,
            detail="Credenciais do Edge ausentes.",
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
            raise HTTPException(
                status_code=401,
                detail="Edge nao autorizado.",
            )

        if device["status"] != "active" or device.get("revoked_at"):
            raise HTTPException(
                status_code=403,
                detail="Edge revogado ou inativo.",
            )

        seen_at = now_iso()

        db.execute(
            """
            UPDATE edge_devices
            SET last_seen_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (seen_at, seen_at, x_edge_id),
        )
        db.commit()

    return {
        "ok": True,
        "edge_id": x_edge_id,
        "status": "online",
        "seen_at": seen_at,
    }


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
