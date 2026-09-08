# Visual Operations MVP — Máquina parada x rodando

Este projeto recebe um vídeo gravado, webcam ou RTSP e mede:

- máquina rodando ou parada;
- quantidade de paradas;
- duração de cada parada;
- tempo total parado;
- CSV dos eventos;
- resumo JSON.

## Gestão da Campex

A direção, as decisões e a execução atual da Campex são registradas em:

- [Documento Mestre](docs/CAMPEX_MASTER.md)
- [Semana Atual](docs/SEMANA_ATUAL.md)

## Instalação Oficial Do MVP Atual

Para instalar a Campex em uma indústria nova, use o guia oficial atual:

- [Campex MVP Instalável V1](docs/INSTALL_MVP.md)

As seções antigas deste README permanecem como histórico técnico do desenvolvimento.

O código e os testes continuam sendo a fonte oficial sobre o estado técnico do produto.

## 1. Instalar no Mac

Abra o Terminal dentro desta pasta:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 2. Criar o vídeo de teste hoje

A forma mais rápida é deixar o celular fixo e gravar:

- a máquina rodando;
- pelo menos uma parada;
- a volta da operação.

Evite mover o celular. Coloque o vídeo nesta pasta e renomeie para:

```text
teste_maquina.mp4
```

## 3. Executar

```bash
python monitor_machine.py --source teste_maquina.mp4
```

Na primeira abertura:

1. marque com o mouse somente a parte que se movimenta quando a máquina funciona;
2. pressione Enter;
3. acompanhe `MOVIMENTO` e `LIMITE` na tela.

### Teclas

- `q`: sair;
- `espaço`: pausar;
- `r`: selecionar outra área;
- `+`: aumentar o limite de movimento;
- `-`: diminuir o limite;
- `s`: salvar imagem.

A máquina rodando precisa ficar acima do limite. A parada precisa ficar abaixo.

## 4. Resultado

A pasta `output/` será criada com:

- `eventos.csv`;
- `resumo.json`;
- `snapshots/`.

## 5. Testar a câmera ao vivo amanhã

Primeiro obtenha do DVR/NVR:

- marca e modelo;
- endereço IP local;
- usuário e senha;
- URL RTSP do canal.

Teste a conexão:

```bash
python check_source.py --source "rtsp://usuario:senha@IP:554/caminho"
```

Depois rode o monitor:

```bash
python monitor_machine.py --source "rtsp://usuario:senha@IP:554/caminho"
```

Não envie nem publique a senha da câmera.

## Limite atual

O MVP usa variação visual dentro da área selecionada. Ele ainda não reconhece causa de parada, EPI ou máquinas específicas. O objetivo de hoje é provar a medição automática de estado e duração.

## MVP local de produto

Foi adicionada uma camada separada para organizar clientes, unidades, câmeras,
regras, eventos, alertas e relatório diário em um banco SQLite local.

Para criar o banco:

```bash
python3 mvp.py init-db
```

Leia o passo a passo completo em:

```text
MVP_LOCAL.md
```

Essa camada não conecta câmeras ao vivo ainda e não altera o detector atual.

## API interna e estrutura de produto

A nova estrutura de produto fica em:

- `app/`: banco local, API interna e relatórios;
- `edge_agent/`: preparação para câmera ao vivo e fila offline;
- `shared/`: formatos compartilhados de evento e saúde de câmera.

Instale as dependências:

```bash
python3 -m pip install -r requirements.txt
```

Crie o banco local:

```bash
python3 manage.py init-db
```

Inicie a API interna:

```bash
python3 -m app.main
```

Exemplo de cadastro via terminal:

```bash
python3 manage.py add-cliente --nome "Cliente Teste"
python3 manage.py add-unidade --cliente-id CLI_ID --nome "Fabrica 1"
python3 manage.py add-camera --unidade-id UNI_ID --nome "Camera Linha 1"
python3 manage.py add-evento --cliente-id CLI_ID --unidade-id UNI_ID --camera-id CAM_ID --tipo machine_stopped --duracao 300 --operador-presente nao --confianca 0.90
python3 manage.py relatorio-diario
```

O arquivo `.env.example` mostra quais variáveis serão usadas futuramente para
câmeras ao vivo. Não coloque IP, usuário ou senha de câmera diretamente no código.

## Verificar compatibilidade de câmera ou vídeo

Use o verificador universal para arquivo, webcam ou RTSP:

```bash
python3 manage.py check-camera --source "teste_maquina.mp4"
python3 manage.py check-camera --source "0"
python3 manage.py check-camera --source "rtsp://usuario:senha@endereco/caminho"
```

O resultado informa conexão, vídeo recebido, resolução, FPS, tipo da conexão e
se a fonte é compatível. Usuário e senha de RTSP são mascarados na saída.

