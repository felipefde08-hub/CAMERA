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

function statusLabel(status) {
  if (status === "online") return "Online";
  if (status === "conectando") return "Conectando";
  if (status === "reconectando") return "Reconectando";
  return "Offline";
}

function renderPicker() {
  const rows = Array.from(cameras.values());
  if (!rows.length) {
    picker.innerHTML = "";
    message.textContent = "Nenhuma câmera cadastrada. Cadastre uma câmera em Configurações > Câmeras.";
    return;
  }
  picker.innerHTML = rows.map((camera) => {
    const checked = selected.has(camera.id) ? "checked" : "";
    return `
      <label class="cx-grid-picker-item">
        <input type="checkbox" data-camera-id="${camera.id}" ${checked} />
        <span>
          <strong>${camera.nome}</strong>
          <small>${camera.rtsp_host || camera.secure_ref || "Fonte protegida"}</small>
        </span>
      </label>
    `;
  }).join("");
  message.textContent = selected.size
    ? `${selected.size} câmera(s) em monitoramento.`
    : "Selecione ao menos duas câmeras para validar operação simultânea.";
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
          <h3>${item.camera.nome}</h3>
          <p>${item.camera.rtsp_host || "Fonte RTSP protegida"}</p>
        </div>
        <span class="badge ${item.status?.status === "online" ? "online" : "offline"}">${statusLabel(item.status?.status)}</span>
      </header>
      <div class="cx-live-grid-frame">
        <img src="${item.streamUrl}" alt="Transmissão ${item.camera.nome}" />
        <span class="cx-live-grid-overlay">${item.status?.status === "reconectando" ? "Tentando reconectar" : ""}</span>
      </div>
      <dl>
        <div><dt>Vídeo</dt><dd>${item.status?.width && item.status?.height ? `${item.status.width}x${item.status.height}` : "indisponível"}</dd></div>
        <div><dt>FPS</dt><dd>${item.status?.fps ?? "-"}</dd></div>
        <div><dt>IA</dt><dd>${item.status?.ai_status || "inativa"}</dd></div>
        <div><dt>FPS IA</dt><dd>${item.status?.analysis_fps ?? "-"}</dd></div>
        <div><dt>Pessoas</dt><dd>${item.status?.people_count ?? 0}</dd></div>
        <div><dt>Área</dt><dd>${item.status?.area_estado || "sem área"}</dd></div>
      </dl>
      <footer>
        <button type="button" data-action="ai-start" data-camera-id="${item.camera.id}" ${item.status?.ai_status === "ativa" ? "hidden" : ""}>Ativar IA</button>
        <button type="button" data-action="ai-stop" data-camera-id="${item.camera.id}" ${item.status?.ai_status !== "ativa" ? "hidden" : ""}>Desativar IA</button>
        <a class="button-link" href="/live-view?camera_id=${encodeURIComponent(item.camera.id)}&nome=${encodeURIComponent(item.camera.nome)}">Configurar zona</a>
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
  await Promise.all(Array.from(selected.keys()).map(async (cameraId) => {
    try {
      const status = await requestJson(`/cameras/${cameraId}/status`);
      const item = selected.get(cameraId);
      if (item) item.status = status;
    } catch (error) {
      const item = selected.get(cameraId);
      if (item) item.status = { status: "offline", error: error.message };
    }
  }));
  try {
    const resource = await requestJson("/live-streams/status");
    resources.textContent = `CPU ${Math.round(resource.cpu_percent)}% · Memória ${Math.round(resource.memory_percent)}% · Streams ${resource.active_streams}`;
  } catch (_error) {
    resources.textContent = "Recursos indisponíveis";
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
  const rows = await requestJson("/cameras/estado");
  rows.forEach((camera) => cameras.set(camera.id, camera));
  renderPicker();
  const auto = rows.slice(0, 2);
  for (const camera of auto) {
    await startCamera(camera.id).catch((error) => { message.textContent = error.message; });
  }
  await refreshStatuses();
  statusTimer = setInterval(refreshStatuses, 2000);
}

window.addEventListener("beforeunload", () => {
  if (statusTimer) clearInterval(statusTimer);
});

boot().catch((error) => {
  message.textContent = error.message;
});
