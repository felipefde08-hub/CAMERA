@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [CAMPEX] Criando ambiente virtual...
    py -3.12 -m venv .venv
    if errorlevel 1 (
        echo [CAMPEX] Nao foi possivel criar o ambiente com py -3.12.
        echo [CAMPEX] Tentando com python...
        python -m venv .venv
        if errorlevel 1 goto error
    )
)

echo [CAMPEX] Instalando/atualizando dependencias...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto error
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto error

echo [CAMPEX] Inicializando banco de dados...
".venv\Scripts\python.exe" scripts\init_db.py
if errorlevel 1 goto error

echo [CAMPEX] Iniciando backend em http://0.0.0.0:8000
".venv\Scripts\python.exe" -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
goto end

:error
echo.
echo [CAMPEX] Falha ao iniciar o backend.
pause

:end
endlocal
