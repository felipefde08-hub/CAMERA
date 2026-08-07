const liveViewName = document.querySelector("#liveViewName");
const liveViewStatus = document.querySelector("#liveViewStatus");
const liveViewStage = document.querySelector("#liveViewStage");
const liveViewMessage = document.querySelector("#liveViewMessage");
const liveViewImage = document.querySelector("#liveViewImage");
const liveViewCanvas = document.querySelector("#liveViewCanvas");
const liveStreamSummary = document.querySelector("#liveStreamSummary");
const liveViewResolution = document.querySelector("#liveViewResolution");
const liveViewFps = document.querySelector("#liveViewFps");
const liveViewInferenceFps = document.querySelector("#liveViewInferenceFps");
const liveViewPeople = document.querySelector("#liveViewPeople");
const liveViewAsset = document.querySelector("#liveViewAsset");
const liveViewPath = document.querySelector("#liveViewPath");
const liveViewMachine = document.querySelector("#liveViewMachine");
const liveViewMachineState = document.querySelector("#liveViewMachineState");
const liveViewOperator = document.querySelector("#liveViewOperator");
const liveViewSituation = document.querySelector("#liveViewSituation");
const liveViewMotion = document.querySelector("#liveViewMotion");
const liveViewRawScore = document.querySelector("#liveViewRawScore");
const liveViewFramesAnalyzed = document.querySelector("#liveViewFramesAnalyzed");
const liveViewRoi = document.querySelector("#liveViewRoi");
const liveViewAnalysisStatus = document.querySelector("#liveViewAnalysisStatus");
const liveViewConfidence = document.querySelector("#liveViewConfidence");
const liveViewStateTime = document.querySelector("#liveViewStateTime");
const liveViewReason = document.querySelector("#liveViewReason");
const liveViewRelation = document.querySelector("#liveViewRelation");
const liveViewHint = document.querySelector("#liveViewHint");
const liveCriticalAlert = document.querySelector("#liveCriticalAlert");
const liveCriticalCamera = document.querySelector("#liveCriticalCamera");
const liveCriticalTime = document.querySelector("#liveCriticalTime");
const liveCriticalDuration = document.querySelector("#liveCriticalDuration");
const liveCriticalEvidence = document.querySelector("#liveCriticalEvidence");
const liveCurrentEvent = document.querySelector("#liveCurrentEvent");
const liveCurrentEventLink = document.querySelector("#liveCurrentEventLink");
const liveLastAlert = document.querySelector("#liveLastAlert");
const liveRealtimeAlerts = document.querySelector("#liveRealtimeAlerts");
const liveToast = document.querySelector("#liveToast");
const liveToastTitle = document.querySelector("#liveToastTitle");
const liveToastText = document.querySelector("#liveToastText");
const liveAiStart = document.querySelector("#liveAiStart");
const liveAiStop = document.querySelector("#liveAiStop");
const configureRestrictedArea = document.querySelector("#configureRestrictedArea");
const clearMachine = document.querySelector("#clearMachine");
const zoneTypeInput = document.querySelector("#zoneTypeInput");
const zoneNameInput = document.querySelector("#zoneNameInput");
const zoneSecondsInput = document.querySelector("#zoneSecondsInput");
const zoneList = document.querySelector("#zoneList");
const machineSelect = document.querySelector("#machineSelect");
const machineNameInput = document.querySelector("#machineNameInput");
const machineStopSecondsInput = document.querySelector("#machineStopSecondsInput");
const operatorAbsenceSecondsInput = document.querySelector("#operatorAbsenceSecondsInput");
const stoppedWithOperatorSecondsInput = document.querySelector("#stoppedWithOperatorSecondsInput");
const createMachineMonitor = document.querySelector("#createMachineMonitor");
const refreshMachines = document.querySelector("#refreshMachines");
const machineRegionStatus = document.querySelector("#machineRegionStatus");
const calibrationStatus = document.querySelector("#calibrationStatus");
const calibrationProgress = document.querySelector("#calibrationProgress");
const calibrationSamples = document.querySelector("#calibrationSamples");
const calibrationBaselines = document.querySelector("#calibrationBaselines");
const calibrationSeparation = document.querySelector("#calibrationSeparation");
const calibrateActive = document.querySelector("#calibrateActive");
const calibrateStopped = document.querySelector("#calibrateStopped");
const startMonitoring = document.querySelector("#startMonitoring");
const liveRailName = document.querySelector("#liveRailName");
const liveRailStatus = document.querySelector("#liveRailStatus");
const liveRailAlert = document.querySelector("#liveRailAlert");
const drawToolbar = document.querySelector("#drawToolbar");
const drawToolbarTitle = document.querySelector("#drawToolbarTitle");
const drawToolbarHint = document.querySelector("#drawToolbarHint");
const undoDrawPoint = document.querySelector("#undoDrawPoint");
const cancelDraw = document.querySelector("#cancelDraw");
const saveDraw = document.querySelector("#saveDraw");
const monitorConfigCard = document.querySelector("#monitorConfigCard");
const monitorConfigTitle = document.querySelector("#monitorConfigTitle");
const monitorConfigText = document.querySelector("#monitorConfigText");

let sessionId = null;
let statusTimer = null;
let drawMode = null;
let draftPoints = [];
let machineConfig = null;
let currentPayload = null;
let currentCameraId = null;
let persistedZones = [];
let editingZoneId = null;
let machines = [];
let selectedMachineId = null;
let calibrationTimer = null;
let eventSource = null;
let liveAlerts = [];
let seenLiveEvents = new Set();
let toastTimer = null;

