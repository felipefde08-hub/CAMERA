from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.config import ROOT
from app.edge_config import EdgeConfigError, validate_edge_config


LABEL = "com.campex.edge"
TEMPLATE_PATH = ROOT / "deployment" / f"{LABEL}.plist"
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
PLIST_PATH = LAUNCH_AGENTS_DIR / f"{LABEL}.plist"
LAUNCHER_PATH = ROOT / "deployment" / "run-campex-edge.sh"
STDOUT_LOG = ROOT / "logs" / "edge.stdout.log"
STDERR_LOG = ROOT / "logs" / "edge.stderr.log"


@dataclass(frozen=True)
class EdgeServiceResult:
    ok: bool
    message: str


def render_plist(root: Path = ROOT) -> str:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    return template.replace("__CAMPEX_ROOT__", str(root))


def validate_plist(text: str) -> dict:
    return plistlib.loads(text.encode("utf-8"))


def _run_launchctl(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["launchctl", *args],
        text=True,
        capture_output=True,
        check=False,
    )


def _ensure_service_files() -> None:
    if not LAUNCHER_PATH.exists():
        raise RuntimeError(f"Launcher não encontrado: {LAUNCHER_PATH}")
    LAUNCHER_PATH.chmod(LAUNCHER_PATH.stat().st_mode | 0o111)
    (ROOT / "logs").mkdir(parents=True, exist_ok=True)
    LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)


def install_service() -> EdgeServiceResult:
    try:
        validate_edge_config()
    except EdgeConfigError as exc:
        return EdgeServiceResult(False, f"Campex Edge configuration error:\n{exc}")
    _ensure_service_files()
    text = render_plist()
    validate_plist(text)
    PLIST_PATH.write_text(text, encoding="utf-8")
    try:
        PLIST_PATH.chmod(0o644)
    except OSError:
        pass
    return EdgeServiceResult(True, f"Serviço instalado em {PLIST_PATH}")


def uninstall_service() -> EdgeServiceResult:
    stop_service()
    if PLIST_PATH.exists():
        PLIST_PATH.unlink()
    return EdgeServiceResult(True, f"Serviço removido de {PLIST_PATH}")


def start_service() -> EdgeServiceResult:
    if not PLIST_PATH.exists():
        install = install_service()
        if not install.ok:
            return install
    user_domain = f"gui/{os.getuid()}"
    bootstrap = _run_launchctl(["bootstrap", user_domain, str(PLIST_PATH)])
    if bootstrap.returncode not in {0, 5}:
        return EdgeServiceResult(False, bootstrap.stderr.strip() or bootstrap.stdout.strip() or "Falha ao carregar serviço.")
    kickstart = _run_launchctl(["kickstart", "-k", f"{user_domain}/{LABEL}"])
    if kickstart.returncode != 0:
        return EdgeServiceResult(False, kickstart.stderr.strip() or kickstart.stdout.strip() or "Falha ao iniciar serviço.")
    return EdgeServiceResult(True, "Serviço Campex Edge iniciado.")


def stop_service() -> EdgeServiceResult:
    user_domain = f"gui/{os.getuid()}"
    result = _run_launchctl(["bootout", user_domain, str(PLIST_PATH)])
    if result.returncode not in {0, 36, 113}:
        return EdgeServiceResult(False, result.stderr.strip() or result.stdout.strip() or "Falha ao parar serviço.")
    return EdgeServiceResult(True, "Serviço Campex Edge parado.")


def restart_service() -> EdgeServiceResult:
    stopped = stop_service()
    if not stopped.ok:
        return stopped
    return start_service()


def service_status() -> EdgeServiceResult:
    user_domain = f"gui/{os.getuid()}"
    result = _run_launchctl(["print", f"{user_domain}/{LABEL}"])
    if result.returncode == 0:
        return EdgeServiceResult(True, result.stdout.strip() or "Serviço carregado.")
    detail = result.stderr.strip() or result.stdout.strip() or "Serviço não carregado."
    return EdgeServiceResult(True, detail)


def service_logs(lines: int = 80) -> EdgeServiceResult:
    paths = [STDOUT_LOG, STDERR_LOG]
    output: list[str] = []
    for path in paths:
        output.append(f"== {path} ==")
        if path.exists():
            tail = shutil.which("tail")
            if tail:
                result = subprocess.run([tail, "-n", str(lines), str(path)], text=True, capture_output=True, check=False)
                output.append(result.stdout.rstrip())
            else:
                output.extend(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
        else:
            output.append("Log ainda não existe.")
    return EdgeServiceResult(True, "\n".join(output))


def run_edge_service_command(action: str) -> EdgeServiceResult:
    actions = {
        "install": install_service,
        "uninstall": uninstall_service,
        "start": start_service,
        "stop": stop_service,
        "restart": restart_service,
        "status": service_status,
        "logs": service_logs,
    }
    return actions[action]()
