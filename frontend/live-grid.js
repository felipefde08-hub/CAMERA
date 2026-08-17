const picker = document.querySelector("#gridCameraPicker");
const grid = document.querySelector("#liveGrid");
const message = document.querySelector("#gridMessage");
const resources = document.querySelector("#gridResources");

const cameras = new Map();
const selected = new Map();
let statusTimer = null;

async function requestJson(url, options) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : { detail: await response.text() };
  if (!response.ok) throw new Error(payload.detail || `Erro HTTP ${response.status}`);
  return payload;
}

function friendlyGridError(error) {
  const raw = String(error?.message || error || "erro desconhecido");
  if (/internal server error/i.test(raw) || raw.startsWith("500")) {
    return "Não foi possível iniciar uma câmera. Verifique a configuração no Setup.";
  }
  if (/401|unauthorized|not authenticated/i.test(raw)) return "Entre para acessar a Live.";
  if (/403|forbidden/i.test(raw)) return "Você não tem permissão para acessar esta câmera.";
  if (/failed to fetch|networkerror/i.test(raw)) return "Não foi possível conectar à API local.";
  return raw;
}

async function authStatus() {
  return requestJson("/auth/status").catch(() => ({ authenticated: false }));
}

function renderAuthGate() {
  picker.innerHTML = "";
  grid.innerHTML = `
    <section class="cx-live-auth-gate">
      <span>Acesso protegido</span>
      <strong>Entre para visualizar câmeras em tempo real.</strong>
      <p>A Campex só carrega streams, status operacional e contexto de câmeras para usuários autenticados.</p>
      <a class="button-link" href="/settings/cameras?next=%2Flive-grid#login">Entrar</a>
    </section>
  `;
  message.textContent = "Sessão necessária para carregar a Live.";
  resources.textContent = "Live protegida";
}

function statusLabel(status) {
  if (status === "online") return "Online";
  if (status === "conectando") return "Conectando";
  if (status === "reconectando") return "Reconectando";
  return "Offline";
}

function secondsLabel(value) {
  const total = Math.max(0, Math.round(Number(value || 0)));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  if (hours) return `${hours}h ${String(minutes).padStart(2, "0")}m`;
  if (minutes) return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
  return `${seconds}s`;
}

function operationalStatusLabel(status, event) {
  if (event) return `${eventLabel(event)} · ${secondsLabel(event.duration_seconds)}`;
  const labels = {
    ativa: "ATIVA",
    parada: "PARADA",
    evento_aberto: "EVENTO ABERTO",
    sem_evento: "Sem evento aberto",
    offline: "Offline",
    sem_frame_recente: "Sem frame recente",
    inferencia_indisponivel: "Inferência indisponível",
    cobertura_parcial: "Cobertura parcial",
  };
  return labels[status] || "Status indisponível";
}

function eventLabel(event) {
  const labels = {
    machine_stoppage: "PARADA",
    machine_running_without_operator: "ATIVA SEM OPERADOR",
    machine_stopped_with_operator: "PARADA COM OPERADOR",
    workstation_unattended: "POSTO SEM OPERADOR",
  };
  return labels[event?.tipo] || "EVENTO ABERTO";
}

function connectionClass(status) {
  if (status === "online") return "online";
  if (status === "conectando" || status === "reconectando") return "warning";
  return "offline";
}

function hasOperationalContext(camera) {
  const context = camera.context || {};
  return Boolean(context.asset_id || context.process_id || context.area_id || context.machine_monitor_id);
}

function displayCameraName(camera) {
  return camera.context?.primary_label || camera.nome || "Setor em configuração";
}

function displayCameraPath(camera) {
  return camera.context?.path_label || "Contexto operacional pendente";
}

