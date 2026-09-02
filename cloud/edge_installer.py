from __future__ import annotations

import base64
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
    powershell = r'''$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "========================================="
Write-Host "          Instalando Campex"
Write-Host "========================================="
Write-Host ""

$CloudUrl = "__CLOUD_URL__"
$EdgeId = "__EDGE_ID__"
$EdgeSecret = "__EDGE_SECRET__"
$CredentialKey = "__CREDENTIAL_KEY__"

$InstallRoot = Join-Path $env:LOCALAPPDATA "Campex\Edge"
$RuntimeRoot = Join-Path $InstallRoot ".runtime"
$PythonRoot = Join-Path $RuntimeRoot "python"
$PythonExe = Join-Path $PythonRoot "python.exe"
$VenvPython = Join-Path $InstallRoot ".venv\Scripts\python.exe"
$PackageZip = Join-Path $env:TEMP "campex-edge-package.zip"
$PythonInstaller = Join-Path $env:TEMP "campex-python-installer.exe"

New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null

Write-Host "[1/6] Baixando Campex Edge..."

$headers = @{
    "X-Edge-Id" = $EdgeId
    "X-Edge-Secret" = $EdgeSecret
}

Invoke-WebRequest `
    -UseBasicParsing `
    -Uri "$CloudUrl/edge-package/windows" `
    -Headers $headers `
    -OutFile $PackageZip

Write-Host "[2/6] Preparando arquivos..."

Expand-Archive `
    -Path $PackageZip `
    -DestinationPath $InstallRoot `
    -Force

if (-not (Test-Path $PythonExe)) {
    Write-Host "[3/6] Instalando runtime da Campex..."

    Invoke-WebRequest `
        -UseBasicParsing `
        -Uri "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe" `
        -OutFile $PythonInstaller

    $process = Start-Process `
        -FilePath $PythonInstaller `
        -ArgumentList @(
            "/quiet",
            "InstallAllUsers=0",
            "PrependPath=0",
            "Include_launcher=0",
            "Include_test=0",
            "TargetDir=$PythonRoot"
        ) `
        -Wait `
        -PassThru

    if ($process.ExitCode -ne 0) {
        throw "Nao foi possivel instalar o runtime da Campex."
    }
} else {
    Write-Host "[3/6] Runtime Campex ja instalado."
}

if (-not (Test-Path $VenvPython)) {
    Write-Host "[4/6] Preparando ambiente..."
    & $PythonExe -m venv (Join-Path $InstallRoot ".venv")
} else {
    Write-Host "[4/6] Ambiente ja preparado."
}

Write-Host "[5/6] Instalando componentes..."

& $VenvPython -m pip install `
    --disable-pip-version-check `
    --quiet `
    -r (Join-Path $InstallRoot "requirements.txt")

if ($LASTEXITCODE -ne 0) {
    throw "Falha ao instalar componentes da Campex."
}

$EnvContent = @"
CAMPEX_CLOUD_URL=$CloudUrl
CAMPEX_EDGE_ID=$EdgeId
CAMPEX_EDGE_SECRET=$EdgeSecret
CAMPEX_CREDENTIAL_KEY=$CredentialKey
CAMPEX_EMAIL_MODE=cloud
"@

Set-Content `
    -Path (Join-Path $InstallRoot ".env") `
    -Value $EnvContent `
    -Encoding UTF8

Write-Host "[6/6] Iniciando Campex Edge..."

Push-Location $InstallRoot

& $VenvPython manage.py edge-service install
if ($LASTEXITCODE -ne 0) {
    Pop-Location
    throw "Nao foi possivel instalar o Campex Edge em segundo plano."
}

& $VenvPython manage.py edge-service start
if ($LASTEXITCODE -ne 0) {
    Pop-Location
    throw "Campex Edge foi instalado, mas nao iniciou."
}

Pop-Location

$Desktop = [Environment]::GetFolderPath("Desktop")
$Shortcut = Join-Path $Desktop "Campex.url"

@"
[InternetShortcut]
URL=$CloudUrl
"@ | Set-Content -Path $Shortcut -Encoding ASCII

Remove-Item $PackageZip -Force -ErrorAction SilentlyContinue
Remove-Item $PythonInstaller -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "========================================="
Write-Host "       Campex instalada com sucesso"
Write-Host "========================================="
Write-Host ""
Write-Host "O monitoramento continuara em segundo plano."

Start-Process "$CloudUrl/edges"
'''

    powershell = (
        powershell
        .replace("__CLOUD_URL__", cloud_url)
        .replace("__EDGE_ID__", edge_id)
        .replace("__EDGE_SECRET__", edge_secret)
        .replace("__CREDENTIAL_KEY__", credential_key)
    )

    encoded = base64.b64encode(
        powershell.encode("utf-16le")
    ).decode("ascii")

    cmd = r'''@echo off
title Instalando Campex

echo.
echo Iniciando instalacao da Campex...
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -EncodedCommand __ENCODED__

if errorlevel 1 (
    echo.
    echo [ERRO] A instalacao da Campex nao foi concluida.
    echo Mantenha esta janela aberta para diagnostico.
    pause
    exit /b 1
)

echo.
echo Campex pronta.
timeout /t 3 /nobreak >nul
del "%~f0"
exit /b 0
'''

    return cmd.replace("__ENCODED__", encoded)


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