ONVIF foi preparado de forma isolada em `edge_agent/onvif_discovery.py`. Quando
houver uma câmera ONVIF disponível na rede local, a próxima etapa pode chamar a
descoberta e transformar o endereço encontrado em configuração segura da câmera.

## Rodar a Edge Box local

O comando principal do serviço contínuo é:

```bash
python3 manage.py run-edge --edge-id EDGE_ID
```

Ele carrega as câmeras cadastradas para aquele Edge, abre cada fonte em um
trabalhador independente, reconecta quando cair, atualiza status/último frame e
envia heartbeats e métricas locais.

Para consultar:

```bash
python3 manage.py edge-status --edge-id EDGE_ID
```

Para RTSP com senha, prefira variável de ambiente local, ignorada pelo Git:

```bash
export CAMERA_SOURCE_CAMERA_ID="rtsp://usuario:senha@endereco/caminho"
python3 manage.py run-edge --edge-id EDGE_ID
```

O arquivo `deployment/visual-ops-edge.service` é um modelo futuro para Linux com
systemd. Ele não instala nada agora; apenas mostra como a Edge Box poderá iniciar
automaticamente junto com o equipamento.

## Campex MVP - Etapa 1: cadastro e teste RTSP

O backend FastAPI agora também serve uma interface local simples em:

```bash
python3 -m app.main
```

Abra no navegador:

```text
http://127.0.0.1:8000
```

Nesta etapa é possível:

- cadastrar nome da câmera;
- informar IP/host, porta, usuário, senha e caminho RTSP;
- ou informar uma URL RTSP completa;
- testar conexão;
- ver Online/Offline, resolução e FPS quando possível;
- salvar a câmera no SQLite local.

As credenciais não aparecem na listagem pública nem nas respostas da API. A API
usa uma referência mascarada como `rtsp://***:***@host:554/caminho`.

Endpoints principais desta etapa:

- `GET /health`
- `POST /cameras/test-connection`
- `POST /cameras/rtsp`
- `GET /cameras/estado`

O fluxo principal do produto deve ser RTSP/câmera ao vivo. Upload de vídeo não é
o fluxo principal do MVP.

## Campex MVP - Etapa 2: visualização ao vivo

Depois de cadastrar uma câmera RTSP, use a própria interface local para clicar
em `Abrir câmera`. O backend abre uma única conexão por câmera e entrega a imagem
ao navegador como MJPEG.

Endpoints da visualização:

- `POST /cameras/{camera_id}/start`
- `POST /cameras/{camera_id}/stop`
- `GET /cameras/{camera_id}/stream`
- `GET /cameras/{camera_id}/status`

Comandos:

```bash
python3 -m app.main
```

Abra:

```text
http://127.0.0.1:8000
```

Para testar sem câmera real, cadastre uma câmera apontando para um arquivo local
ou use os testes automatizados. Para RTSP real, confirme primeiro o caminho do
DVR/NVR e use `Testar conexão`.

Erros comuns:

- `Offline`: host, porta, usuário, senha ou caminho RTSP incorreto.
- `Tentando reconectar`: a câmera abriu antes, mas parou de entregar frames.
- Sem imagem no navegador: verifique se o backend está rodando e se o status da
  câmera está `online`.

O navegador nunca recebe a URL RTSP completa nem as credenciais.

## Campex MVP - Etapa 3: detecção de pessoas

A visualização ao vivo pode desenhar caixas de pessoas usando YOLO. O modelo
padrão é leve:

```text
yolo11n.pt
```

Instale as dependências:

```bash
python3 -m pip install -r requirements.txt
```

Inicie:

```bash
python3 -m app.main
```

Abra:

```text
http://127.0.0.1:8000
```

Depois:

1. abra a câmera;
2. clique em `Ligar análise`;
3. veja as caixas, ID da pessoa e confiança diretamente na transmissão;
4. clique em `Desligar análise` para parar a análise daquela câmera.

Configurações por variável de ambiente:

```bash
export CAMPEX_YOLO_MODEL=yolo11n.pt
export CAMPEX_YOLO_CONFIDENCE=0.35
export CAMPEX_ANALYSIS_FPS=2
export CAMPEX_TRACKING_ENABLED=true
```

Se ficar lento no Mac, reduza:

```bash
export CAMPEX_ANALYSIS_FPS=1
export CAMPEX_YOLO_CONFIDENCE=0.45
```

Problemas comuns no Mac:

- primeira execução pode demorar enquanto o YOLO inicializa;
- sem `ultralytics`, a IA fica `indisponível`, mas a câmera continua ao vivo;
- CPU alta: reduza `CAMPEX_ANALYSIS_FPS`;
- pouca detecção: reduza `CAMPEX_YOLO_CONFIDENCE`.

Esta etapa não salva frames, não cria eventos, não envia alertas e não usa
WebSocket.

## Campex MVP - Etapa 4: área restrita

Com a câmera aberta, é possível desenhar uma área restrita sobre a imagem ao
vivo.