const LIVE_EVENT_TYPES = new Set([
  "workstation_unattended",
  "machine_running_without_operator",
  "machine_stoppage",
  "machine_stopped_with_operator",
]);

const LIVE_EVENT_LABELS = {
  workstation_unattended: "Operador fora da zona",
  machine_running_without_operator: "Máquina ativa sem operador",
  machine_stoppage: "Parada de máquina",
  machine_stopped_with_operator: "Máquina parada com operador",
};

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
    throw new Error(`${response.status} - ${payload.detail || `Erro HTTP ${response.status}`}`);
  }
  if (payload && typeof payload === "object") payload._http_status = response.status;
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
  if (message !== undefined) liveViewMessage.textContent = message;
}

function canvasRect() {
  const stageRect = liveViewStage.getBoundingClientRect();
  const imageRect = liveViewImage.getBoundingClientRect();
  const naturalWidth = liveViewImage.naturalWidth || 0;
  const naturalHeight = liveViewImage.naturalHeight || 0;
  let width = imageRect.width > 1 ? imageRect.width : stageRect.width;
  let height = imageRect.height > 1 ? imageRect.height : stageRect.height;
  let left = imageRect.width > 1 ? imageRect.left - stageRect.left : 0;
  let top = imageRect.height > 1 ? imageRect.top - stageRect.top : 0;

  if (naturalWidth > 0 && naturalHeight > 0) {
    const scale = Math.min(stageRect.width / naturalWidth, stageRect.height / naturalHeight);
    width = naturalWidth * scale;
    height = naturalHeight * scale;
    left = (stageRect.width - width) / 2;
    top = (stageRect.height - height) / 2;
  }

  liveViewCanvas.style.left = `${Math.max(0, left)}px`;
  liveViewCanvas.style.top = `${Math.max(0, top)}px`;
  liveViewCanvas.style.width = `${Math.max(1, width)}px`;
  liveViewCanvas.style.height = `${Math.max(1, height)}px`;
  liveViewCanvas.width = Math.max(1, Math.round(width));
  liveViewCanvas.height = Math.max(1, Math.round(height));
  return {
    left: stageRect.left + Math.max(0, left),
    top: stageRect.top + Math.max(0, top),
    width: Math.max(1, width),
    height: Math.max(1, height),
  };
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
  points.forEach((point, index) => {
    const x = point.x * liveViewCanvas.width;
    const y = point.y * liveViewCanvas.height;
    ctx.beginPath();
    ctx.arc(x, y, 5, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
    ctx.fillStyle = "#ffffff";
    ctx.font = "12px Inter, sans-serif";
    ctx.fillText(String(index + 1), x + 8, y - 8);
  });
}

function drawCanvas() {
  canvasRect();
  const ctx = liveViewCanvas.getContext("2d");
  ctx.clearRect(0, 0, liveViewCanvas.width, liveViewCanvas.height);
  if (machineConfig) {
    drawPolygon(machineConfig.machine_polygon || [], "#38bdf8", "rgba(56, 189, 248, 0.10)");
    drawPolygon(machineConfig.operator_polygon || [], "#f97316", "rgba(249, 115, 22, 0.10)");
  }
  persistedZones.forEach((zone) => {
    const color = ["workstation", "operator_zone"].includes(zone.tipo) ? "#2454f4" : ["restricted_area", "restricted_zone"].includes(zone.tipo) ? "#ef4444" : ["dwell_area", "work_area"].includes(zone.tipo) ? "#f59e0b" : "#38bdf8";
    drawPolygon(zone.pontos || [], color, "rgba(36, 84, 244, 0.06)");
  });
  if (drawMode) {
    drawPolygon(draftPoints, "#ef4444", "rgba(239, 68, 68, 0.14)");
  }
}

function renderStatus(payload) {
  const status = payload.status || "offline";
  const ops = payload.ops || {};
  const context = payload.context || {};
  const currentEvent = context.current_event;
  machineConfig = ops.machine || machineConfig;
  liveViewName.textContent = context.primary_label || payload.nome || "Live View";
  if (liveRailName) liveRailName.textContent = context.primary_label || payload.nome || "Live View";
  const cameraText = formatCameraStatus(status);
  const aiText = formatAiStatus(payload.ai_status || ops.ai_status);
  if (liveRailStatus) liveRailStatus.textContent = `${cameraText} · ${aiText}`;
  if (liveStreamSummary) {
    liveStreamSummary.textContent = `${context.path_label || "Contexto operacional em configuração"} | ${cameraText} | ${formatLastFrame(payload.last_frame_at || ops.last_frame_at)}`;
  }
  liveViewResolution.textContent = payload.width && payload.height ? `${payload.width}x${payload.height}` : "indisponível";
  liveViewFps.textContent = payload.fps ?? "indisponível";
  liveViewInferenceFps.textContent = ops.inference_fps ?? 0;
  liveViewPeople.textContent = ops.people_count ?? 0;
  if (liveViewAsset) liveViewAsset.textContent = context.primary_label || currentMachine()?.nome || "Não configurado";
  if (liveViewPath) liveViewPath.textContent = context.path_label || "Contexto em configuração";
  liveViewMachine.textContent = currentMachine()?.nome || (machineConfig ? machineConfig.nome : "Não configurada");
  liveViewMachineState.textContent = formatMachineState(ops.machine_state);
  liveViewOperator.textContent = operatorLabel(ops);
  if (liveViewSituation) liveViewSituation.textContent = currentSituation(status, ops);
  liveViewMotion.textContent = `${ops.machine_motion ?? 0}${ops.machine_threshold ? ` / limite ${ops.machine_threshold.toFixed ? ops.machine_threshold.toFixed(2) : ops.machine_threshold}` : ""}`;
  if (liveViewRawScore) liveViewRawScore.textContent = ops.raw_activity_score ?? "—";
  if (liveViewFramesAnalyzed) {
    liveViewFramesAnalyzed.textContent = ops.frames_analyzed || ops.inference_frames || 0;
  }
  if (liveViewRoi) liveViewRoi.textContent = ops.roi?.width && ops.roi?.height ? `${ops.roi.width}x${ops.roi.height}` : "—";
  if (liveViewAnalysisStatus) liveViewAnalysisStatus.textContent = formatAnalysisStatus(ops.analysis_status);
  if (liveViewConfidence) liveViewConfidence.textContent = Number(ops.visual_confidence || 0).toFixed(2);
  if (liveViewStateTime) liveViewStateTime.textContent = `${Math.round(ops.machine_seconds_in_state || 0)}s`;
  if (liveViewReason) liveViewReason.textContent = ops.machine_reason || ops.analysis_error || "Aguardando análise";
  if (currentEvent) {
    const label = liveEventLabel(currentEvent);
    liveCurrentEvent.textContent = `${label} · ${formatDuration(currentEvent.duration_seconds)} · workflow ${currentEvent.workflow_status || "new"}`;
    if (liveCurrentEventLink) {
      liveCurrentEventLink.href = `/events?event_uuid=${encodeURIComponent(currentEvent.event_uuid || "")}`;
      liveCurrentEventLink.hidden = false;
    }
  } else {
    liveCurrentEvent.textContent = liveCurrentEventText(status, ops, context);
    if (liveCurrentEventLink) liveCurrentEventLink.hidden = true;
  }
  const observation = payload.observation || {};
  liveViewRelation.textContent = observation.machine_state
    ? `${observation.machine_state} · conf. ${observation.machine_confidence} · operador ${observation.people_in_operator_zone} · restrita ${observation.people_in_restricted_zone}`
    : ops.relation || "Aguardando configuração";
  updateMonitorConfigCard();
  updateAiControls(payload.ai_status || ops.ai_status);
  if (payload.calibration && payload.calibration.status && payload.calibration.status !== "idle") {
    renderCalibration(payload.calibration);
  }
  updateActiveZoneAlert(payload);
  if (status === "online") {
    setStatus("online", "Transmissão ativa.");
  } else if (status === "conectando" || status === "reconectando") {
    setStatus(status, "Tentando reconectar...");
  } else {
    setStatus("offline", payload.error || "Câmera offline.");
  }
  drawCanvas();
}

function liveEventLabel(event) {
  const labels = {
    machine_stoppage: "Parada operacional",
    machine_running_without_operator: "Máquina ativa sem operador",
    machine_stopped_with_operator: "Máquina parada com operador",
    workstation_unattended: "Posto sem operador",
  };
  return labels[event?.tipo] || "Evento operacional aberto";
}

function liveCurrentEventText(status, ops, context) {
  if (status !== "online") return "Sem evento operacional aberto. Conexão técnica indisponível.";
  if (ops.analysis_status && !["ANALYZING", "WAITING_FOR_PREVIOUS_FRAME"].includes(ops.analysis_status)) {
    return "Sem evento aberto. Dados ainda insuficientes para afirmar operação normal.";
  }
  if (context.operational_status === "sem_evento") return "Sem evento operacional aberto.";
  if (context.operational_status === "ativa") return "Operação normal.";
  return "Nenhum evento operacional aberto.";
}

function eventTypeFromAlert(alert) {
  if (alert.tipo) return alert.tipo;
  const title = (alert.titulo || "").toLowerCase();
  if (title.includes("operador fora")) return "workstation_unattended";
  if (title.includes("ativa sem operador")) return "machine_running_without_operator";
  if (title.includes("parada com operador")) return "machine_stopped_with_operator";
  if (title.includes("parada de máquina") || title.includes("parada de maquina")) return "machine_stoppage";
  return "";
}

function normalizeLiveAlert(alert) {
  const tipo = eventTypeFromAlert(alert);
  return {
    ...alert,
    tipo,
    titulo: alert.titulo || LIVE_EVENT_LABELS[tipo] || "Evento operacional",
    horario: alert.horario || alert.inicio || new Date().toISOString(),
    evidence_url: alert.evidence_url || (alert.midia_path && alert.id ? `/eventos/${alert.id}/evidence` : null),
    event_id: alert.event_id || alert.id,
  };
}

function isLiveEvent(alert) {
  return LIVE_EVENT_TYPES.has(eventTypeFromAlert(alert));
}

function formatDuration(seconds) {
  const value = Math.max(0, Math.round(Number(seconds || 0)));
  const minutes = Math.floor(value / 60);
  const rest = value % 60;
  return minutes ? `${minutes}m ${rest}s` : `${rest}s`;
}

function formatLastFrame(value) {
  if (!value) return "Último frame indisponível";
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) return "Último frame recebido";
  const seconds = Math.max(0, Math.round((Date.now() - parsed) / 1000));
  if (seconds < 3) return "Último frame agora";
  if (seconds < 60) return `Último frame há ${seconds}s`;
  return `Último frame há ${Math.round(seconds / 60)}min`;
}

