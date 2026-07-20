from __future__ import annotations

import sqlite3
import json
import uuid
from typing import Any

from app.security import decrypt_secret, encrypt_secret
from edge_agent.camera_connector import safe_source_ref
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
    cliente_id: str | None = None,
    edge_id: str | None = None,
    source_type: str | None = None,
    secure_ref: str | None = None,
    rtsp_host: str | None = None,
    rtsp_port: int | None = None,
    rtsp_path: str | None = None,
    rtsp_username: str | None = None,
    rtsp_password: str | None = None,
) -> str:
    item_id = new_id("cam")
    encrypted_password = encrypt_secret(rtsp_password)
    connection.execute(
        """
        INSERT INTO cameras (
            id, cliente_id, unidade_id, dispositivo_id, edge_id, nome, status,
            config_ref, source_type, secure_ref, rtsp_host, rtsp_port, rtsp_path,
            rtsp_username, rtsp_password, rtsp_password_encrypted
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item_id,
            cliente_id,
            unidade_id,
            dispositivo_id,
            edge_id or dispositivo_id,
            nome,
            status,
            config_ref,
            source_type,
            secure_ref,
            rtsp_host,
            rtsp_port,
            rtsp_path,
            rtsp_username,
            None,
            encrypted_password,
        ),
    )
    connection.commit()
    return item_id


def camera_public_dict(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    data.pop("rtsp_username", None)
    data.pop("rtsp_password", None)
    data.pop("rtsp_password_encrypted", None)
    if data.get("config_ref") and str(data["config_ref"]).lower().startswith(("rtsp://", "rtsps://")):
        data["config_ref"] = safe_source_ref(str(data["config_ref"]))
    return data


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


def evento_public_dict(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    if "track_ids_json" in data:
        data["track_ids"] = json.loads(data.pop("track_ids_json") or "[]")
    return data


def criar_ocorrencia_area_restrita(
    connection: sqlite3.Connection,
    cliente_id: str,
    unidade_id: str,
    camera_id: str,
    area_id: str,
    regra_id: str | None,
    inicio: str,
    quantidade_inicial: int,
    quantidade_maxima: int,
    track_ids: list[int],
    confianca: float | None,
    midia_path: str | None,
    severidade: str = "high",
    evidence_error: str | None = None,
) -> str:
    evento_id = new_id("evt")
    track_ids_json = json.dumps(sorted(set(track_ids)))
    connection.execute(
        """
        INSERT INTO eventos (
            id, cliente_id, unidade_id, camera_id, area_id, regra_id, tipo,
            severidade, status, inicio, quantidade_inicial, quantidade_atual,
            quantidade_maxima, track_ids_json, confianca, midia_path,
            ultimo_ocupado_em, evidence_error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            evento_id,
            cliente_id,
            unidade_id,
            camera_id,
            area_id,
            regra_id,
            "restricted_area_occupied",
            severidade,
            "open",
            inicio,
            quantidade_inicial,
            quantidade_inicial,
            quantidade_maxima,
            track_ids_json,
            confianca,
            midia_path,
            inicio,
            evidence_error,
        ),
    )
    connection.commit()
    return evento_id


def atualizar_ocorrencia_area(
    connection: sqlite3.Connection,
    evento_id: str,
    quantidade_atual: int,
    quantidade_maxima: int,
    track_ids: list[int],
    confianca: float | None,
    ultimo_ocupado_em: str,
) -> None:
    connection.execute(
        """
        UPDATE eventos
        SET quantidade_atual = ?,
            quantidade_maxima = MAX(COALESCE(quantidade_maxima, 0), ?),
            track_ids_json = ?,
            confianca = MAX(COALESCE(confianca, 0), COALESCE(?, 0)),
            ultimo_ocupado_em = ?,
            atualizado_em = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            quantidade_atual,
            quantidade_maxima,
            json.dumps(sorted(set(track_ids))),
            confianca,
            ultimo_ocupado_em,
            evento_id,
        ),
    )
    connection.commit()


def fechar_ocorrencia_area(
    connection: sqlite3.Connection,
    evento_id: str,
    fim: str,
    duracao: float,
    observacao: str | None = None,
) -> None:
    connection.execute(
        """
        UPDATE eventos
        SET status = 'closed',
            fim = ?,
            duracao = ?,
            quantidade_atual = 0,
            observacao = COALESCE(?, observacao),
            atualizado_em = CURRENT_TIMESTAMP
        WHERE id = ? AND status = 'open'
        """,
        (fim, duracao, observacao, evento_id),
    )
    connection.commit()


def reconhecer_ocorrencia(
    connection: sqlite3.Connection,
    evento_id: str,
    observacao: str | None,
    acknowledged_by: str | None,
    acknowledged_at: str,
) -> dict[str, Any] | None:
    connection.execute(
        """
        UPDATE eventos
        SET status = 'acknowledged',
            observacao = COALESCE(?, observacao),
            acknowledged_by = ?,
            acknowledged_at = ?,
            atualizado_em = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (observacao, acknowledged_by, acknowledged_at, evento_id),
    )
    connection.commit()
    return obter_evento(connection, evento_id)


