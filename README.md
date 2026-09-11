# CAMPEX

CAMPEX esta em Sprint 2 - Vision Core V1.

O objetivo atual e manter a Sprint 1 funcionando e acrescentar o primeiro Vision Core:

Camera
↕
CAMPEX Camera Layer
↕
FastAPI
↕
SQLite

Ainda nao existem Video Wall sofisticado, zonas funcionais, observations, rules engine, events engine ou evidence operacional.

## Stack

- Frontend: HTML, CSS e JavaScript ES Modules.
- Backend: Python 3.12+ com FastAPI.
- Camera Layer: OpenCV apenas para abrir fontes e ler frames.
- Vision: RF-DETR Nano por contrato modular, com fallback seguro quando o modelo nao carregar.
- Tracking: tracker modular com implementacao inicial `ByteTrackTracker`.
- Banco de desenvolvimento: SQLite.
- Testes: pytest.

## Estrutura

```text
backend/
  api/          rotas REST
  cameras/      CameraSource, fontes OpenCV, manager, repository e seguranca
  vision/       detector, tracker, sessoes, engine e overlay MJPEG
  database/     inicializacao SQLite
frontend/       shell CAMPEX e pagina administrativa de cameras
storage/        SQLite local e arquivos locais de desenvolvimento
tests/          testes automatizados
scripts/        utilitarios de desenvolvimento
docs/           especificacoes do produto
```

## Requisitos

- Python 3.12+
- pip

## Instalacao

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Variaveis de ambiente

Use `.env.example` como referencia:

- `CAMPEX_ENV`
- `CAMPEX_SERVICE_NAME`
- `CAMPEX_VERSION`
- `CAMPEX_LOG_LEVEL`
- `DATABASE_URL`
- `CAMPEX_FRONTEND_ORIGINS`
- `CAMERA_RECONNECT_SECONDS`
- `CAMERA_STALE_SECONDS`
- `CAMERA_READ_FAILURE_LIMIT`
- `CAMERA_TEST_TIMEOUT_SECONDS`
- `VISION_ENABLED`
- `VISION_DETECTOR`
- `VISION_DEVICE`
- `VISION_FPS`
- `VISION_CONFIDENCE`

## Inicializar Banco

```powershell
python scripts\init_db.py
```

Por padrao, o SQLite de desenvolvimento fica em `storage/campex_dev.sqlite3`.

## Iniciar Backend

```powershell
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

## Iniciar Frontend

Em outro terminal:

```powershell
python -m http.server 5500 --directory frontend
```

Acesse:

```text
http://127.0.0.1:5500
```

## Endpoints

```text
GET    /api/v1/health
GET    /api/v1/cameras
POST   /api/v1/cameras
GET    /api/v1/cameras/{id}
PATCH  /api/v1/cameras/{id}
DELETE /api/v1/cameras/{id}
POST   /api/v1/cameras/{id}/test
GET    /api/v1/cameras/{id}/health
POST   /api/v1/cameras/{id}/vision/start
POST   /api/v1/cameras/{id}/vision/stop
POST   /api/v1/cameras/{id}/vision/restart
GET    /api/v1/cameras/{id}/vision/status
GET    /api/v1/cameras/{id}/vision/objects
GET    /api/v1/cameras/{id}/stream
```

## CameraSource

Todas as fontes seguem a interface interna:

```text
connect()
read()
reconnect()
close()
health()
```

Tipos implementados:

- `webcam`: usa device index, por exemplo `0`.
- `video_file`: usa caminho local para arquivo de video.
- `rtsp`: usa URI RTSP. Credenciais sao sanitizadas nas respostas comuns e logs.

## Cadastrar Camera

Exemplo com arquivo de video:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/cameras -ContentType 'application/json' -Body '{
  "name": "Arquivo local",
  "source_type": "video_file",
  "source_uri": "C:\\videos\\teste.mp4",
  "enabled": false,
  "vision_enabled": false
}'
```

Exemplo com webcam:

```json
{
  "name": "Webcam local",
  "source_type": "webcam",
  "source_uri": "0",
  "enabled": true,
  "vision_enabled": false
}
```

Exemplo RTSP sem credenciais reais:

```json
{
  "name": "Camera IP",
  "source_type": "rtsp",
  "source_uri": "rtsp://usuario:senha@192.168.1.50/stream",
  "enabled": false,
  "vision_enabled": false
}
```

## Testar Conexao

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/cameras/{id}/test
```

O teste abre a fonte, tenta receber pelo menos um frame valido dentro do timeout configurado, retorna resolucao quando disponivel e fecha o recurso de captura.

## Health

Estados implementados:

- `CONNECTING`: tentativa de abertura em andamento.
- `ONLINE`: pelo menos um frame valido foi recebido recentemente.
- `DEGRADED`: fonte aberta ou ativa, mas sem frames validos recentes ou com falhas repetidas.
- `OFFLINE`: fonte fechada, inacessivel ou sem frame valido.

Campos retornados quando disponiveis:

- `camera_id`
- `status`
- `last_successful_frame`
- `last_error`
- `resolution`
- `approximate_fps`
- `reconnect_attempts`
- `frames_received`

## Vision Core V1

A Sprint 2 adiciona o primeiro pipeline modular:

```text
Camera Worker
↓
Latest Frame Buffer
↓
Vision Engine
↓
RFDETRDetector
↓
ByteTrackTracker
↓
TrackedObject
↓
MJPEG Stream com overlay
```

Inicie o backend e cadastre uma camera `video_file`, `webcam` ou `rtsp`. Na pagina `Ao vivo`, selecione a camera e use `Vision ON`.

Se RF-DETR nao estiver instalado ou nao conseguir carregar, a camera e o streaming continuam funcionando e o status da Vision fica `ERROR`.

Streaming inicial usa MJPEG em:

```text
GET /api/v1/cameras/{id}/stream
```

## Executar Testes

```powershell
python -m pytest
python -m compileall backend scripts tests
```

## Limitacoes Atuais

- RTSP foi implementado, mas precisa de validacao manual com uma camera RTSP real.
- RF-DETR pode exigir instalacao pesada de dependencias de ML e download/carregamento de modelo.
- A implementacao inicial do tracking mantem IDs por camera, mas ainda precisa validacao longa com videos reais.
- Nao ha upload complexo de videos; use caminhos locais de desenvolvimento.
- Zonas, observations, rules, events e evidence continuam fora desta Sprint.

## Status Atual

Sprint 2 - Vision Core V1 implementa:

- CRUD de cameras;
- CameraSource comum;
- WebcamSource;
- VideoFileSource;
- RTSPSource;
- CameraManager;
- health de cameras;
- teste real de fonte por frame;
- reconexao simples;
- sanitizacao de URI sensivel;
- pagina Câmeras funcional.

- pagina Ao vivo 1x1;
- stream MJPEG;
- Vision Engine;
- RFDETRDetector;
- ByteTrackTracker;
- start/stop/status/objects de Vision;
- overlay de bounding boxes no stream.

Funcionalidades de Sprint 3+ nao foram implementadas.
