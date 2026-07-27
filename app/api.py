from __future__ import annotations

from typing import Any, Optional
import hashlib
import time

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.camera_rtsp import build_rtsp_url, test_rtsp_connection
from app.alerts import resume_pending_deliveries, retry_delivery, send_test_alert, stream_events
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
from app.machine_monitoring import calibrate_threshold
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
    nome: str
    pontos: list[AreaPointIn]
    tipo: str = "restricted_area"
    ativa: bool = True


class AreaPatchIn(BaseModel):
    nome: Optional[str] = None
    pontos: Optional[list[AreaPointIn]] = None
    ativa: Optional[bool] = None


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


class MachineMonitorPatchIn(BaseModel):
    nome: Optional[str] = None
    machine_polygon: Optional[list[AreaPointIn]] = None
    operator_polygon: Optional[list[AreaPointIn]] = None
    ativo: Optional[bool] = None
    motion_sensitivity: Optional[float] = None
    motion_threshold: Optional[float] = None
    stop_seconds: Optional[float] = None
    recovery_seconds: Optional[float] = None


class MachineCalibrationIn(BaseModel):
    running_motion: Optional[float] = None
    stopped_motion: Optional[float] = None
    duration_seconds: float = 20.0


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
    "live-view",
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
    session_id = "live_" + hashlib.sha256(f"{payload.nome}|{rtsp.safe_url}".encode()).hexdigest()[:16]
    live_view_sessions[session_id] = {
        "nome": payload.nome,
        "source": rtsp.url,
        "safe_url": rtsp.safe_url,
        "created_at": time.time(),
    }
    stream = live_streams.get_or_create(session_id, rtsp.url)
    stream.enable_live_view_ops()
    stream.start()
    status = stream.public_status()
    return {
        "session_id": session_id,
        "nome": payload.nome,
        "status": status,
    }


@api.get("/live-view/{session_id}/status")
def get_live_view_status(session_id: str) -> dict[str, object]:
    session = live_view_sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Live View não encontrada.")
    stream = live_streams.get(session_id)
    status = stream.public_status() if stream else {"status": "offline", "width": None, "height": None, "fps": None}
    ops = stream.live_view_ops.public_state() if stream and stream.live_view_ops else {}
    return {"session_id": session_id, "nome": session["nome"], **status, "ops": ops}


@api.get("/live-view/{session_id}/stream")
def get_live_view_stream(session_id: str) -> StreamingResponse:
    session = live_view_sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Live View não encontrada.")
    stream = live_streams.get_or_create(session_id, str(session["source"]))
    stream.enable_live_view_ops()
    stream.start()
    return StreamingResponse(stream.frames(), media_type="multipart/x-mixed-replace; boundary=frame")


def live_view_ops_for(session_id: str):
    session = live_view_sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Live View não encontrada.")
    stream = live_streams.get_or_create(session_id, str(session["source"]))
    return stream.enable_live_view_ops()


@api.post("/live-view/{session_id}/ai/start")
def post_live_view_ai_start(session_id: str) -> dict[str, object]:
    ops = live_view_ops_for(session_id)
    stream = live_streams.get(session_id)
    if stream:
        stream.set_analysis(True)
    return ops.public_state()


@api.post("/live-view/{session_id}/ai/stop")
def post_live_view_ai_stop(session_id: str) -> dict[str, object]:
    ops = live_view_ops_for(session_id)
    stream = live_streams.get(session_id)
    if stream:
        stream.set_analysis(False)
    return ops.public_state()


@api.post("/live-view/{session_id}/machine")
def post_live_view_machine(session_id: str, payload: LiveViewMachineIn) -> dict[str, object]:
    ops = live_view_ops_for(session_id)
    return ops.configure_machine(
        payload.nome,
        [point.model_dump() for point in payload.machine_polygon],
        [point.model_dump() for point in payload.operator_polygon] if payload.operator_polygon else None,
        payload.tipo,
    )


@api.post("/live-view/{session_id}/operator-zone")
def post_live_view_operator_zone(session_id: str, payload: LiveViewOperatorZoneIn) -> dict[str, object]:
    ops = live_view_ops_for(session_id)
    return ops.configure_operator_zone([point.model_dump() for point in payload.operator_polygon])


@api.post("/live-view/{session_id}/machine/calibrate-active")
def post_live_view_machine_calibrate_active(session_id: str) -> dict[str, object]:
    ops = live_view_ops_for(session_id)
    return ops.calibrate_active()


@api.delete("/live-view/{session_id}/machine")
def delete_live_view_machine(session_id: str) -> dict[str, object]:
    ops = live_view_ops_for(session_id)
    return ops.clear()


@api.post("/live-view/{session_id}/stop")
def post_live_view_stop(session_id: str) -> dict[str, object]:
    stopped = live_streams.stop(session_id)
    live_view_sessions.pop(session_id, None)
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


@api.post("/cameras/{camera_id}/areas")
def post_camera_area(camera_id: str, payload: AreaIn) -> dict[str, Any]:
    try:
        points = normalize_points([point.model_dump() for point in payload.pontos])
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if payload.tipo != "restricted_area":
        raise HTTPException(status_code=400, detail="Tipo de area invalido para o MVP.")
    with connect() as connection:
        init_db(connection)
        if obter_camera(connection, camera_id) is None:
            raise HTTPException(status_code=404, detail="Camera nao encontrada.")
        area_id = criar_area_monitorada(connection, camera_id, payload.nome, points, payload.tipo, payload.ativa)
        areas = listar_areas_camera(connection, camera_id)
    return next(area for area in areas if area["id"] == area_id)


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
        area = atualizar_area_monitorada(connection, area_id, payload.nome, points, payload.ativa)
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