Como usar:

1. abra a câmera;
2. ligue a análise;
3. clique em `Criar área`;
4. clique nos pontos da imagem para formar o polígono;
5. use `Desfazer ponto` se errar;
6. clique em `Salvar área`;
7. informe um nome para a área.

O sistema salva os pontos em coordenadas normalizadas de `0` a `1`, não em pixels
da tela. Assim a área continua alinhada quando a janela ou a resolução mudam.

O painel mostra:

- nome da área ativa;
- estado `livre` ou `ocupada`;
- quantidade de pessoas dentro;
- IDs rastreados dentro da área.

Também é possível ativar, desativar e excluir a área pela interface.

Nesta etapa, o sistema apenas monitora presença dentro/fora da área. Ele ainda
não cria eventos, imagens, clipes, alertas, e-mail, WhatsApp ou WebSocket.

Problemas comuns:

- se a área parecer deslocada, recarregue a página e confira se o vídeo já está
  aberto antes de desenhar;
- se a ocupação não mudar, confira se a análise está ligada;
- pessoas muito na borda podem demorar alguns frames para mudar de estado por
  causa do debounce contra oscilações.

## Campex MVP - Etapa 5: ocorrências automáticas

Com a câmera aberta, a análise ligada e uma área restrita ativa, o sistema agora
registra uma ocorrência automaticamente quando uma pessoa permanece dentro da
área pelo tempo mínimo configurado.

Como testar:

1. inicie o backend;
2. abra `http://127.0.0.1:8000`;
3. abra uma câmera cadastrada;
4. clique em `Ligar análise`;
5. crie ou ative uma área restrita;
6. entre com uma pessoa na área;
7. aguarde a ocorrência aparecer em `Ocorrências recentes`;
8. saia da área e aguarde o fechamento automático;
9. clique em `Reconhecer` para marcar a ocorrência como verificada.

Comando para iniciar:

```bash
python3 -m app.main
```

Endpoints usados nesta etapa:

- `GET /eventos`
- `GET /eventos/{evento_id}`
- `PATCH /eventos/{evento_id}`
- `GET /eventos/{evento_id}/evidence`

O sistema salva uma imagem de evidência no início da ocorrência em:

```text
data/evidence/{camera_id}/{ano}/{mes}/{dia}/
```

Configurações por variável de ambiente:

```bash
export CAMPEX_EVENT_ENTRY_DELAY_SECONDS=1.0
export CAMPEX_EVENT_EXIT_GRACE_SECONDS=2.0
export CAMPEX_EVENT_COOLDOWN_SECONDS=3.0
export CAMPEX_EVENT_SEVERITY=high
```

Esses tempos evitam duplicidade:

- `ENTRY_DELAY`: a pessoa precisa ficar dentro da área antes de abrir ocorrência;
- `EXIT_GRACE`: a pessoa precisa sair por alguns segundos antes de fechar;
- `COOLDOWN`: evita abrir outra ocorrência imediatamente depois do fechamento.

Esta etapa não envia alertas, não usa e-mail, WhatsApp, SMS, sirene, WebSocket
ou integrações externas. Também não cria relatórios de violações ainda.

## Campex MVP - Etapa 6: alertas no painel e e-mail

Quando uma ocorrência de área restrita é aberta, o painel recebe um alerta em
tempo real por Server-Sent Events. O sistema também cria entregas de e-mail para
os responsáveis cadastrados.

Como testar sem e-mail real:

```bash
export CAMPEX_EMAIL_MODE=console
python3 -m app.main
```

Abra:

```text
http://127.0.0.1:8000
```

Na interface:

1. cadastre um responsável em `Responsáveis por alertas`;
2. clique em `Enviar alerta de teste`;
3. confira o alerta em `Alertas em tempo real`;
4. confira a entrega em `Entregas de e-mail`;
5. abra uma câmera, ligue a análise e use uma área restrita para gerar uma ocorrência real;
6. confira o alerta visual, a miniatura e os botões `Ver ocorrência` e `Reconhecer`.

O botão `Som ligado` permite ativar ou desativar o aviso sonoro no navegador. O
som toca uma vez por ocorrência, não em repetição.

Endpoints desta etapa:

- `GET /events/stream`
- `GET /alert-recipients`
- `POST /alert-recipients`
- `PATCH /alert-recipients/{recipient_id}`
- `DELETE /alert-recipients/{recipient_id}`
- `POST /alert-recipients/{recipient_id}/test`
- `GET /alert-deliveries`
- `GET /alert-deliveries/{delivery_id}`
- `POST /alert-deliveries/{delivery_id}/retry`

Configuração SMTP real:

