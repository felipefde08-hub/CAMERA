from __future__ import annotations

import os
import subprocess
import sys
import time
import traceback
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs"
STDOUT_LOG = LOG_DIR / "edge.stdout.log"
STDERR_LOG = LOG_DIR / "edge.stderr.log"


def main() -> None:
    os.chdir(ROOT)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    python = Path(sys.executable)
    python_console = python.with_name("python.exe")
    if python_console.exists():
        python = python_console

    command = [
        str(python),
        str(ROOT / "manage.py"),
        "run-edge-production",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
    ]

    while True:
        try:
            with STDOUT_LOG.open("a", encoding="utf-8") as stdout, \
                 STDERR_LOG.open("a", encoding="utf-8") as stderr:
                process = subprocess.run(
                    command,
                    cwd=ROOT,
                    stdout=stdout,
                    stderr=stderr,
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                stderr.write(
                    f"\nCampex Edge encerrou com código "
                    f"{process.returncode}; reiniciando em 5s.\n"
                )
                stderr.flush()
        except Exception:
            with STDERR_LOG.open("a", encoding="utf-8") as stderr:
                traceback.print_exc(file=stderr)

        time.sleep(5)


if __name__ == "__main__":
    main()
