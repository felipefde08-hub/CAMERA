import {
  createCamera,
  deleteCamera,
  cameraStreamUrl,
  cameraVideoUrl,
  getCameraHealth,
  getHealth,
  getStreamInfo,
  getVisionObjects,
  getVisionStatus,
  listCameras,
  restartVision,
  startVision,
  stopVision,
  testCamera,
  updateCamera,
} from "./api.js";
import { currentRoute, routes } from "./state.js";

const statusElement = document.querySelector("#backend-status");
const statusText = statusElement.querySelector(".status-text");
const pageTitle = document.querySelector("#page-title");
const appView = document.querySelector("#app-view");
const navLinks = document.querySelectorAll("[data-route]");
let activeMediaCameraId = null;

function renderRoute() {
  const routeKey = currentRoute();
  const route = routes[routeKey];

  pageTitle.textContent = route.title;
  navLinks.forEach((link) => {
    const isCurrent = link.dataset.route === routeKey;
    if (isCurrent) {
      link.setAttribute("aria-current", "page");
    } else {
      link.removeAttribute("aria-current");
    }
  });

  if (routeKey === "cameras") {
    renderCamerasPage();
    return;
  }

  if (routeKey === "live") {
    renderLivePage();
    return;
  }

  appView.innerHTML = `
    <div class="foundation-panel">
      <section class="module-notice">
        <h2>${route.title}</h2>
        <p>${route.message}</p>
      </section>
      <section class="system-strip" aria-label="Estado da fundacao">
        <div class="system-cell">
          <span>Frontend</span>
          <strong>Shell carregado</strong>
        </div>
        <div class="system-cell">
          <span>Backend</span>
          <strong id="backend-summary">Aguardando health check</strong>
        </div>
        <div class="system-cell">
          <span>Banco</span>
          <strong>SQLite inicializado pelo backend</strong>
        </div>
      </section>
    </div>
  `;
}

async function renderLivePage() {
  appView.innerHTML = `
    <div class="live-console">
      <section class="live-toolbar" aria-label="Controles ao vivo">
        <label>
          Camera
          <select id="live-camera-select"></select>
        </label>
        <div class="row-actions">
          <button type="button" id="live-start-vision">Vision ON</button>
          <button type="button" id="live-stop-vision">Vision OFF</button>
          <button type="button" id="live-restart-vision">Reiniciar Vision</button>
          <button type="button" id="live-refresh">Atualizar</button>
        </div>
      </section>
      <section class="live-grid">
        <div class="live-feed">
          <div class="live-feed-header">
            <strong id="live-camera-name">Nenhuma camera selecionada</strong>
            <span class="health-badge" id="live-camera-status" data-status="OFFLINE">OFFLINE</span>
          </div>
          <div id="live-media-host" class="live-media-host" aria-live="polite">
            <div class="media-placeholder">Selecione uma camera</div>
          </div>
        </div>
        <aside class="live-inspector">
          <h2>Vision Core</h2>
          <dl id="vision-metrics" class="metric-list"></dl>
          <h3>Objetos</h3>
          <div id="vision-objects" class="object-list"></div>
        </aside>
      </section>
    </div>
  `;

  document.querySelector("#live-camera-select").addEventListener("change", selectLiveCamera);
  document.querySelector("#live-start-vision").addEventListener("click", handleStartVision);
  document.querySelector("#live-stop-vision").addEventListener("click", handleStopVision);
  document.querySelector("#live-restart-vision").addEventListener("click", handleRestartVision);
  document.querySelector("#live-refresh").addEventListener("click", refreshLiveStatus);
  await loadLiveCameras();
}

async function loadLiveCameras() {
  const select = document.querySelector("#live-camera-select");
  try {
    const cameras = await listCameras();
    select.innerHTML = cameras
      .map((camera) => `<option value="${camera.id}">${camera.name}</option>`)
      .join("");

    if (!cameras.length) {
      select.innerHTML = `<option value="">Cadastre uma camera</option>`;
      renderVisionStatus(null, [], null);
      return;
    }

    await selectLiveCamera();
  } catch (error) {
    select.innerHTML = `<option value="">Backend indisponivel</option>`;
    renderVisionStatus(null, [], null);
    console.error(error);
  }
}