```bash
export CAMPEX_EMAIL_MODE=smtp
export CAMPEX_SMTP_HOST=smtp.seudominio.com
export CAMPEX_SMTP_PORT=587
export CAMPEX_SMTP_USERNAME=usuario_smtp
export CAMPEX_SMTP_PASSWORD=senha_smtp
export CAMPEX_SMTP_USE_TLS=true
export CAMPEX_EMAIL_FROM=campex@seudominio.com
export CAMPEX_APP_URL=http://127.0.0.1:8000
export CAMPEX_EMAIL_MAX_ATTEMPTS=3
```

Para habilitar e-mail real, você precisa fornecer:

- servidor SMTP;
- porta SMTP;
- usuário SMTP;
- senha ou token SMTP;
- e-mail remetente autorizado;
- confirmação se usa TLS.

As credenciais ficam apenas no backend/ambiente local. O e-mail não inclui IP,
URL RTSP, usuário ou senha da câmera.

Se uma entrega falhar, ela aparece como `Falhou` no painel. Use `Tentar
novamente` para reenviar. Ao reiniciar o backend, entregas pendentes são
retomadas quando possível.

Limitações atuais:

- sem WhatsApp, SMS, aplicativo móvel, sirene, cobrança ou cloud;
- o painel usa SSE com reconexão automática e mantém consulta periódica como
  fallback;
- o modo `console` apenas registra que o e-mail seria enviado, sem envio real.

## Campex MVP - Etapa 7: piloto comercial assistido

Esta etapa prepara a instalação local para um primeiro cliente piloto, operado
com acompanhamento da equipe Campex.

### Guia técnico

Instalar:

```bash
./scripts/install.sh
./scripts/configure_env.sh
```

Edite `.env` e troque pelo menos:

```text
CAMPEX_SECRET_KEY
CAMPEX_CREDENTIAL_KEY
CAMPEX_EMAIL_MODE
CAMPEX_SMTP_HOST
CAMPEX_SMTP_PORT
CAMPEX_SMTP_USERNAME
CAMPEX_SMTP_PASSWORD
CAMPEX_EMAIL_FROM
```

Criar o primeiro usuário:

```bash
source .venv/bin/activate
python3 manage.py create-user --email admin@campex.local --senha "SENHA_FORTE" --role admin_campex
```

Iniciar:

```bash
./scripts/start.sh
```

Abrir:

```text
http://127.0.0.1:8000
```

Parar:

```bash
./scripts/stop.sh
```

Status:

```bash
./scripts/status.sh
python3 manage.py system-health
python3 manage.py pilot-checklist
```

Backup:

```bash
python3 manage.py backup --output-dir backups
```

Restauração:

```bash
python3 manage.py restore --archive backups/NOME_DO_BACKUP.tar.gz
```

Retenção de evidências antigas:

```bash
python3 manage.py prune-evidence --days 90 --confirm
```

Dados locais:

- banco SQLite: `data/visual_ops_product.sqlite3`;
- evidências: `data/evidence/`;
- backups: `backups/`;
- configuração local: `.env`;
- logs locais: `logs/`.

Segurança adicionada:

- login por e-mail e senha;
- senha com hash PBKDF2;
- sessão HTTP-only;
- funções `admin_campex`, `admin_cliente`, `operador` e `visualizador`;
- filtro básico por cliente nas consultas principais;
- senha RTSP criptografada no banco para novos cadastros;
- rota administrativa para trocar senha de câmera;
- ocultação de dados técnicos para operador/visualizador.

### Guia simples para implantação

O que pedir ao cliente:

- nome da empresa e unidade;
- local onde ficará o computador da Campex;
- ponto de rede e energia estáveis;
- IP/host do DVR, NVR ou câmera;
- porta RTSP;
- usuário e senha da câmera;
- canal/caminho RTSP;
- e-mails dos responsáveis pelos alertas;
- horário em que o teste pode ser feito com segurança;
- autorização para gravar evidências locais.

Passo a passo do piloto:

1. instalar a Campex no computador local;
2. criar usuário administrador;
3. cadastrar cliente;
4. cadastrar unidade;
5. cadastrar câmera;
6. testar conexão;
7. abrir transmissão;
8. ligar IA;
9. desenhar área restrita;
10. cadastrar responsáveis;
11. enviar alerta de teste;
12. gerar uma ocorrência controlada;
13. conferir evidência, alerta no painel e e-mail;
14. rodar `python3 manage.py pilot-checklist`;
15. combinar data de revisão do piloto.

Checklist de aceite:

- login funcionando;
- usuário do cliente não vê dados de outro cliente;
- câmera conectada;
- transmissão ao vivo abrindo;
- IA ativa;
- área criada;
- ocorrência automática criada;
- evidência salva;
- alerta aparece no painel;
- e-mail de teste entregue ou registrado em modo console;
- backup criado;
- saúde da instalação sem erro crítico.

Limitações e riscos nesta versão:

