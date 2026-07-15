from __future__ import annotations

import csv
import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any


def daily_report_data(connection: sqlite3.Connection, report_date: str | None = None) -> dict[str, Any]:
    day = report_date or date.today().isoformat()
    totals = connection.execute(
        """
        SELECT
            COUNT(*) AS quantidade_eventos,
            COALESCE(SUM(duracao), 0) AS tempo_total_parado,
            COALESCE(SUM(CASE WHEN operador_presente = 0 THEN duracao ELSE 0 END), 0) AS tempo_parado_sem_operador,
            COALESCE(MAX(duracao), 0) AS maior_parada
        FROM eventos
        WHERE substr(inicio, 1, 10) = ?
        """,
        (day,),
    ).fetchone()
    cameras = connection.execute(
        """
        SELECT
            SUM(CASE WHEN status = 'online' THEN 1 ELSE 0 END) AS online,
            SUM(CASE WHEN status != 'online' THEN 1 ELSE 0 END) AS offline
        FROM cameras
        """
    ).fetchone()
    return {
        "data": day,
        "quantidade_eventos": int(totals["quantidade_eventos"]),
        "tempo_total_parado": float(totals["tempo_total_parado"]),
        "tempo_parado_sem_operador": float(totals["tempo_parado_sem_operador"]),
        "maior_parada": float(totals["maior_parada"]),
        "cameras_online": int(cameras["online"] or 0),
        "cameras_offline": int(cameras["offline"] or 0),
    }


def save_daily_report(connection: sqlite3.Connection, output_dir: Path, report_date: str | None = None) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = daily_report_data(connection, report_date)
    stem = f"relatorio_diario_{data['data']}"
    json_path = output_dir / f"{stem}.json"
    csv_path = output_dir / f"{stem}.csv"
    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(data.keys()))
        writer.writeheader()
        writer.writerow(data)
    return {"json": json_path, "csv": csv_path}