function formatAnalysisStatus(status) {
  const map = {
    WAITING_FOR_REGION: "Aguardando configuração da máquina",
    WAITING_FOR_MACHINE_REGION: "Aguardando configuração da máquina",
    INFERENCE_NOT_READY: "IA ainda não iniciou",
    NO_RECENT_FRAME: "Sem imagem recente",
    CAMERA_OFFLINE: "Câmera desconectada",
    WAITING_FOR_PREVIOUS_FRAME: "Aguardando próximo frame",
    INVALID_ROI: "Região da máquina inválida",
    FRAME_STALE: "Sem imagem recente",
    ANALYZING: "Analisando",
    ANALYSIS_ERROR: "Erro na análise",
    ERROR: "Erro na análise",
  };
  return map[status] || status || "Aguardando análise";
}

function formatCameraStatus(status) {
  if (status === "online") return "Câmera online";
  if (status === "conectando") return "Câmera conectando";
  if (status === "reconectando") return "Tentando reconectar";
  return "Câmera offline";
}

function formatAiStatus(status) {
  if (status === "ativa") return "IA ativa";
  if (status === "carregando") return "IA carregando";
  if (status === "erro") return "IA indisponível";
  return "IA inativa";
}

function operatorLabel(ops) {
  if (!ops || (!ops.ai_status && !ops.analysis_status)) return "Dados indisponíveis";
  if (ops.analysis_status && ops.analysis_status !== "ANALYZING" && !Number(ops.inference_frames || ops.frames_analyzed || 0)) {
    return "Dados indisponíveis";
  }
  if (ops.operator_present) return `Presente${ops.operator_people_count ? ` (${ops.operator_people_count})` : ""}`;
  return "Ausente";
}