- ainda não há WhatsApp, SMS, pagamento, app móvel ou cloud;
- isolamento é local e simples, adequado para piloto assistido;
- não há atualização remota automática;
- o computador local precisa permanecer ligado;
- SMTP real depende das credenciais fornecidas pelo cliente;
- a criptografia depende da preservação segura de `CAMPEX_SECRET_KEY`;
- a operação em larga escala ainda não foi implementada.

## CAMPEX OPERATIONS V1

Esta evolução adiciona monitoramento operacional de máquina parada usando a
câmera ao vivo já cadastrada. A regra antiga de pessoa em área restrita continua
existindo.

O que a Campex passa a identificar:

- `running`: máquina funcionando;
- `suspected_stop`: possível parada, aguardando tempo mínimo;
- `stopped`: parada confirmada;
- `recovered`: movimento voltou de forma estável;
- `unavailable`: análise indisponível.

Como cadastrar uma máquina:

1. abra a câmera;
2. clique em `Adicionar máquina`;
3. clique nos pontos da região visual da máquina;
4. clique em `Próxima zona`;
5. clique nos pontos da zona onde o operador costuma ficar;
6. clique em `Salvar máquina`;
7. informe o nome da máquina.

Como calibrar:

1. deixe a máquina funcionando normalmente;
2. clique em `Calibrar`;
3. informe o movimento médio funcionando;
4. deixe a máquina parada;
5. informe o movimento médio parada;
6. a Campex sugere um limite entre os dois valores.

Configurações por ambiente:

```bash
export CAMPEX_MACHINE_ANALYSIS_FPS=5
export CAMPEX_MACHINE_STOP_SECONDS=10
export CAMPEX_MACHINE_RECOVERY_SECONDS=3
export CAMPEX_MACHINE_MOTION_SMOOTHING_SECONDS=2
export CAMPEX_REPLAY_PRE_SECONDS=60
export CAMPEX_REPLAY_POST_SECONDS=30
export CAMPEX_REPLAY_FPS=5
export CAMPEX_REPLAY_MAX_WIDTH=1280
```

Quando uma parada é confirmada:

- cria uma ocorrência `machine_stoppage`;
- registra início, câmera, unidade e máquina;
- registra movimento, confiança e presença do operador;
- mantém uma única ocorrência aberta enquanto a máquina está parada;
- fecha a ocorrência quando a recuperação permanece estável;
- salva imagem principal;
- gera Replay Causal em segundo plano em `data/replays/{camera_id}/{ano}/{mes}/{dia}/`.

Para abrir Replay Causal:

- use o botão `Abrir Replay Causal` na ocorrência quando o clipe estiver pronto;
- ou acesse `GET /eventos/{evento_id}/replay`.

Para informar causa:

1. abra `Ocorrências recentes`;
2. clique em `Informar causa`;
3. escolha uma das categorias:
   `manutenção`, `falta de material`, `ajuste de máquina`, `intervalo`,
   `operador ausente`, `bloqueio de processo`, `parada planejada`,
   `falso alerta` ou `outra`.

Endpoints Operations V1:

- `GET /cameras/{camera_id}/machine-monitors`
- `POST /cameras/{camera_id}/machine-monitors`
- `PATCH /machine-monitors/{monitor_id}`
- `DELETE /machine-monitors/{monitor_id}`
- `POST /machine-monitors/{monitor_id}/activate`
- `POST /machine-monitors/{monitor_id}/deactivate`
- `POST /machine-monitors/{monitor_id}/calibrate`
- `GET /eventos/{evento_id}/replay`
- `PATCH /eventos/{evento_id}/cause`
- `GET /operations`

Limitações atuais:

- a calibração assistida ainda recebe os valores medidos de forma simples pela
  interface;
- o método usa visão computacional clássica, não modelo personalizado;
- Replay Causal é gerado localmente e pode demorar dependendo do computador;
- não há WhatsApp, cloud ou treinamento próprio nesta etapa.

## Sprint final do piloto: cadastros persistentes

Abra `http://127.0.0.1:8000/settings/cameras` para configurar o piloto local.

Fluxo recomendado:

1. cadastrar o cliente, por exemplo `FL Plásticos`;
2. cadastrar a unidade;
3. cadastrar o usuário do cliente;
4. cadastrar a câmera RTSP;
5. cadastrar a máquina/área vinculada à câmera;
6. cadastrar o destinatário de alerta;
7. clicar em `Enviar alerta de teste`;
8. reiniciar a aplicação e conferir que os dados continuam salvos.

Dados sensíveis:

- senha de usuário é salva com hash;
- senha RTSP é criptografada no banco;
- a API não devolve senha nem URL RTSP completa;
- operador e visualizador não recebem detalhes técnicos da câmera.

Endpoints de configuração:

- `GET /clientes`
- `POST /clientes`
- `GET /unidades`
- `POST /unidades`
- `GET /auth/users`
- `POST /auth/users`
- `POST /cameras/rtsp`
- `GET /cameras/estado`
- `GET /cameras/{camera_id}/machine-monitors`
- `POST /cameras/{camera_id}/machine-monitors`
- `GET /alert-recipients`
- `POST /alert-recipients`
- `POST /alert-recipients/{recipient_id}/test`
- `GET /alert-deliveries`

