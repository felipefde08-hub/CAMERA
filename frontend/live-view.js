const liveViewName = document.querySelector("#liveViewName");
const liveViewStatus = document.querySelector("#liveViewStatus");
const liveViewStage = document.querySelector("#liveViewStage");
const liveViewMessage = document.querySelector("#liveViewMessage");
const liveViewImage = document.querySelector("#liveViewImage");
const liveViewCanvas = document.querySelector("#liveViewCanvas");
const liveViewResolution = document.querySelector("#liveViewResolution");
const liveViewFps = document.querySelector("#liveViewFps");
const liveViewInferenceFps = document.querySelector("#liveViewInferenceFps");
const liveViewPeople = document.querySelector("#liveViewPeople");
const liveViewMachine = document.querySelector("#liveViewMachine");
const liveViewMachineState = document.querySelector("#liveViewMachineState");
const liveViewOperator = document.querySelector("#liveViewOperator");
const liveViewMotion = document.querySelector("#liveViewMotion");
const liveViewRelation = document.querySelector("#liveViewRelation");
const liveViewHint = document.querySelector("#liveViewHint");
const liveAiStart = document.querySelector("#liveAiStart");
const liveAiStop = document.querySelector("#liveAiStop");
const configureMachine = document.querySelector("#configureMachine");
const configureOperatorZone = document.querySelector("#configureOperatorZone");
const calibrateMachine = document.querySelector("#calibrateMachine");
const clearMachine = document.querySelector("#clearMachine");
const liveRailName = document.querySelector("#liveRailName");

let sessionId = null;
let statusTimer = null;
let drawMode = null;
let draftPoints = [];
let machineConfig = null;

async function requestJson(url, options) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : { detail: await response.text() };
  if (!response.ok) {
    throw new Error(payload.detail || `Erro HTTP ${response.status}`);
  }
  return payload;
}

function sourcePayload() {
  const stored = sessionStorage.getItem("campex_live_view_source");
  if (!stored) return null;
  return JSON.parse(stored);
}

function setStatus(status, message) {
  liveViewStatus.textContent = status;
  liveViewStatus.classList.toggle("offline", status !== "online");
  liveViewStage.classList.toggle("online", status === "online");
  if (message) liveViewMessage.textContent = message;
}

function canvasRect() {
  const rect = liveViewCanvas.getBoundingClientRect();
  liveViewCanvas.width = Math.max(1, Math.round(rect.width));
  liveViewCanvas.height = Math.max(1, Math.round(rect.height));
  return rect;
}