function currentSituation(status, ops) {
  if (status !== "online") return "Câmera offline";
  const analysisStatus = ops.analysis_status || "";
  if (analysisStatus && !["ANALYZING", "WAITING_FOR_PREVIOUS_FRAME"].includes(analysisStatus)) {
    return formatAnalysisStatus(analysisStatus);
  }
  const state = ops.machine_state || "";
  if (!state || state === "NAO_CONFIGURADA" || state === "UNKNOWN") return "Aguardando configuração";
  if (state === "STOPPED" || state === "PARADA") return "Máquina parada";
  if ((state === "ACTIVE" || state === "ATIVA") && !ops.operator_present) return "Máquina ativa sem operador";
  return "Operação normal";
}

function updateMonitorConfigCard() {
  if (!monitorConfigCard) return;
  const selected = currentMachine();
  const machineRegion = zoneByType("machine_region");
  const operatorZone = zoneByType("operator_zone") || zoneByType("workstation");
  const configured = Boolean(selected && machineRegion && operatorZone);
  monitorConfigCard.classList.toggle("is-configured", configured);
  if (configured) {
    monitorConfigTitle.textContent = selected.nome || "Monitor configurado";
    monitorConfigText.textContent = "Monitor ativo para esta câmera. Use editar configuração se precisar ajustar zonas ou calibração.";
    createMachineMonitor.textContent = "Editar configuração";
    return;
  }
  monitorConfigTitle.textContent = "Configure esta câmera";
  monitorConfigText.textContent = "Defina a região da máquina e a área do operador para iniciar o monitoramento operacional.";
  createMachineMonitor.textContent = "Configurar monitoramento";
}

function updateActiveZoneAlert(payload) {
  const activeEvents = (payload.active_zone_events || []).concat(payload.ops?.active_zone_events || []);
  const zones = (payload.zones || []).concat(payload.ops?.zones || []);
  const active = activeEvents.find((event) => event.event_type === "workstation_unattended");
  const zone = zones.find((item) => item.event_type === "workstation_unattended");
  const seconds = zone?.condition_seconds || (active ? Math.max(0, (Date.now() - Date.parse(active.started_at_iso || new Date().toISOString())) / 1000) : 0);
  if (!active && !zone?.event_active) {
    liveCriticalAlert.hidden = true;
    return;
  }
  liveCriticalAlert.hidden = false;
  liveCriticalCamera.textContent = `Câmera: ${currentPayload?.nome || liveViewName.textContent || currentCameraId || "—"}`;
  liveCriticalTime.textContent = `Horário: ${active?.started_at_iso || new Date().toLocaleString("pt-BR")}`;
  liveCriticalDuration.textContent = `Tempo de ausência: ${formatDuration(seconds)}`;
  if (active?.event_id) {
    liveCriticalEvidence.href = `/eventos/${active.event_id}/evidence`;
    liveCriticalEvidence.hidden = false;
  } else {
    liveCriticalEvidence.hidden = true;
  }
}

function renderRealtimeAlerts() {
  if (!liveRealtimeAlerts) return;
  if (!liveAlerts.length) {
    liveRealtimeAlerts.innerHTML = '<div class="muted">Aguardando eventos reais.</div>';
    return;
  }
  liveRealtimeAlerts.innerHTML = liveAlerts.slice(0, 5).map((alert) => `
    <article class="live-alert-item ${alert.tipo === "workstation_unattended" ? "danger" : ""}">
      <strong>${alert.titulo}</strong>
      <span>${alert.machine_name || "Máquina"} · ${alert.horario || "—"}</span>
      ${alert.duracao !== undefined && alert.duracao !== null ? `<span>Duração: ${formatDuration(alert.duracao)}</span>` : ""}
      ${alert.operator_present !== undefined ? `<span>Operador: ${alert.operator_present ? "presente" : "ausente"}</span>` : ""}
      ${alert.severity ? `<span>Severidade: ${alert.severity}</span>` : ""}
      ${alert.evidence_url ? `<a href="${alert.evidence_url}" target="_blank" rel="noreferrer">Ver evidência</a>` : ""}
    </article>
  `).join("");
  const latest = liveAlerts[0];
  if (latest) {
    if (liveLastAlert) {
      liveLastAlert.textContent = `${latest.titulo} · ${latest.horario || "horário indisponível"} · ${latest.delivery_status || latest.status || "registrado"}`;
    }
    if (liveRailAlert) {
      liveRailAlert.textContent = latest.tipo === "workstation_unattended" ? "Alerta: operador fora da zona" : `Alerta: ${latest.titulo}`;
    }
  }
}