## Executando a Campex na fábrica — Windows

Esta forma de execução é para o computador local instalado na fábrica. Ele acessa
o DVR/câmeras RTSP pela rede interna, executa backend, processamento visual e
interface web no próprio Windows e permite abrir a Campex pelo navegador em
`localhost` ou por outros dispositivos da mesma rede local.

Não use Vercel, cloud, port forwarding ou abertura de porta no roteador para
acessar DVR/RTSP. Nesta etapa, a Campex deve funcionar somente dentro da rede
local da fábrica.

### Versão e componentes

- Python recomendado: `Python 3.11 64-bit`.
- Python mínimo aceito pelos scripts: `Python 3.9`.
- Entrypoint real do backend: `python -m app.main`.
- Comando real de inicialização no Windows: `.\scripts\start_factory_windows.ps1`.
- Frontend separado: não precisa. O FastAPI serve a interface em HTML/CSS/JS.
- Porta padrão: `8000`.
- Host de fábrica: `0.0.0.0`, para permitir acesso por outros dispositivos da LAN.

Dependências de sistema:

- Git para clonar o repositório;
- Python 3.11 64-bit com `Add python.exe to PATH` marcado;
- FFmpeg no `PATH`, recomendado para melhor suporte a stream, snapshot e replay;
- acesso de rede local ao DVR/câmeras RTSP;
- firewall do Windows liberando a porta local escolhida, por exemplo `8000`,
  somente na rede privada/local.

Variáveis principais do `.env`:

- `DATABASE_PATH`: caminho do SQLite local. Padrão: `data/visual_ops_product.sqlite3`;
- `API_HOST`: usado pelo app. O script de fábrica força `0.0.0.0` ao iniciar;
- `API_PORT`: porta HTTP local. Padrão: `8000`;
- `CAMPEX_SECRET_KEY`: chave local de sessão;
- `CAMPEX_CREDENTIAL_KEY`: chave local para credenciais sensíveis;
- `CAMPEX_YOLO_MODEL`: modelo YOLO, por exemplo `yolo11n.pt`;
- `CAMPEX_YOLO_CONFIDENCE`: confiança mínima;
- `CAMPEX_ANALYSIS_FPS`: FPS de análise;
- `CAMPEX_YOLO_CLASSES`: classes analisadas. Padrão: `person`;
- `CAMPEX_EMAIL_MODE`: `console` ou `smtp`;
- `CAMPEX_SMTP_HOST`, `CAMPEX_SMTP_PORT`, `CAMPEX_SMTP_USERNAME`,
  `CAMPEX_SMTP_PASSWORD`, `CAMPEX_SMTP_USE_TLS`: somente se usar SMTP.

Credenciais de DVR/RTSP não devem ser colocadas em logs, prints ou arquivos
versionados. O arquivo `.env` já é ignorado pelo Git e o setup nunca sobrescreve
um `.env` existente.

### Instalação desde o clone

Abra o PowerShell no Windows:

```powershell
git clone https://github.com/SEU_USUARIO/CAMERA.git
cd CAMERA
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\setup_factory_windows.ps1
```

Depois edite o arquivo `.env` gerado e troque pelo menos:

```text
CAMPEX_SECRET_KEY=uma-chave-grande-do-piloto
CAMPEX_CREDENTIAL_KEY=outra-chave-grande-do-piloto
CAMPEX_EMAIL_MODE=console
```

Se for usar envio real de e-mail, configure também as variáveis SMTP.

Se o setup der erro, rode o diagnóstico e envie a saída:

```powershell
.\scripts\diagnose_factory_windows.ps1
```

### Iniciar

```powershell
.\scripts\start_factory_windows.ps1
```

O terminal exibirá duas URLs:

```text
Localhost: http://127.0.0.1:8000
Rede local: http://IP_DA_MAQUINA:8000
```

No próprio computador da fábrica, abra:

```text
http://127.0.0.1:8000/dashboard
```

Em outro dispositivo da mesma rede local, abra:

```text
http://IP_DA_MAQUINA:8000/dashboard
```

Também é possível iniciar por duplo clique:

```text
start_campex.bat
```

### Parar

No terminal onde a Campex está rodando, pressione:

```text
Ctrl+C
```

Ou execute em outro PowerShell:

```powershell
.\scripts\stop_factory_windows.ps1
```

### Dados persistentes

O setup cria e preserva:

- banco local: `data/visual_ops_product.sqlite3`;
- evidências: `data/evidence/`;
- replays: `data/replays/`;
- logs: `logs/`;
- backups: `backups/`.

