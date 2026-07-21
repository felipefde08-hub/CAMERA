const dashboardUpdated = document.querySelector("#dashboardUpdated");
const periodFilter = document.querySelector("#periodFilter");
const cameraFilter = document.querySelector("#cameraFilter");
const machineFilter = document.querySelector("#machineFilter");
const customStart = document.querySelector("#customStart");
const customEnd = document.querySelector("#customEnd");
const currentMachine = document.querySelector("#currentMachine");
const currentOperator = document.querySelector("#currentOperator");
const currentPeople = document.querySelector("#currentPeople");
const currentCamera = document.querySelector("#currentCamera");
const statusCameraText = document.querySelector("#statusCameraText");
const currentMachineName = document.querySelector("#currentMachineName");
const timeline = document.querySelector("#timeline");
const operationsEvents = document.querySelector("#operationsEvents");
const timelineStartLabel = document.querySelector("#timelineStartLabel");
const timelineMiddleLabel = document.querySelector("#timelineMiddleLabel");
const timelineEndLabel = document.querySelector("#timelineEndLabel");
const periodDonut = document.querySelector("#periodDonut");

const metrics = {
  total: document.querySelector("#metricTotal"),
  active: document.querySelector("#metricActive"),
  stopped: document.querySelector("#metricStopped"),
  availability: document.querySelector("#metricAvailability"),
  stops: document.querySelector("#metricStops"),
  biggestStop: document.querySelector("#metricBiggestStop"),
  activeNoOperator: document.querySelector("#metricActiveNoOperator"),
  activityPercent: document.querySelector("#metricActivityPercent"),
  averageStop: document.querySelector("#metricAverageStop"),
  operatorAbsences: document.querySelector("#metricOperatorAbsences"),
  activeHint: document.querySelector("#metricActiveHint"),
  stoppedHint: document.querySelector("#metricStoppedHint"),
  stopsHint: document.querySelector("#metricStopsHint"),
  noOperatorHint: document.querySelector("#metricNoOperatorHint"),
  breakdownActive: document.querySelector("#breakdownActive"),
  breakdownStopped: document.querySelector("#breakdownStopped"),
  breakdownNoOperator: document.querySelector("#breakdownNoOperator"),
};

async function requestJson(url) {
  const response = await fetch(url);
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : { detail: await response.text() };
  if (!response.ok) throw new Error(payload.detail || `Erro HTTP ${response.status}`);
  return payload;
}

function periodRange() {
  const now = new Date();
  const end = now.toISOString();
  if (periodFilter.value === "today") {
    const start = new Date(now);
    start.setHours(0, 0, 0, 0);
    return { start: start.toISOString(), end };
  }
  if (periodFilter.value === "yesterday") {
    const start = new Date(now);
    start.setDate(start.getDate() - 1);
    start.setHours(0, 0, 0, 0);
    const yesterdayEnd = new Date(start);
    yesterdayEnd.setHours(23, 59, 59, 999);
    return { start: start.toISOString(), end: yesterdayEnd.toISOString() };
  }
  if (periodFilter.value === "7d") {
    return { start: new Date(now.getTime() - 7 * 86400 * 1000).toISOString(), end };
  }
  if (periodFilter.value === "custom") {
    const start = customStart?.value ? new Date(customStart.value).toISOString() : new Date(now.getTime() - 24 * 3600 * 1000).toISOString();
    const customEndValue = customEnd?.value ? new Date(customEnd.value).toISOString() : end;
    return { start, end: customEndValue };
  }
  return { start: new Date(now.getTime() - 24 * 3600 * 1000).toISOString(), end };
}

function queryParams(extra = {}) {
  const range = periodRange();
  const params = new URLSearchParams({ ...range, ...extra });
  if (cameraFilter.value.trim()) params.set("camera_id", cameraFilter.value.trim());
  if (machineFilter.value.trim()) params.set("machine_name", machineFilter.value.trim());
  return params.toString();
}

function formatDuration(seconds) {
  const value = Number(seconds || 0);
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  if (hours) return `${hours}h ${minutes}min`;
  return `${minutes}min`;
}

function formatPercent(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return `${number.toFixed(number % 1 ? 1 : 0)}%`;
}