function renderPicker() {
  const rows = Array.from(cameras.values());
  const operationalRows = rows.filter(hasOperationalContext);
  const technicalRows = rows.filter((camera) => !hasOperationalContext(camera));
  if (!rows.length) {
    picker.innerHTML = "";
    message.textContent = "Nenhuma câmera cadastrada. Cadastre uma câmera em Configurações > Câmeras.";
    return;
  }
  if (!operationalRows.length) {
    picker.innerHTML = `
      <section class="cx-live-config-note">
        <strong>Nenhum setor monitorado configurado.</strong>
        <span>Associe câmera, área, processo e ativo no Setup para a Live priorizar a operação.</span>
        <a class="button-link" href="/settings/cameras">Abrir Setup</a>
      </section>
      ${technicalRows.length ? `<details class="cx-live-technical-list"><summary>Câmeras sem contexto operacional (${technicalRows.length})</summary>${technicalRows.map((camera) => `<span>${camera.nome || camera.id}</span>`).join("")}</details>` : ""}
    `;
    grid.innerHTML = "";
    message.textContent = "A Live oficial mostra setores monitorados, não câmeras técnicas soltas.";
    return;
  }
  picker.innerHTML = operationalRows.map((camera) => {
    const checked = selected.has(camera.id) ? "checked" : "";
    return `
      <label class="cx-grid-picker-item">
        <input type="checkbox" data-camera-id="${camera.id}" ${checked} />
        <span>
          <strong>${displayCameraName(camera)}</strong>
          <small>${displayCameraPath(camera)}</small>
        </span>
      </label>
    `;
  }).join("") + (technicalRows.length ? `
    <details class="cx-live-technical-list">
      <summary>${technicalRows.length} câmera(s) aguardando Setup</summary>
      ${technicalRows.map((camera) => `<span>${camera.nome || camera.id}</span>`).join("")}
    </details>
  ` : "");
  message.textContent = selected.size
    ? `${selected.size} setor(es) em monitoramento.`
    : "Selecione setores configurados para acompanhar a operação.";
}

function renderGrid() {
  if (!selected.size) {
    grid.innerHTML = "";
    return;
  }
  grid.innerHTML = Array.from(selected.values()).map((item) => `
    <article class="cx-live-grid-card" data-camera-id="${item.camera.id}">
      <header>
        <div>
          <h3>${item.status?.context?.primary_label || displayCameraName(item.camera)}</h3>
          <p>${item.status?.context?.path_label || displayCameraPath(item.camera)}</p>
        </div>
        <span class="badge ${item.status?.context?.current_event ? "danger" : connectionClass(item.status?.status)}">${operationalStatusLabel(item.status?.context?.operational_status, item.status?.context?.current_event)}</span>
      </header>
      <div class="cx-live-grid-frame">
        <img src="${item.streamUrl}" alt="Transmissão ${displayCameraName(item.camera)}" />
        <a class="cx-live-grid-hit" href="/live-view?camera_id=${encodeURIComponent(item.camera.id)}&nome=${encodeURIComponent(item.camera.nome)}" aria-label="Abrir ${item.status?.context?.primary_label || displayCameraName(item.camera)}"></a>
        <span class="cx-live-grid-overlay">${item.status?.status === "reconectando" ? "Tentando reconectar" : item.status?.context?.current_event ? eventLabel(item.status.context.current_event) : ""}</span>
      </div>
      <section class="cx-live-operational-summary">
        <strong>${item.status?.context?.current_event ? "Evento físico em andamento" : item.status?.context?.operational_status === "sem_evento" ? "Sem evento aberto" : "Estado atual"}</strong>
        <span>${operationalStatusLabel(item.status?.context?.operational_status, item.status?.context?.current_event)}</span>
        ${item.status?.context?.current_event ? `<a href="/events?event_uuid=${encodeURIComponent(item.status.context.current_event.event_uuid || "")}">Ver evento</a>` : ""}
      </section>
      <dl>
        <div><dt>Conexão</dt><dd>${statusLabel(item.status?.status)}</dd></div>
        <div><dt>Inferência</dt><dd>${item.status?.ai_status || "inativa"}</dd></div>
        <div><dt>Pessoas</dt><dd>${item.status?.people_count ?? 0}</dd></div>
        <div><dt>Último frame</dt><dd>${item.status?.last_frame_at ? "recente" : "sem frame"}</dd></div>
      </dl>
      <footer>
        <button type="button" data-action="ai-start" data-camera-id="${item.camera.id}" ${item.status?.ai_status === "ativa" ? "hidden" : ""}>Ativar IA</button>
        <button type="button" data-action="ai-stop" data-camera-id="${item.camera.id}" ${item.status?.ai_status !== "ativa" ? "hidden" : ""}>Desativar IA</button>
        <a class="button-link" href="/live-view?camera_id=${encodeURIComponent(item.camera.id)}&nome=${encodeURIComponent(item.camera.nome)}">Abrir setor</a>
        <button type="button" data-action="stop" data-camera-id="${item.camera.id}">Parar esta câmera</button>
      </footer>
    </article>
  `).join("");
}

