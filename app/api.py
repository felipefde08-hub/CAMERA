from __future__ import annotations

from typing import Any, Optional
import hashlib
import time
import os
import psutil
from pathlib import Path
import logging

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.camera_rtsp import build_rtsp_url, test_rtsp_connection
from app.alerts import enqueue_event_alert, resume_pending_deliveries, retry_delivery, send_test_alert, stream_events
from app.auth import ADMIN_ROLES, authenticate, create_session, create_user, delete_session, get_request_user, require_role, require_user, tenant_filter, update_user_password, users_exist
from app.config import ROOT
from app.database import connect, init_db
from app.live_stream import LiveStreamManager
from app.models import (
    atualizar_evento,
    atualizar_area_monitorada,
    atualizar_alert_recipient,
    atualizar_machine_monitor,
    atualizar_camera_video_info,
    alterar_senha_camera,
    classificar_evento,
    criar_camera,
    criar_alert_recipient,
    criar_cliente,
    criar_dispositivo,
    criar_area_monitorada,
    criar_ocorrencia_zona,
    criar_machine_monitor,
    criar_regra,
    criar_unidade,
    excluir_area_monitorada,
    excluir_alert_recipient,
    excluir_machine_monitor,
    listar,
    listar_alert_deliveries,
    listar_alert_recipients,
    listar_areas_camera,
    listar_eventos_filtrados,
    listar_machine_monitors_camera,
    listar_regras,
    listar_por_cliente,
    obter_alert_delivery,
    obter_alert_recipient,
    obter_camera,
    obter_evento,
    obter_machine_monitor,
    obter_regra,
    reconhecer_ocorrencia,
    registrar_evento,
    atualizar_regra,
)
from app.pilot import acceptance_checklist, health_snapshot
from app.machine_monitoring import baseline_stats, calibrate_threshold
from app.operations_history import (
    current_status,
    list_operational_events,
    operations_summary,
    operations_timeline,
)
from app.reports import daily_report_data
from app.restricted_area import normalize_points
from app.visual_rule_engine import condition_templates, default_rule_payloads, evaluate_rule
from shared.schemas import now_iso

api = FastAPI(title="Visual Operations Internal API")
logger = logging.getLogger("campex.api")
FRONTEND_DIR = ROOT / "frontend"
live_streams = LiveStreamManager()
live_view_sessions: dict[str, dict[str, Any]] = {}

if FRONTEND_DIR.exists():
    api.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


class ClienteIn(BaseModel):
    nome: str
    documento: Optional[str] = None
    status: str = "ativo"


class UnidadeIn(BaseModel):
    cliente_id: Optional[str] = None
    nome: str
    localizacao: Optional[str] = None
    timezone: str = "America/Sao_Paulo"


class DispositivoIn(BaseModel):
    unidade_id: str
    nome: str
    status: str = "offline"


class CameraIn(BaseModel):
    cliente_id: Optional[str] = None
    unidade_id: Optional[str] = None
    dispositivo_id: Optional[str] = None
    edge_id: Optional[str] = None
    nome: str
    config_ref: Optional[str] = None
    source_type: Optional[str] = None
    secure_ref: Optional[str] = None
    status: str = "nao_conectada"


class CameraRtspIn(BaseModel):
    nome: str
    unidade_id: Optional[str] = None
    cliente_id: Optional[str] = None
    dispositivo_id: Optional[str] = None
    edge_id: Optional[str] = None
    host: Optional[str] = None
    porta_rtsp: int = 554
    usuario: Optional[str] = None
    senha: Optional[str] = None
    caminho_rtsp: Optional[str] = None
    rtsp_url: Optional[str] = None
    testar_conexao: bool = True
    canal: Optional[str] = None
    ativa: bool = True


class CameraRtspTestIn(BaseModel):
    host: Optional[str] = None
    porta_rtsp: int = 554
    usuario: Optional[str] = None
    senha: Optional[str] = None
    caminho_rtsp: Optional[str] = None
    rtsp_url: Optional[str] = None
    timeout_seconds: float = 5.0


class LiveViewStartIn(CameraRtspTestIn):
    nome: str = "Live View"
    camera_id: Optional[str] = None


class RegraIn(BaseModel):
    camera_id: str
    tipo_evento: str
    tempo_minimo: float = 0
    ativo: bool = True
    nome: Optional[str] = None
    cliente_id: Optional[str] = None
    unidade_id: Optional[str] = None
    entidade: Optional[str] = None
    regiao_id: Optional[str] = None
    condicao: dict[str, Any] = {}
    severidade: str = "medium"
    cooldown_seconds: float = 60
    destinatarios: list[str] = []
    alerta_inicio: bool = True
    alerta_normalizacao: bool = False
    debounce_seconds: float = 1
    hysteresis_seconds: float = 1
    metadata: dict[str, Any] = {}


class RegraPatchIn(BaseModel):
    nome: Optional[str] = None
    tipo_evento: Optional[str] = None
    tempo_minimo: Optional[float] = None
    ativo: Optional[bool] = None
    entidade: Optional[str] = None
    regiao_id: Optional[str] = None
    condicao: Optional[dict[str, Any]] = None
    severidade: Optional[str] = None
    cooldown_seconds: Optional[float] = None
    destinatarios: Optional[list[str]] = None
    alerta_inicio: Optional[bool] = None
    alerta_normalizacao: Optional[bool] = None
    debounce_seconds: Optional[float] = None
    hysteresis_seconds: Optional[float] = None
    metadata: Optional[dict[str, Any]] = None


class VisualRuleSimulationIn(BaseModel):
    facts: dict[str, Any]
    at: Optional[str] = None


class VisualRuleDefaultsIn(BaseModel):
    zone_id: Optional[str] = None


class DevTestEventIn(BaseModel):
    camera_id: Optional[str] = None
    area_id: Optional[str] = None
    event_type: str = "workstation_unattended"


class EventoIn(BaseModel):
    cliente_id: str
    unidade_id: str
    camera_id: str
    tipo: str
    inicio: Optional[str] = None
    fim: Optional[str] = None
    duracao: Optional[float] = None
    operador_presente: Optional[bool] = None
    confianca: Optional[float] = None
    midia_path: Optional[str] = None


class EventoUpdateIn(BaseModel):
    fim: Optional[str] = None
    duracao: Optional[float] = None
    operador_presente: Optional[bool] = None
    confianca: Optional[float] = None
    midia_path: Optional[str] = None
    status: Optional[str] = None
    observacao: Optional[str] = None
    acknowledged_by: Optional[str] = None


class AreaPointIn(BaseModel):
    x: float
    y: float


class AreaIn(BaseModel):
    camera_id: Optional[str] = None
    cliente_id: Optional[str] = None
    unidade_id: Optional[str] = None
    machine_id: Optional[str] = None
    nome: Optional[str] = None
    name: Optional[str] = None
    pontos: Optional[list[AreaPointIn]] = None
    polygon: Optional[list[AreaPointIn]] = None
    tipo: Optional[str] = None
    area_type: Optional[str] = None
    ativa: Optional[bool] = None
    active: Optional[bool] = None
    collaborator_name: Optional[str] = None
    expected_start: Optional[str] = None
    expected_end: Optional[str] = None
    absence_tolerance_seconds: Optional[float] = None
    dwell_limit_seconds: Optional[float] = None
    expected_min_people: Optional[int] = None
    metadata: Optional[dict[str, Any]] = None

    def resolved_name(self) -> str:
        value = self.name or self.nome
        if not value:
            raise ValueError("Nome da zona obrigatorio.")
        return value

    def resolved_type(self) -> str:
        return self.area_type or self.tipo or "restricted_area"

    def resolved_points(self) -> list[AreaPointIn]:
        points = self.polygon or self.pontos
        if points is None:
            raise ValueError("Poligono da zona obrigatorio.")
        return points

    def resolved_active(self) -> bool:
        if self.active is not None:
            return self.active
        if self.ativa is not None:
            return self.ativa
        return True


class AreaPatchIn(BaseModel):
    machine_id: Optional[str] = None
    nome: Optional[str] = None
    tipo: Optional[str] = None
    pontos: Optional[list[AreaPointIn]] = None
    ativa: Optional[bool] = None
    collaborator_name: Optional[str] = None
    expected_start: Optional[str] = None
    expected_end: Optional[str] = None
    absence_tolerance_seconds: Optional[float] = None
    dwell_limit_seconds: Optional[float] = None
    expected_min_people: Optional[int] = None
    metadata: Optional[dict[str, Any]] = None


class AlertRecipientIn(BaseModel):
    nome: str
    email: str
    ativo: bool = True
    cliente_id: Optional[str] = None
    camera_id: Optional[str] = None
    area_id: Optional[str] = None
    severidade_minima: str = "low"
    event_types: list[str] = []


class AlertRecipientPatchIn(BaseModel):
    nome: Optional[str] = None
    email: Optional[str] = None
    ativo: Optional[bool] = None
    camera_id: Optional[str] = None
    area_id: Optional[str] = None
    severidade_minima: Optional[str] = None
    event_types: Optional[list[str]] = None


class LoginIn(BaseModel):
    email: str
    senha: str


class UserIn(BaseModel):
    nome: Optional[str] = None
    email: str
    senha: str
    role: str
    cliente_id: Optional[str] = None


class ResetPasswordIn(BaseModel):
    email: str
    nova_senha: str


class CameraPasswordIn(BaseModel):
    senha: str


class MachineMonitorIn(BaseModel):
    nome: str
    machine_polygon: list[AreaPointIn]
    operator_polygon: list[AreaPointIn]
    ativo: bool = True
    motion_sensitivity: float = 25.0
    stop_seconds: float = 10.0
    recovery_seconds: float = 3.0
    replay_pre_seconds: float = 60.0
    replay_post_seconds: float = 30.0
    operator_absence_seconds: float = 30.0
    stopped_with_operator_seconds: float = 120.0
    microstop_window_seconds: float = 3600.0
    microstop_limit: int = 5
    loss_model: Optional[str] = None
    loss_per_minute: Optional[float] = None
    units_per_minute: Optional[float] = None
    margin_per_unit: Optional[float] = None
    indicator_polygon: Optional[list[AreaPointIn]] = None


