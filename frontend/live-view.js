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
const configureRestrictedArea = document.querySelector("#configureRestrictedArea");
const clearMachine = document.querySelector("#clearMachine");
const zoneTypeInput = document.querySelector("#zoneTypeInput");
const zoneNameInput = document.querySelector("#zoneNameInput");
const zoneSecondsInput = document.querySelector("#zoneSecondsInput");
const zoneList = document.querySelector("#zoneList");
const machineSelect = document.querySelector("#machineSelect");
const machineNameInput = document.querySelector("#machineNameInput");
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
const drawToolbar = document.querySelector("#drawToolbar");
const drawToolbarTitle = document.querySelector("#drawToolbarTitle");
const drawToolbarHint = document.querySelector("#drawToolbarHint");
const undoDrawPoint = document.querySelector("#undoDrawPoint");
const cancelDraw = document.querySelector("#cancelDraw");
const saveDraw = document.querySelector("#saveDraw");

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
  const hasImageBox = imageRect.width > 1 && imageRect.height > 1;
  const rect = hasImageBox ? imageRect : stageRect;
  liveViewCanvas.style.left = `${rect.left - stageRect.left}px`;
  liveViewCanvas.style.top = `${rect.top - stageRect.top}px`;
  liveViewCanvas.style.width = `${rect.width}px`;
  liveViewCanvas.style.height = `${rect.height}px`;
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
  machineConfig = ops.machine || machineConfig;
  liveViewName.textContent = payload.nome || "Live View";
  if (liveRailName) liveRailName.textContent = payload.nome || "Live View";
  liveViewResolution.textContent = payload.width && payload.height ? `${payload.width}x${payload.height}` : "indisponível";
  liveViewFps.textContent = payload.fps ?? "indisponível";
  liveViewInferenceFps.textContent = ops.inference_fps ?? 0;
  liveViewPeople.textContent = ops.people_count ?? 0;
  liveViewMachine.textContent = machineConfig ? machineConfig.nome : "sem configuração";
  liveViewMachineState.textContent = formatMachineState(ops.machine_state);
  liveViewOperator.textContent = ops.operator_present ? `Operador presente (${ops.operator_people_count})` : "Sem operador";
  liveViewMotion.textContent = `${ops.machine_motion ?? 0}${ops.machine_threshold ? ` / limite ${ops.machine_threshold.toFixed ? ops.machine_threshold.toFixed(2) : ops.machine_threshold}` : ""}`;
  const observation = payload.observation || {};
  liveViewRelation.textContent = observation.machine_state
    ? `${observation.machine_state} · conf. ${observation.machine_confidence} · operador ${observation.people_in_operator_zone} · restrita ${observation.people_in_restricted_zone}`
    : ops.relation || "Aguardando configuração";
  updateAiControls(payload.ai_status || ops.ai_status);
  if (payload.calibration && payload.calibration.status && payload.calibration.status !== "idle") {
    renderCalibration(payload.calibration);
  }
  if (status === "online") {
    setStatus("online", "Transmissão ativa.");
  } else if (status === "conectando" || status === "reconectando") {
    setStatus(status, "Tentando reconectar...");
  } else {
    setStatus("offline", payload.error || "Câmera offline.");
  }
  drawCanvas();
}

function updateAiControls(aiStatus) {
  const active = aiStatus === "ativa" || aiStatus === "carregando";
  liveAiStart.hidden = active;
  liveAiStop.hidden = !active;
  liveAiStart.classList.toggle("active", !active);
  liveAiStop.classList.toggle("active", active);
}

function formatMachineState(state) {
  if (!state || state === "NAO_CONFIGURADA") return "Máquina não configurada";
  if (state === "SEM SINAL") return "Sem sinal";
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
  liveViewImage.onload = () => setStatus("online", "Transmissão ativa.");
  liveViewImage.onerror = () => setStatus("reconectando", "Sem imagem no momento. Tentando reconectar...");
  statusTimer = setInterval(pollStatus, 1500);
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
  liveViewMachine.textContent = selected ? selected.nome : machineConfig ? machineConfig.nome : "sem configuração";
  updateMachineRegionStatus();
  renderCalibrationFromMachine(selected);
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
    ? `machine_region: salva (${machineRegion.id})`
    : "machine_region: ausente. Crie uma zona do tipo machine_region antes de calibrar.";
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
  zoneTypeInput.value = zone?.tipo || "machine_region";
  zoneNameInput.value = zone?.nome || "";
  zoneSecondsInput.value = zone?.absence_tolerance_seconds ?? zone?.dwell_limit_seconds ?? "";
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
  if (["workstation", "operator_zone"].includes(zoneType)) {
    payload.absence_tolerance_seconds = Number.isFinite(seconds) ? seconds : 30;
  }
  if (["dwell_area", "work_area"].includes(zoneType)) {
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
  try {
    const created = await requestJson(`/cameras/${currentCameraId}/machine-monitors`, {
      method: "POST",
      body: JSON.stringify({
        nome,
        machine_polygon: machineRegion.pontos,
        operator_polygon: operatorZone.pontos,
        stop_seconds: 30,
        recovery_seconds: 10,
        operator_absence_seconds: 15,
      }),
    });
    selectedMachineId = created.id;
    calibrationStatus.textContent = `Máquina cadastrada: ${created.nome} (${created.id})`;
    await loadMachines();
  } catch (error) {
    calibrationStatus.textContent = `Erro ao cadastrar máquina: ${error.message}`;
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
  if (sessionId) fetch(`/live-view/${sessionId}/stop`, { method: "POST", keepalive: true }).catch(() => {});
});

startLiveView().catch((error) => setStatus("offline", error.message));
