from __future__ import annotations

import argparse
from pathlib import Path

from app.database import connect, init_db
from app.models import (
    criar_camera,
    criar_cliente,
    criar_dispositivo,
    criar_regra,
    criar_unidade,
    listar,
    registrar_evento,
)
from app.reports import save_daily_report
from edge_agent.camera_connector import detect_source_type, safe_source_ref
from edge_agent.camera_check import check_camera


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Comandos locais do MVP de produto.")
    parser.add_argument("--db", default="data/visual_ops_product.sqlite3")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init-db")

    cliente = subparsers.add_parser("add-cliente")
    cliente.add_argument("--nome", required=True)

    unidade = subparsers.add_parser("add-unidade")
    unidade.add_argument("--cliente-id", required=True)
    unidade.add_argument("--nome", required=True)
    unidade.add_argument("--localizacao")

    dispositivo = subparsers.add_parser("add-dispositivo")
    dispositivo.add_argument("--unidade-id", required=True)
    dispositivo.add_argument("--nome", required=True)

    camera = subparsers.add_parser("add-camera")
    camera.add_argument("--unidade-id", required=True)
    camera.add_argument("--nome", required=True)
    camera.add_argument("--cliente-id")
    camera.add_argument("--dispositivo-id")
    camera.add_argument("--edge-id")
    camera.add_argument("--config-ref")
    camera.add_argument("--source")

    regra = subparsers.add_parser("add-regra")
    regra.add_argument("--camera-id", required=True)
    regra.add_argument("--tipo-evento", required=True)
    regra.add_argument("--tempo-minimo", type=float, default=0)

    evento = subparsers.add_parser("add-evento")
    evento.add_argument("--cliente-id", required=True)
    evento.add_argument("--unidade-id", required=True)
    evento.add_argument("--camera-id", required=True)
    evento.add_argument("--tipo", required=True)
    evento.add_argument("--duracao", type=float)
    evento.add_argument("--operador-presente", choices=["sim", "nao"])
    evento.add_argument("--confianca", type=float)

    report = subparsers.add_parser("relatorio-diario")
    report.add_argument("--data")
    report.add_argument("--output-dir", default="reports")

    listing = subparsers.add_parser("list")
    listing.add_argument("table", choices=["clientes", "unidades", "dispositivos", "cameras", "regras", "eventos", "alertas"])

    camera_check = subparsers.add_parser("check-camera")
    camera_check.add_argument("--source", required=True)
    camera_check.add_argument("--timeout", type=float, default=5.0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    with connect(args.db) as connection:
        init_db(connection)
        if args.command == "init-db":
            print(f"Banco local pronto: {args.db}")
        elif args.command == "add-cliente":
            print(criar_cliente(connection, args.nome))
        elif args.command == "add-unidade":
            print(criar_unidade(connection, args.cliente_id, args.nome, args.localizacao))
        elif args.command == "add-dispositivo":
            print(criar_dispositivo(connection, args.unidade_id, args.nome))
        elif args.command == "add-camera":
            source_type = detect_source_type(args.source).value if args.source else None
            secure_ref = safe_source_ref(args.source) if args.source else None
            print(criar_camera(
                connection,
                args.unidade_id,
                args.nome,
                args.dispositivo_id,
                args.config_ref,
                cliente_id=args.cliente_id,
                edge_id=args.edge_id,
                source_type=source_type,
                secure_ref=secure_ref,
            ))
        elif args.command == "add-regra":
            print(criar_regra(connection, args.camera_id, args.tipo_evento, args.tempo_minimo))
        elif args.command == "add-evento":
            operador = None
            if args.operador_presente:
                operador = args.operador_presente == "sim"
            print(registrar_evento(
                connection,
                args.cliente_id,
                args.unidade_id,
                args.camera_id,
                args.tipo,
                duracao=args.duracao,
                operador_presente=operador,
                confianca=args.confianca,
            ))
        elif args.command == "relatorio-diario":
            paths = save_daily_report(connection, Path(args.output_dir), args.data)
            print(f"JSON: {paths['json']}")
            print(f"CSV: {paths['csv']}")
        elif args.command == "list":
            for row in listar(connection, args.table):
                print(row)
        elif args.command == "check-camera":
            result = check_camera(args.source, args.timeout)
            print(f"conexao_realizada: {'sim' if result.conexao_realizada else 'nao'}")
            print(f"video_recebido: {'sim' if result.video_recebido else 'nao'}")
            print(f"resolucao: {result.resolucao or 'indisponivel'}")
            print(f"fps: {result.fps if result.fps is not None else 'indisponivel'}")
            print(f"tipo_conexao: {result.tipo_conexao}")
            print(f"compativel: {'sim' if result.compativel else 'nao'}")
            print(f"referencia_segura: {result.referencia_segura}")
            if result.motivo_erro:
                print(f"motivo_erro: {result.motivo_erro}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