class MachineMonitorPatchIn(BaseModel):
    nome: Optional[str] = None
    machine_polygon: Optional[list[AreaPointIn]] = None
    operator_polygon: Optional[list[AreaPointIn]] = None
    ativo: Optional[bool] = None
    motion_sensitivity: Optional[float] = None
    motion_threshold: Optional[float] = None
    stop_seconds: Optional[float] = None
    recovery_seconds: Optional[float] = None
    operator_absence_seconds: Optional[float] = None
    stopped_with_operator_seconds: Optional[float] = None
    microstop_window_seconds: Optional[float] = None
    microstop_limit: Optional[int] = None
    loss_model: Optional[str] = None
    loss_per_minute: Optional[float] = None
    units_per_minute: Optional[float] = None
    margin_per_unit: Optional[float] = None
    indicator_polygon: Optional[list[AreaPointIn]] = None


class MachineCalibrationIn(BaseModel):
    running_motion: Optional[float] = None
    stopped_motion: Optional[float] = None
    samples: Optional[list[float]] = None
    duration_seconds: float = 20.0


class AssistedMachineCalibrationIn(BaseModel):
    duration_seconds: float = 30.0


class EventCauseIn(BaseModel):
    cause_category: str
    cause_notes: Optional[str] = None
    classified_by: Optional[str] = None


class LiveViewMachineIn(BaseModel):
    nome: str
    tipo: Optional[str] = None
    machine_polygon: list[AreaPointIn]
    operator_polygon: Optional[list[AreaPointIn]] = None


class LiveViewOperatorZoneIn(BaseModel):
    operator_polygon: list[AreaPointIn]


def resolve_unidade_cliente(connection, unidade_id: str, cliente_id: str | None) -> str:
    unidade = connection.execute("SELECT id, cliente_id FROM unidades WHERE id = ?", (unidade_id,)).fetchone()
    if unidade is None:
        raise HTTPException(status_code=400, detail="Unidade não encontrada. Cadastre ou informe um unidade_id válido.")
    real_cliente_id = str(unidade["cliente_id"])
    if cliente_id and cliente_id != real_cliente_id:
        raise HTTPException(status_code=400, detail="Cliente informado não pertence à unidade selecionada.")
    return real_cliente_id


def default_cliente_unidade(connection, cliente_id: str | None = None, unidade_id: str | None = None) -> tuple[str, str]:
    if unidade_id:
        resolved_cliente_id = resolve_unidade_cliente(connection, unidade_id, cliente_id)
        return resolved_cliente_id, unidade_id

    if cliente_id:
        cliente = connection.execute("SELECT id FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
        if cliente is None:
            raise HTTPException(status_code=400, detail="Cliente não encontrado.")
    else:
        cliente = connection.execute("SELECT id FROM clientes ORDER BY criado_em ASC LIMIT 1").fetchone()
        if cliente is None:
            cliente_id = criar_cliente(connection, "Cliente padrão")
        else:
            cliente_id = str(cliente["id"])

    unidade = connection.execute(
        "SELECT id FROM unidades WHERE cliente_id = ? ORDER BY criado_em ASC LIMIT 1",
        (cliente_id,),
    ).fetchone()
    if unidade is None:
        unidade_id = criar_unidade(connection, str(cliente_id), "Unidade padrão")
    else:
        unidade_id = str(unidade["id"])
    return str(cliente_id), unidade_id


def require_same_tenant(user: dict[str, Any], cliente_id: str | None, message: str = "Registro de outro cliente.") -> None:
    tenant = tenant_filter(user)
    if tenant and cliente_id != tenant:
        raise HTTPException(status_code=403, detail=message)


def effective_cliente_id(user: dict[str, Any], requested: str | None = None) -> str | None:
    return requested if user["role"] == "admin_campex" else user.get("cliente_id")


def require_camera_access(connection, user: dict[str, Any], camera_id: str | None) -> None:
    if not camera_id:
        return
    camera = obter_camera(connection, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera nao encontrada.")
    require_same_tenant(user, camera.get("cliente_id"), "Camera de outro cliente.")


@api.on_event("startup")
def startup() -> None:
    with connect() as connection:
        init_db(connection)
    resume_pending_deliveries()


@api.on_event("shutdown")
def shutdown() -> None:
    live_streams.stop_all()


@api.get("/")
def index() -> RedirectResponse:
    return RedirectResponse(url="/dashboard", status_code=307)


@api.get("/home")
def home_page() -> RedirectResponse:
    return RedirectResponse(url="/dashboard", status_code=307)


INTERNAL_ROUTE_FILES = {
    "/dashboard": "dashboard.html",
    "/overview": "dashboard.html",
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
    "/settings": "workspace.html",
    "/settings/cameras": "index.html",
    "/settings/notifications": "workspace.html",
    "/settings/account": "workspace.html",
    "/help": "workspace.html",
}

FRONTEND_404_PREFIXES = {"settings"}
API_404_PREFIXES = {
    "alert-deliveries",
    "alert-recipients",
    "api",
    "assets",
    "auth",
    "cameras",
    "clientes",
    "dispositivos",
    "eventos",
    "events",
    "health",
    "live-grid",
    "live-view",
    "people-zones",
    "operations",
    "relatorios",
    "static",
    "unidades",
}


def serve_internal_route(request: Request) -> FileResponse:
    filename = INTERNAL_ROUTE_FILES.get(request.url.path)
    if filename is None:
        raise HTTPException(status_code=404, detail="Página não encontrada.")
    return FileResponse(FRONTEND_DIR / filename)


for internal_route in INTERNAL_ROUTE_FILES:
    api.add_api_route(
        internal_route,
        serve_internal_route,
        methods=["GET"],
        include_in_schema=False,
        name=f"internal_{internal_route.strip('/').replace('/', '_') or 'home'}",
    )


def serve_internal_not_found(request: Request) -> FileResponse:
    path = request.url.path.strip("/")
    first_segment = path.split("/", 1)[0]
    if "." in path or first_segment in API_404_PREFIXES:
        raise HTTPException(status_code=404, detail="Not Found")
    if "/" in path and first_segment not in FRONTEND_404_PREFIXES:
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(FRONTEND_DIR / "workspace.html", status_code=404)


@api.get("/live-view")
def live_view_page() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "live-view.html")


@api.get("/live-view/")
def live_view_page_slash() -> FileResponse:
    return live_view_page()


@api.get("/live-grid")
def live_grid_page() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "live-grid.html")


@api.get("/live-grid/")
def live_grid_page_slash() -> FileResponse:
    return live_grid_page()


@api.get("/people-zones")
def people_zones_page() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "people-zones.html")


@api.get("/people-zones/")
def people_zones_page_slash() -> FileResponse:
    return people_zones_page()


@api.get("/local-diagnostics-view")
def local_diagnostics_view_page() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "local-diagnostics.html")


@api.get("/local-diagnostics-view/")
def local_diagnostics_view_page_slash() -> FileResponse:
    return local_diagnostics_view_page()


@api.get("/operations-dashboard")
def operations_dashboard_page() -> RedirectResponse:
    return RedirectResponse(url="/dashboard", status_code=307)


@api.get("/dashboard.html")
def dashboard_html_page() -> RedirectResponse:
    return RedirectResponse(url="/dashboard", status_code=307)


@api.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@api.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "campex-logo-oficial.png", media_type="image/png")


@api.post("/auth/login")
def post_login(payload: LoginIn, response: Response) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        user = authenticate(connection, payload.email, payload.senha)
        if user is None:
            raise HTTPException(status_code=401, detail="E-mail ou senha invalidos.")
        token = create_session(connection, user["id"])
    response.set_cookie("campex_session", token, httponly=True, samesite="lax")
    return {"user": user}


@api.post("/auth/logout")
def post_logout(request: Request, response: Response) -> dict[str, object]:
    token = request.cookies.get("campex_session")
    if token:
        with connect() as connection:
            init_db(connection)
            delete_session(connection, token)
    response.delete_cookie("campex_session")
    return {"ok": True}


@api.get("/auth/me")
def get_me(request: Request) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
    return {"user": user}


@api.get("/auth/status")
def get_auth_status(request: Request) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        user = get_request_user(request, connection)
        has_users = users_exist(connection)
    if user is not None:
        return {"authenticated": True, "bootstrap": False, "user": user}
    return {"authenticated": False, "bootstrap": not has_users, "user": None}


@api.post("/auth/users")
def post_user(payload: UserIn, request: Request) -> dict[str, str]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_role(user, ADMIN_ROLES)
        cliente_id = payload.cliente_id if user["role"] == "admin_campex" else user.get("cliente_id")
        return {"id": create_user(connection, payload.email, payload.senha, payload.role, cliente_id, payload.nome)}


@api.post("/auth/reset-password")
def post_reset_password(payload: ResetPasswordIn, request: Request) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_role(user, ADMIN_ROLES)
        return {"updated": update_user_password(connection, payload.email, payload.nova_senha)}


@api.get("/system/health")
def get_system_health() -> dict[str, object]:
    return health_snapshot()


@api.get("/pilot/checklist")
def get_pilot_checklist() -> dict[str, object]:
    return acceptance_checklist()


@api.get("/clientes")
def get_clientes(request: Request) -> list[dict[str, Any]]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        return listar_por_cliente(connection, "clientes", tenant_filter(user))


@api.post("/clientes")
def post_cliente(payload: ClienteIn, request: Request) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_role(user, ADMIN_ROLES)
        if user["role"] != "admin_campex" and user.get("cliente_id"):
            raise HTTPException(status_code=403, detail="Somente admin Campex cria novos clientes.")
        cliente_id = criar_cliente(connection, payload.nome, payload.status, payload.documento)
        return listar_por_cliente(connection, "clientes", cliente_id)[0]


@api.post("/unidades")
def post_unidade(payload: UnidadeIn, request: Request) -> dict[str, str]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_role(user, ADMIN_ROLES)
        cliente_id = effective_cliente_id(user, payload.cliente_id)
        if cliente_id is None:
            raise HTTPException(status_code=400, detail="Informe o cliente da unidade.")
        return {"id": criar_unidade(connection, cliente_id, payload.nome, payload.localizacao, payload.timezone)}


