# Visual Operations MVP — Máquina parada x rodando

Este projeto recebe um vídeo gravado, webcam ou RTSP e mede:

- máquina rodando ou parada;
- quantidade de paradas;
- duração de cada parada;
- tempo total parado;
- CSV dos eventos;
- resumo JSON.

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