function showLiveToast(alert) {
  if (!liveToast) return;
  liveToastTitle.textContent = alert.titulo;
  liveToastText.textContent = `${alert.camera_id || currentCameraId || "Câmera"} · ${alert.horario || new Date().toLocaleString("pt-BR")}`;
  liveToast.hidden = false;
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    liveToast.hidden = true;
  }, 6000);
}

function pushLiveAlert(alert) {
  const normalized = normalizeLiveAlert(alert);
  if (!isLiveEvent(normalized)) return;
  const dedupeKey = `${normalized.event_id || normalized.tipo}-${normalized.type || "event"}`;
  if (seenLiveEvents.has(dedupeKey)) return;
  seenLiveEvents.add(dedupeKey);
  liveAlerts = [normalized, ...liveAlerts].slice(0, 20);
  if (liveCurrentEvent && ["open", "aberto", undefined].includes(normalized.status)) {
    liveCurrentEvent.textContent = `${normalized.titulo} · ${normalized.horario || "horário indisponível"}`;
  }
  renderRealtimeAlerts();
  showLiveToast(normalized);
}

async function loadRecentLiveEvents() {
  if (!currentCameraId) {
    renderRealtimeAlerts();
    return;
  }
  try {
    const query = new URLSearchParams({ camera_id: currentCameraId });
    const events = await requestJson(`/eventos?${query.toString()}`);
    liveAlerts = events.filter(isLiveEvent).map(normalizeLiveAlert).slice(0, 8);
    liveAlerts.forEach((alert) => seenLiveEvents.add(`${alert.event_id || alert.tipo}-history`));
    renderRealtimeAlerts();
  } catch (error) {
    liveRealtimeAlerts.innerHTML = '<div class="muted">Histórico indisponível nesta sessão. Alertas novos aparecerão aqui.</div>';
  }
}

function connectLiveEvents() {
  if (eventSource) eventSource.close();
  eventSource = new EventSource("/events/stream");
  eventSource.addEventListener("alert", (message) => {
    try {
      pushLiveAlert(JSON.parse(message.data));
    } catch (_error) {
      // SSE malformado não deve derrubar a Live View.
    }
  });
  eventSource.onerror = () => {
    eventSource.close();
    setTimeout(connectLiveEvents, 3000);
  };
}

function updateAiControls(aiStatus) {
  const active = aiStatus === "ativa" || aiStatus === "carregando";
  liveAiStart.hidden = active;
  liveAiStop.hidden = !active;
  liveAiStart.classList.toggle("active", !active);
  liveAiStop.classList.toggle("active", active);
}

function formatMachineState(state) {
  if (!state || state === "NAO_CONFIGURADA") return "Não configurada";
  if (state === "UNKNOWN") return "Dados indisponíveis";
  if (state === "SEM SINAL") return "Dados indisponíveis";
  if (state === "ACTIVE" || state === "ATIVA") return "Ativa";
  if (state === "STOPPED" || state === "PARADA") return "Parada";
  return state;
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
  const params = new URLSearchParams(window.location.search);
  const cameraId = params.get("camera_id");
  const payload = cameraId ? { camera_id: cameraId, nome: params.get("nome") || "Live View" } : sourcePayload();
  if (!payload) {
    setStatus("offline", "Volte à página inicial, teste o RTSP e clique em Abrir Live View.");
    return;
  }
  currentPayload = payload;
  currentCameraId = payload.camera_id || null;
  await loadPersistedZones();
  await loadMachines();
  await loadRecentLiveEvents();
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
  liveViewImage.onload = () => {
    setStatus("online", "Transmissão ativa.");
    drawCanvas();
  };
  liveViewImage.onerror = () => setStatus("reconectando", "Sem imagem no momento. Tentando reconectar...");
  requestJson(`/live-view/${sessionId}/ai/start`, { method: "POST" })
    .then((ops) => renderStatus({ status: "online", nome: payload.nome, ops }))
    .catch((error) => {
      if (liveViewReason) liveViewReason.textContent = `IA não iniciou automaticamente: ${error.message}`;
    });
  statusTimer = setInterval(pollStatus, 1500);
  connectLiveEvents();
}

async function loadPersistedZones() {
  if (!currentCameraId) {
    persistedZones = [];
    return;
  }
  try {
    persistedZones = await requestJson(`/cameras/${currentCameraId}/areas`);
    liveViewHint.textContent = persistedZones.length
      ? `${persistedZones.length} zona(s) carregada(s) desta câmera.`
      : "Nenhuma zona salva nesta câmera.";
    renderZoneList();
    updateMachineRegionStatus();
    drawCanvas();
  } catch (error) {
    persistedZones = [];
    setStatus("offline", `Não foi possível carregar zonas: ${error.message}`);
  }
}

async function loadMachines() {
  if (!currentCameraId) {
    machines = [];
    renderMachines();
    return;
  }
  try {
    machines = await requestJson(`/cameras/${currentCameraId}/machine-monitors`);
    if (!selectedMachineId && machines.length) selectedMachineId = machines[0].id;
    if (selectedMachineId && !machines.some((machine) => machine.id === selectedMachineId)) {
      selectedMachineId = machines[0]?.id || null;
    }
    renderMachines();
  } catch (error) {
    calibrationStatus.textContent = `Máquinas: erro ao carregar (${error.message})`;
  }
}