Reiniciar a aplicação não apaga clientes, câmeras, eventos, regras, alertas ou
evidências. O script de inicialização evita abrir duas instâncias ao mesmo tempo
usando `logs/campex.pid`.

### Observações de segurança

- Não exponha a porta `8000` para a internet.
- Não configure port forwarding no roteador.
- Não tente acessar o DVR/RTSP por serviço em nuvem.
- Use apenas a rede local da fábrica.
- O RTSP e as senhas ficam no backend/banco local; o navegador não recebe a URL
  completa nem a senha.

## Primeira integração Edge -> Cloud

Esta etapa envia apenas eventos operacionais. O Cloud não acessa RTSP, IP do DVR,
vídeo ao vivo nem câmera privada da fábrica.

Fluxo:

```text
evento local -> SQLite local -> sync_outbox -> HTTPS -> Campex Cloud -> PostgreSQL -> dashboard
```

### Cloud local de desenvolvimento

Sem `DATABASE_URL`, o Cloud usa SQLite local em `data/campex_cloud.sqlite3`:

```bash
python3 -m cloud.main
```

Abra:

```text
http://127.0.0.1:8000/health
```

### Cloud no Render

Comandos configurados:

```text
Build Command: pip install -r requirements.txt
Start Command: python -m cloud.main
Health Check Path: /health
```

O arquivo `render.yaml` cria um Web Service e um PostgreSQL.

Variáveis do Cloud:

```text
DATABASE_URL=postgresql://...
CLOUD_HOST=0.0.0.0
PORT=8000
```

O Render normalmente preenche `DATABASE_URL` a partir do banco configurado no
`render.yaml`. Nenhuma credencial deve ser commitada.

### Migration

A migration reproduzível está em:

```text
cloud/migrations/001_edge_cloud.sql
```

Ela cria:

- `edge_devices`;
- `edge_events`;
- índices de evento, cliente, unidade, câmera, Edge e data de recebimento.

### Cadastrar o primeiro Edge da FL Plásticos

Gere um segredo forte e guarde somente no `.env` do Edge:

```bash
python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
```

Cadastre o Edge no Cloud:

```bash
curl -X POST https://SUA-CAMPEX-CLOUD.onrender.com/admin/edge-devices \
  -H "Content-Type: application/json" \
  -d '{
    "id": "edge_fl_plasticos_01",
    "tenant_id": "cli_fl_plasticos",
    "cliente_id": "cli_fl_plasticos",
    "unidade_id": "uni_fl_plasticos_matriz",
    "nome": "Edge FL Plasticos - Matriz",
    "secret": "COLE_AQUI_O_SEGREDO_GERADO"
  }'
```

No `.env` local da Edge Box:

```text
CAMPEX_EDGE_ID=edge_fl_plasticos_01
CAMPEX_EDGE_SECRET=COLE_AQUI_O_SEGREDO_GERADO
CAMPEX_CLOUD_URL=https://SUA-CAMPEX-CLOUD.onrender.com
```

### Sincronizar eventos da outbox

Quando um evento é criado localmente por `registrar_evento`, ele recebe
`event_uuid` e entra em `sync_outbox`.

Para validar manualmente sem mexer em RTSP, YOLO ou regras:

```bash
python3 manage.py sync-cloud
```

Se o Cloud estiver fora do ar, a outbox permanece no SQLite local com status
`failed` e tenta novamente depois com backoff. O monitoramento local continua
funcionando.

Para deixar a sincronização tentando continuamente:

```bash
python3 manage.py sync-cloud --loop
```

### Validar no Cloud

```bash
curl https://SUA-CAMPEX-CLOUD.onrender.com/health
curl https://SUA-CAMPEX-CLOUD.onrender.com/eventos
```

`POST /edge/events` exige:

- `X-Edge-Id`;
- `X-Edge-Secret`;
- `Idempotency-Key` igual ao `event_uuid`.

Reenviar o mesmo `event_uuid` não duplica evento.

## Validação local Edge -> Cloud com PostgreSQL

Esta validação roda Edge e Cloud no mesmo computador, mas mantém as camadas
separadas:

```text
Campex Edge local -> SQLite local -> sync_outbox -> HTTP local -> Campex Cloud local -> PostgreSQL local -> dashboard Cloud
```

O Edge nunca acessa o PostgreSQL. O Cloud nunca acessa o SQLite do Edge.

### 1. Iniciar PostgreSQL local

Com Docker instalado:

```bash
docker compose -f docker-compose.cloud-local.yml up -d
```

URL local do banco:

```text
postgresql://campex:campex_local_dev@127.0.0.1:5432/campex_cloud
```

### 2. Iniciar o Cloud local

Use uma porta diferente da aplicação Edge local. Exemplo: Cloud na `8010`.

```bash
export DATABASE_URL="postgresql://campex:campex_local_dev@127.0.0.1:5432/campex_cloud"
export PORT=8010
python3 -m cloud.main
```

Validar:

