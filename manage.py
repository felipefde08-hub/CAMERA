from __future__ import annotations

import argparse
import logging
import os
import signal
from pathlib import Path

from app.database import connect, init_db
from app.auth import create_user, update_user_password
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
from app.pilot import acceptance_checklist, create_backup, health_snapshot, prune_old_evidence, restore_backup
from app.machine_replay import run_machine_replay
from edge_agent.camera_connector import detect_source_type, safe_source_ref
from edge_agent.camera_check import check_camera
from edge_agent.service import EdgeSupervisor, edge_status
from edge_agent.sync_outbox import flush_sync_outbox, pending_sync_count, run_sync_loop


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Comandos locais do MVP de produto.")
    parser.add_argument("--db", default="data/visual_ops_product.sqlite3")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init-db")

    user = subparsers.add_parser("create-user")
    user.add_argument("--email", required=True)
    user.add_argument("--senha", required=True)
    user.add_argument("--role", required=True, choices=["admin_campex", "admin_cliente", "operador", "visualizador"])
    user.add_argument("--cliente-id")

    reset = subparsers.add_parser("reset-password")
    reset.add_argument("--email", required=True)
    reset.add_argument("--nova-senha", required=True)

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

    run_edge = subparsers.add_parser("run-edge")
    run_edge.add_argument("--edge-id", required=True)
    run_edge.add_argument("--api-url", default=os.getenv("API_URL"))
    run_edge.add_argument("--heartbeat-seconds", type=float, default=10.0)

    status = subparsers.add_parser("edge-status")
    status.add_argument("--edge-id", required=True)

    backup = subparsers.add_parser("backup")
    backup.add_argument("--output-dir", default="backups")

    restore = subparsers.add_parser("restore")
    restore.add_argument("--archive", required=True)

    retention = subparsers.add_parser("prune-evidence")
    retention.add_argument("--days", type=int, required=True)
    retention.add_argument("--confirm", action="store_true")

    subparsers.add_parser("system-health")
    subparsers.add_parser("pilot-checklist")

    sync_cloud = subparsers.add_parser("sync-cloud")
    sync_cloud.add_argument("--cloud-url", default=os.getenv("CAMPEX_CLOUD_URL"))
    sync_cloud.add_argument("--edge-id", default=os.getenv("CAMPEX_EDGE_ID"))
    sync_cloud.add_argument("--edge-secret", default=os.getenv("CAMPEX_EDGE_SECRET"))
    sync_cloud.add_argument("--loop", action="store_true")
    sync_cloud.add_argument("--interval-seconds", type=float, default=10.0)

    replay = subparsers.add_parser("machine-replay")
    replay.add_argument("--video", required=True)
    replay.add_argument("--machine-config", required=True)
    replay.add_argument("--annotations", required=True)
    replay.add_argument("--output", default="reports/machine_replay_report.json")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "sync-cloud" and args.loop:
        if not args.cloud_url or not args.edge_id or not args.edge_secret:
            raise SystemExit("Configure CAMPEX_CLOUD_URL, CAMPEX_EDGE_ID e CAMPEX_EDGE_SECRET.")
        print(f"Sincronizando outbox com {args.cloud_url}. Pressione Ctrl+C para parar.")
        run_sync_loop(args.db, args.cloud_url, args.edge_id, args.edge_secret, args.interval_seconds)
        return 0

    with connect(args.db) as connection:
        init_db(connection)
        if args.command == "init-db":
            print(f"Banco local pronto: {args.db}")
        elif args.command == "create-user":
            print(create_user(connection, args.email, args.senha, args.role, args.cliente_id))
        elif args.command == "reset-password":
            print("senha atualizada" if update_user_password(connection, args.email, args.nova_senha) else "usuario nao encontrado")
        elif args.command == "add-cliente":
            print(criar_cliente(connection, args.nome))
        elif args.command == "add-unidade":
            print(criar_unidade(connection, args.cliente_id, args.nome, args.localizacao))
        elif args.command == "add-dispositivo":
            print(criar_dispositivo(connection, args.unidade_id, args.nome))
        elif args.command == "add-camera":
            source_type = detect_source_type(args.source).value if args.source else None
            secure_ref = safe_source_ref(args.source) if args.source else None
            config_ref = args.config_ref
            if args.source and source_type in {"file", "webcam"}:
                config_ref = args.source
            print(criar_camera(
                connection,
                args.unidade_id,
                args.nome,
                args.dispositivo_id,
                config_ref,
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
        elif args.command == "run-edge":
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s %(levelname)s %(name)s: %(message)s",
            )
            supervisor = EdgeSupervisor(
                edge_id=args.edge_id,
                db_path=Path(args.db),
                api_url=args.api_url,
                heartbeat_seconds=args.heartbeat_seconds,
            )
            def stop_service(_signum: int, _frame: object) -> None:
                supervisor.shutdown()
                raise SystemExit(0)

            signal.signal(signal.SIGTERM, stop_service)
            signal.signal(signal.SIGINT, stop_service)
            try:
                supervisor.run_forever()
            except KeyboardInterrupt:
                print("\nEdge encerrado pelo usuario.")
                supervisor.shutdown()
        elif args.command == "edge-status":
            status = edge_status(args.edge_id, Path(args.db))
            print(f"Edge: {args.edge_id}")
            print(f"Status: {status['edge_status']}")
            print(f"Ultimo contato: {status['ultimo_contato'] or 'indisponivel'}")
            print(f"Tempo ligado: {int(status['uptime_seconds'])} segundos")
            print(f"CPU: {status['cpu_percent'] if status['cpu_percent'] is not None else 'indisponivel'}")
            print(f"Memoria: {status['memory_percent'] if status['memory_percent'] is not None else 'indisponivel'}")
            print(f"Cameras cadastradas: {status['cameras_total']}")
            print(f"Cameras online: {status['cameras_online']}")
            print(f"Cameras offline: {status['cameras_offline']}")
            print(f"Eventos pendentes na fila: {status['eventos_pendentes']}")
            for camera in status["cameras"]:
                print(
                    "- "
                    f"{camera['nome']} ({camera['id']}): {camera['status']} | "
                    f"ultimo frame: {camera.get('ultimo_frame') or 'nunca'} | "
                    f"reconexoes: {camera.get('reconexoes') or 0} | "
                    f"erro: {camera.get('ultimo_erro') or 'nenhum'}"
                )
        elif args.command == "backup":
            print(create_backup(Path(args.output_dir), Path(args.db)))
        elif args.command == "restore":
            restore_backup(Path(args.archive))
            print("Backup restaurado.")
        elif args.command == "prune-evidence":
            removed = prune_old_evidence(args.days, args.confirm)
            print(f"Evidencias removidas: {len(removed)}")
        elif args.command == "system-health":
            print(health_snapshot(Path(args.db)))
        elif args.command == "pilot-checklist":
            print(acceptance_checklist(Path(args.db)))
        elif args.command == "sync-cloud":
            if not args.cloud_url or not args.edge_id or not args.edge_secret:
                raise SystemExit("Configure CAMPEX_CLOUD_URL, CAMPEX_EDGE_ID e CAMPEX_EDGE_SECRET.")
            before = pending_sync_count(connection)
            synced = flush_sync_outbox(connection, args.cloud_url, args.edge_id, args.edge_secret)
            after = pending_sync_count(connection)
            print(f"Pendentes antes: {before}")
            print(f"Sincronizados agora: {synced}")
            print(f"Pendentes depois: {after}")
        elif args.command == "machine-replay":
            report = run_machine_replay(args.video, args.machine_config, args.annotations, args.output)
            metrics = report["metrics"]
            print(f"Relatorio: {args.output}")
            print(f"Tempo correto por estado: {metrics['tempo_correto_percentual']}%")
            print(f"Transicoes anotadas: {metrics['transicoes_anotadas']}")
            print(f"Transicoes perdidas: {metrics['transicoes_perdidas']}")
            print(f"Confianca media: {metrics['confianca_media']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