@api.get("/unidades")
def get_unidades(request: Request, cliente_id: Optional[str] = None) -> list[dict[str, Any]]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        effective = effective_cliente_id(user, cliente_id)
        return listar_por_cliente(connection, "unidades", effective)


@api.get("/auth/users")
def get_users(request: Request) -> list[dict[str, Any]]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_role(user, ADMIN_ROLES)
        tenant = tenant_filter(user)
        if tenant:
            rows = connection.execute("SELECT id, cliente_id, nome, email, role, ativo, criado_em FROM users WHERE cliente_id = ? ORDER BY criado_em DESC", (tenant,)).fetchall()
        else:
            rows = connection.execute("SELECT id, cliente_id, nome, email, role, ativo, criado_em FROM users ORDER BY criado_em DESC").fetchall()
        return [dict(row) for row in rows]


@api.post("/dispositivos")
def post_dispositivo(payload: DispositivoIn) -> dict[str, str]:
    with connect() as connection:
        init_db(connection)
        return {"id": criar_dispositivo(connection, payload.unidade_id, payload.nome, payload.status)}


@api.post("/cameras")
def post_camera(payload: CameraIn) -> dict[str, str]:
    with connect() as connection:
        init_db(connection)
        cliente_id, unidade_id = default_cliente_unidade(connection, payload.cliente_id, payload.unidade_id)
        return {"id": criar_camera(
            connection,
            unidade_id,
            payload.nome,
            payload.dispositivo_id,
            payload.config_ref,
            payload.status,
            cliente_id,
            payload.edge_id,
            payload.source_type,
            payload.secure_ref,
        )}