```bash
curl http://127.0.0.1:8010/health
```

Abrir dashboard Cloud:

```text
http://127.0.0.1:8010/dashboard
```

### 3. Configurar o Edge local para falar com o Cloud

Em outro terminal:

```bash
export CAMPEX_CLOUD_URL="http://127.0.0.1:8010"
export CAMPEX_EDGE_ID="edge_fl_plasticos_01"
export CAMPEX_EDGE_SECRET="secret-local-com-mais-de-12"
export CAMPEX_TENANT_ID="cli_fl_plasticos"
export CAMPEX_UNIDADE_ID="uni_fl_plasticos_matriz"
export CAMPEX_CAMERA_ID="cam_fl_plasticos_01"
```

### 4. Cadastrar o Edge da FL Plásticos no Cloud

O script de validação abaixo cadastra o Edge automaticamente se ainda não existir.
Para cadastrar manualmente:

```bash
curl -X POST http://127.0.0.1:8010/admin/edge-devices \
  -H "Content-Type: application/json" \
  -d '{
    "id": "edge_fl_plasticos_01",
    "tenant_id": "cli_fl_plasticos",
    "cliente_id": "cli_fl_plasticos",
    "unidade_id": "uni_fl_plasticos_matriz",
    "nome": "Edge FL Plasticos - Matriz",
    "secret": "secret-local-com-mais-de-12"
  }'
```

Em piloto real, troque `CAMPEX_EDGE_SECRET` por uma chave forte gerada localmente.
Não coloque essa chave no Git.

### 5. Disparar um evento de teste sem câmera real

Com o Cloud ligado:

```bash
python3 scripts/validate_edge_cloud_local.py
```

Resultado esperado:

```text
Evento local criado: evt_...
Outbox pendente antes: 0
Sincronizados agora: 1
Outbox pendente depois: 0
Dashboard Cloud: http://127.0.0.1:8010/dashboard
```

Abra:

```text
http://127.0.0.1:8010/dashboard
```

O dashboard deve mostrar exatamente o evento recebido pelo Cloud. Ele vem de
`edge_events`, não do SQLite do Edge.

### 6. Validar Cloud desligado -> Edge guarda -> Cloud volta -> sincroniza

Com o Cloud desligado, crie um evento local normalmente. Por exemplo, usando IDs
já existentes no Edge:

```bash
python3 manage.py add-evento \
  --cliente-id cli_fl_plasticos \
  --unidade-id uni_fl_plasticos_matriz \
  --camera-id cam_fl_plasticos_01 \
  --tipo machine_stoppage \
  --duracao 300 \
  --operador-presente nao \
  --confianca 0.91
```

Confira que ficou pendente:

```bash
python3 manage.py sync-cloud
```

Se o Cloud estiver desligado, a outbox fica preservada com status `failed`.

Ligue o Cloud novamente e rode:

```bash
python3 manage.py sync-cloud
```

Resultado esperado:

```text
Sincronizados agora: 1
Pendentes depois: 0
```

### 7. Confirmar diretamente no Cloud

```bash
curl http://127.0.0.1:8010/eventos
curl http://127.0.0.1:8010/operations/events
```

Reenviar o mesmo `event_uuid` retorna `duplicate` e não cria uma segunda linha.

### 8. Validar com a câmera real da FL Plásticos

Use este teste apenas depois que a Live View e a regra operacional já estiverem
funcionando localmente.

1. Inicie o Edge normalmente na fábrica e confirme que a câmera está abrindo.
2. Deixe o Cloud local desligado.
3. Gere uma ocorrência real pela regra configurada, por exemplo parada de máquina
   ou pessoa em área restrita.
4. Confira que o evento entrou na outbox local:

```bash
python3 manage.py sync-cloud
```

Com o Cloud desligado, o esperado é ficar pendente/failed, preservado no SQLite.

5. Ligue o Cloud local:

```bash
export DATABASE_URL="postgresql://campex:campex_local_dev@127.0.0.1:5432/campex_cloud"
export PORT=8010
python3 -m cloud.main
```

6. Em outro terminal, sincronize:

```bash
export CAMPEX_CLOUD_URL="http://127.0.0.1:8010"
export CAMPEX_EDGE_ID="edge_fl_plasticos_01"
export CAMPEX_EDGE_SECRET="secret-local-com-mais-de-12"
python3 manage.py sync-cloud
```

7. Abra o dashboard Cloud:

```text
http://127.0.0.1:8010/dashboard
```

Critério esperado:

- aparece um único evento para a ocorrência;
- `event_uuid` não muda entre reenvios;
- horário original da ocorrência vem do Edge;
- `camera_id`, `unidade_id`, `tipo`, `severidade`, `status` e `duracao`
  aparecem no payload recebido pelo Cloud;
- não existe envio frame a frame;
- se o evento fechar depois, o mesmo `event_uuid` é atualizado, não duplicado.
