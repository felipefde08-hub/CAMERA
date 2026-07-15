from __future__ import annotations

import sqlite3
import uuid
from typing import Any

from shared.schemas import now_iso


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def criar_cliente(connection: sqlite3.Connection, nome: str, status: str = "ativo") -> str:
    item_id = new_id("cli")
    connection.execute(
        "INSERT INTO clientes (id, nome, status) VALUES (?, ?, ?)",
        (item_id, nome, status),
    )
    connection.commit()
    return item_id


def criar_unidade(connection: sqlite3.Connection, cliente_id: str, nome: str, localizacao: str | None = None) -> str:
    item_id = new_id("uni")
    connection.execute(
        "INSERT INTO unidades (id, cliente_id, nome, localizacao) VALUES (?, ?, ?, ?)",
        (item_id, cliente_id, nome, localizacao),
    )
    connection.commit()
    return item_id


def criar_dispositivo(connection: sqlite3.Connection, unidade_id: str, nome: str, status: str = "offline") -> str:
    item_id = new_id("edge")
    connection.execute(
        "INSERT INTO dispositivos (id, unidade_id, nome, status, ultimo_contato) VALUES (?, ?, ?, ?, ?)",
        (item_id, unidade_id, nome, status, now_iso()),
    )
    connection.commit()
    return item_id


def criar_camera(
    connection: sqlite3.Connection,
    unidade_id: str,
    nome: str,
    dispositivo_id: str | None = None,
    config_ref: str | None = None,
    status: str = "nao_conectada",
) -> str:
    item_id = new_id("cam")
    connection.execute(
        """
        INSERT INTO cameras (id, unidade_id, dispositivo_id, nome, status, config_ref)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (item_id, unidade_id, dispositivo_id, nome, status, config_ref),
    )
    connection.commit()
    return item_id


def criar_regra(connection: sqlite3.Connection, camera_id: str, tipo_evento: str, tempo_minimo: float = 0, ativo: bool = True) -> str:
    item_id = new_id("regra")
    connection.execute(
        "INSERT INTO regras (id, camera_id, tipo_evento, tempo_minimo, ativo) VALUES (?, ?, ?, ?, ?)",
        (item_id, camera_id, tipo_evento, tempo_minimo, 1 if ativo else 0),
    )
    connection.commit()
    return item_id


def registrar_evento(
    connection: sqlite3.Connection,
    cliente_id: str,
    unidade_id: str,
    camera_id: str,
    tipo: str,
    inicio: str | None = None,
    fim: str | None = None,
    duracao: float | None = None,
    operador_presente: bool | None = None,
    confianca: float | None = None,
    midia_path: str | None = None,
) -> str:
    item_id = new_id("evt")
    connection.execute(
        """
        INSERT INTO eventos (
            id, cliente_id, unidade_id, camera_id, tipo, inicio, fim, duracao,
            operador_presente, confianca, midia_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item_id,
            cliente_id,
            unidade_id,
            camera_id,
            tipo,
            inicio or now_iso(),
            fim,
            duracao,
            None if operador_presente is None else int(operador_presente),
            confianca,
            midia_path,
        ),
    )
    connection.commit()
    return item_id


def registrar_alerta(
    connection: sqlite3.Connection,
    evento_id: str,
    canal: str,
    destinatario: str | None = None,
    status: str = "pendente",
) -> str:
    item_id = new_id("alerta")
    connection.execute(
        "INSERT INTO alertas (id, evento_id, canal, destinatario, status) VALUES (?, ?, ?, ?, ?)",
        (item_id, evento_id, canal, destinatario, status),
    )
    connection.commit()
    return item_id


def atualizar_camera_status(
    connection: sqlite3.Connection,
    camera_id: str,
    status: str,
    ultimo_frame: str | None = None,
) -> None:
    connection.execute(
        "UPDATE cameras SET status = ?, ultimo_frame = COALESCE(?, ultimo_frame) WHERE id = ?",
        (status, ultimo_frame, camera_id),
    )
    connection.commit()


def listar(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    allowed = {"clientes", "unidades", "dispositivos", "cameras", "regras", "eventos", "alertas"}
    if table not in allowed:
        raise ValueError(f"Tabela inválida: {table}")
    return [row_to_dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY criado_em DESC")]