function renderMachines() {
  if (!machineSelect) return;
  machineSelect.innerHTML = machines.length
    ? machines.map((machine) => `<option value="${machine.id}" ${machine.id === selectedMachineId ? "selected" : ""}>${machine.nome} · ${machine.id}</option>`).join("")
    : '<option value="">Nenhuma máquina cadastrada</option>';
  const selected = currentMachine();
  liveViewMachine.textContent = selected ? selected.nome : machineConfig ? machineConfig.nome : "Não configurada";
  if (selected) {
    if (machineNameInput) machineNameInput.value = selected.nome || "";
    if (machineStopSecondsInput) machineStopSecondsInput.value = selected.stop_seconds ?? 10;
    if (operatorAbsenceSecondsInput) operatorAbsenceSecondsInput.value = selected.operator_absence_seconds ?? 5;
    if (stoppedWithOperatorSecondsInput) stoppedWithOperatorSecondsInput.value = selected.stopped_with_operator_seconds ?? 5;
  }
  updateMachineRegionStatus();
  renderCalibrationFromMachine(selected);
  updateMonitorConfigCard();
}

function secondsFromInput(input, fallback) {
  const value = Number(input?.value || fallback);
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

function currentMachine() {
  return machines.find((machine) => machine.id === selectedMachineId) || null;
}

function zoneByType(type) {
  return persistedZones.find((zone) => zone.tipo === type && zone.ativa);
}

function updateMachineRegionStatus() {
  if (!machineRegionStatus) return;
  const machineRegion = zoneByType("machine_region");
  machineRegionStatus.textContent = machineRegion
    ? `Região da máquina salva (${machineRegion.id})`
    : "Região da máquina ausente. Crie uma zona machine_region antes de calibrar.";
}

function renderCalibrationFromMachine(machine) {
  if (!machine) {
    calibrationStatus.textContent = "Calibração: selecione ou cadastre uma máquina.";
    calibrationProgress.textContent = "Progresso: 0%";
    calibrationSamples.textContent = "Amostras: 0";
    calibrationBaselines.textContent = "Baselines: ativa — / parada —";
    calibrationSeparation.textContent = "Separação: —";
    return;
  }
  calibrationStatus.textContent = `Calibração: ${machine.calibration_result || machine.calibration_status || "aguardando"}`;
  calibrationProgress.textContent = "Progresso: 0%";
  calibrationSamples.textContent = `Amostras: ativa ${machine.active_calibration?.samples_count || 0} / parada ${machine.stopped_calibration?.samples_count || 0}`;
  calibrationBaselines.textContent = `Baselines: ativa ${machine.active_baseline ?? "—"} / parada ${machine.stopped_baseline ?? "—"}`;
  calibrationSeparation.textContent = `Separação: ${machine.separation_score ?? "—"} · ${machine.calibration_result || "INVALID"}`;
}

function renderCalibration(payload) {
  calibrationStatus.textContent = `Calibração ${payload.phase || ""}: ${payload.status || "idle"}`;
  calibrationProgress.textContent = `Progresso: ${payload.progress ?? 0}%`;
  calibrationSamples.textContent = `Amostras: ${payload.samples_count ?? 0}`;
  if (payload.stats) {
    calibrationBaselines.textContent = `Baseline ${payload.phase}: média ${payload.stats.mean} · mediana ${payload.stats.median} · desvio ${payload.stats.std}`;
  }
  if (payload.separation) {
    calibrationSeparation.textContent = `Separação: ${payload.separation.score ?? "—"} · ${payload.separation.result} · ${payload.separation.message}`;
  }
  const running = payload.status === "running";
  calibrateActive.disabled = running;
  calibrateStopped.disabled = running;
}

function renderZoneList() {
  if (!zoneList) return;
  if (!persistedZones.length) {
    zoneList.innerHTML = '<div class="muted">Nenhuma zona salva.</div>';
    return;
  }
  zoneList.innerHTML = persistedZones.map((zone) => `
    <article class="zone-card">
      <strong>${zone.nome}</strong>
      <span>${zone.tipo} · ID: ${zone.id}</span>
      <span>${zone.ativa ? "Ativa" : "Inativa"}</span>
      <div class="actions">
        <button type="button" data-zone-action="edit" data-zone-id="${zone.id}">Editar</button>
        <button type="button" data-zone-action="toggle" data-zone-id="${zone.id}" data-zone-active="${zone.ativa}">${zone.ativa ? "Desativar" : "Ativar"}</button>
        <button type="button" data-zone-action="delete" data-zone-id="${zone.id}">Excluir</button>
      </div>
    </article>
  `).join("");
}

function startZoneEditor(zone) {
  if (!sessionId) return;
  drawMode = "zone";
  editingZoneId = zone?.id || null;
  draftPoints = zone?.pontos ? zone.pontos.map((point) => ({ x: point.x, y: point.y })) : [];
  liveViewStage.classList.add("drawing");
  configureRestrictedArea.classList.add("active");
  drawToolbar.hidden = false;
  zoneTypeInput.value = zone?.tipo || "work_area";
  zoneNameInput.value = zone?.nome || (zone ? "" : "Área de corte A6");
  zoneSecondsInput.value = zone?.absence_tolerance_seconds ?? zone?.dwell_limit_seconds ?? 20;
  drawToolbarTitle.textContent = editingZoneId ? "Editar zona" : "Nova zona";
  drawToolbarHint.textContent = "Escolha tipo/nome, clique no vídeo para adicionar pontos e salve.";
  liveViewHint.textContent = editingZoneId ? `Editando zona ${editingZoneId}.` : "Modo ativo: desenhe uma nova zona.";
  drawCanvas();
}

function cancelDrawing() {
  drawMode = null;
  editingZoneId = null;
  draftPoints = [];
  liveViewStage.classList.remove("drawing");
  configureRestrictedArea.classList.remove("active");
  drawToolbar.hidden = true;
  liveViewHint.textContent = "Configuração cancelada.";
  drawCanvas();
}

async function finishZoneDrawing() {
  if (!currentCameraId) {
    setStatus("offline", "Abra uma câmera cadastrada para salvar zona.");
    return;
  }
  if (draftPoints.length < 3) {
    liveViewHint.textContent = "A zona precisa de pelo menos 3 pontos. O desenho foi preservado.";
    return;
  }
  const zoneType = zoneTypeInput.value;
  const nome = zoneNameInput.value.trim();
  if (!nome) {
    liveViewHint.textContent = "Informe um nome para a zona. O desenho foi preservado.";
    return;
  }
  saveDraw.disabled = true;
  liveViewHint.textContent = "Salvando zona...";
  const payload = {
    camera_id: currentCameraId,
    name: nome,
    area_type: zoneType,
    active: true,
    polygon: draftPoints,
  };
  const seconds = Number(zoneSecondsInput.value || "0");
  if (["workstation", "operator_zone", "work_area"].includes(zoneType)) {
    payload.absence_tolerance_seconds = Number.isFinite(seconds) ? seconds : 20;
  }
  if (["dwell_area"].includes(zoneType)) {
    payload.dwell_limit_seconds = Number.isFinite(seconds) ? seconds : 300;
  }
  try {
    const saved = editingZoneId
      ? await requestJson(`/areas/${editingZoneId}`, {
          method: "PATCH",
          body: JSON.stringify({
            nome: payload.name,
            tipo: payload.area_type,
            ativa: payload.active,
            pontos: payload.polygon,
            absence_tolerance_seconds: payload.absence_tolerance_seconds,
            dwell_limit_seconds: payload.dwell_limit_seconds,
          }),
        })
      : await requestJson(`/cameras/${currentCameraId}/areas`, {
          method: "POST",
          body: JSON.stringify(payload),
        });
    if (!editingZoneId && saved._http_status !== 201) {
      throw new Error(`Resposta inesperada ao salvar zona: HTTP ${saved._http_status}`);
    }
    await loadPersistedZones();
    const reloaded = persistedZones.find((zone) => zone.id === saved.id);
    if (!reloaded) {
      throw new Error(`Zona salva (${saved.id}), mas o GET posterior nao retornou o registro.`);
    }
    cancelDrawing();
    liveViewHint.textContent = `Zona salva com sucesso. ID persistente: ${saved.id}`;
  } catch (error) {
    liveViewHint.textContent = `Não foi possível salvar a zona. A configuração não foi alterada. ${error.message}`;
  } finally {
    saveDraw.disabled = false;
  }
}

liveAiStart.addEventListener("click", () => {
  if (!sessionId) return;
  requestJson(`/live-view/${sessionId}/ai/start`, { method: "POST" }).then((ops) => renderStatus({ status: "online", ops })).catch((error) => setStatus("offline", error.message));
});

liveAiStop.addEventListener("click", () => {
  if (!sessionId) return;
  requestJson(`/live-view/${sessionId}/ai/stop`, { method: "POST" }).then((ops) => renderStatus({ status: "online", ops })).catch((error) => setStatus("offline", error.message));
});

configureRestrictedArea.addEventListener("click", () => {
  if (!currentCameraId) {
    setStatus("offline", "A zona precisa de uma câmera cadastrada. Abra pela lista de câmeras.");
    return;
  }
  startZoneEditor();
});

clearMachine.addEventListener("click", () => {
  if (!sessionId) return;
  if (!window.confirm("Limpar somente as zonas da câmera atual? Câmeras e eventos serão preservados.")) return;
  (currentCameraId
    ? requestJson(`/cameras/${currentCameraId}/areas`).then((areas) => Promise.all(areas.map((area) => requestJson(`/areas/${area.id}`, { method: "DELETE" }))))
    : Promise.resolve([])
  ).then(() => {
    machineConfig = null;
    persistedZones = [];
    cancelDrawing();
    liveViewHint.textContent = "Zonas da câmera atual limpas. Câmeras e eventos foram preservados.";
    renderZoneList();
  }).catch((error) => setStatus("offline", error.message));
});

undoDrawPoint.addEventListener("click", () => {
  if (!drawMode) return;
  draftPoints.pop();
  drawCanvas();
});

cancelDraw.addEventListener("click", cancelDrawing);

saveDraw.addEventListener("click", () => {
  if (drawMode === "zone") finishZoneDrawing().catch((error) => setStatus("offline", error.message));
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

zoneList.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-zone-action]");
  if (!button) return;
  const zone = persistedZones.find((item) => item.id === button.dataset.zoneId);
  if (!zone) return;
  const action = button.dataset.zoneAction;
  try {
    if (action === "edit") {
      startZoneEditor(zone);
      return;
    }
    if (action === "toggle") {
      await requestJson(`/areas/${zone.id}`, {
        method: "PATCH",
        body: JSON.stringify({ ativa: button.dataset.zoneActive !== "true" }),
      });
      await loadPersistedZones();
      liveViewHint.textContent = "Zona atualizada com sucesso.";
      return;
    }
    if (action === "delete") {
      if (!window.confirm(`Excluir a zona ${zone.nome}?`)) return;
      await requestJson(`/areas/${zone.id}`, { method: "DELETE" });
      await loadPersistedZones();
      liveViewHint.textContent = "Zona excluída com sucesso.";
    }
  } catch (error) {
    liveViewHint.textContent = `Erro na zona: ${error.message}`;
  }
});

