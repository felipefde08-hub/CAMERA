const dashboardUpdated = document.querySelector("#dashboardUpdated");
const dashboardSyncLabel = document.querySelector("#dashboardSyncLabel");
const dashboardSyncState = document.querySelector("#dashboardSyncState");
const dashboardLoginAction = document.querySelector("#dashboardLoginAction");
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
const operationsTableBody = document.querySelector("#operationsTableBody");
const operationSearch = document.querySelector("#operationSearch");
const operationStateFilter = document.querySelector("#operationStateFilter");
const timelineStartLabel = document.querySelector("#timelineStartLabel");
const timelineMiddleLabel = document.querySelector("#timelineMiddleLabel");
const timelineEndLabel = document.querySelector("#timelineEndLabel");
const periodDonut = document.querySelector("#periodDonut");
const homeEventSearch = document.querySelector("#homeEventSearch");
const homeRecentEvents = document.querySelector("#homeRecentEvents");
const homeCameraGrid = document.querySelector("#homeCameraGrid");
const homeActiveCameras = document.querySelector("#homeActiveCameras");
const homeEventsToday = document.querySelector("#homeEventsToday");
const homePendingAlerts = document.querySelector("#homePendingAlerts");
const homeEvidenceCount = document.querySelector("#homeEvidenceCount");
const homeActiveCamerasHint = document.querySelector("#homeActiveCamerasHint");
const homeEventsTodayHint = document.querySelector("#homeEventsTodayHint");
const homePendingAlertsHint = document.querySelector("#homePendingAlertsHint");
const homeEvidenceCountHint = document.querySelector("#homeEvidenceCountHint");
const homePriorityTitle = document.querySelector("#homePriorityTitle");
const homePriorityDescription = document.querySelector("#homePriorityDescription");
const homePriorityAction = document.querySelector("#homePriorityAction");
const homeCameraActionTitle = document.querySelector("#homeCameraActionTitle");
const homeCameraActionDescription = document.querySelector("#homeCameraActionDescription");
let homeEventFilter = "all";
let homeEventsCache = [];
let homeCamerasCache = [];

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
  if (!response.ok) {
    const error = new Error(payload.detail || `Erro HTTP ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return payload;
}

function renderLoggedOutDashboard() {
  setDashboardSyncState("auth");
  if (homeCamerasCache.length || homeEventsCache.length) {
    homeCamerasCache = [];
    homeEventsCache = [];
  }
  updateHomeSummary([], [], []);
  renderHomeEvents();
  renderHomeCameras();
  if (timeline) timeline.innerHTML = '<div class="empty-dark">Entre para carregar o histórico operacional.</div>';
  if (operationsEvents) operationsEvents.innerHTML = '<tr><td colspan="5">Entre para ver os eventos operacionais.</td></tr>';
  if (operationsTableBody) operationsTableBody.innerHTML = '<tr><td colspan="8">Entre para ver as operações cadastradas.</td></tr>';
}

async function authStatus() {
  return requestJson("/auth/status").catch(() => ({ authenticated: false, bootstrap: false }));
}

function setDashboardSyncState(state, detail = "") {
  if (!dashboardUpdated || !dashboardSyncLabel) return;
  dashboardSyncState?.classList.remove("auth-required", "error");
  if (dashboardLoginAction) dashboardLoginAction.hidden = true;
  dashboardUpdated.classList.remove("offline");
  if (state === "loading") {
    dashboardSyncLabel.textContent = "Atualizando";
    dashboardUpdated.textContent = "agora";
    return;
  }
  if (state === "auth") {
    dashboardSyncState?.classList.add("auth-required");
    dashboardSyncLabel.textContent = "Login necessário";
    dashboardUpdated.textContent = "";
    if (dashboardLoginAction) dashboardLoginAction.hidden = false;
    return;
  }
  if (state === "error") {
    dashboardSyncState?.classList.add("error");
    dashboardSyncLabel.textContent = "Erro de atualização";
    dashboardUpdated.textContent = detail || "verifique a API";
    dashboardUpdated.classList.add("offline");
    return;
  }
  dashboardSyncLabel.textContent = "Atualizado";
  dashboardUpdated.textContent = detail || new Date().toLocaleTimeString();
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

function formatDurationShort(seconds) {
  const value = Number(seconds || 0);
  if (!value) return "—";
  const minutes = Math.floor(value / 60);
  const sec = Math.floor(value % 60);
  if (minutes >= 60) return formatDuration(value);
  return `${String(minutes).padStart(2, "0")} min ${String(sec).padStart(2, "0")} s`;
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

function stateBadgeClass(state) {
  const normalized = String(state || "").toLowerCase();
  if (["running", "ativa", "online", "recovered"].includes(normalized)) return "success";
  if (["stopped", "parada"].includes(normalized)) return "danger";
  if (["suspected_stop", "ativa_sem_operador"].includes(normalized)) return "warning";
  return "offline";
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
    operationsEvents.innerHTML = '<tr><td colspan="5">Nenhum evento operacional registrado.</td></tr>';
    return;
  }
  operationsEvents.innerHTML = events.map((event) => `
    <tr>
      <td>${new Date(event.started_at).toLocaleString()}${event.ended_at ? ` → ${new Date(event.ended_at).toLocaleTimeString()}` : ""}</td>
      <td><span class="cx-status-dot ${timelineClass({ event_type: event.event_type, state: event.new_state })}"></span>${eventLabel(event)}: ${event.previous_state || "-"} → ${event.new_state}</td>
      <td>${event.machine_name || "—"}</td>
      <td>${formatDuration(event.duration_seconds)}</td>
      <td>${event.snapshot_path ? `<span class="snapshot-pill">Evidência</span>` : "—"}</td>
    </tr>
  `).join("");
}

function renderOperations(payload) {
  if (!operationsTableBody) return;
  const search = (operationSearch?.value || "").trim().toLowerCase();
  const stateFilter = operationStateFilter?.value || "";
  const rows = (payload.machines || []).filter((item) => {
    const monitor = item.monitor || {};
    const haystack = `${monitor.nome || ""} ${monitor.camera_id || ""} ${monitor.current_state || ""}`.toLowerCase();
    if (search && !haystack.includes(search)) return false;
    if (stateFilter && monitor.current_state !== stateFilter) return false;
    return true;
  });
  if (!rows.length) {
    operationsTableBody.innerHTML = '<tr><td colspan="8">Nenhuma operação encontrada.</td></tr>';
    return;
  }
  operationsTableBody.innerHTML = rows.map((item) => {
    const monitor = item.monitor || {};
    const last = (item.ultimas_ocorrencias || [])[0];
    return `
      <tr>
        <td><strong>Campex Operations</strong></td>
        <td>${monitor.nome || "—"}</td>
        <td><span class="cx-badge ${stateBadgeClass(monitor.current_state)}">${monitor.current_state || "unavailable"}</span></td>
        <td>${monitor.operator_present ? "Presente" : "Ausente"}</td>
        <td>${monitor.max_people || 0}</td>
        <td>${monitor.camera_id || "—"}</td>
        <td>${last ? `${last.tipo} · ${formatDuration(last.duracao)}` : "Sem evento"}</td>
        <td>${monitor.atualizado_em || monitor.last_state_change || "—"}</td>
      </tr>
    `;
  }).join("");
}

function categoryForEvent(event) {
  const text = `${event.tipo || event.event_type || ""} ${event.new_state || ""}`.toLowerCase();
  if (text.includes("stoppage") || text.includes("parada") || text.includes("machine")) return "Máquina";
  if (text.includes("person") || text.includes("restricted") || text.includes("pessoa")) return "Pessoas";
  if (text.includes("alert")) return "Alerta";
  return "Operação";
}

function statusForEvent(event) {
  if (event.status === "acknowledged") return "Resolvido";
  if (event.status === "open") return "Em análise";
  if (event.status === "closed") return "Registrado";
  if (event.event_type) return event.ended_at ? "Registrado" : "Em análise";
  return "Registrado";
}

function eventTitle(event) {
  if (event.tipo === "machine_stoppage") return "Parada detectada";
  if (event.tipo === "restricted_area_occupied") return "Pessoa em área restrita";
  if (event.event_type === "active_without_operator") return "Ativa sem operador";
  if (event.event_type === "camera_status") return "Estado da câmera";
  if (event.event_type === "machine_state") return "Estado da máquina";
  return event.tipo || event.event_type || "Evento operacional";
}

function eventTime(event) {
  const value = event.inicio || event.started_at || event.criado_em;
  if (!value) return "—";
  return new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function eventEvidence(event) {
  return event.midia_path || event.snapshot_path ? "Disponível" : "—";
}

function eventMatchesFilter(event) {
  const category = categoryForEvent(event).toLowerCase();
  const title = eventTitle(event).toLowerCase();
  if (homeEventFilter === "paradas") return title.includes("parada") || title.includes("máquina");
  if (homeEventFilter === "pessoas") return category.includes("pessoas");
  if (homeEventFilter === "maquinas") return category.includes("máquina");
  if (homeEventFilter === "alertas") return title.includes("alerta") || category.includes("alerta");
  return true;
}

function renderHomeEvents() {
  if (!homeRecentEvents) return;
  const query = (homeEventSearch?.value || "").trim().toLowerCase();
  const rows = homeEventsCache
    .filter(eventMatchesFilter)
    .filter((event) => !query || JSON.stringify(event).toLowerCase().includes(query) || eventTitle(event).toLowerCase().includes(query))
    .slice(0, 5);
  if (!rows.length) {
    homeRecentEvents.innerHTML = `
      <tr>
        <td colspan="6">
          <div class="cx-home-empty">
            <span class="cx-nav-icon" data-icon="events"></span>
            <strong>Nenhum evento registrado</strong>
            <p>Os acontecimentos identificados pelas câmeras aparecerão aqui.</p>
            <a class="cx-secondary-action" href="/alerts">Configurar primeiro evento</a>
          </div>
        </td>
      </tr>
    `;
    return;
  }
  homeRecentEvents.innerHTML = rows.map((event) => `
    <tr>
      <td><strong>${eventTitle(event)}</strong></td>
      <td>${event.camera_id || "—"}</td>
      <td>${categoryForEvent(event)}</td>
      <td>${eventTime(event)}</td>
      <td><span class="cx-badge ${stateBadgeClass(statusForEvent(event))}">${statusForEvent(event)}</span></td>
      <td><a class="cx-link" href="/events">Abrir</a></td>
    </tr>
  `).join("");
}

function renderHomeCameras() {
  if (!homeCameraGrid) return;
  const cameras = homeCamerasCache.slice(0, 4);
  if (!cameras.length) {
    homeCameraGrid.innerHTML = `
      <div class="cx-home-empty compact">
        <span class="cx-nav-icon" data-icon="camera"></span>
        <strong>Nenhuma câmera conectada</strong>
        <p>Adicione uma câmera para começar a acompanhar a operação.</p>
        <a class="cx-primary-action" href="/settings/cameras">Adicionar câmera</a>
      </div>
    `;
    return;
  }
  homeCameraGrid.innerHTML = cameras.map((camera) => `
    <article class="cx-camera-row-card">
      <div class="cx-camera-mini"><span class="cx-nav-icon" data-icon="camera"></span></div>
      <div>
        <strong>${camera.nome || "Câmera"}</strong>
        <span>${camera.unidade_id || "Área não informada"}</span>
      </div>
      <span class="cx-badge ${camera.status === "online" ? "success" : "offline"}">${camera.status === "online" ? "Online" : "Offline"}</span>
      <small>Último evento: ${camera.ultimo_frame || "sem registro"}</small>
    </article>
  `).join("");
}

function updateHomeSummary(cameras, events, deliveries) {
  const activeCameras = cameras.filter((camera) => camera.status === "online").length;
  if (homeActiveCameras) homeActiveCameras.textContent = activeCameras;
  const today = new Date().toISOString().slice(0, 10);
  const todayEvents = events.filter((event) => String(event.inicio || event.started_at || event.criado_em || "").startsWith(today));
  if (homeEventsToday) homeEventsToday.textContent = todayEvents.length;
  const pendingAlerts = deliveries.filter((delivery) => delivery.status === "pending").length;
  const evidenceCount = events.filter((event) => event.midia_path || event.snapshot_path).length;
  if (homePendingAlerts) homePendingAlerts.textContent = pendingAlerts;
  if (homeEvidenceCount) homeEvidenceCount.textContent = evidenceCount;
  if (homeActiveCamerasHint) homeActiveCamerasHint.textContent = activeCameras ? "Câmeras online agora" : "Nenhuma câmera conectada";
  if (homeEventsTodayHint) homeEventsTodayHint.textContent = todayEvents.length ? "Ocorrências registradas" : "Nenhuma ocorrência registrada";
  if (homePendingAlertsHint) homePendingAlertsHint.textContent = pendingAlerts ? "Entregas ainda abertas" : "Nenhum alerta pendente";
  if (homeEvidenceCountHint) homeEvidenceCountHint.textContent = evidenceCount ? "Snapshots disponíveis" : "Nenhuma evidência disponível";
  document.querySelectorAll(".cx-home-metrics article").forEach((card) => {
    const value = Number(card.querySelector("strong")?.textContent || 0);
    card.classList.toggle("is-zero", value === 0);
  });
  if (!homePriorityTitle || !homePriorityDescription || !homePriorityAction) return;
  if (!cameras.length) {
    homePriorityTitle.textContent = "Conecte o primeiro ponto da operação";
    homePriorityDescription.textContent = "Adicione uma câmera, escolha o evento que deseja acompanhar e comece a validar a Campex com a operação real.";
    homePriorityAction.textContent = "Adicionar câmera";
    homePriorityAction.href = "/settings/cameras";
    if (homeCameraActionTitle) homeCameraActionTitle.textContent = "Adicionar câmera";
    if (homeCameraActionDescription) homeCameraActionDescription.textContent = "Conecte o primeiro ponto da operação.";
    return;
  }
  if (todayEvents.length) {
    homePriorityTitle.textContent = "Revise os eventos registrados hoje";
    homePriorityDescription.textContent = "Confira horários, duração, evidências e estados que merecem atenção no período selecionado.";
    homePriorityAction.textContent = "Revisar eventos";
    homePriorityAction.href = "/events";
    if (homeCameraActionTitle) homeCameraActionTitle.textContent = "Ver câmeras";
    if (homeCameraActionDescription) homeCameraActionDescription.textContent = "Acompanhe pontos conectados.";
    return;
  }
  homePriorityTitle.textContent = "Acompanhe as câmeras conectadas";
  homePriorityDescription.textContent = "As câmeras cadastradas aparecem na lista com status, última atualização e acesso rápido à operação.";
  homePriorityAction.textContent = "Ver câmeras";
  homePriorityAction.href = "/cameras";
  if (homeCameraActionTitle) homeCameraActionTitle.textContent = "Ver câmeras";
  if (homeCameraActionDescription) homeCameraActionDescription.textContent = "Acompanhe pontos conectados.";
}

async function loadHome() {
  try {
    const auth = await authStatus();
    if (!auth.authenticated && !auth.bootstrap) {
      renderLoggedOutDashboard();
      return;
    }
    const [cameras, eventList, operationalEvents, deliveries] = await Promise.all([
      requestJson("/cameras/estado").catch(() => []),
      requestJson("/eventos").catch(() => []),
      requestJson(`/operations/events?${queryParams({ limit: 20, offset: 0 })}`).catch(() => ({ events: [] })),
      requestJson("/alert-deliveries").catch(() => []),
    ]);
    homeCamerasCache = cameras;
    homeEventsCache = [...eventList, ...(operationalEvents.events || [])]
      .sort((a, b) => new Date(b.inicio || b.started_at || b.criado_em || 0) - new Date(a.inicio || a.started_at || a.criado_em || 0));
    updateHomeSummary(cameras, homeEventsCache, deliveries);
    renderHomeEvents();
    renderHomeCameras();
  } catch (_error) {
    if (homeRecentEvents) homeRecentEvents.innerHTML = '<tr><td colspan="6">Não foi possível carregar a Home.</td></tr>';
  }
}

async function loadDashboard() {
  try {
    setDashboardSyncState("loading");
    const auth = await authStatus();
    if (!auth.authenticated && !auth.bootstrap) {
      renderLoggedOutDashboard();
      return;
    }
    const params = queryParams();
    const [summary, current, timelineItems, events, operations] = await Promise.all([
      requestJson(`/operations/summary?${params}`),
      requestJson(`/operations/current-status?${queryParams({})}`),
      requestJson(`/operations/timeline?${params}`),
      requestJson(`/operations/events?${queryParams({ limit: 30, offset: 0 })}`),
      requestJson("/operations"),
    ]);
    renderSummary(summary);
    renderCurrent(current);
    renderTimeline(timelineItems);
    renderEvents(events);
    renderOperations(operations);
    loadHome();
    setDashboardSyncState("ok");
  } catch (error) {
    setDashboardSyncState(error.status === 401 || error.status === 403 ? "auth" : "error", error.message);
  }
}

[periodFilter, cameraFilter, machineFilter, customStart, customEnd].filter(Boolean).forEach((element) => {
  element.addEventListener("change", loadDashboard);
  element.addEventListener("input", () => window.clearTimeout(element._timer));
  element.addEventListener("input", () => {
    element._timer = window.setTimeout(loadDashboard, 500);
  });
});

[operationSearch, operationStateFilter].filter(Boolean).forEach((element) => {
  element.addEventListener("input", loadDashboard);
  element.addEventListener("change", loadDashboard);
});

document.querySelectorAll("[data-home-event-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll("[data-home-event-filter]").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    homeEventFilter = button.dataset.homeEventFilter || "all";
    renderHomeEvents();
  });
});

[homeEventSearch].filter(Boolean).forEach((element) => {
  element.addEventListener("input", renderHomeEvents);
});

document.querySelectorAll("[data-home-link]").forEach((card) => {
  const open = () => { window.location.href = card.dataset.homeLink; };
  card.addEventListener("click", open);
  card.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      open();
    }
  });
});

loadDashboard();
loadHome();
setInterval(loadDashboard, 15000);
