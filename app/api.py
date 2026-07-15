from __future__ import annotations

from typing import Any, Optional

from fastapi import FastAPI
from pydantic import BaseModel

from app.database import connect, init_db
from app.models import (
    atualizar_evento,
    criar_camera,
    criar_cliente,
    criar_dispositivo,
    criar_regra,
    criar_unidade,
    listar,
    registrar_evento,
)
from app.reports import daily_report_data

api = FastAPI(title="Visual Operations Internal API")


class ClienteIn(BaseModel):
    nome: str
    status: str = "ativo"


class UnidadeIn(BaseModel):
    cliente_id: str
    nome: str
    localizacao: Optional[str] = None


class DispositivoIn(BaseModel):
    unidade_id: str
    nome: str
    status: str = "offline"


class CameraIn(BaseModel):
    cliente_id: Optional[str] = None
    unidade_id: str
    dispositivo_id: Optional[str] = None
    edge_id: Optional[str] = None
    nome: str
    config_ref: Optional[str] = None
    source_type: Optional[str] = None
    secure_ref: Optional[str] = None
    status: str = "nao_conectada"


class RegraIn(BaseModel):
    camera_id: str
    tipo_evento: str
    tempo_minimo: float = 0
    ativo: bool = True


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


@api.on_event("startup")
def startup() -> None:
    with connect() as connection:
        init_db(connection)


@api.post("/clientes")
def post_cliente(payload: ClienteIn) -> dict[str, str]:
    with connect() as connection:
        init_db(connection)
        return {"id": criar_cliente(connection, payload.nome, payload.status)}


@api.post("/unidades")
def post_unidade(payload: UnidadeIn) -> dict[str, str]:
    with connect() as connection:
        init_db(connection)
        return {"id": criar_unidade(connection, payload.cliente_id, payload.nome, payload.localizacao)}


@api.post("/dispositivos")
def post_dispositivo(payload: DispositivoIn) -> dict[str, str]:
    with connect() as connection:
        init_db(connection)
        return {"id": criar_dispositivo(connection, payload.unidade_id, payload.nome, payload.status)}


@api.post("/cameras")
def post_camera(payload: CameraIn) -> dict[str, str]:
    with connect() as connection:
        init_db(connection)
        return {"id": criar_camera(
            connection,
            payload.unidade_id,
            payload.nome,
            payload.dispositivo_id,
            payload.config_ref,
            payload.status,
            payload.cliente_id,
            payload.edge_id,
            payload.source_type,
            payload.secure_ref,
        )}


@api.post("/regras")
def post_regra(payload: RegraIn) -> dict[str, str]:
    with connect() as connection:
        init_db(connection)
        return {"id": criar_regra(connection, payload.camera_id, payload.tipo_evento, payload.tempo_minimo, payload.ativo)}


@api.post("/eventos")
def post_evento(payload: EventoIn) -> dict[str, str]:
    with connect() as connection:
        init_db(connection)
        return {"id": registrar_evento(connection, **payload.model_dump())}


@api.patch("/eventos/{evento_id}")
def patch_evento(evento_id: str, payload: EventoUpdateIn) -> dict[str, str]:
    with connect() as connection:
        init_db(connection)
        atualizar_evento(connection, evento_id, **payload.model_dump())
        return {"id": evento_id}


@api.get("/eventos")
def get_eventos() -> list[dict[str, Any]]:
    with connect() as connection:
        init_db(connection)
        return listar(connection, "eventos")


@api.get("/cameras/estado")
def get_camera_estado() -> list[dict[str, Any]]:
    with connect() as connection:
        init_db(connection)
        return listar(connection, "cameras")


@api.get("/relatorios/diario")
def get_relatorio_diario(data: Optional[str] = None) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        return daily_report_data(connection, data)