def obter_evento(connection: sqlite3.Connection, evento_id: str) -> dict[str, Any] | None:
    row = connection.execute("SELECT * FROM eventos WHERE id = ?", (evento_id,)).fetchone()
    return evento_public_dict(row) if row else None


def listar_eventos_filtrados(
    connection: sqlite3.Connection,
    camera_id: str | None = None,
    area_id: str | None = None,
    status: str | None = None,
    tipo: str | None = None,
    data_inicio: str | None = None,
    data_fim: str | None = None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    values: list[Any] = []
    filters = {
        "camera_id": camera_id,
        "area_id": area_id,
        "status": status,
        "tipo": tipo,
    }
    for column, value in filters.items():
        if value:
            clauses.append(f"{column} = ?")
            values.append(value)
    if data_inicio:
        clauses.append("inicio >= ?")
        values.append(data_inicio)
    if data_fim:
        clauses.append("inicio <= ?")
        values.append(data_fim)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = connection.execute(
        f"SELECT * FROM eventos {where} ORDER BY inicio DESC, criado_em DESC LIMIT 200",
        values,
    ).fetchall()
    return [evento_public_dict(row) for row in rows]


def atualizar_evento(
    connection: sqlite3.Connection,
    evento_id: str,
    fim: str | None = None,
    duracao: float | None = None,
    operador_presente: bool | None = None,
    confianca: float | None = None,
    midia_path: str | None = None,
) -> None:
    connection.execute(
        """
        UPDATE eventos
        SET
            fim = COALESCE(?, fim),
            duracao = COALESCE(?, duracao),
            operador_presente = COALESCE(?, operador_presente),
            confianca = COALESCE(?, confianca),
            midia_path = COALESCE(?, midia_path)
        WHERE id = ?
        """,
        (
            fim,
            duracao,
            None if operador_presente is None else int(operador_presente),
            confianca,
            midia_path,
            evento_id,
        ),
    )
    connection.commit()


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


def atualizar_camera_operacao(
    connection: sqlite3.Connection,
    camera_id: str,
    status: str,
    ultimo_frame: str | None = None,
    ultimo_erro: str | None = None,
    reconectar: bool = False,
    frames_increment: int = 0,
) -> None:
    connection.execute(
        """
        UPDATE cameras
        SET
            status = ?,
            ultimo_frame = COALESCE(?, ultimo_frame),
            ultimo_erro = ?,
            reconexoes = reconexoes + ?,
            frames_processados = frames_processados + ?
        WHERE id = ?
        """,
        (
            status,
            ultimo_frame,
            ultimo_erro,
            1 if reconectar else 0,
            frames_increment,
            camera_id,
        ),
    )
    connection.commit()


def listar_cameras_do_edge(connection: sqlite3.Connection, edge_id: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT *
        FROM cameras
        WHERE (edge_id = ? OR dispositivo_id = ?)
          AND status != 'inativa'
        ORDER BY nome
        """,
        (edge_id, edge_id),
    ).fetchall()
    return [row_to_dict(row) for row in rows]


def registrar_edge_metricas(
    connection: sqlite3.Connection,
    edge_id: str,
    uptime_seconds: float,
    cpu_percent: float | None,
    memory_percent: float | None,
    active_cameras: int,
    frames_processed: int,
) -> None:
    connection.execute(
        """
        INSERT INTO edge_metrics (
            edge_id, uptime_seconds, cpu_percent, memory_percent,
            active_cameras, frames_processed
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            edge_id,
            uptime_seconds,
            cpu_percent,
            memory_percent,
            active_cameras,
            frames_processed,
        ),
    )
    connection.commit()


def ultima_metrica_edge(connection: sqlite3.Connection, edge_id: str) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT *
        FROM edge_metrics
        WHERE edge_id = ?
        ORDER BY recorded_at DESC, id DESC
        LIMIT 1
        """,
        (edge_id,),
    ).fetchone()
    return row_to_dict(row) if row else None


def listar(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    allowed = {"clientes", "unidades", "dispositivos", "cameras", "regras", "eventos", "alertas"}
    if table not in allowed:
        raise ValueError(f"Tabela inválida: {table}")
    rows = connection.execute(f"SELECT * FROM {table} ORDER BY criado_em DESC")
    if table == "cameras":
        return [camera_public_dict(row) for row in rows]
    if table == "eventos":
        return [evento_public_dict(row) for row in rows]
    return [row_to_dict(row) for row in rows]


def obter_camera(connection: sqlite3.Connection, camera_id: str, include_secret: bool = False) -> dict[str, Any] | None:
    row = connection.execute("SELECT * FROM cameras WHERE id = ?", (camera_id,)).fetchone()
    if row is None:
        return None
    if not include_secret:
        return camera_public_dict(row)
    data = row_to_dict(row)
    if data.get("rtsp_password_encrypted"):
        data["rtsp_password"] = decrypt_secret(data["rtsp_password_encrypted"])
    return data


def area_public_dict(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    data["ativa"] = bool(data["ativa"])
    data["pontos"] = json.loads(data.pop("pontos_json"))
    return data


def listar_areas_camera(connection: sqlite3.Connection, camera_id: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT * FROM monitored_areas WHERE camera_id = ? ORDER BY criado_em DESC",
        (camera_id,),
    ).fetchall()
    return [area_public_dict(row) for row in rows]


def listar_areas_ativas_camera(connection: sqlite3.Connection, camera_id: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT * FROM monitored_areas WHERE camera_id = ? AND ativa = 1 ORDER BY criado_em DESC",
        (camera_id,),
    ).fetchall()
    return [area_public_dict(row) for row in rows]


def criar_area_monitorada(
    connection: sqlite3.Connection,
    camera_id: str,
    nome: str,
    pontos: list[dict[str, float]],
    tipo: str = "restricted_area",
    ativa: bool = True,
) -> str:
    area_id = new_id("area")
    connection.execute(
        """
        INSERT INTO monitored_areas (id, camera_id, nome, tipo, pontos_json, ativa)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (area_id, camera_id, nome, tipo, json.dumps(pontos), 1 if ativa else 0),
    )
    connection.commit()
    return area_id