@api.post("/cameras/rtsp")
def post_camera_rtsp(payload: CameraRtspIn, request: Request) -> dict[str, object]:
    try:
        rtsp = build_rtsp_url(
            host=payload.host,
            port=payload.porta_rtsp,
            path=payload.caminho_rtsp,
            username=payload.usuario,
            password=payload.senha,
            full_url=payload.rtsp_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    test_result = None
    status = "nao_testada"
    if payload.testar_conexao:
        test_result = test_rtsp_connection(rtsp)
        status = "online" if test_result["compativel"] else "offline"
    with connect() as connection:
        init_db(connection)
        user = get_request_user(request, connection)
        cliente_hint = payload.cliente_id
        if user and user["role"] != "admin_campex":
            cliente_hint = user.get("cliente_id")
        cliente_id, unidade_id = default_cliente_unidade(connection, cliente_hint, payload.unidade_id)
        camera_id = criar_camera(
            connection,
            unidade_id,
            payload.nome,
            payload.dispositivo_id,
            rtsp.safe_url,
            status=status,
            cliente_id=cliente_id,
            edge_id=payload.edge_id,
            source_type="rtsp",
            secure_ref=rtsp.safe_url,
            rtsp_host=rtsp.host,
            rtsp_port=rtsp.port,
            rtsp_path=rtsp.path,
            rtsp_username=rtsp.username,
            rtsp_password=rtsp.password,
            canal=payload.canal,
            ativa=payload.ativa,
        )
        if test_result:
            atualizar_camera_video_info(
                connection,
                camera_id,
                resolucao=str(test_result.get("resolucao")) if test_result.get("resolucao") else None,
                fps=float(test_result["fps"]) if test_result.get("fps") is not None else None,
            )
        camera = obter_camera(connection, camera_id)
    return {"id": camera_id, "camera": camera, "teste": test_result}


@api.post("/cameras/test-connection")
def post_camera_test_connection(payload: CameraRtspTestIn) -> dict[str, object]:
    try:
        rtsp = build_rtsp_url(
            host=payload.host,
            port=payload.porta_rtsp,
            path=payload.caminho_rtsp,
            username=payload.usuario,
            password=payload.senha,
            full_url=payload.rtsp_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return test_rtsp_connection(rtsp, timeout_seconds=payload.timeout_seconds)


@api.post("/live-view/start")
def post_live_view_start(payload: LiveViewStartIn) -> dict[str, object]:
    camera_id = payload.camera_id
    camera_name = payload.nome
    if camera_id and not payload.rtsp_url and not payload.host:
        with connect() as connection:
            init_db(connection)
            camera = obter_camera(connection, camera_id, include_secret=True)
        if camera is None:
            raise HTTPException(status_code=404, detail="Câmera não encontrada.")
        camera_name = str(camera.get("nome") or payload.nome)
        try:
            rtsp = build_rtsp_url(
                host=camera.get("rtsp_host"),
                port=int(camera.get("rtsp_port") or 554),
                path=camera.get("rtsp_path"),
                username=camera.get("rtsp_username"),
                password=camera.get("rtsp_password"),
                full_url=None,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    else:
        try:
            rtsp = build_rtsp_url(
                host=payload.host,
                port=payload.porta_rtsp,
                path=payload.caminho_rtsp,
                username=payload.usuario,
                password=payload.senha,
                full_url=payload.rtsp_url,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    session_id = "live_" + hashlib.sha256(f"{camera_id or camera_name}|{rtsp.safe_url}".encode()).hexdigest()[:16]
    live_view_sessions[session_id] = {
        "nome": camera_name,
        "source": rtsp.url,
        "safe_url": rtsp.safe_url,
        "camera_id": camera_id,
        "stream_id": camera_id or session_id,
        "created_at": time.time(),
    }
    stream_id = str(camera_id or session_id)
    stream = live_streams.get_or_create(stream_id, rtsp.url)
    stream.start()
    status = stream.public_status()
    return {
        "session_id": session_id,
        "stream_id": stream_id,
        "nome": camera_name,
        "status": status,
    }


def live_view_stream_id(session_id: str) -> str:
    session = live_view_sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Live View não encontrada.")
    return str(session.get("stream_id") or session.get("camera_id") or session_id)


@api.get("/live-view/{session_id}/status")
def get_live_view_status(session_id: str) -> dict[str, object]:
    session = live_view_sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Live View não encontrada.")
    stream = live_streams.get(live_view_stream_id(session_id))
    status = stream.public_status() if stream else {"status": "offline", "width": None, "height": None, "fps": None}
    ops = live_view_official_ops(session, stream)
    return {"session_id": session_id, "nome": session["nome"], **status, "ops": ops}


@api.get("/live-view/{session_id}/stream")
def get_live_view_stream(session_id: str) -> StreamingResponse:
    session = live_view_sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Live View não encontrada.")
    stream = live_streams.get_or_create(live_view_stream_id(session_id), str(session["source"]))
    stream.start()
    return StreamingResponse(stream.frames(), media_type="multipart/x-mixed-replace; boundary=frame")


def live_view_stream_for(session_id: str):
    session = live_view_sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Live View não encontrada.")
    stream = live_streams.get_or_create(live_view_stream_id(session_id), str(session["source"]))
    return session, stream


def live_view_official_ops(session: dict[str, object] | None, stream) -> dict[str, object]:
    camera_id = session.get("camera_id") if session else None
    monitor = None
    if camera_id:
        with connect() as connection:
            init_db(connection)
            monitors = listar_machine_monitors_camera(connection, str(camera_id))
            monitor = monitors[0] if monitors else None
    status = stream.public_status() if stream else {}
    observation = status.get("observation") or {}
    machine_state = status.get("machine_state")
    if machine_state == "ACTIVE":
        compat_state = "ATIVA"
    elif machine_state == "STOPPED":
        compat_state = "PARADA"
    elif machine_state == "UNKNOWN":
        compat_state = "UNKNOWN"
    else:
        compat_state = "NAO_CONFIGURADA"
    return {
        "ai_enabled": (status.get("ai_status") or "") in {"ativa", "carregando"},
        "ai_status": status.get("ai_status", "inativa"),
        "people_count": status.get("people_count", 0),
        "machine_state": compat_state,
        "machine_motion": status.get("machine_motion"),
        "machine_threshold": status.get("machine_threshold"),
        "machine_reason": status.get("machine_reason"),
        "machine_seconds_in_state": status.get("machine_seconds_in_state"),
        "analysis_status": status.get("machine_analysis_status"),
        "analysis_error": status.get("machine_analysis_error"),
        "raw_activity_score": status.get("machine_raw_activity_score"),
        "smoothed_activity_score": status.get("machine_motion"),
        "frames_analyzed": status.get("machine_frames_analyzed"),
        "roi": {
            "width": status.get("machine_roi_width"),
            "height": status.get("machine_roi_height"),
        },
        "operator_present": status.get("machine_operator_present", False),
        "operator_people_count": 1 if status.get("machine_operator_present") else 0,
        "visual_confidence": status.get("machine_confidence") or observation.get("machine_confidence") or 0,
        "calibration_status": (status.get("calibration") or {}).get("calibration_result") or (monitor or {}).get("calibration_result") or "não calibrada",
        "baselines": {
            "active": (status.get("calibration") or {}).get("active_baseline") or (monitor or {}).get("active_baseline"),
            "stopped": (status.get("calibration") or {}).get("stopped_baseline") or (monitor or {}).get("stopped_baseline"),
        },
        "separation_score": (status.get("calibration") or {}).get("separation_score") or (monitor or {}).get("separation_score"),
        "machine": {
            "id": monitor.get("id"),
            "nome": monitor.get("nome"),
            "machine_polygon": monitor.get("machine_polygon"),
            "operator_polygon": monitor.get("operator_polygon"),
            "threshold": monitor.get("motion_threshold"),
            "calibrated": monitor.get("calibration_result") == "READY",
        } if monitor else None,
        "event_id": status.get("machine_event_id"),
        "observation": observation,
    }


def expanded_live_view_polygon(points: list[dict[str, float]], margin: float = 0.08) -> list[dict[str, float]]:
    normalized = normalize_points(points)
    xs = [float(point["x"]) for point in normalized]
    ys = [float(point["y"]) for point in normalized]
    return [
        {"x": max(0.0, min(xs) - margin), "y": max(0.0, min(ys) - margin)},
        {"x": min(1.0, max(xs) + margin), "y": max(0.0, min(ys) - margin)},
        {"x": min(1.0, max(xs) + margin), "y": min(1.0, max(ys) + margin)},
        {"x": max(0.0, min(xs) - margin), "y": min(1.0, max(ys) + margin)},
    ]


def persist_live_view_machine_config(session_id: str, machine: dict[str, object], nome: str | None = None) -> dict[str, object] | None:
    session = live_view_sessions.get(session_id)
    camera_id = session.get("camera_id") if session else None
    if not camera_id:
        return None
    with connect() as connection:
        init_db(connection)
        camera = obter_camera(connection, str(camera_id))
        if camera is None:
            return None
        monitors = listar_machine_monitors_camera(connection, str(camera_id))
        if monitors:
            return atualizar_machine_monitor(
                connection,
                monitors[0]["id"],
                nome=nome or machine["nome"],
                machine_polygon=machine["machine_polygon"],
                operator_polygon=machine["operator_polygon"],
                motion_threshold=machine.get("threshold"),
            )
        monitor_id = criar_machine_monitor(
            connection,
            str(camera.get("cliente_id") or ""),
            str(camera.get("unidade_id")),
            str(camera_id),
            nome or machine["nome"],
            machine["machine_polygon"],
            machine["operator_polygon"],
            True,
        )
        return obter_machine_monitor(connection, monitor_id)


@api.post("/live-view/{session_id}/ai/start")
def post_live_view_ai_start(session_id: str) -> dict[str, object]:
    session, stream = live_view_stream_for(session_id)
    stream.set_analysis(True)
    return {"ai_enabled": True, **live_view_official_ops(session, stream)}


@api.post("/live-view/{session_id}/ai/stop")
def post_live_view_ai_stop(session_id: str) -> dict[str, object]:
    session, stream = live_view_stream_for(session_id)
    stream.set_analysis(False)
    return {"ai_enabled": False, **live_view_official_ops(session, stream)}


@api.post("/live-view/{session_id}/machine")
def post_live_view_machine(session_id: str, payload: LiveViewMachineIn) -> dict[str, object]:
    session, stream = live_view_stream_for(session_id)
    machine_polygon = normalize_points([point.model_dump() for point in payload.machine_polygon])
    operator_polygon = normalize_points([point.model_dump() for point in payload.operator_polygon]) if payload.operator_polygon else expanded_live_view_polygon(machine_polygon)
    machine = {
        "nome": payload.nome,
        "machine_polygon": machine_polygon,
        "operator_polygon": operator_polygon,
        "threshold": None,
    }
    monitor = persist_live_view_machine_config(session_id, machine, payload.nome)
    stream._machine_engines.pop(monitor["id"], None) if monitor else None
    state = live_view_official_ops(session, stream)
    state["machine"] = {
        "id": monitor.get("id") if monitor else None,
        "nome": payload.nome,
        "machine_polygon": machine_polygon,
        "operator_polygon": operator_polygon,
        "threshold": monitor.get("motion_threshold") if monitor else None,
        "calibrated": False,
    }
    state["machine_state"] = "UNKNOWN" if monitor else "NAO_CONFIGURADA"
    return state


@api.post("/live-view/{session_id}/operator-zone")
def post_live_view_operator_zone(session_id: str, payload: LiveViewOperatorZoneIn) -> dict[str, object]:
    session, stream = live_view_stream_for(session_id)
    camera_id = session.get("camera_id") if session else None
    if not camera_id:
        raise HTTPException(status_code=400, detail="Zona do operador exige câmera persistente.")
    operator_polygon = normalize_points([point.model_dump() for point in payload.operator_polygon])
    with connect() as connection:
        init_db(connection)
        monitors = listar_machine_monitors_camera(connection, str(camera_id))
        if not monitors:
            raise HTTPException(status_code=400, detail="Configure a máquina antes da zona do operador.")
        monitor = atualizar_machine_monitor(connection, monitors[0]["id"], operator_polygon=operator_polygon)
    stream._machine_engines.pop(monitor["id"], None) if monitor else None
    return live_view_official_ops(session, stream)


@api.post("/live-view/{session_id}/machine/calibrate-active")
def post_live_view_machine_calibrate_active(session_id: str) -> dict[str, object]:
    session, stream = live_view_stream_for(session_id)
    state = live_view_official_ops(session, stream)
    state["calibration_status"] = "use_assisted_calibration_endpoint"
    state["message"] = "Use POST /machine-monitors/{id}/calibration/active/start para calibração assistida real."
    return state


@api.delete("/live-view/{session_id}/machine")
def delete_live_view_machine(session_id: str) -> dict[str, object]:
    session = live_view_sessions.get(session_id)
    camera_id = session.get("camera_id") if session else None
    if camera_id:
        with connect() as connection:
            init_db(connection)
            for monitor in listar_machine_monitors_camera(connection, str(camera_id)):
                excluir_machine_monitor(connection, monitor["id"])
    stream = live_streams.get(live_view_stream_id(session_id))
    if stream:
        stream._machine_engines.clear()
    return {"machine": None, "machine_state": "NAO_CONFIGURADA", "calibration_status": "não calibrada"}


@api.post("/live-view/{session_id}/stop")
def post_live_view_stop(session_id: str) -> dict[str, object]:
    session = live_view_sessions.pop(session_id, None)
    stream_id = str(session.get("stream_id") or session_id) if session else session_id
    stopped = False if session and session.get("camera_id") else live_streams.stop(stream_id)
    return {"session_id": session_id, "status": "offline", "stopped": stopped}


@api.post("/cameras/{camera_id}/test-connection")
def post_existing_camera_test_connection(camera_id: str) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        camera = obter_camera(connection, camera_id, include_secret=True)
    if camera is None:
        return {"compativel": False, "motivo_erro": "Camera nao encontrada."}
    source = camera.get("config_ref")
    if not source:
        return {"compativel": False, "motivo_erro": "Camera sem fonte configurada."}
    rtsp = build_rtsp_url(full_url=str(source))
    return test_rtsp_connection(rtsp)


@api.post("/cameras/{camera_id}/password")
def post_camera_password(camera_id: str, payload: CameraPasswordIn, request: Request) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_role(user, ADMIN_ROLES)
        camera = obter_camera(connection, camera_id)
        if camera is None:
            raise HTTPException(status_code=404, detail="Camera nao encontrada.")
        if tenant_filter(user) and camera.get("cliente_id") != tenant_filter(user):
            raise HTTPException(status_code=403, detail="Camera de outro cliente.")
        return {"updated": alterar_senha_camera(connection, camera_id, payload.senha)}


def load_camera_source(camera_id: str) -> tuple[dict[str, Any], str]:
    with connect() as connection:
        init_db(connection)
        camera = obter_camera(connection, camera_id, include_secret=True)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera nao encontrada.")
    if os.getenv("CAMPEX_VIDEO_SOURCE_MODE", "").strip().lower() == "file":
        video_file = os.getenv("CAMPEX_VIDEO_FILE", "").strip()
        if not video_file:
            raise HTTPException(status_code=400, detail="CAMPEX_VIDEO_SOURCE_MODE=file exige CAMPEX_VIDEO_FILE.")
        if not Path(video_file).exists():
            raise HTTPException(status_code=400, detail="Arquivo de video de teste nao encontrado.")
        return camera, video_file
    source = camera.get("config_ref")
    if camera.get("rtsp_host"):
        source = build_rtsp_url(
            host=str(camera.get("rtsp_host")),
            port=int(camera.get("rtsp_port") or 554),
            path=camera.get("rtsp_path"),
            username=camera.get("rtsp_username"),
            password=camera.get("rtsp_password"),
        ).url
    if not source:
        raise HTTPException(status_code=400, detail="Camera sem fonte configurada.")
    return camera, str(source)


@api.post("/cameras/{camera_id}/start")
def post_camera_start(camera_id: str) -> dict[str, object]:
    _camera, source = load_camera_source(camera_id)
    stream = live_streams.get_or_create(camera_id, source)
    stream.start()
    return stream.public_status()


@api.post("/cameras/{camera_id}/stop")
def post_camera_stop(camera_id: str) -> dict[str, object]:
    stopped = live_streams.stop(camera_id)
    return {"camera_id": camera_id, "status": "offline", "stopped": stopped}


@api.get("/cameras/{camera_id}/stream")
def get_camera_stream(camera_id: str) -> StreamingResponse:
    _camera, source = load_camera_source(camera_id)
    stream = live_streams.get_or_create(camera_id, source)
    stream.start()
    return StreamingResponse(
        stream.frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@api.get("/cameras/{camera_id}/status")
def get_camera_live_status(camera_id: str) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        camera = obter_camera(connection, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera nao encontrada.")
    stream = live_streams.get(camera_id)
    if stream is None:
        return {
            "camera_id": camera_id,
            "status": "offline",
            "width": None,
            "height": None,
            "fps": None,
            "last_frame_at": camera.get("ultimo_frame"),
            "error": None,
            "viewers": 0,
            "reconnect_attempts": camera.get("reconexoes") or 0,
        }
    return stream.public_status()


@api.get("/live-streams/status")
def get_live_streams_status() -> dict[str, object]:
    streams = live_streams.statuses()
    return {
        "active_streams": len(streams),
        "streams": streams,
        "cpu_percent": psutil.cpu_percent(interval=None),
        "memory_percent": psutil.virtual_memory().percent,
    }


@api.get("/people-zones/summary")
def get_people_zones_summary(camera_id: Optional[str] = None) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        cameras = listar(connection, "cameras")
        if camera_id:
            cameras = [camera for camera in cameras if camera["id"] == camera_id]
        camera_ids = {camera["id"] for camera in cameras}
        zones = []
        events = []
        for current_camera_id in camera_ids:
            zones.extend(listar_areas_camera(connection, current_camera_id))
            events.extend(listar_eventos_filtrados(connection, camera_id=current_camera_id))
    live = {status["camera_id"]: status for status in live_streams.statuses()}
    workstation_zones = [zone for zone in zones if zone.get("tipo") == "workstation"]
    zone_states = []
    for zone in zones:
        status = live.get(zone["camera_id"], {})
        current = next((item for item in status.get("zones", []) if item.get("area_id") == zone["id"]), {})
        zone_events = [event for event in events if event.get("area_id") == zone["id"]]
        unattended = [event for event in zone_events if event.get("tipo") == "workstation_unattended"]
        unattended_seconds = sum(float(event.get("duracao") or 0) for event in unattended if event.get("duracao") is not None)
        active_unattended = next((event for event in unattended if event.get("status") == "open"), None)
        zone_states.append({
            "id": zone["id"],
            "camera_id": zone["camera_id"],
            "nome": zone["nome"],
            "tipo": zone["tipo"],
            "ativa": zone["ativa"],
            "ocupacao_atual": current.get("pessoas_dentro", 0),
            "estado": current.get("estado", "sem_dados"),
            "evento_ativo": current.get("event_active", False),
            "evento_id": current.get("event_id"),
            "colaborador_turno": zone.get("collaborator_name"),
            "tolerancia_ausencia": zone.get("absence_tolerance_seconds"),
            "ausencias": len(unattended),
            "tempo_total_desocupado": unattended_seconds,
            "inicio_desocupacao": active_unattended.get("inicio") if active_unattended else None,
        })
    people_visible = sum(int(status.get("people_count") or 0) for status in live.values())
    return {
        "catalog": [
            "restricted_zone_occupied",
            "workstation_unattended",
            "minimum_staff_not_met",
            "shift_start_incomplete",
            "excessive_zone_dwell",
            "after_hours_presence",
        ],
        "cameras": cameras,
        "zones": zone_states,
        "workstations": [zone for zone in zone_states if zone["tipo"] == "workstation"],
        "expected_staff": len([zone for zone in workstation_zones if zone.get("ativa")]),
        "identified_people": people_visible,
        "active_events": [event for event in events if event.get("status") == "open"],
        "events": events[:100],
    }


@api.get("/local-diagnostics")
def get_local_diagnostics() -> dict[str, object]:
    disk = psutil.disk_usage(str(ROOT))
    with connect() as connection:
        init_db(connection)
        zones = connection.execute("SELECT COUNT(*) AS total FROM monitored_areas WHERE ativa = 1").fetchone()["total"]
        rules = connection.execute("SELECT COUNT(*) AS total FROM regras WHERE ativo = 1").fetchone()["total"]
        open_events = connection.execute("SELECT COUNT(*) AS total FROM eventos WHERE status = 'open'").fetchone()["total"]
        outbox = connection.execute("SELECT COUNT(*) AS total FROM sync_outbox WHERE status IN ('pending', 'failed')").fetchone()["total"]
        last_delivery = connection.execute("SELECT status, last_attempt_at, sent_at, erro FROM alert_deliveries ORDER BY criado_em DESC LIMIT 1").fetchone()
    streams = live_streams.statuses()
    return {
        "sqlite": "ok",
        "cameras_online": len([stream for stream in streams if stream.get("status") == "online"]),
        "ultimo_frame": max([str(stream.get("last_frame_at") or "") for stream in streams], default=None),
        "ia_ativa": len([stream for stream in streams if stream.get("ai_status") == "ativa"]),
        "zonas_ativas": zones,
        "regras_ativas": rules,
        "eventos_abertos": open_events,
        "outbox_pendente": outbox,
        "email_mode": os.getenv("CAMPEX_EMAIL_MODE", "console"),
        "ultima_entrega": dict(last_delivery) if last_delivery else None,
        "disco_livre_percentual": round(100 - disk.percent, 2),
    }


def test_events_enabled() -> bool:
    return os.getenv("CAMPEX_ENABLE_TEST_EVENT", "").lower() in {"1", "true", "sim", "yes"} and os.getenv("CAMPEX_ENV", "development").lower() != "production"


def create_test_evidence(camera_id: str, area_id: str, event_type: str) -> str:
    import cv2
    import numpy as np

    folder = ROOT / "data" / "evidence" / "test" / camera_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{int(time.time() * 1000)}_{event_type}_{area_id}.jpg"
    image = np.zeros((360, 640, 3), dtype=np.uint8)
    cv2.putText(image, "Campex - evidencia de teste", (24, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(image, event_type, (24, 105), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (80, 170, 255), 2, cv2.LINE_AA)
    if not cv2.imwrite(str(path), image):
        raise HTTPException(status_code=500, detail="Nao foi possivel salvar evidencia de teste.")
    return str(path.relative_to(ROOT))


@api.post("/dev/test-event")
def post_dev_test_event(payload: DevTestEventIn) -> dict[str, object]:
    if not test_events_enabled():
        raise HTTPException(status_code=404, detail="Ocorrencia de teste indisponivel neste ambiente.")
    with connect() as connection:
        init_db(connection)
        camera = obter_camera(connection, payload.camera_id) if payload.camera_id else None
        if camera is None:
            cameras = listar(connection, "cameras")
            camera = cameras[0] if cameras else None
        if camera is None:
            raise HTTPException(status_code=400, detail="Cadastre uma camera antes de gerar ocorrencia de teste.")
        areas = listar_areas_camera(connection, camera["id"])
        area = next((item for item in areas if item["id"] == payload.area_id), None) if payload.area_id else (areas[0] if areas else None)
        if area is None:
            raise HTTPException(status_code=400, detail="Cadastre uma zona antes de gerar ocorrencia de teste.")
        rules = listar_regras(connection, camera_id=camera["id"])
        rule = next((item for item in rules if item.get("regiao_id") == area["id"] and item.get("tipo_evento") == payload.event_type), None)
        evidence_path = create_test_evidence(camera["id"], area["id"], payload.event_type)
        event_id = criar_ocorrencia_zona(
            connection,
            cliente_id=str(area.get("cliente_id") or camera.get("cliente_id") or ""),
            unidade_id=str(area.get("unidade_id") or camera.get("unidade_id") or ""),
            camera_id=camera["id"],
            area_id=area["id"],
            regra_id=rule["id"] if rule else None,
            tipo=payload.event_type,
            inicio=now_iso(),
            quantidade_inicial=0,
            quantidade_maxima=0,
            track_ids=[],
            confianca=1.0,
            midia_path=evidence_path,
            severidade=str(rule.get("severidade") if rule else "high"),
            metadata={"is_test": True, "source": "dev_test_event", "zone_name": area["nome"], "zone_type": area["tipo"]},
        )
    enqueue_event_alert(event_id)
    return {"event_id": event_id, "status": "created", "is_test": True, "evidence_path": evidence_path}


@api.post("/cameras/{camera_id}/analysis/start")
def post_camera_analysis_start(camera_id: str) -> dict[str, object]:
    _camera, source = load_camera_source(camera_id)
    stream = live_streams.get_or_create(camera_id, source)
    stream.start()
    return stream.set_analysis(True)


@api.post("/cameras/{camera_id}/analysis/stop")
def post_camera_analysis_stop(camera_id: str) -> dict[str, object]:
    stream = live_streams.get(camera_id)
    if stream is None:
        return {
            "camera_id": camera_id,
            "status": "offline",
            "ai_status": "inativa",
            "people_count": 0,
        }
    return stream.set_analysis(False)


@api.get("/cameras/{camera_id}/areas")
def get_camera_areas(camera_id: str, request: Request) -> list[dict[str, Any]]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        camera = obter_camera(connection, camera_id)
        if camera is None:
            raise HTTPException(status_code=404, detail="Camera nao encontrada.")
        if tenant_filter(user) and camera.get("cliente_id") != tenant_filter(user):
            raise HTTPException(status_code=403, detail="Camera de outro cliente.")
        return listar_areas_camera(connection, camera_id)


@api.post("/cameras/{camera_id}/areas", status_code=status.HTTP_201_CREATED)
def post_camera_area(camera_id: str, payload: AreaIn) -> dict[str, Any]:
    try:
        zone_name = payload.resolved_name()
        zone_type = payload.resolved_type()
        zone_active = payload.resolved_active()
        points = normalize_points([point.model_dump() for point in payload.resolved_points()])
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    allowed_types = {"workstation", "restricted_area", "dwell_area", "machine_region", "operator_zone", "restricted_zone", "work_area"}
    if zone_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Tipo de zona invalido para People & Zones V1.")
    try:
        with connect() as connection:
            init_db(connection)
            camera = obter_camera(connection, camera_id)
            if camera is None:
                raise HTTPException(status_code=404, detail="Camera nao encontrada.")
            area_id = criar_area_monitorada(
                connection,
                camera_id,
                zone_name,
                points,
                zone_type,
                zone_active,
                metadata=payload.metadata,
                collaborator_name=payload.collaborator_name,
                expected_start=payload.expected_start,
                expected_end=payload.expected_end,
                absence_tolerance_seconds=payload.absence_tolerance_seconds,
                dwell_limit_seconds=payload.dwell_limit_seconds,
                expected_min_people=payload.expected_min_people,
                machine_id=payload.machine_id,
            )
            event_by_type = {
                "restricted_area": "restricted_zone_occupied",
                "restricted_zone": "restricted_zone_occupied",
                "workstation": "workstation_unattended",
                "operator_zone": "workstation_unattended",
                "dwell_area": "excessive_zone_dwell",
                "work_area": "excessive_zone_dwell",
            }
            event_type = event_by_type.get(zone_type)
            if event_type:
                minimum_seconds = (
                    payload.absence_tolerance_seconds
                    if zone_type == "workstation"
                    else payload.dwell_limit_seconds
                    if zone_type == "dwell_area"
                    else (payload.metadata or {}).get("minimum_seconds", 5)
                )
                criar_regra(
                    connection,
                    camera_id,
                    event_type,
                    tempo_minimo=float(minimum_seconds or 0),
                    ativo=zone_active,
                    nome=f"{zone_name} · {event_type}",
                    cliente_id=str(camera.get("cliente_id") or ""),
                    unidade_id=str(camera.get("unidade_id") or ""),
                    entidade="person",
                    regiao_id=area_id,
                    condicao={"type": "absence_in_zone" if event_type == "workstation_unattended" else "presence_in_zone", "zone_id": area_id},
                    severidade=(payload.metadata or {}).get("severidade", "high" if event_type in {"restricted_zone_occupied", "workstation_unattended"} else "medium"),
                    cooldown_seconds=float((payload.metadata or {}).get("cooldown_seconds", 60)),
                    alerta_inicio=True,
                    alerta_normalizacao=True,
                )
            areas = listar_areas_camera(connection, camera_id)
        return next(area for area in areas if area["id"] == area_id)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Falha ao persistir zona para camera %s", camera_id)
        raise HTTPException(status_code=500, detail="Nao foi possivel salvar a zona. A configuracao nao foi alterada.") from exc


@api.patch("/areas/{area_id}")
def patch_area(area_id: str, payload: AreaPatchIn) -> dict[str, Any]:
    points = None
    if payload.pontos is not None:
        try:
            points = normalize_points([point.model_dump() for point in payload.pontos])
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    with connect() as connection:
        init_db(connection)
        area = atualizar_area_monitorada(
            connection,
            area_id,
            payload.nome,
            points,
            tipo=payload.tipo,
            ativa=payload.ativa,
            metadata=payload.metadata,
            collaborator_name=payload.collaborator_name,
            expected_start=payload.expected_start,
            expected_end=payload.expected_end,
            absence_tolerance_seconds=payload.absence_tolerance_seconds,
            dwell_limit_seconds=payload.dwell_limit_seconds,
            expected_min_people=payload.expected_min_people,
            machine_id=payload.machine_id,
        )
    if area is None:
        raise HTTPException(status_code=404, detail="Area nao encontrada.")
    return area


@api.delete("/areas/{area_id}")
def delete_area(area_id: str) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        deleted = excluir_area_monitorada(connection, area_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Area nao encontrada.")
    return {"id": area_id, "deleted": True}


@api.post("/areas/{area_id}/activate")
def post_area_activate(area_id: str) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        area = atualizar_area_monitorada(connection, area_id, ativa=True)
    if area is None:
        raise HTTPException(status_code=404, detail="Area nao encontrada.")
    return area


@api.post("/areas/{area_id}/deactivate")
def post_area_deactivate(area_id: str) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        area = atualizar_area_monitorada(connection, area_id, ativa=False)
    if area is None:
        raise HTTPException(status_code=404, detail="Area nao encontrada.")
    return area


@api.get("/cameras/{camera_id}/machine-monitors")
def get_machine_monitors(camera_id: str, request: Request) -> list[dict[str, Any]]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        camera = obter_camera(connection, camera_id)
        if camera is None:
            raise HTTPException(status_code=404, detail="Camera nao encontrada.")
        if tenant_filter(user) and camera.get("cliente_id") != tenant_filter(user):
            raise HTTPException(status_code=403, detail="Camera de outro cliente.")
        return listar_machine_monitors_camera(connection, camera_id)


@api.post("/cameras/{camera_id}/machine-monitors")
def post_machine_monitor(camera_id: str, payload: MachineMonitorIn, request: Request) -> dict[str, Any]:
    machine_points = normalize_points([point.model_dump() for point in payload.machine_polygon])
    operator_points = normalize_points([point.model_dump() for point in payload.operator_polygon])
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        camera = obter_camera(connection, camera_id)
        if camera is None:
            raise HTTPException(status_code=404, detail="Camera nao encontrada.")
        if tenant_filter(user) and camera.get("cliente_id") != tenant_filter(user):
            raise HTTPException(status_code=403, detail="Camera de outro cliente.")
        client_id = str(camera.get("cliente_id") or tenant_filter(user) or "")
        unit_id = str(camera.get("unidade_id"))
        monitor_id = criar_machine_monitor(
            connection,
            client_id,
            unit_id,
            camera_id,
            payload.nome,
            machine_points,
            operator_points,
            payload.ativo,
            payload.motion_sensitivity,
            payload.stop_seconds,
            payload.recovery_seconds,
            payload.replay_pre_seconds,
            payload.replay_post_seconds,
            payload.operator_absence_seconds,
            payload.stopped_with_operator_seconds,
            payload.microstop_window_seconds,
            payload.microstop_limit,
            payload.loss_model,
            payload.loss_per_minute,
            payload.units_per_minute,
            payload.margin_per_unit,
            normalize_points([point.model_dump() for point in payload.indicator_polygon]) if payload.indicator_polygon else None,
        )
        return obter_machine_monitor(connection, monitor_id)


@api.patch("/machine-monitors/{monitor_id}")
def patch_machine_monitor(monitor_id: str, payload: MachineMonitorPatchIn, request: Request) -> dict[str, Any]:
    machine_points = normalize_points([point.model_dump() for point in payload.machine_polygon]) if payload.machine_polygon else None
    operator_points = normalize_points([point.model_dump() for point in payload.operator_polygon]) if payload.operator_polygon else None
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        monitor = obter_machine_monitor(connection, monitor_id)
        if monitor is None:
            raise HTTPException(status_code=404, detail="Monitor nao encontrado.")
        if tenant_filter(user) and monitor.get("client_id") != tenant_filter(user):
            raise HTTPException(status_code=403, detail="Monitor de outro cliente.")
        updated = atualizar_machine_monitor(
            connection,
            monitor_id,
            nome=payload.nome,
            machine_polygon=machine_points,
            operator_polygon=operator_points,
            ativo=payload.ativo,
            motion_sensitivity=payload.motion_sensitivity,
            motion_threshold=payload.motion_threshold,
            stop_seconds=payload.stop_seconds,
            recovery_seconds=payload.recovery_seconds,
            operator_absence_seconds=payload.operator_absence_seconds,
            stopped_with_operator_seconds=payload.stopped_with_operator_seconds,
            microstop_window_seconds=payload.microstop_window_seconds,
            microstop_limit=payload.microstop_limit,
            loss_model=payload.loss_model,
            loss_per_minute=payload.loss_per_minute,
            units_per_minute=payload.units_per_minute,
            margin_per_unit=payload.margin_per_unit,
            indicator_polygon=normalize_points([point.model_dump() for point in payload.indicator_polygon]) if payload.indicator_polygon else None,
        )
    return updated


@api.delete("/machine-monitors/{monitor_id}")
def delete_machine_monitor(monitor_id: str, request: Request) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        monitor = obter_machine_monitor(connection, monitor_id)
        if monitor is None:
            raise HTTPException(status_code=404, detail="Monitor nao encontrado.")
        if tenant_filter(user) and monitor.get("client_id") != tenant_filter(user):
            raise HTTPException(status_code=403, detail="Monitor de outro cliente.")
        return {"id": monitor_id, "deleted": excluir_machine_monitor(connection, monitor_id)}


@api.post("/machine-monitors/{monitor_id}/activate")
def post_machine_monitor_activate(monitor_id: str, request: Request) -> dict[str, Any]:
    return patch_machine_monitor(monitor_id, MachineMonitorPatchIn(ativo=True), request)


@api.post("/machine-monitors/{monitor_id}/deactivate")
def post_machine_monitor_deactivate(monitor_id: str, request: Request) -> dict[str, Any]:
    return patch_machine_monitor(monitor_id, MachineMonitorPatchIn(ativo=False), request)


@api.post("/machine-monitors/{monitor_id}/calibrate")
def post_machine_monitor_calibrate(monitor_id: str, payload: MachineCalibrationIn, request: Request) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        monitor = obter_machine_monitor(connection, monitor_id)
        if monitor is None:
            raise HTTPException(status_code=404, detail="Monitor nao encontrado.")
        if tenant_filter(user) and monitor.get("client_id") != tenant_filter(user):
            raise HTTPException(status_code=403, detail="Monitor de outro cliente.")
        running = payload.running_motion if payload.running_motion is not None else monitor.get("running_motion")
        stopped = payload.stopped_motion if payload.stopped_motion is not None else monitor.get("stopped_motion")
        threshold = calibrate_threshold(running or monitor["motion_sensitivity"] * 2, stopped or monitor["motion_sensitivity"] * 0.3)
        return atualizar_machine_monitor(
            connection,
            monitor_id,
            motion_threshold=threshold,
            calibration_status="calibrated",
            running_motion=running,
            stopped_motion=stopped,
        )


@api.post("/machine-monitors/{monitor_id}/calibrate-active")
def post_machine_monitor_calibrate_active(monitor_id: str, payload: MachineCalibrationIn, request: Request) -> dict[str, Any]:
    return calibrate_machine_monitor_phase(monitor_id, payload, request, "active")


@api.post("/machine-monitors/{monitor_id}/calibrate-stopped")
def post_machine_monitor_calibrate_stopped(monitor_id: str, payload: MachineCalibrationIn, request: Request) -> dict[str, Any]:
    return calibrate_machine_monitor_phase(monitor_id, payload, request, "stopped")


@api.post("/machine-monitors/{monitor_id}/calibration/active/start")
def post_machine_monitor_assisted_active_start(monitor_id: str, payload: AssistedMachineCalibrationIn, request: Request) -> dict[str, object]:
    return start_assisted_machine_calibration(monitor_id, payload, request, "active")


@api.post("/machine-monitors/{monitor_id}/calibration/stopped/start")
def post_machine_monitor_assisted_stopped_start(monitor_id: str, payload: AssistedMachineCalibrationIn, request: Request) -> dict[str, object]:
    return start_assisted_machine_calibration(monitor_id, payload, request, "stopped")


@api.get("/machine-monitors/{monitor_id}/calibration/status")
def get_machine_monitor_calibration_status(monitor_id: str, request: Request) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        monitor = obter_machine_monitor(connection, monitor_id)
        if monitor is None:
            raise HTTPException(status_code=404, detail="Monitor nao encontrado.")
        if tenant_filter(user) and monitor.get("client_id") != tenant_filter(user):
            raise HTTPException(status_code=403, detail="Monitor de outro cliente.")
    stream = live_streams.get(str(monitor["camera_id"]))
    stream_status = stream.calibration_status() if stream else {"status": "idle"}
    return {
        "machine_id": monitor_id,
        "camera_id": monitor["camera_id"],
        "stream": stream_status,
        "active_calibration": monitor.get("active_calibration"),
        "stopped_calibration": monitor.get("stopped_calibration"),
        "active_baseline": monitor.get("active_baseline"),
        "stopped_baseline": monitor.get("stopped_baseline"),
        "separation_score": monitor.get("separation_score"),
        "calibration_result": monitor.get("calibration_result"),
        "calibration_status": monitor.get("calibration_status"),
    }


def start_assisted_machine_calibration(monitor_id: str, payload: AssistedMachineCalibrationIn, request: Request, phase: str) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        monitor = obter_machine_monitor(connection, monitor_id)
        if monitor is None:
            raise HTTPException(status_code=404, detail="Monitor nao encontrado.")
        if tenant_filter(user) and monitor.get("client_id") != tenant_filter(user):
            raise HTTPException(status_code=403, detail="Monitor de outro cliente.")
        region = next(
            (
                area
                for area in listar_areas_camera(connection, str(monitor["camera_id"]))
                if area.get("ativa", True)
                and area.get("tipo") == "machine_region"
                and (not area.get("machine_id") or area.get("machine_id") == monitor_id)
            ),
            None,
        )
    if region is None:
        raise HTTPException(status_code=400, detail="Calibracao exige uma machine_region salva para esta camera.")
    _camera, source = load_camera_source(str(monitor["camera_id"]))
    stream = live_streams.get_or_create(str(monitor["camera_id"]), source)
    stream.start()
    try:
        status_payload = stream.start_machine_calibration(
            monitor,
            region["pontos"],
            phase,
            duration_seconds=payload.duration_seconds,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "machine_id": monitor_id,
        "camera_id": monitor["camera_id"],
        "phase": phase,
        "machine_region_id": region["id"],
        "status": status_payload,
    }


def calibrate_machine_monitor_phase(monitor_id: str, payload: MachineCalibrationIn, request: Request, phase: str) -> dict[str, Any]:
    samples = payload.samples or []
    if phase == "active" and payload.running_motion is not None:
        samples = [payload.running_motion]
    if phase == "stopped" and payload.stopped_motion is not None:
        samples = [payload.stopped_motion]
    try:
        baseline, noise = baseline_stats(samples)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        monitor = obter_machine_monitor(connection, monitor_id)
        if monitor is None:
            raise HTTPException(status_code=404, detail="Monitor nao encontrado.")
        if tenant_filter(user) and monitor.get("client_id") != tenant_filter(user):
            raise HTTPException(status_code=403, detail="Monitor de outro cliente.")
        active = baseline if phase == "active" else monitor.get("active_baseline") or monitor.get("running_motion")
        stopped = baseline if phase == "stopped" else monitor.get("stopped_baseline") or monitor.get("stopped_motion")
        threshold = calibrate_threshold(active, stopped) if active is not None and stopped is not None else monitor.get("motion_threshold")
        status_text = "calibrated" if active is not None and stopped is not None else f"{phase}_calibrated"
        return atualizar_machine_monitor(
            connection,
            monitor_id,
            motion_threshold=threshold,
            calibration_status=status_text,
            running_motion=active,
            stopped_motion=stopped,
            active_baseline=active,
            stopped_baseline=stopped,
            active_noise=noise if phase == "active" else None,
            stopped_noise=noise if phase == "stopped" else None,
        )


def _rule_context(connection, payload: RegraIn, user: dict[str, Any]) -> tuple[str | None, str | None]:
    camera = obter_camera(connection, payload.camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera nao encontrada.")
    require_same_tenant(user, camera.get("cliente_id"), "Camera de outro cliente.")
    cliente_id = payload.cliente_id or camera.get("cliente_id") or tenant_filter(user)
    unidade_id = payload.unidade_id or camera.get("unidade_id")
    return cliente_id, unidade_id


@api.get("/visual-rules/templates")
def get_visual_rule_templates() -> dict[str, Any]:
    return {"conditions": condition_templates()}


@api.get("/visual-rules")
def get_visual_rules(request: Request, camera_id: Optional[str] = None) -> list[dict[str, Any]]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        if camera_id:
            require_camera_access(connection, user, camera_id)
        return listar_regras(connection, tenant_filter(user), camera_id)


@api.post("/visual-rules")
def post_visual_rule(payload: RegraIn, request: Request) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_role(user, ADMIN_ROLES)
        cliente_id, unidade_id = _rule_context(connection, payload, user)
        rule_id = criar_regra(
            connection,
            payload.camera_id,
            payload.tipo_evento,
            payload.tempo_minimo,
            payload.ativo,
            nome=payload.nome,
            cliente_id=cliente_id,
            unidade_id=unidade_id,
            entidade=payload.entidade,
            regiao_id=payload.regiao_id,
            condicao=payload.condicao or {"type": payload.tipo_evento},
            severidade=payload.severidade,
            cooldown_seconds=payload.cooldown_seconds,
            destinatarios=payload.destinatarios,
            alerta_inicio=payload.alerta_inicio,
            alerta_normalizacao=payload.alerta_normalizacao,
            debounce_seconds=payload.debounce_seconds,
            hysteresis_seconds=payload.hysteresis_seconds,
            metadata=payload.metadata,
        )
        return obter_regra(connection, rule_id)


@api.post("/regras")
def post_regra(payload: RegraIn, request: Request) -> dict[str, Any]:
    return post_visual_rule(payload, request)


@api.patch("/visual-rules/{rule_id}")
def patch_visual_rule(rule_id: str, payload: RegraPatchIn, request: Request) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_role(user, ADMIN_ROLES)
        rule = obter_regra(connection, rule_id)
        if rule is None:
            raise HTTPException(status_code=404, detail="Regra nao encontrada.")
        require_same_tenant(user, rule.get("cliente_id"), "Regra de outro cliente.")
        updated = atualizar_regra(connection, rule_id, **payload.model_dump())
    if updated is None:
        raise HTTPException(status_code=404, detail="Regra nao encontrada.")
    return updated


@api.post("/visual-rules/{rule_id}/simulate")
def post_visual_rule_simulate(rule_id: str, payload: VisualRuleSimulationIn, request: Request) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        rule = obter_regra(connection, rule_id)
        if rule is None:
            raise HTTPException(status_code=404, detail="Regra nao encontrada.")
        require_same_tenant(user, rule.get("cliente_id"), "Regra de outro cliente.")
        return evaluate_rule(connection, rule_id, payload.facts, at=payload.at)


@api.post("/cameras/{camera_id}/visual-rules/defaults")
def post_camera_visual_rule_defaults(camera_id: str, payload: VisualRuleDefaultsIn, request: Request) -> dict[str, Any]:
    created: list[dict[str, Any]] = []
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_role(user, ADMIN_ROLES)
        camera = obter_camera(connection, camera_id)
        if camera is None:
            raise HTTPException(status_code=404, detail="Camera nao encontrada.")
        require_same_tenant(user, camera.get("cliente_id"), "Camera de outro cliente.")
        existing_names = {rule["nome"] for rule in listar_regras(connection, camera_id=camera_id)}
        for item in default_rule_payloads(camera_id, payload.zone_id):
            if item["nome"] in existing_names:
                continue
            rule_id = criar_regra(
                connection,
                camera_id,
                item["tipo_evento"],
                item["tempo_minimo"],
                True,
                nome=item["nome"],
                cliente_id=camera.get("cliente_id"),
                unidade_id=camera.get("unidade_id"),
                entidade=item.get("entidade"),
                regiao_id=item.get("regiao_id"),
                condicao=item["condicao"],
                severidade=item["severidade"],
                cooldown_seconds=item["cooldown_seconds"],
                alerta_inicio=item["alerta_inicio"],
                alerta_normalizacao=item["alerta_normalizacao"],
            )
            created.append(obter_regra(connection, rule_id))
    return {"created": created, "total": len(created)}


@api.post("/eventos")
def post_evento(payload: EventoIn) -> dict[str, str]:
    with connect() as connection:
        init_db(connection)
        return {"id": registrar_evento(connection, **payload.model_dump())}


@api.patch("/eventos/{evento_id}")
def patch_evento(evento_id: str, payload: EventoUpdateIn) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        if payload.status == "acknowledged":
            event = reconhecer_ocorrencia(
                connection,
                evento_id,
                payload.observacao,
                payload.acknowledged_by,
                now_iso(),
            )
            if event is None:
                raise HTTPException(status_code=404, detail="Evento nao encontrado.")
            return event
        atualizar_evento(
            connection,
            evento_id,
            fim=payload.fim,
            duracao=payload.duracao,
            operador_presente=payload.operador_presente,
            confianca=payload.confianca,
            midia_path=payload.midia_path,
        )
        event = obter_evento(connection, evento_id)
        if event is None:
            raise HTTPException(status_code=404, detail="Evento nao encontrado.")
        return event


@api.get("/eventos")
def get_eventos(
    request: Request,
    camera_id: Optional[str] = None,
    area_id: Optional[str] = None,
    status: Optional[str] = None,
    tipo: Optional[str] = None,
    data_inicio: Optional[str] = None,
    data_fim: Optional[str] = None,
) -> list[dict[str, Any]]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        if tenant_filter(user):
            events = listar_eventos_filtrados(connection, camera_id, area_id, status, tipo, data_inicio, data_fim)
            return [event for event in events if event.get("cliente_id") == tenant_filter(user)]
        return listar_eventos_filtrados(connection, camera_id, area_id, status, tipo, data_inicio, data_fim)


@api.get("/eventos/{evento_id}")
def get_evento(evento_id: str) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        event = obter_evento(connection, evento_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Evento nao encontrado.")
    return event


@api.get("/eventos/{evento_id}/evidence")
def get_evento_evidence(evento_id: str) -> FileResponse:
    with connect() as connection:
        init_db(connection)
        event = obter_evento(connection, evento_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Evento nao encontrado.")
    midia_path = event.get("midia_path")
    if not midia_path:
        raise HTTPException(status_code=404, detail="Evidencia nao encontrada.")
    path = (ROOT / str(midia_path)).resolve()
    evidence_root = (ROOT / "data" / "evidence").resolve()
    if evidence_root not in path.parents:
        raise HTTPException(status_code=403, detail="Caminho de evidencia invalido.")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Arquivo de evidencia nao encontrado.")
    return FileResponse(path, media_type="image/jpeg", filename=f"{evento_id}.jpg")


@api.get("/eventos/{evento_id}/replay")
def get_evento_replay(evento_id: str) -> FileResponse:
    with connect() as connection:
        init_db(connection)
        event = obter_evento(connection, evento_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Evento nao encontrado.")
    replay_path = event.get("replay_path")
    if not replay_path:
        raise HTTPException(status_code=404, detail="Replay nao encontrado.")
    path = (ROOT / str(replay_path)).resolve()
    replay_root = (ROOT / "data" / "replays").resolve()
    if replay_root not in path.parents:
        raise HTTPException(status_code=403, detail="Caminho de replay invalido.")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Arquivo de replay nao encontrado.")
    return FileResponse(path, media_type="video/mp4", filename=f"{evento_id}.mp4")


@api.patch("/eventos/{evento_id}/cause")
def patch_evento_cause(evento_id: str, payload: EventCauseIn, request: Request) -> dict[str, Any]:
    allowed = {
        "manutenção",
        "falta de material",
        "ajuste de máquina",
        "intervalo",
        "operador ausente",
        "bloqueio de processo",
        "parada planejada",
        "falso alerta",
        "outra",
    }
    if payload.cause_category not in allowed:
        raise HTTPException(status_code=400, detail="Categoria de causa invalida.")
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        event = obter_evento(connection, evento_id)
        if event is None:
            raise HTTPException(status_code=404, detail="Evento nao encontrado.")
        if tenant_filter(user) and event.get("cliente_id") != tenant_filter(user):
            raise HTTPException(status_code=403, detail="Evento de outro cliente.")
        return classificar_evento(
            connection,
            evento_id,
            payload.cause_category,
            payload.cause_notes,
            payload.classified_by or user.get("email"),
            now_iso(),
        )


@api.get("/operations/summary")
def get_operations_summary(
    request: Request,
    start: Optional[str] = None,
    end: Optional[str] = None,
    camera_id: Optional[str] = None,
    machine_name: Optional[str] = None,
) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        require_camera_access(connection, require_user(request, connection), camera_id)
        return operations_summary(connection, start, end, camera_id, machine_name)


@api.get("/operations/timeline")
def get_operations_timeline(
    request: Request,
    start: Optional[str] = None,
    end: Optional[str] = None,
    camera_id: Optional[str] = None,
    machine_name: Optional[str] = None,
) -> list[dict[str, Any]]:
    with connect() as connection:
        init_db(connection)
        require_camera_access(connection, require_user(request, connection), camera_id)
        return operations_timeline(connection, start, end, camera_id, machine_name)


@api.get("/operations/events")
def get_operations_events(
    request: Request,
    start: Optional[str] = None,
    end: Optional[str] = None,
    camera_id: Optional[str] = None,
    machine_name: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        require_camera_access(connection, require_user(request, connection), camera_id)
        events = list_operational_events(connection, start, end, camera_id, machine_name, limit, offset)
        return {"events": events, "limit": limit, "offset": offset}


@api.get("/operations/current-status")
def get_operations_current_status(
    request: Request,
    camera_id: Optional[str] = None,
    machine_name: Optional[str] = None,
) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        require_camera_access(connection, require_user(request, connection), camera_id)
        return current_status(connection, camera_id, machine_name)


@api.get("/operations")
def get_operations(
    request: Request,
    cliente_id: Optional[str] = None,
    unidade_id: Optional[str] = None,
    camera_id: Optional[str] = None,
    machine_id: Optional[str] = None,
    cause: Optional[str] = None,
) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        effective_cliente = tenant_filter(user) or cliente_id
        monitors = []
        rows = connection.execute("SELECT * FROM machine_monitors ORDER BY nome").fetchall()
        for row in rows:
            monitor = dict(row)
            if effective_cliente and monitor["client_id"] != effective_cliente:
                continue
            if unidade_id and monitor["unit_id"] != unidade_id:
                continue
            if camera_id and monitor["camera_id"] != camera_id:
                continue
            if machine_id and monitor["id"] != machine_id:
                continue
            monitor_public = obter_machine_monitor(connection, monitor["id"])
            events = listar_eventos_filtrados(connection, camera_id=monitor["camera_id"], tipo="machine_stoppage")
            events = [event for event in events if event.get("machine_monitor_id") == monitor["id"]]
            if cause:
                events = [event for event in events if event.get("cause_category") == cause]
            total = sum(float(event.get("duracao") or 0) for event in events)
            monitors.append({
                "monitor": monitor_public,
                "paradas": len(events),
                "tempo_total_parado": total,
                "duracao_media": total / len(events) if events else 0,
                "maior_parada": max([float(event.get("duracao") or 0) for event in events], default=0),
                "operador_ausente_percentual": round(100 * len([e for e in events if not e.get("operator_present_start")]) / len(events), 2) if events else 0,
                "ultimas_ocorrencias": events[:10],
            })
    return {"machines": monitors}


@api.get("/alert-recipients")
def get_alert_recipients(request: Request) -> list[dict[str, Any]]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        recipients = listar_alert_recipients(connection)
        tenant = tenant_filter(user)
        if not tenant:
            return recipients
        cameras = {row["id"] for row in listar_por_cliente(connection, "cameras", tenant)}
        return [r for r in recipients if r.get("cliente_id") == tenant or (not r.get("cliente_id") and (not r.get("camera_id") or r.get("camera_id") in cameras))]


@api.post("/alert-recipients")
def post_alert_recipient(payload: AlertRecipientIn, request: Request) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_role(user, ADMIN_ROLES)
        cliente_id = effective_cliente_id(user, payload.cliente_id)
        if cliente_id is None and payload.camera_id:
            camera = obter_camera(connection, payload.camera_id)
            cliente_id = camera.get("cliente_id") if camera else None
        if tenant_filter(user):
            require_same_tenant(user, cliente_id)
        recipient_id = criar_alert_recipient(
            connection,
            payload.nome,
            payload.email,
            payload.ativo,
            payload.camera_id,
            payload.area_id,
            payload.severidade_minima,
            cliente_id,
            payload.event_types,
        )
        return next(recipient for recipient in listar_alert_recipients(connection) if recipient["id"] == recipient_id)


@api.patch("/alert-recipients/{recipient_id}")
def patch_alert_recipient(recipient_id: str, payload: AlertRecipientPatchIn, request: Request) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        existing = obter_alert_recipient(connection, recipient_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Responsavel nao encontrado.")
        require_same_tenant(user, existing.get("cliente_id"))
        recipient = atualizar_alert_recipient(
            connection,
            recipient_id,
            nome=payload.nome,
            email=payload.email,
            ativo=payload.ativo,
            camera_id=payload.camera_id,
            area_id=payload.area_id,
            severidade_minima=payload.severidade_minima,
            event_types=payload.event_types,
        )
    if recipient is None:
        raise HTTPException(status_code=404, detail="Responsavel nao encontrado.")
    return recipient


@api.delete("/alert-recipients/{recipient_id}")
def delete_alert_recipient(recipient_id: str, request: Request) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        existing = obter_alert_recipient(connection, recipient_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Responsavel nao encontrado.")
        require_same_tenant(user, existing.get("cliente_id"))
        deleted = excluir_alert_recipient(connection, recipient_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Responsavel nao encontrado.")
    return {"id": recipient_id, "deleted": True}


@api.post("/alert-recipients/{recipient_id}/test")
def post_alert_recipient_test(recipient_id: str, request: Request) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        recipient = obter_alert_recipient(connection, recipient_id)
        if recipient is None:
            raise HTTPException(status_code=404, detail="Responsavel nao encontrado.")
        require_same_tenant(user, recipient.get("cliente_id"))
    delivery_id = send_test_alert(recipient_id)
    if delivery_id is None:
        raise HTTPException(status_code=404, detail="Responsavel nao encontrado.")
    return {"delivery_id": delivery_id, "status": "pending"}


@api.get("/alert-deliveries")
def get_alert_deliveries(
    request: Request,
    evento_id: Optional[str] = None,
    recipient_id: Optional[str] = None,
    status: Optional[str] = None,
) -> list[dict[str, Any]]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        deliveries = listar_alert_deliveries(connection, evento_id, recipient_id, status)
        if not tenant_filter(user):
            return deliveries
        allowed_events = {event["id"] for event in listar_por_cliente(connection, "eventos", tenant_filter(user))}
        allowed_recipients = {recipient["id"] for recipient in get_alert_recipients(request)}
        return [d for d in deliveries if d.get("evento_id") in allowed_events or d.get("recipient_id") in allowed_recipients]


@api.get("/alert-deliveries/{delivery_id}")
def get_alert_delivery(delivery_id: str) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        delivery = obter_alert_delivery(connection, delivery_id)
    if delivery is None:
        raise HTTPException(status_code=404, detail="Entrega nao encontrada.")
    return delivery


@api.post("/alert-deliveries/{delivery_id}/retry")
def post_alert_delivery_retry(delivery_id: str) -> dict[str, Any]:
    delivery = retry_delivery(delivery_id)
    if delivery is None:
        raise HTTPException(status_code=404, detail="Entrega nao encontrada.")
    return delivery


@api.get("/events/stream")
def get_events_stream() -> StreamingResponse:
    return StreamingResponse(stream_events(), media_type="text/event-stream")


@api.get("/cameras/estado")
def get_camera_estado(request: Request) -> list[dict[str, Any]]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        cameras = listar_por_cliente(connection, "cameras", tenant_filter(user))
        if user["role"] in {"operador", "visualizador"}:
            for camera in cameras:
                camera.pop("rtsp_host", None)
                camera.pop("rtsp_port", None)
                camera.pop("rtsp_path", None)
                camera.pop("config_ref", None)
        return cameras


@api.get("/relatorios/diario")
def get_relatorio_diario(data: Optional[str] = None) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        return daily_report_data(connection, data)


api.add_api_route(
    "/{internal_path:path}",
    serve_internal_not_found,
    methods=["GET"],
    include_in_schema=False,
    name="internal_not_found",
)