async function selectLiveCamera() {
  const cameraId = document.querySelector("#live-camera-select").value;
  try {
    const camera = await selectedCamera();
    document.querySelector("#live-camera-name").textContent = camera?.name || "Camera";
    const status = statusLabel(camera?.status);
    const statusElement = document.querySelector("#live-camera-status");
    statusElement.textContent = status;
    statusElement.dataset.status = status;
    const visionStatus = await refreshLiveStatus();
    await renderLiveMedia(camera, visionStatus?.status === "RUNNING");
  } catch (error) {
    document.querySelector("#live-camera-name").textContent = "Backend indisponivel";
    document.querySelector("#live-camera-status").textContent = "OFFLINE";
    document.querySelector("#live-camera-status").dataset.status = "OFFLINE";
    renderMediaPlaceholder("Stream indisponivel");
    renderVisionStatus(null, [], null);
    console.error(error);
  }
}

async function selectedCamera() {
  const cameraId = document.querySelector("#live-camera-select").value;
  if (!cameraId) {
    return null;
  }
  const cameras = await listCameras();
  return cameras.find((item) => item.id === cameraId) || null;
}

async function renderLiveMedia(camera, visionEnabled = false) {
  activeMediaCameraId = camera?.id || null;
  if (!camera?.id) {
    renderMediaPlaceholder("Selecione uma camera");
    return;
  }

  renderMediaPlaceholder("Abrindo stream...");

  if (visionEnabled) {
    renderMjpegElement(camera);
    return;
  }

  if (camera.source_type === "video_file") {
    renderVideoElement(camera);
    return;
  }

  try {
    const info = await getStreamInfo(camera.id);
    if (activeMediaCameraId !== camera.id) {
      return;
    }

    if (info.mode === "file_video") {
      renderVideoElement(camera);
      return;
    }

    renderMjpegElement(camera);
  } catch (error) {
    renderMjpegElement(camera);
  }
}

function renderVideoElement(camera) {
  const mediaHost = document.querySelector("#live-media-host");
  const sources = videoSourcesFor(camera);
  mediaHost.innerHTML = `
    <video
      id="live-video"
      class="live-media"
      src="${sources[0]}"
      controls
      autoplay
      muted
      playsinline
      loop
    ></video>
  `;

  const video = mediaHost.querySelector("video");
  let sourceIndex = 0;
  video.addEventListener("error", () => {
    sourceIndex += 1;
    if (sources[sourceIndex]) {
      video.src = sources[sourceIndex];
      video.load();
      video.play().catch(() => {
        video.controls = true;
      });
      return;
    }
    renderMediaPlaceholder("Nao foi possivel reproduzir o arquivo de video.");
  });
  video.play().catch(() => {
    video.controls = true;
  });
}

function renderMjpegElement(camera) {
  const mediaHost = document.querySelector("#live-media-host");
  const streamUrl = `${cameraStreamUrl(camera.id)}?t=${Date.now()}`;
  mediaHost.innerHTML = `
    <img
      id="live-stream"
      class="live-media"
      alt="Video ao vivo da camera selecionada"
      src="${streamUrl}"
    />
  `;

  mediaHost.querySelector("img").addEventListener("error", () => {
    renderMediaPlaceholder("Aguardando frames da camera ao vivo.");
  });
}

function videoSourcesFor(camera) {
  const sources = [cameraVideoUrl(camera.id)];
  const staticUrl = staticVideoUrlFromSource(camera.source_uri);
  if (staticUrl && !sources.includes(staticUrl)) {
    sources.push(staticUrl);
  }
  return sources;
}

function staticVideoUrlFromSource(sourceUri) {
  if (!sourceUri) {
    return null;
  }
  const normalized = sourceUri.replaceAll("\\", "/");
  const filename = normalized.split("/").filter(Boolean).pop();
  if (!filename || !filename.toLowerCase().endsWith(".mp4")) {
    return null;
  }
  return `${window.location.origin}/${encodeURIComponent(filename)}`;
}

function renderMediaPlaceholder(message) {
  const mediaHost = document.querySelector("#live-media-host");
  if (!mediaHost) {
    return;
  }
  mediaHost.innerHTML = `<div class="media-placeholder">${message}</div>`;
}

async function handleStartVision() {
  const cameraId = document.querySelector("#live-camera-select").value;
  if (!cameraId) {
    return;
  }
  await startVision(cameraId);
  const camera = await selectedCamera();
  if (camera) {
    renderMjpegElement(camera);
  }
  await refreshLiveStatus();
}

