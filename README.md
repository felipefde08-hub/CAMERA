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
