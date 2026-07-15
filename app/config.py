from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def env(name: str, default: str) -> str:
    return os.getenv(name, default)


DATABASE_PATH = Path(env("DATABASE_PATH", str(ROOT / "data" / "visual_ops_product.sqlite3")))
API_HOST = env("API_HOST", "127.0.0.1")
API_PORT = int(env("API_PORT", "8000"))
LOG_DIR = ROOT / "logs"