async function handleStopVision() {
  const cameraId = document.querySelector("#live-camera-select").value;
  if (!cameraId) {
    return;
  }
  await stopVision(cameraId);
  const camera = await selectedCamera();
  await renderLiveMedia(camera, false);
  await refreshLiveStatus();
}

async function handleRestartVision() {
  const cameraId = document.querySelector("#live-camera-select").value;
  if (!cameraId) {
    return;
  }
  await restartVision(cameraId);
  const camera = await selectedCamera();
  if (camera) {
    renderMjpegElement(camera);
  }
  await refreshLiveStatus();
}

async function refreshLiveStatus() {
  const cameraId = document.querySelector("#live-camera-select")?.value;
  if (!cameraId) {
    return;
  }

  try {
    const [health, visionStatus, objects] = await Promise.all([
      getCameraHealth(cameraId),
      getVisionStatus(cameraId),
      getVisionObjects(cameraId),
    ]);
    renderVisionStatus(visionStatus, objects, health);
    return visionStatus;
  } catch (error) {
    renderVisionStatus({ status: "ERROR", error: error.message, metrics: null }, [], null);
    return null;
  }
}

function renderVisionStatus(visionStatus, objects, health) {
  const metrics = visionStatus?.metrics || {};
  const status = visionStatus?.status || "STOPPED";
  document.querySelector("#vision-metrics").innerHTML = `
    <dt>Camera</dt><dd>${health?.status || "UNKNOWN"}</dd>
    <dt>Vision</dt><dd>${status}</dd>
    <dt>Camera FPS</dt><dd>${health?.approximate_fps ?? metrics.camera_fps ?? "0"}</dd>
    <dt>Vision FPS</dt><dd>${metrics.vision_fps ?? "0"}</dd>
    <dt>Frames</dt><dd>${metrics.frames_processed ?? 0}/${metrics.frames_received ?? 0}</dd>
    <dt>Drops</dt><dd>${metrics.frames_dropped ?? 0}</dd>
    <dt>Frame Age</dt><dd>${metrics.frame_age_ms ? `${metrics.frame_age_ms.toFixed(1)} ms` : "-"}</dd>
    <dt>Device</dt><dd>${metrics.device || "-"}</dd>
    <dt>Detector</dt><dd>${metrics.detector || "-"}</dd>
    <dt>Tracker</dt><dd>${metrics.tracker || "-"}</dd>
    <dt>Inferencia</dt><dd>${metrics.inference_ms ? `${metrics.inference_ms.toFixed(1)} ms` : "-"}</dd>
    <dt>Objetos</dt><dd>${objects.length}</dd>
    <dt>Erro</dt><dd>${visionStatus?.error || "-"}</dd>
  `;

  document.querySelector("#vision-objects").innerHTML = objects.length
    ? objects
        .map(
          (object) => `
            <article class="object-row">
              <strong>${object.class_name.toUpperCase()} #${object.track_id}</strong>
              <span>${Math.round(object.confidence * 100)}% · ${object.bounding_box.map((value) => Math.round(value)).join(", ")}</span>
            </article>
          `
        )
        .join("")
    : `<div class="empty-state"><strong>Nenhum objeto ativo</strong><span>Inicie Vision e aguarde deteccoes do stream.</span></div>`;
}

function statusLabel(status) {
  return status || "OFFLINE";
}

function cameraRows(cameras) {
  if (!cameras.length) {
    return `
      <div class="empty-state">
        <strong>Nenhuma câmera cadastrada</strong>
        <span>Cadastre uma fonte local, arquivo de vídeo ou RTSP para iniciar a camada de câmera.</span>
      </div>
    `;
  }

  return cameras
    .map(
      (camera) => `
        <article class="camera-row" data-camera-id="${camera.id}">
          <div>
            <strong>${camera.name}</strong>
            <span>${camera.source_type} · ${camera.source_uri}</span>
          </div>
          <span class="health-badge" data-status="${statusLabel(camera.status)}">${statusLabel(camera.status)}</span>
          <label class="inline-toggle">
            <input type="checkbox" data-action="toggle-enabled" ${camera.enabled ? "checked" : ""} />
            Ativa
          </label>
          <div class="row-actions">
            <button type="button" data-action="test">Testar</button>
            <button type="button" data-action="health">Health</button>
            <button type="button" data-action="delete">Excluir</button>
          </div>
          <pre class="camera-result" hidden></pre>
        </article>
      `
    )
    .join("");
}

