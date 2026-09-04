from __future__ import annotations

import os
import tempfile
import zipfile
from pathlib import Path


def build_windows_installer_cmd(
    *,
    cloud_url: str,
    edge_id: str,
    edge_secret: str,
    credential_key: str,
) -> str:
    cmd = r"""@echo off

powershell -NoProfile -Command "if (-not ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { exit 1 }"
if errorlevel 1 (
    echo Solicitando permissao de administrador...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

setlocal EnableDelayedExpansion
title Campex Edge

set "CAMPEX_CLOUD_URL=__CLOUD_URL__"
set "CAMPEX_EDGE_ID=__EDGE_ID__"
set "CAMPEX_EDGE_SECRET=__EDGE_SECRET__"
set "CAMPEX_CREDENTIAL_KEY=__CREDENTIAL_KEY__"

set "INSTALL_ROOT=%LOCALAPPDATA%\Campex\Edge"
set "PYTHON_ROOT=%INSTALL_ROOT%\.runtime\python"
set "PYTHON_EXE=%PYTHON_ROOT%\python.exe"
set "VENV_PYTHON=%INSTALL_ROOT%\.venv\Scripts\python.exe"
set "VENV_PYTHONW=%INSTALL_ROOT%\.venv\Scripts\pythonw.exe"
set "PACKAGE_ZIP=%TEMP%\campex-edge-package.zip"
set "PYTHON_INSTALLER=%TEMP%\campex-python-installer.exe"
set "STARTUP_FILE=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\CampexEdge.cmd"
set "ENV_FILE=%INSTALL_ROOT%\.env"

echo.
echo =========================================
echo            Instalando Campex
echo =========================================
echo.

if not exist "%INSTALL_ROOT%" mkdir "%INSTALL_ROOT%"
if not exist "%PYTHON_ROOT%" mkdir "%PYTHON_ROOT%"

if exist "%ENV_FILE%" (
    set "EXISTING_EDGE_ID="
    for /f "usebackq tokens=1,* delims==" %%A in ("%ENV_FILE%") do (
        if /I "%%A"=="CAMPEX_EDGE_ID" set "EXISTING_EDGE_ID=%%B"
    )

    if defined EXISTING_EDGE_ID (
        if /I not "!EXISTING_EDGE_ID!"=="%CAMPEX_EDGE_ID%" (
            echo.
            echo Este computador ja esta vinculado a outro Edge Campex.
            echo Instalacao atual: !EXISTING_EDGE_ID!
            echo Instalacao solicitada: %CAMPEX_EDGE_ID%
            echo.
            echo A Campex nao substituiu a identidade existente para evitar mistura entre unidades.
            goto :error
        )
    )

    echo Instalacao existente detectada. Preservando identidade, credenciais e dados locais.
)

echo [1/6] Baixando Campex Edge...

curl.exe -fL ^
  -H "X-Edge-Id: %CAMPEX_EDGE_ID%" ^
  -H "X-Edge-Secret: %CAMPEX_EDGE_SECRET%" ^
  "%CAMPEX_CLOUD_URL%/edge-package/windows" ^
  -o "%PACKAGE_ZIP%"

if errorlevel 1 goto :error

echo [2/6] Preparando arquivos...

tar.exe -xf "%PACKAGE_ZIP%" -C "%INSTALL_ROOT%"

if errorlevel 1 goto :error

if not exist "%PYTHON_EXE%" (
    echo [3/6] Preparando runtime Campex...

    curl.exe -fL ^
      "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe" ^
      -o "%PYTHON_INSTALLER%"

    if errorlevel 1 goto :error

    "%PYTHON_INSTALLER%" /quiet ^
      InstallAllUsers=0 ^
      PrependPath=0 ^
      Include_launcher=0 ^
      Include_test=0 ^
      Shortcuts=0 ^
      AssociateFiles=0 ^
      TargetDir="%PYTHON_ROOT%"

    if errorlevel 1 goto :error
) else (
    echo [3/6] Runtime Campex ja preparado.
)

if not exist "%VENV_PYTHON%" (
    echo [4/6] Criando ambiente Campex...
    "%PYTHON_EXE%" -m venv "%INSTALL_ROOT%\.venv"
    if errorlevel 1 goto :error
) else (
    echo [4/6] Ambiente Campex ja preparado.
)

echo [5/6] Instalando componentes...

"%VENV_PYTHON%" -m pip install ^
  --disable-pip-version-check ^
  --no-input ^
  -r "%INSTALL_ROOT%\requirements.txt"

if errorlevel 1 goto :error

if not exist "%ENV_FILE%" (
    > "%ENV_FILE%" (
        echo CAMPEX_CLOUD_URL=%CAMPEX_CLOUD_URL%
        echo CAMPEX_EDGE_ID=%CAMPEX_EDGE_ID%
        echo CAMPEX_EDGE_SECRET=%CAMPEX_EDGE_SECRET%
        echo CAMPEX_CREDENTIAL_KEY=%CAMPEX_CREDENTIAL_KEY%
        echo CAMPEX_EMAIL_MODE=cloud
    )
) else (
    echo [5/6] Arquivo .env existente preservado.
)

echo [6/6] Validando e iniciando Campex Edge...

pushd "%INSTALL_ROOT%"
"%VENV_PYTHON%" manage.py edge-config-check
if errorlevel 1 (
    popd
    goto :error
)
popd

rem Remove mecanismo legado da pasta Startup, se existir.
if exist "%STARTUP_FILE%" del /f /q "%STARTUP_FILE%" >nul 2>&1

rem Encerra launcher legado antes de instalar a tarefa oficial.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*run_campex_edge_windows.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1

pushd "%INSTALL_ROOT%"

"%VENV_PYTHON%" manage.py edge-service install
if errorlevel 1 (
    popd
    echo Nao foi possivel instalar o Campex Edge no Windows.
    goto :error
)

"%VENV_PYTHON%" manage.py edge-service start
if errorlevel 1 (
    popd
    echo O servico Campex Edge foi instalado, mas nao iniciou corretamente.
    goto :error
)

popd

curl.exe -fsS ^
  -X POST ^
  -H "Content-Type: application/json" ^
  -H "X-Edge-Id: %CAMPEX_EDGE_ID%" ^
  -H "X-Edge-Secret: %CAMPEX_EDGE_SECRET%" ^
  -d "{}" ^
  "%CAMPEX_CLOUD_URL%/edge/heartbeat" ^
  >nul

if errorlevel 1 (
    echo O Edge iniciou, mas nao conseguiu conectar ao Campex Cloud.
    goto :error
)

> "%USERPROFILE%\Desktop\Campex.url" (
    echo [InternetShortcut]
    echo URL=%CAMPEX_CLOUD_URL%
)

del "%PACKAGE_ZIP%" >nul 2>&1
del "%PYTHON_INSTALLER%" >nul 2>&1

echo.
echo =========================================
echo       Campex instalada com sucesso
echo =========================================
echo.
echo O Campex Edge esta rodando em segundo plano.
echo Voce pode fechar esta janela.
echo.

start "" "%CAMPEX_CLOUD_URL%/edges"
pause
exit /b 0

:error
echo.

if exist "%INSTALL_ROOT%\logs\edge.stderr.log" (
    echo Ultimo diagnostico automatico:
    echo -----------------------------------------
    type "%INSTALL_ROOT%\logs\edge.stderr.log"
    echo -----------------------------------------
)

echo =========================================
echo A instalacao da Campex nao foi concluida.
echo =========================================
echo.
echo Nao desative o Windows Defender.
echo Deixe esta janela aberta e informe a etapa acima.
echo.
pause
exit /b 1
"""

    return (
        cmd.replace("__CLOUD_URL__", cloud_url)
        .replace("__EDGE_ID__", edge_id)
        .replace("__EDGE_SECRET__", edge_secret)
        .replace("__CREDENTIAL_KEY__", credential_key)
    )


def create_windows_edge_package(project_root: Path) -> str:
    excluded_dirs = {
        ".git",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        "data",
        "logs",
        "tmp",
        "tests",
    }

    excluded_files = {
        ".env",
        ".DS_Store",
    }

    fd, zip_path = tempfile.mkstemp(
        prefix="campex-edge-",
        suffix=".zip",
    )
    os.close(fd)

    with zipfile.ZipFile(
        zip_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        for path in project_root.rglob("*"):
            relative = path.relative_to(project_root)

            if any(part in excluded_dirs for part in relative.parts):
                continue

            if path.name in excluded_files or path.is_dir():
                continue

            archive.write(path, arcname=str(relative))

    return zip_path