def atualizar_area_monitorada(
    connection: sqlite3.Connection,
    area_id: str,
    nome: str | None = None,
    pontos: list[dict[str, float]] | None = None,
    ativa: bool | None = None,
) -> dict[str, Any] | None:
    existing = connection.execute("SELECT * FROM monitored_areas WHERE id = ?", (area_id,)).fetchone()
    if existing is None:
        return None
    current = area_public_dict(existing)
    next_nome = nome if nome is not None else current["nome"]
    next_pontos = pontos if pontos is not None else current["pontos"]
    next_ativa = ativa if ativa is not None else current["ativa"]
    connection.execute(
        """
        UPDATE monitored_areas
        SET nome = ?, pontos_json = ?, ativa = ?, atualizado_em = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (next_nome, json.dumps(next_pontos), 1 if next_ativa else 0, area_id),
    )
    connection.commit()
    row = connection.execute("SELECT * FROM monitored_areas WHERE id = ?", (area_id,)).fetchone()
    return area_public_dict(row) if row else None


def excluir_area_monitorada(connection: sqlite3.Connection, area_id: str) -> bool:
    cursor = connection.execute("DELETE FROM monitored_areas WHERE id = ?", (area_id,))
    connection.commit()
    return cursor.rowcount > 0


def alert_recipient_public_dict(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    data["ativo"] = bool(data["ativo"])
    return data


def alert_delivery_public_dict(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    data["is_test"] = bool(data["is_test"])
    return data


def listar_alert_recipients(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute("SELECT * FROM alert_recipients ORDER BY criado_em DESC").fetchall()
    return [alert_recipient_public_dict(row) for row in rows]


def criar_alert_recipient(
    connection: sqlite3.Connection,
    nome: str,
    email: str,
    ativo: bool = True,
    camera_id: str | None = None,
    area_id: str | None = None,
    severidade_minima: str = "low",
) -> str:
    recipient_id = new_id("rec")
    connection.execute(
        """
        INSERT INTO alert_recipients (
            id, nome, email, ativo, camera_id, area_id, severidade_minima
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (recipient_id, nome, email, 1 if ativo else 0, camera_id, area_id, severidade_minima),
    )
    connection.commit()
    return recipient_id


def atualizar_alert_recipient(
    connection: sqlite3.Connection,
    recipient_id: str,
    nome: str | None = None,
    email: str | None = None,
    ativo: bool | None = None,
    camera_id: str | None = None,
    area_id: str | None = None,
    severidade_minima: str | None = None,
) -> dict[str, Any] | None:
    existing = connection.execute("SELECT * FROM alert_recipients WHERE id = ?", (recipient_id,)).fetchone()
    if existing is None:
        return None
    current = alert_recipient_public_dict(existing)
    connection.execute(
        """
        UPDATE alert_recipients
        SET nome = ?,
            email = ?,
            ativo = ?,
            camera_id = ?,
            area_id = ?,
            severidade_minima = ?,
            atualizado_em = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            nome if nome is not None else current["nome"],
            email if email is not None else current["email"],
            1 if (ativo if ativo is not None else current["ativo"]) else 0,
            camera_id if camera_id is not None else current.get("camera_id"),
            area_id if area_id is not None else current.get("area_id"),
            severidade_minima if severidade_minima is not None else current["severidade_minima"],
            recipient_id,
        ),
    )
    connection.commit()
    row = connection.execute("SELECT * FROM alert_recipients WHERE id = ?", (recipient_id,)).fetchone()
    return alert_recipient_public_dict(row) if row else None


def excluir_alert_recipient(connection: sqlite3.Connection, recipient_id: str) -> bool:
    cursor = connection.execute("DELETE FROM alert_recipients WHERE id = ?", (recipient_id,))
    connection.commit()
    return cursor.rowcount > 0


def listar_recipients_para_evento(connection: sqlite3.Connection, event: dict[str, Any]) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT *
        FROM alert_recipients
        WHERE ativo = 1
          AND (camera_id IS NULL OR camera_id = ?)
          AND (area_id IS NULL OR area_id = ?)
        ORDER BY criado_em DESC
        """,
        (event.get("camera_id"), event.get("area_id")),
    ).fetchall()
    return [alert_recipient_public_dict(row) for row in rows]


def obter_alert_recipient(connection: sqlite3.Connection, recipient_id: str) -> dict[str, Any] | None:
    row = connection.execute("SELECT * FROM alert_recipients WHERE id = ?", (recipient_id,)).fetchone()
    return alert_recipient_public_dict(row) if row else None


def criar_alert_delivery(
    connection: sqlite3.Connection,
    recipient_id: str,
    evento_id: str | None = None,
    canal: str = "email",
    status: str = "pending",
    is_test: bool = False,
) -> str:
    delivery_id = new_id("del")
    if evento_id is not None:
        existing = connection.execute(
            "SELECT id FROM alert_deliveries WHERE evento_id = ? AND recipient_id = ? AND canal = ?",
            (evento_id, recipient_id, canal),
        ).fetchone()
        if existing:
            return str(existing["id"])
    connection.execute(
        """
        INSERT INTO alert_deliveries (
            id, evento_id, recipient_id, canal, status, is_test
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (delivery_id, evento_id, recipient_id, canal, status, 1 if is_test else 0),
    )
    connection.commit()
    return delivery_id


def obter_alert_delivery(connection: sqlite3.Connection, delivery_id: str) -> dict[str, Any] | None:
    row = connection.execute("SELECT * FROM alert_deliveries WHERE id = ?", (delivery_id,)).fetchone()
    return alert_delivery_public_dict(row) if row else None


def listar_alert_deliveries(
    connection: sqlite3.Connection,
    evento_id: str | None = None,
    recipient_id: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    values: list[Any] = []
    for column, value in {"evento_id": evento_id, "recipient_id": recipient_id, "status": status}.items():
        if value:
            clauses.append(f"{column} = ?")
            values.append(value)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = connection.execute(
        f"SELECT * FROM alert_deliveries {where} ORDER BY criado_em DESC LIMIT 300",
        values,
    ).fetchall()
    return [alert_delivery_public_dict(row) for row in rows]


def atualizar_alert_delivery_attempt(
    connection: sqlite3.Connection,
    delivery_id: str,
    status: str,
    attempts: int,
    last_attempt_at: str,
    next_attempt_at: str | None = None,
    sent_at: str | None = None,
    erro: str | None = None,
) -> dict[str, Any] | None:
    connection.execute(
        """
        UPDATE alert_deliveries
        SET status = ?,
            attempts = ?,
            last_attempt_at = ?,
            next_attempt_at = ?,
            sent_at = ?,
            erro = ?,
            atualizado_em = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (status, attempts, last_attempt_at, next_attempt_at, sent_at, erro, delivery_id),
    )
    connection.commit()
    return obter_alert_delivery(connection, delivery_id)


def listar_por_cliente(connection: sqlite3.Connection, table: str, cliente_id: str | None) -> list[dict[str, Any]]:
    if cliente_id is None:
        return listar(connection, table)
    if table == "clientes":
        rows = connection.execute("SELECT * FROM clientes WHERE id = ? ORDER BY criado_em DESC", (cliente_id,)).fetchall()
        return [row_to_dict(row) for row in rows]
    if table == "unidades":
        rows = connection.execute("SELECT * FROM unidades WHERE cliente_id = ? ORDER BY criado_em DESC", (cliente_id,)).fetchall()
        return [row_to_dict(row) for row in rows]
    if table == "cameras":
        rows = connection.execute("SELECT * FROM cameras WHERE cliente_id = ? ORDER BY criado_em DESC", (cliente_id,)).fetchall()
        return [camera_public_dict(row) for row in rows]
    if table == "eventos":
        rows = connection.execute("SELECT * FROM eventos WHERE cliente_id = ? ORDER BY criado_em DESC", (cliente_id,)).fetchall()
        return [evento_public_dict(row) for row in rows]
    return listar(connection, table)


def alterar_senha_camera(connection: sqlite3.Connection, camera_id: str, password: str) -> bool:
    cursor = connection.execute(
        """
        UPDATE cameras
        SET rtsp_password = NULL,
            rtsp_password_encrypted = ?
        WHERE id = ?
        """,
        (encrypt_secret(password), camera_id),
    )
    connection.commit()
    return cursor.rowcount > 0


def criar_technical_notice(
    connection: sqlite3.Connection,
    component: str,
    cliente_id: str | None = None,
    camera_id: str | None = None,
    erro: str | None = None,
    inicio: str | None = None,
) -> str:
    existing = connection.execute(
        """
        SELECT id
        FROM technical_notices
        WHERE component = ? AND COALESCE(camera_id, '') = COALESCE(?, '') AND status = 'open'
        LIMIT 1
        """,
        (component, camera_id),
    ).fetchone()
    if existing:
        return str(existing["id"])
    notice_id = new_id("tec")
    connection.execute(
        """
        INSERT INTO technical_notices (id, cliente_id, camera_id, component, inicio, erro)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (notice_id, cliente_id, camera_id, component, inicio or now_iso(), erro),
    )
    connection.commit()
    return notice_id


def fechar_technical_notice(connection: sqlite3.Connection, notice_id: str, fim: str | None = None) -> bool:
    cursor = connection.execute(
        "UPDATE technical_notices SET status = 'closed', fim = ?, atualizado_em = CURRENT_TIMESTAMP WHERE id = ?",
        (fim or now_iso(), notice_id),
    )
    connection.commit()
    return cursor.rowcount > 0


def listar_technical_notices(connection: sqlite3.Connection, cliente_id: str | None = None) -> list[dict[str, Any]]:
    if cliente_id:
        rows = connection.execute(
            "SELECT * FROM technical_notices WHERE cliente_id = ? ORDER BY criado_em DESC LIMIT 200",
            (cliente_id,),
        ).fetchall()
    else:
        rows = connection.execute("SELECT * FROM technical_notices ORDER BY criado_em DESC LIMIT 200").fetchall()
    return [row_to_dict(row) for row in rows]


def set_installation_state(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        """
        INSERT INTO installation_state (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, atualizado_em = CURRENT_TIMESTAMP
        """,
        (key, value),
    )
    connection.commit()


def get_installation_state(connection: sqlite3.Connection) -> dict[str, str]:
    rows = connection.execute("SELECT key, value FROM installation_state").fetchall()
    return {row["key"]: row["value"] for row in rows}


def machine_monitor_public_dict(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    data["ativo"] = bool(data["ativo"])
    data["operator_present"] = bool(data.get("operator_present"))
    data["machine_polygon"] = json.loads(data.pop("machine_polygon_json"))
    data["operator_polygon"] = json.loads(data.pop("operator_polygon_json"))
    return data


def criar_machine_monitor(
    connection: sqlite3.Connection,
    client_id: str,
    unit_id: str,
    camera_id: str,
    nome: str,
    machine_polygon: list[dict[str, float]],
    operator_polygon: list[dict[str, float]],
    ativo: bool = True,
    motion_sensitivity: float = 25.0,
    stop_seconds: float = 10.0,
    recovery_seconds: float = 3.0,
    replay_pre_seconds: float = 60.0,
    replay_post_seconds: float = 30.0,
) -> str:
    monitor_id = new_id("mach")
    connection.execute(
        """
        INSERT INTO machine_monitors (
            id, client_id, unit_id, camera_id, nome, machine_polygon_json,
            operator_polygon_json, ativo, motion_sensitivity, stop_seconds,
            recovery_seconds, replay_pre_seconds, replay_post_seconds
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            monitor_id,
            client_id,
            unit_id,
            camera_id,
            nome,
            json.dumps(machine_polygon),
            json.dumps(operator_polygon),
            1 if ativo else 0,
            motion_sensitivity,
            stop_seconds,
            recovery_seconds,
            replay_pre_seconds,
            replay_post_seconds,
        ),
    )
    connection.commit()
    return monitor_id


def listar_machine_monitors_camera(connection: sqlite3.Connection, camera_id: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT * FROM machine_monitors WHERE camera_id = ? ORDER BY criado_em DESC",
        (camera_id,),
    ).fetchall()
    return [machine_monitor_public_dict(row) for row in rows]


def listar_machine_monitors_ativos_camera(connection: sqlite3.Connection, camera_id: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT * FROM machine_monitors WHERE camera_id = ? AND ativo = 1 ORDER BY criado_em DESC",
        (camera_id,),
    ).fetchall()
    return [machine_monitor_public_dict(row) for row in rows]


def obter_machine_monitor(connection: sqlite3.Connection, monitor_id: str) -> dict[str, Any] | None:
    row = connection.execute("SELECT * FROM machine_monitors WHERE id = ?", (monitor_id,)).fetchone()
    return machine_monitor_public_dict(row) if row else None


def atualizar_machine_monitor(
    connection: sqlite3.Connection,
    monitor_id: str,
    nome: str | None = None,
    machine_polygon: list[dict[str, float]] | None = None,
    operator_polygon: list[dict[str, float]] | None = None,
    ativo: bool | None = None,
    motion_sensitivity: float | None = None,
    motion_threshold: float | None = None,
    stop_seconds: float | None = None,
    recovery_seconds: float | None = None,
    calibration_status: str | None = None,
    running_motion: float | None = None,
    stopped_motion: float | None = None,
) -> dict[str, Any] | None:
    current = obter_machine_monitor(connection, monitor_id)
    if current is None:
        return None
    connection.execute(
        """
        UPDATE machine_monitors
        SET nome = ?,
            machine_polygon_json = ?,
            operator_polygon_json = ?,
            ativo = ?,
            motion_sensitivity = ?,
            motion_threshold = COALESCE(?, motion_threshold),
            stop_seconds = ?,
            recovery_seconds = ?,
            calibration_status = COALESCE(?, calibration_status),
            running_motion = COALESCE(?, running_motion),
            stopped_motion = COALESCE(?, stopped_motion),
            atualizado_em = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            nome if nome is not None else current["nome"],
            json.dumps(machine_polygon if machine_polygon is not None else current["machine_polygon"]),
            json.dumps(operator_polygon if operator_polygon is not None else current["operator_polygon"]),
            1 if (ativo if ativo is not None else current["ativo"]) else 0,
            motion_sensitivity if motion_sensitivity is not None else current["motion_sensitivity"],
            motion_threshold,
            stop_seconds if stop_seconds is not None else current["stop_seconds"],
            recovery_seconds if recovery_seconds is not None else current["recovery_seconds"],
            calibration_status,
            running_motion,
            stopped_motion,
            monitor_id,
        ),
    )
    connection.commit()
    return obter_machine_monitor(connection, monitor_id)


def excluir_machine_monitor(connection: sqlite3.Connection, monitor_id: str) -> bool:
    cursor = connection.execute("DELETE FROM machine_monitors WHERE id = ?", (monitor_id,))
    connection.commit()
    return cursor.rowcount > 0


def atualizar_machine_monitor_estado(
    connection: sqlite3.Connection,
    monitor_id: str,
    state: str,
    motion: float | None,
    operator_present: bool,
    changed_at: str | None = None,
) -> None:
    connection.execute(
        """
        UPDATE machine_monitors
        SET current_state = ?,
            current_motion = ?,
            operator_present = ?,
            last_state_change = COALESCE(?, last_state_change),
            atualizado_em = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (state, motion, 1 if operator_present else 0, changed_at, monitor_id),
    )
    connection.commit()


def criar_evento_machine_stoppage(
    connection: sqlite3.Connection,
    cliente_id: str,
    unidade_id: str,
    camera_id: str,
    machine_monitor_id: str,
    inicio: str,
    motion_level: float,
    operator_present_start: bool,
    confidence: float,
    midia_path: str | None,
    track_ids: list[int],
) -> str:
    evento_id = new_id("evt")
    connection.execute(
        """
        INSERT INTO eventos (
            id, cliente_id, unidade_id, camera_id, machine_monitor_id, tipo,
            severidade, status, inicio, motion_level, operator_present_start,
            operador_presente, confianca, midia_path, track_ids_json,
            operator_present_seconds, operator_absent_seconds, max_people
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            evento_id,
            cliente_id,
            unidade_id,
            camera_id,
            machine_monitor_id,
            "machine_stoppage",
            "medium",
            "open",
            inicio,
            motion_level,
            1 if operator_present_start else 0,
            1 if operator_present_start else 0,
            confidence,
            midia_path,
            json.dumps(sorted(set(track_ids))),
            0.0,
            0.0,
            len(set(track_ids)),
        ),
    )
    connection.commit()
    return evento_id


def atualizar_evento_machine_stoppage(
    connection: sqlite3.Connection,
    evento_id: str,
    duracao: float,
    motion_level: float,
    operator_present_seconds: float,
    operator_absent_seconds: float,
    max_people: int,
    track_ids: list[int],
) -> None:
    connection.execute(
        """
        UPDATE eventos
        SET duracao = ?,
            motion_level = ?,
            operator_present_seconds = ?,
            operator_absent_seconds = ?,
            max_people = ?,
            track_ids_json = ?,
            atualizado_em = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (duracao, motion_level, operator_present_seconds, operator_absent_seconds, max_people, json.dumps(sorted(set(track_ids))), evento_id),
    )
    connection.commit()


def fechar_evento_machine_stoppage(connection: sqlite3.Connection, evento_id: str, fim: str, duracao: float) -> None:
    connection.execute(
        """
        UPDATE eventos
        SET status = 'closed', fim = ?, duracao = ?, atualizado_em = CURRENT_TIMESTAMP
        WHERE id = ? AND status = 'open'
        """,
        (fim, duracao, evento_id),
    )
    connection.commit()


def atualizar_evento_replay(
    connection: sqlite3.Connection,
    evento_id: str,
    replay_path: str | None = None,
    replay_error: str | None = None,
) -> None:
    connection.execute(
        "UPDATE eventos SET replay_path = COALESCE(?, replay_path), replay_error = ?, atualizado_em = CURRENT_TIMESTAMP WHERE id = ?",
        (replay_path, replay_error, evento_id),
    )
    connection.commit()


def classificar_evento(
    connection: sqlite3.Connection,
    evento_id: str,
    cause_category: str,
    cause_notes: str | None,
    classified_by: str | None,
    classified_at: str,
) -> dict[str, Any] | None:
    connection.execute(
        """
        UPDATE eventos
        SET cause_category = ?,
            cause_notes = ?,
            classified_by = ?,
            classified_at = ?,
            atualizado_em = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (cause_category, cause_notes, classified_by, classified_at, evento_id),
    )
    connection.commit()
    return obter_evento(connection, evento_id)