machineSelect.addEventListener("change", () => {
  selectedMachineId = machineSelect.value || null;
  renderMachines();
  refreshCalibrationStatus().catch((error) => {
    calibrationStatus.textContent = `Calibração: erro (${error.message})`;
  });
});

refreshMachines.addEventListener("click", () => {
  loadPersistedZones().then(loadMachines).catch((error) => {
    calibrationStatus.textContent = `Erro ao atualizar: ${error.message}`;
  });
});

createMachineMonitor.addEventListener("click", async () => {
  if (!currentCameraId) {
    calibrationStatus.textContent = "Abra uma câmera cadastrada antes de criar máquina.";
    return;
  }
  const machineRegion = zoneByType("machine_region");
  const operatorZone = zoneByType("operator_zone") || zoneByType("workstation");
  if (!machineRegion) {
    calibrationStatus.textContent = "Crie e salve uma machine_region antes de cadastrar a máquina.";
    return;
  }
  if (!operatorZone) {
    calibrationStatus.textContent = "Crie e salve uma operator_zone antes de cadastrar a máquina.";
    return;
  }
  const nome = machineNameInput.value.trim() || "Máquina principal";
  const stopSeconds = secondsFromInput(machineStopSecondsInput, 10);
  const operatorAbsenceSeconds = secondsFromInput(operatorAbsenceSecondsInput, 5);
  const stoppedWithOperatorSeconds = secondsFromInput(stoppedWithOperatorSecondsInput, 5);
  try {
    createMachineMonitor.disabled = true;
    calibrationStatus.textContent = currentMachine() ? "Salvando configuração da máquina..." : "Cadastrando máquina...";
    const payload = {
      nome,
      machine_polygon: machineRegion.pontos,
      operator_polygon: operatorZone.pontos,
      ativo: true,
      stop_seconds: stopSeconds,
      recovery_seconds: 3,
      operator_absence_seconds: operatorAbsenceSeconds,
      stopped_with_operator_seconds: stoppedWithOperatorSeconds,
    };
    const machine = currentMachine();
    const saved = await requestJson(machine ? `/machine-monitors/${machine.id}` : `/cameras/${currentCameraId}/machine-monitors`, {
      method: machine ? "PATCH" : "POST",
      body: JSON.stringify({
        ...payload,
      }),
    });
    selectedMachineId = saved.id;
    await loadPersistedZones();
    await loadMachines();
    const action = machine ? "atualizada" : "cadastrada";
    calibrationStatus.textContent = `Máquina ${action}: ${saved.nome} (${saved.id})`;
    liveViewHint.textContent = `Configuração operacional salva. Monitor: ${saved.id}`;
  } catch (error) {
    calibrationStatus.textContent = `Erro ao salvar configuração da máquina: ${error.message}`;
  } finally {
    createMachineMonitor.disabled = false;
  }
});