async function renderCamerasPage() {
  appView.innerHTML = `
    <div class="camera-admin">
      <section class="camera-form-panel">
        <h2>Adicionar câmera</h2>
        <form id="camera-form">
          <label>
            Nome
            <input name="name" required maxlength="120" placeholder="Entrada principal" />
          </label>
          <label>
            Tipo da fonte
            <select name="source_type">
              <option value="webcam">Webcam</option>
              <option value="video_file">Video File</option>
              <option value="rtsp">RTSP</option>
            </select>
          </label>
          <label>
            Fonte
            <input name="source_uri" required maxlength="1000" placeholder="0, C:\\videos\\teste.mp4 ou rtsp://..." />
          </label>
          <label>
            Área opcional
            <input name="area_id" maxlength="80" placeholder="entrada" />
          </label>
          <div class="form-options">
            <label class="inline-toggle">
              <input name="enabled" type="checkbox" checked />
              Ativa
            </label>
            <label class="inline-toggle">
              <input name="vision_enabled" type="checkbox" />
              Vision habilitada quando existir
            </label>
          </div>
          <button type="submit">Salvar câmera</button>
        </form>
      </section>
      <section class="camera-list-panel">
        <div class="section-heading">
          <h2>Câmeras cadastradas</h2>
          <button type="button" id="refresh-cameras">Atualizar</button>
        </div>
        <div id="camera-list" class="camera-list">Carregando câmeras...</div>
      </section>
    </div>
  `;

  document.querySelector("#camera-form").addEventListener("submit", handleCameraSubmit);
  document.querySelector("#refresh-cameras").addEventListener("click", loadCameras);
  await loadCameras();
}

async function loadCameras() {
  const listElement = document.querySelector("#camera-list");
  try {
    const cameras = await listCameras();
    listElement.innerHTML = cameraRows(cameras);
    listElement.querySelectorAll(".camera-row").forEach((row) => {
      row.addEventListener("click", handleCameraAction);
      row
        .querySelector("[data-action='toggle-enabled']")
        .addEventListener("change", handleEnabledChange);
    });
  } catch (error) {
    listElement.innerHTML = `<div class="empty-state"><strong>Falha ao carregar câmeras</strong><span>${error.message}</span></div>`;
  }
}

async function handleCameraSubmit(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const data = new FormData(form);
  const payload = {
    name: data.get("name").trim(),
    source_type: data.get("source_type"),
    source_uri: data.get("source_uri").trim(),
    area_id: data.get("area_id").trim() || null,
    enabled: data.get("enabled") === "on",
    vision_enabled: data.get("vision_enabled") === "on",
  };

  await createCamera(payload);
  form.reset();
  form.elements.enabled.checked = true;
  await loadCameras();
}

async function handleEnabledChange(event) {
  const row = event.currentTarget.closest(".camera-row");
  await updateCamera(row.dataset.cameraId, { enabled: event.currentTarget.checked });
  await loadCameras();
}

async function handleCameraAction(event) {
  const button = event.target.closest("button[data-action]");
  if (!button) {
    return;
  }

  const row = button.closest(".camera-row");
  const result = row.querySelector(".camera-result");
  const cameraId = row.dataset.cameraId;
  const action = button.dataset.action;

  try {
    if (action === "delete") {
      await deleteCamera(cameraId);
      await loadCameras();
      return;
    }

    const response =
      action === "test" ? await testCamera(cameraId) : await getCameraHealth(cameraId);
    result.hidden = false;
    result.textContent = JSON.stringify(response, null, 2);
  } catch (error) {
    result.hidden = false;
    result.textContent = error.message;
  }
}

async function refreshBackendStatus() {
  const backendSummary = document.querySelector("#backend-summary");

  try {
    const health = await getHealth();
    statusElement.dataset.state = "online";
    statusText.textContent = `${health.service} ${health.version} online`;
    if (backendSummary) {
      backendSummary.textContent = "Conectado via /api/v1/health";
    }
  } catch (error) {
    statusElement.dataset.state = "offline";
    statusText.textContent = "Backend indisponivel";
    if (backendSummary) {
      backendSummary.textContent = "Sem resposta do backend";
    }
    console.error(error);
  }
}

window.addEventListener("hashchange", () => {
  renderRoute();
  refreshBackendStatus();
});

renderRoute();
refreshBackendStatus();
setInterval(refreshBackendStatus, 30000);
setInterval(() => {
  if (currentRoute() === "live") {
    refreshLiveStatus();
  }
}, 2000);
