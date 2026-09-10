const queryApiBaseUrl = new URLSearchParams(window.location.search).get("api");
const defaultApiBaseUrl = `${window.location.protocol}//${window.location.hostname}:8000/api/v1`;
const API_BASE_URL =
  queryApiBaseUrl || window.CAMPEX_API_BASE_URL || defaultApiBaseUrl;

async function requestJson(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      detail = response.statusText || detail;
    }
    throw new Error(detail);
  }

  if (response.status === 204) {
    return null;
  }

  return response.json();
}

export async function getHealth() {
  return requestJson("/health");
}

export function listCameras() {
  return requestJson("/cameras");
}

export function createCamera(payload) {
  return requestJson("/cameras", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateCamera(cameraId, payload) {
  return requestJson(`/cameras/${cameraId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function deleteCamera(cameraId) {
  const response = await fetch(`${API_BASE_URL}/cameras/${cameraId}`, {
    method: "DELETE",
  });

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
}

export function testCamera(cameraId) {
  return requestJson(`/cameras/${cameraId}/test`, {
    method: "POST",
  });
}

export function getCameraHealth(cameraId) {
  return requestJson(`/cameras/${cameraId}/health`);
}

export function startVision(cameraId) {
  return requestJson(`/cameras/${cameraId}/vision/start`, {
    method: "POST",
  });
}

export function restartVision(cameraId) {
  return requestJson(`/cameras/${cameraId}/vision/restart`, {
    method: "POST",
  });
}

export function stopVision(cameraId) {
  return requestJson(`/cameras/${cameraId}/vision/stop`, {
    method: "POST",
  });
}

export function getVisionStatus(cameraId) {
  return requestJson(`/cameras/${cameraId}/vision/status`);
}

export function getVisionObjects(cameraId) {
  return requestJson(`/cameras/${cameraId}/vision/objects`);
}

export function cameraStreamUrl(cameraId) {
  return `${API_BASE_URL}/cameras/${cameraId}/stream`;
}