async function startCamera(cameraId) {
  if (selected.size >= 4) {
    message.textContent = "Para preservar desempenho, monitore até quatro câmeras nesta tela.";
    renderPicker();
    return;
  }
  const camera = cameras.get(cameraId);
  if (!camera) return;
  await requestJson(`/cameras/${cameraId}/start`, { method: "POST" });
  selected.set(cameraId, {
    camera,
    status: { status: "conectando" },
    streamUrl: `/cameras/${encodeURIComponent(cameraId)}/stream?ts=${Date.now()}`,
  });
  renderPicker();
  renderGrid();
}

async function stopCamera(cameraId) {
  await requestJson(`/cameras/${cameraId}/stop`, { method: "POST" }).catch(() => {});
  selected.delete(cameraId);
  renderPicker();
  renderGrid();
}

async function refreshStatuses() {
  try {
    const overview = await requestJson("/live/overview");
    overview.cameras.forEach((entry) => {
      cameras.set(entry.camera.id, { ...entry.camera, context: entry.status?.context });
      const item = selected.get(entry.camera.id);
      if (item) {
        item.camera = { ...entry.camera, context: entry.status?.context };
        item.status = entry.status;
      }
    });
    const resource = overview.resources || {};
    resources.textContent = `${rowsWithContextLabel()} · diagnóstico técnico no Setup`;
  } catch (error) {
    resources.textContent = "Recursos indisponíveis";
    await Promise.all(Array.from(selected.keys()).map(async (cameraId) => {
      try {
        const status = await requestJson(`/cameras/${cameraId}/status`);
        const item = selected.get(cameraId);
        if (item) item.status = status;
      } catch (statusError) {
        const item = selected.get(cameraId);
        if (item) item.status = { status: "offline", error: statusError.message };
      }
    }));
  }
  renderGrid();
}

async function toggleAnalysis(cameraId, enabled) {
  await requestJson(`/cameras/${cameraId}/analysis/${enabled ? "start" : "stop"}`, { method: "POST" });
  await refreshStatuses();
}

picker.addEventListener("change", (event) => {
  const input = event.target.closest("input[data-camera-id]");
  if (!input) return;
  const cameraId = input.dataset.cameraId;
  if (input.checked) startCamera(cameraId).catch((error) => {
    message.textContent = error.message;
    selected.delete(cameraId);
    renderPicker();
  });
  else stopCamera(cameraId);
});

grid.addEventListener("click", (event) => {
  const target = event.target.closest("[data-action][data-camera-id]");
  if (!target) return;
  const cameraId = target.dataset.cameraId;
  const action = target.dataset.action;
  if (action === "stop") stopCamera(cameraId);
  if (action === "ai-start") toggleAnalysis(cameraId, true).catch((error) => { message.textContent = error.message; });
  if (action === "ai-stop") toggleAnalysis(cameraId, false).catch((error) => { message.textContent = error.message; });
});

async function boot() {
  const auth = await authStatus();
  if (!auth.authenticated) {
    renderAuthGate();
    return;
  }
  const overview = await requestJson("/live/overview").catch(async () => {
    const rows = await requestJson("/cameras/estado");
    return { cameras: rows.map((camera) => ({ camera, status: { context: null } })), resources: {} };
  });
  const rows = overview.cameras.map((entry) => ({ ...entry.camera, context: entry.status?.context }));
  rows.forEach((camera) => cameras.set(camera.id, camera));
  renderPicker();
  const auto = rows.filter(hasOperationalContext).slice(0, 2);
  for (const camera of auto) {
    await startCamera(camera.id).catch((error) => { message.textContent = friendlyGridError(error); });
  }
  await refreshStatuses();
  statusTimer = setInterval(refreshStatuses, 2000);
}

function rowsWithContextLabel() {
  const total = Array.from(cameras.values()).filter(hasOperationalContext).length;
  return `${total} setor(es) configurado(s)`;
}

window.addEventListener("beforeunload", () => {
  if (statusTimer) clearInterval(statusTimer);
});

boot().catch((error) => {
  message.textContent = friendlyGridError(error);
});