function drawPolygon(points, color, fill) {
  if (!points.length) return;
  const ctx = liveViewCanvas.getContext("2d");
  ctx.beginPath();
  points.forEach((point, index) => {
    const x = point.x * liveViewCanvas.width;
    const y = point.y * liveViewCanvas.height;
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  if (points.length >= 3) ctx.closePath();
  ctx.strokeStyle = color;
  ctx.lineWidth = 3;
  ctx.stroke();
  if (fill && points.length >= 3) {
    ctx.fillStyle = fill;
    ctx.fill();
  }
}

function drawCanvas() {
  canvasRect();
  const ctx = liveViewCanvas.getContext("2d");
  ctx.clearRect(0, 0, liveViewCanvas.width, liveViewCanvas.height);
  if (machineConfig) {
    drawPolygon(machineConfig.machine_polygon || [], "#38bdf8", "rgba(56, 189, 248, 0.10)");
    drawPolygon(machineConfig.operator_polygon || [], "#f97316", "rgba(249, 115, 22, 0.10)");
  }
  if (drawMode) {
    drawPolygon(draftPoints, drawMode === "machine" ? "#38bdf8" : "#f97316", drawMode === "machine" ? "rgba(56, 189, 248, 0.15)" : "rgba(249, 115, 22, 0.15)");
  }
}

function renderStatus(payload) {
  const status = payload.status || "offline";
  const ops = payload.ops || {};
  machineConfig = ops.machine || machineConfig;
  liveViewName.textContent = payload.nome || "Live View";
  if (liveRailName) liveRailName.textContent = payload.nome || "Live View";
  liveViewResolution.textContent = payload.width && payload.height ? `${payload.width}x${payload.height}` : "indisponível";
  liveViewFps.textContent = payload.fps ?? "indisponível";
  liveViewInferenceFps.textContent = ops.inference_fps ?? 0;
  liveViewPeople.textContent = ops.people_count ?? 0;
  liveViewMachine.textContent = machineConfig ? machineConfig.nome : "sem configuração";
  liveViewMachineState.textContent = ops.machine_state || "SEM SINAL";
  liveViewOperator.textContent = ops.operator_present ? `Operador presente (${ops.operator_people_count})` : "Sem operador";
  liveViewMotion.textContent = `${ops.machine_motion ?? 0}${ops.machine_threshold ? ` / limite ${ops.machine_threshold.toFixed ? ops.machine_threshold.toFixed(2) : ops.machine_threshold}` : ""}`;
  liveViewRelation.textContent = ops.relation || "Aguardando configuração";
  if (status === "online") {
    setStatus("online");
  } else if (status === "conectando" || status === "reconectando") {
    setStatus(status, "Tentando reconectar...");
  } else {
    setStatus("offline", payload.error || "Câmera offline.");
  }
  drawCanvas();
}

async function pollStatus() {
  if (!sessionId) return;
  try {
    renderStatus(await requestJson(`/live-view/${sessionId}/status`));
  } catch (error) {
    setStatus("offline", error.message);
  }
}

async function startLiveView() {
  const payload = sourcePayload();
  if (!payload) {
    setStatus("offline", "Volte à página inicial, teste o RTSP e clique em Abrir Live View.");
    return;
  }
  liveViewName.textContent = payload.nome || "Live View";
  if (liveRailName) liveRailName.textContent = payload.nome || "Live View";
  setStatus("conectando", "Abrindo transmissão...");
  const started = await requestJson("/live-view/start", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  sessionId = started.session_id;
  renderStatus({ nome: payload.nome, ...started.status });
  liveViewImage.src = `/live-view/${sessionId}/stream?ts=${Date.now()}`;
  liveViewImage.onerror = () => setStatus("offline", "Sem imagem no momento. Tentando reconectar...");
  statusTimer = setInterval(pollStatus, 1500);
}

function startDrawing(mode) {
  if (!sessionId) return;
  drawMode = mode;
  draftPoints = [];
  liveViewStage.classList.add("drawing");
  liveViewHint.textContent = mode === "machine"
    ? "Clique nos pontos da região visual da máquina. Clique em Configurar máquina novamente para salvar."
    : "Clique nos pontos da zona do operador. Clique em Configurar zona do operador novamente para salvar.";
  drawCanvas();
}

async function finishMachineDrawing() {
  if (draftPoints.length < 3) {
    startDrawing("machine");
    return;
  }
  const nome = window.prompt("Nome da máquina", "Extrusora principal");
  if (!nome) return;
  const payload = await requestJson(`/live-view/${sessionId}/machine`, {
    method: "POST",
    body: JSON.stringify({ nome, machine_polygon: draftPoints }),
  });
  machineConfig = payload.machine;
  drawMode = null;
  draftPoints = [];
  liveViewStage.classList.remove("drawing");
  liveViewHint.textContent = "Máquina configurada. Calibre com a máquina ativa.";
  renderStatus({ status: "online", ops: payload });
}

async function finishOperatorDrawing() {
  if (draftPoints.length < 3) {
    startDrawing("operator");
    return;
  }
  const payload = await requestJson(`/live-view/${sessionId}/operator-zone`, {
    method: "POST",
    body: JSON.stringify({ operator_polygon: draftPoints }),
  });
  machineConfig = payload.machine;
  drawMode = null;
  draftPoints = [];
  liveViewStage.classList.remove("drawing");
  liveViewHint.textContent = "Zona do operador configurada.";
  renderStatus({ status: "online", ops: payload });
}

liveAiStart.addEventListener("click", () => {
  if (!sessionId) return;
  requestJson(`/live-view/${sessionId}/ai/start`, { method: "POST" }).then((ops) => renderStatus({ status: "online", ops })).catch((error) => setStatus("offline", error.message));
});

liveAiStop.addEventListener("click", () => {
  if (!sessionId) return;
  requestJson(`/live-view/${sessionId}/ai/stop`, { method: "POST" }).then((ops) => renderStatus({ status: "online", ops })).catch((error) => setStatus("offline", error.message));
});

configureMachine.addEventListener("click", () => {
  if (drawMode === "machine") finishMachineDrawing().catch((error) => setStatus("offline", error.message));
  else startDrawing("machine");
});

configureOperatorZone.addEventListener("click", () => {
  if (drawMode === "operator") finishOperatorDrawing().catch((error) => setStatus("offline", error.message));
  else startDrawing("operator");
});

calibrateMachine.addEventListener("click", () => {
  if (!sessionId) return;
  requestJson(`/live-view/${sessionId}/machine/calibrate-active`, { method: "POST" }).then((ops) => renderStatus({ status: "online", ops })).catch((error) => setStatus("offline", error.message));
});

clearMachine.addEventListener("click", () => {
  if (!sessionId) return;
  requestJson(`/live-view/${sessionId}/machine`, { method: "DELETE" }).then((ops) => {
    machineConfig = null;
    renderStatus({ status: "online", ops });
  }).catch((error) => setStatus("offline", error.message));
});

liveViewCanvas.addEventListener("click", (event) => {
  if (!drawMode) return;
  const rect = canvasRect();
  draftPoints.push({
    x: Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)),
    y: Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height)),
  });
  drawCanvas();
});

window.addEventListener("resize", drawCanvas);

window.addEventListener("beforeunload", () => {
  if (statusTimer) clearInterval(statusTimer);
  if (sessionId) fetch(`/live-view/${sessionId}/stop`, { method: "POST", keepalive: true }).catch(() => {});
});

startLiveView().catch((error) => setStatus("offline", error.message));