async function startAssistedCalibration(phase) {
  if (!selectedMachineId) {
    calibrationStatus.textContent = "Selecione ou cadastre uma máquina antes de calibrar.";
    return;
  }
  if (!zoneByType("machine_region")) {
    calibrationStatus.textContent = "Calibração recusada: machine_region ausente.";
    return;
  }
  try {
    const result = await requestJson(`/machine-monitors/${selectedMachineId}/calibration/${phase}/start`, {
      method: "POST",
      body: JSON.stringify({ duration_seconds: 30 }),
    });
    renderCalibration(result.status);
    if (calibrationTimer) clearInterval(calibrationTimer);
    calibrationTimer = setInterval(() => {
      refreshCalibrationStatus().catch((error) => {
        calibrationStatus.textContent = `Erro ao consultar calibração: ${error.message}`;
      });
    }, 1000);
  } catch (error) {
    calibrationStatus.textContent = `Não foi possível iniciar calibração: ${error.message}`;
  }
}

async function refreshCalibrationStatus() {
  if (!selectedMachineId) return;
  const payload = await requestJson(`/machine-monitors/${selectedMachineId}/calibration/status`);
  renderCalibration(payload.stream || {});
  if (payload.stream?.status === "completed" || payload.stream?.status === "failed" || payload.stream?.status === "idle") {
    if (calibrationTimer) clearInterval(calibrationTimer);
    calibrationTimer = null;
    await loadMachines();
  } else {
    calibrationBaselines.textContent = `Baselines: ativa ${payload.active_baseline ?? "—"} / parada ${payload.stopped_baseline ?? "—"}`;
    calibrationSeparation.textContent = `Separação: ${payload.separation_score ?? "—"} · ${payload.calibration_result || "INVALID"}`;
  }
}

calibrateActive.addEventListener("click", () => startAssistedCalibration("active"));
calibrateStopped.addEventListener("click", () => startAssistedCalibration("stopped"));
startMonitoring.addEventListener("click", async () => {
  if (!selectedMachineId) {
    calibrationStatus.textContent = "Selecione uma máquina para iniciar monitoramento.";
    return;
  }
  await requestJson(`/machine-monitors/${selectedMachineId}/activate`, { method: "POST" });
  await requestJson(`/live-view/${sessionId}/ai/start`, { method: "POST" });
  calibrationStatus.textContent = "Monitoramento iniciado com IA ativa.";
  await loadMachines();
});

window.addEventListener("beforeunload", () => {
  if (statusTimer) clearInterval(statusTimer);
  if (calibrationTimer) clearInterval(calibrationTimer);
  if (eventSource) eventSource.close();
  if (sessionId) fetch(`/live-view/${sessionId}/stop`, { method: "POST", keepalive: true }).catch(() => {});
});

startLiveView().catch((error) => setStatus("offline", error.message));