function formatClock(value) {
  return new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function hasOperationalData(summary) {
  return Boolean(
    Number(summary.tempo_maquina_ativa || 0) ||
    Number(summary.tempo_maquina_parada || 0) ||
    Number(summary.tempo_ativa_sem_operador || 0) ||
    Number(summary.quantidade_paradas || 0)
  );
}

function eventLabel(event) {
  const labels = {
    machine_state: "Máquina",
    operator_presence: "Operador",
    camera_status: "Câmera",
    calibration: "Calibração",
    active_without_operator: "Ativa sem operador",
  };
  return labels[event.event_type] || event.event_type;
}

function timelineClass(item) {
  if (item.event_type === "camera_status" && item.state === "offline") return "offline";
  if (item.event_type === "camera_status" && item.state === "online") return "active";
  if (item.event_type === "active_without_operator" && item.state === "ATIVA_SEM_OPERADOR") return "warning";
  if (item.state === "SEM SINAL") return "offline";
  if (item.state === "CALIBRANDO") return "neutral";
  if (item.state === "PARADA") return "stopped";
  if (item.state === "ATIVA") return "active";
  return "neutral";
}

function renderSummary(summary) {
  const hasData = hasOperationalData(summary);
  metrics.total.textContent = hasData ? formatDuration(summary.tempo_total_monitorado) : "Aguardando monitoramento";
  metrics.active.textContent = hasData ? formatDuration(summary.tempo_maquina_ativa) : "Sem dados";
  metrics.stopped.textContent = hasData ? formatDuration(summary.tempo_maquina_parada) : "Sem dados";
  metrics.availability.textContent = hasData ? `${summary.disponibilidade_camera}%` : "—";
  metrics.stops.textContent = hasData ? summary.quantidade_paradas : "—";
  metrics.biggestStop.textContent = hasData ? formatDuration(summary.maior_parada) : "—";
  metrics.activeNoOperator.textContent = hasData ? formatDuration(summary.tempo_ativa_sem_operador) : "Sem dados";
  if (metrics.activityPercent) metrics.activityPercent.textContent = hasData ? formatPercent(summary.percentual_atividade_estimada) : "—";
  if (metrics.averageStop) metrics.averageStop.textContent = hasData ? formatDuration(summary.duracao_media_paradas) : "—";
  if (metrics.operatorAbsences) metrics.operatorAbsences.textContent = hasData ? summary.quantidade_ausencias_operador : "—";
  if (metrics.activeHint) metrics.activeHint.textContent = hasData ? `${formatPercent(summary.percentual_atividade_estimada)} do período` : "Aguardando monitoramento";
  if (metrics.stoppedHint) metrics.stoppedHint.textContent = hasData ? `${formatDuration(summary.duracao_media_paradas)} média` : "Aguardando monitoramento";
  if (metrics.stopsHint) metrics.stopsHint.textContent = hasData ? `${formatDuration(summary.maior_parada)} maior parada` : "Sem atividade registrada";
  if (metrics.noOperatorHint) metrics.noOperatorHint.textContent = hasData ? `${summary.quantidade_ausencias_operador} ausências` : "Aguardando monitoramento";
  if (metrics.breakdownActive) metrics.breakdownActive.textContent = hasData ? `${formatDuration(summary.tempo_maquina_ativa)} · ${formatPercent(summary.percentual_atividade_estimada)}` : "Sem dados";
  if (metrics.breakdownStopped) metrics.breakdownStopped.textContent = hasData ? formatDuration(summary.tempo_maquina_parada) : "Sem dados";
  if (metrics.breakdownNoOperator) metrics.breakdownNoOperator.textContent = hasData ? formatDuration(summary.tempo_ativa_sem_operador) : "Sem dados";
  if (periodDonut) {
    const total = Math.max(1, Number(summary.tempo_total_monitorado || 0));
    const activeDeg = hasData ? (Number(summary.tempo_maquina_ativa || 0) / total) * 360 : 0;
    const stoppedDeg = hasData ? (Number(summary.tempo_maquina_parada || 0) / total) * 360 : 0;
    const noOperatorDeg = hasData ? (Number(summary.tempo_ativa_sem_operador || 0) / total) * 360 : 0;
    periodDonut.style.setProperty("--active-deg", `${activeDeg}deg`);
    periodDonut.style.setProperty("--stopped-deg", `${stoppedDeg}deg`);
    periodDonut.style.setProperty("--warning-deg", `${noOperatorDeg}deg`);
  }
  if (timelineStartLabel && summary.period) {
    timelineStartLabel.textContent = formatClock(summary.period.start);
    timelineEndLabel.textContent = formatClock(summary.period.end);
    const middle = new Date((new Date(summary.period.start).getTime() + new Date(summary.period.end).getTime()) / 2);
    timelineMiddleLabel.textContent = formatClock(middle.toISOString());
  }
}

function renderCurrent(status) {
  const machineName = status.machine_name || machineFilter.value.trim() || "Extrusora principal";
  if (currentMachineName) currentMachineName.textContent = machineName;
  currentMachine.textContent = status.machine_state || "SEM SINAL";
  currentOperator.textContent = status.operator_state === "PRESENTE" ? "Operador presente" : "Operador ausente";
  currentPeople.textContent = status.people_count ?? 0;
  const cameraText = status.camera_status === "online" ? "Câmera online" : "Câmera offline";
  currentCamera.textContent = cameraText;
  if (statusCameraText) statusCameraText.textContent = status.camera_status === "online" ? "Online" : "Offline";
}

function renderTimeline(items) {
  if (!items.length) {
    timeline.innerHTML = '<div class="empty-dark">Ainda não há histórico para este período.</div>';
    return;
  }
  const totalDuration = items.reduce((sum, item) => sum + Number(item.duration_seconds || 0), 0) || 1;
  const segments = items.map((item) => {
    const width = Math.max(4, (Number(item.duration_seconds || 0) / totalDuration) * 100);
    const started = new Date(item.start).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    return `<div class="timeline-segment ${timelineClass(item)}" style="width:${width}%" title="${item.state} · ${formatDuration(item.duration_seconds)} · ${started}"></div>`;
  }).join("");
  timeline.innerHTML = `<div class="timeline-strip">${segments}</div>`;
}

function renderEvents(payload) {
  const events = payload.events || [];
  if (!events.length) {
    operationsEvents.innerHTML = '<div class="empty-dark">Nenhum evento operacional registrado.</div>';
    return;
  }
  operationsEvents.innerHTML = events.map((event) => `
    <div class="premium-event">
      <i class="${timelineClass({ event_type: event.event_type, state: event.new_state })}"></i>
      <div>
        <span>${new Date(event.started_at).toLocaleTimeString()}${event.ended_at ? ` → ${new Date(event.ended_at).toLocaleTimeString()}` : " → em aberto"}</span>
        <strong>${eventLabel(event)}: ${event.previous_state || "-"} → ${event.new_state}</strong>
      </div>
      <div>${formatDuration(event.duration_seconds)}</div>
      <div>${event.snapshot_path ? `<span class="snapshot-pill">Evidência</span>` : ""}</div>
    </div>
  `).join("");
}

async function loadDashboard() {
  try {
    const params = queryParams();
    const [summary, current, timelineItems, events] = await Promise.all([
      requestJson(`/operations/summary?${params}`),
      requestJson(`/operations/current-status?${queryParams({})}`),
      requestJson(`/operations/timeline?${params}`),
      requestJson(`/operations/events?${queryParams({ limit: 30, offset: 0 })}`),
    ]);
    renderSummary(summary);
    renderCurrent(current);
    renderTimeline(timelineItems);
    renderEvents(events);
    dashboardUpdated.textContent = new Date().toLocaleTimeString();
    dashboardUpdated.classList.remove("offline");
  } catch (error) {
    dashboardUpdated.textContent = error.message;
    dashboardUpdated.classList.add("offline");
  }
}

[periodFilter, cameraFilter, machineFilter, customStart, customEnd].filter(Boolean).forEach((element) => {
  element.addEventListener("change", loadDashboard);
  element.addEventListener("input", () => window.clearTimeout(element._timer));
  element.addEventListener("input", () => {
    element._timer = window.setTimeout(loadDashboard, 500);
  });
});

loadDashboard();
setInterval(loadDashboard, 15000);
