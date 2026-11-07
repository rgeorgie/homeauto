// Camera / video doorbell viewer: a snapshot on demand (and when the doorbell rings), plus a live MJPEG view.
// The backend runs a single ffmpeg for the live view; closing the fetch connection stops it.

let cameraViewer = { devId: null, objectUrl: null, token: 0, abort: null };
const ringSeen = {}; // device id -> last ring_seq we have reacted to

function cameraEl(id) { return document.getElementById(id); }

function setCameraStatus(text) {
  const el = cameraEl("camera-viewer-status");
  if (!el) return;
  el.textContent = text || "";
  el.style.display = text ? "flex" : "none";
}

function releaseCameraMedia() {
  if (cameraViewer.abort) { cameraViewer.abort.abort(); cameraViewer.abort = null; }
  const img = cameraEl("camera-viewer-img");
  if (img) img.removeAttribute("src");
  if (cameraViewer.objectUrl) { URL.revokeObjectURL(cameraViewer.objectUrl); cameraViewer.objectUrl = null; }
}

function closeCameraViewer() {
  cameraControlsToken++;
  const panel = cameraEl("camera-controls-panel");
  if (panel) { panel.style.display = "none"; panel.innerHTML = ""; }
  cameraViewer.token++;
  releaseCameraMedia();
  cameraViewer.devId = null;
  const modal = cameraEl("modal-camera-viewer");
  if (modal) modal.style.display = "none";
  if (typeof resetIdleTimer === "function") resetIdleTimer();
}

async function errorDetail(res, fallback) {
  try { return (await res.json()).detail || fallback; } catch (e) { return fallback; }
}

async function showCameraSnapshot() {
  const devId = cameraViewer.devId;
  if (!devId) return;
  const token = ++cameraViewer.token;
  releaseCameraMedia();
  setCameraStatus("Waking the camera...");
  const ctrl = new AbortController();
  cameraViewer.abort = ctrl;
  try {
    const res = await fetch(`/api/devices/${encodeURIComponent(devId)}/snapshot?t=${Date.now()}`, { signal: ctrl.signal });
    if (token !== cameraViewer.token) return;
    if (!res.ok) {
      setCameraStatus(await errorDetail(res, `Snapshot failed (${res.status})`));
      return;
    }
    const blob = await res.blob();
    if (token !== cameraViewer.token) return;
    cameraViewer.objectUrl = URL.createObjectURL(blob);
    cameraEl("camera-viewer-img").src = cameraViewer.objectUrl;
    setCameraStatus("");
  } catch (e) {
    if (token === cameraViewer.token && e.name !== "AbortError") setCameraStatus("Snapshot failed: " + e.message);
  }
}

async function startCameraLive() {
  const devId = cameraViewer.devId;
  if (!devId) return;
  const token = ++cameraViewer.token;
  releaseCameraMedia();
  setCameraStatus("Starting live view (a battery camera needs a few seconds to wake)...");
  const ctrl = new AbortController();
  cameraViewer.abort = ctrl;
  try {
    const res = await fetch(`/api/devices/${encodeURIComponent(devId)}/live.mjpeg?t=${Date.now()}`, { signal: ctrl.signal });
    if (token !== cameraViewer.token) return;
    if (!res.ok) {
      setCameraStatus(await errorDetail(res, `Live view failed (${res.status})`));
      return;
    }
    // Read the multipart stream ourselves and paint the newest JPEG: one connection means one ffmpeg on the Pi
    const reader = res.body.getReader();
    const img = cameraEl("camera-viewer-img");
    let buf = new Uint8Array(0);
    let first = true;
    while (token === cameraViewer.token) {
      const { value, done } = await reader.read();
      if (done) break;
      const merged = new Uint8Array(buf.length + value.length);
      merged.set(buf);
      merged.set(value, buf.length);
      buf = merged;
      // A JPEG runs from FFD8 to FFD9: show the newest complete one and keep the remainder
      let end = -1;
      for (let i = buf.length - 2; i >= 0; i--) { if (buf[i] === 0xFF && buf[i + 1] === 0xD9) { end = i + 2; break; } }
      if (end < 0) continue;
      let start = -1;
      for (let i = end - 2; i >= 0; i--) { if (buf[i] === 0xFF && buf[i + 1] === 0xD8) { start = i; break; } }
      if (start >= 0) {
        const old = cameraViewer.objectUrl;
        cameraViewer.objectUrl = URL.createObjectURL(new Blob([buf.slice(start, end)], { type: "image/jpeg" }));
        img.src = cameraViewer.objectUrl;
        if (old) URL.revokeObjectURL(old);
        if (first) { setCameraStatus(""); first = false; }
      }
      buf = buf.slice(end);
    }
    if (token === cameraViewer.token) setCameraStatus("Live view ended");
  } catch (e) {
    if (token === cameraViewer.token && e.name !== "AbortError") setCameraStatus("Live view failed: " + e.message);
  }
}

function openCameraViewer(devId, mode) {
  cameraControlsToken++;
  const panel = cameraEl("camera-controls-panel");
  if (panel) { panel.style.display = "none"; panel.innerHTML = ""; }
  const dev = (state.devices || []).find(d => d.id === devId);
  cameraViewer.devId = devId;
  cameraEl("camera-viewer-title").textContent = dev ? dev.name : "Camera";
  cameraEl("modal-camera-viewer").style.display = "flex";
  if (mode === "live") startCameraLive(); else showCameraSnapshot();
}

// Called with every device update: pop up the camera when a doorbell rings.
function checkDoorbellRings(devices) {
  (devices || []).forEach(dev => {
    if (deviceKind(dev) !== "camera") return;
    const seq = dev.ring_seq || 0; // the backend only sets it once the first ring has happened
    const known = ringSeen[dev.id];
    ringSeen[dev.id] = seq;
    if (known === undefined || known === seq) return; // first sighting (e.g. page load) or no new ring
    if (typeof showToast === "function") showToast(`🔔 ${dev.name} rang`, 6000);
    if (typeof stopScreensaver === "function") stopScreensaver();
    openCameraViewer(dev.id, "snapshot");
  });
}

// ----- Controls: pan/tilt and the settings this camera model supports (the backend reads them from Tuya) -----

let cameraControlsToken = 0;
const PTZ_PAD = [["up_left", "↖"], ["up", "↑"], ["up_right", "↗"], ["left", "←"], null, ["right", "→"], ["down_left", "↙"], ["down", "↓"], ["down_right", "↘"]];

async function sendCameraControl(code, value, rollback) {
  const devId = cameraViewer.devId;
  try {
    const res = await fetch(`/api/devices/${encodeURIComponent(devId)}/camera-controls`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code, value }),
    });
    if (!res.ok) throw new Error(await errorDetail(res, `Failed (${res.status})`));
  } catch (e) {
    if (rollback) rollback();
    showToast("Camera: " + e.message);
  }
}

async function moveCamera(direction, btn) {
  const devId = cameraViewer.devId;
  btn.disabled = true;
  try {
    const res = await fetch(`/api/devices/${encodeURIComponent(devId)}/camera-move`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ direction }),
    });
    if (!res.ok) showToast("Camera: " + await errorDetail(res, `Move failed (${res.status})`));
  } catch (e) {
    showToast("Camera: " + e.message);
  } finally {
    btn.disabled = false;
  }
}

function controlRowHtml(c) {
  const id = `cam-ctl-${c.code}`;
  const label = `<label for="${id}" style="font-size: 14px;">${escapeHtml(c.label)}</label>`;
  let input = "";
  if (c.kind === "bool") {
    input = `<button id="${id}" class="device-toggle-btn ${c.value ? "is-on" : ""}" data-code="${c.code}" data-kind="bool" style="width: auto; padding: 6px 16px; font-size: 13px;">${c.value ? "On" : "Off"}</button>`;
  } else if (c.kind === "enum") {
    input = `<select id="${id}" class="form-select" data-code="${c.code}" data-kind="enum" style="width: auto; min-width: 130px;">${
      (c.value == null ? '<option value="" disabled selected>-</option>' : "") +
      c.options.map(o => `<option value="${escapeHtml(o.value)}" ${o.value === c.value ? "selected" : ""}>${escapeHtml(o.label)}</option>`).join("")}</select>`;
  } else if (c.kind === "range") {
    const v = c.value == null ? c.min : c.value;
    input = `<span style="display: flex; align-items: center; gap: 10px;"><input id="${id}" type="range" class="touch-slider" style="width: 150px;" data-code="${c.code}" data-kind="range" min="${c.min}" max="${c.max}" step="${c.step}" value="${v}"><span data-value-of="${c.code}" style="font-size: 13px; min-width: 38px;">${v}${escapeHtml(c.unit || "")}</span></span>`;
  }
  return `<div style="display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 7px 0;">${label}${input}</div>`;
}

function bindControlRow(panel, c) {
  const el = panel.querySelector(`#cam-ctl-${c.code}`);
  if (!el) return;
  if (c.kind === "bool") {
    el.onclick = () => {
      const next = !el.classList.contains("is-on");
      const set = on => { el.classList.toggle("is-on", on); el.textContent = on ? "On" : "Off"; };
      set(next);
      sendCameraControl(c.code, next, () => set(!next));
    };
  } else if (c.kind === "enum") {
    let previous = el.value;
    el.onchange = () => {
      const chosen = el.value, back = previous;
      previous = chosen;
      sendCameraControl(c.code, chosen, () => { el.value = back; previous = back; });
    };
  } else if (c.kind === "range") {
    const shown = panel.querySelector(`[data-value-of="${c.code}"]`);
    el.oninput = () => { shown.textContent = el.value + (c.unit || ""); };
    el.onchange = () => sendCameraControl(c.code, parseInt(el.value, 10));
  }
}

async function loadCameraControls() {
  const panel = cameraEl("camera-controls-panel");
  const devId = cameraViewer.devId;
  if (!panel || !devId) return;
  const token = ++cameraControlsToken;
  panel.style.display = "block";
  panel.innerHTML = `<div style="color: var(--text-muted); font-size: 13px;">Reading the camera's settings...</div>`;
  try {
    const res = await fetch(`/api/devices/${encodeURIComponent(devId)}/camera-controls`);
    if (token !== cameraControlsToken) return;
    if (!res.ok) throw new Error(await errorDetail(res, `Failed (${res.status})`));
    const data = await res.json();
    if (token !== cameraControlsToken) return;
    if (!data.ptz.length && !data.controls.length) {
      panel.innerHTML = `<div style="color: var(--text-muted); font-size: 13px;">This camera has no settings that can be changed here.</div>`;
      return;
    }
    const pad = data.ptz.length ? `
      <div style="display: grid; grid-template-columns: repeat(3, 52px); grid-auto-rows: 44px; gap: 6px; justify-content: center; margin-bottom: 12px;">
        ${PTZ_PAD.map(p => !p ? "<span></span>" : (data.ptz.includes(p[0])
            ? `<button class="action-btn" data-ptz="${p[0]}" style="padding: 0; font-size: 18px; background: rgba(255,255,255,0.1);">${p[1]}</button>`
            : "<span></span>")).join("")}
      </div>` : "";
    panel.innerHTML = pad + data.controls.map(controlRowHtml).join("");
    panel.querySelectorAll("[data-ptz]").forEach(b => { b.onclick = () => moveCamera(b.dataset.ptz, b); });
    data.controls.forEach(c => bindControlRow(panel, c));
  } catch (e) {
    if (token === cameraControlsToken) panel.innerHTML = `<div style="color: var(--accent-amber); font-size: 13px;">${escapeHtml(e.message)}</div>`;
  }
}

// ----- History of rings and alerts (pictures stored by the backend) -----

let cameraEvents = [];

function formatEventTime(ts) {
  const d = new Date(ts * 1000);
  const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const today = new Date();
  if (d.toDateString() === today.toDateString()) return time;
  return `${d.toLocaleDateString([], { month: "short", day: "numeric" })} ${time}`;
}

function renderCameraEvents() {
  const panel = cameraEl("camera-events-panel");
  const list = cameraEl("camera-events-list");
  if (!panel || !list) return;
  panel.style.display = cameraEvents.length ? "block" : "none";
  list.innerHTML = cameraEvents.slice(0, 20).map(e => `
    <div style="flex: 0 0 168px;">
      <div style="width: 168px; height: 95px; background: #000; border-radius: 10px; overflow: hidden; display: flex; align-items: center; justify-content: center; ${e.image_url ? "cursor: pointer;" : ""}"
           ${e.image_url ? `onclick="openEventPicture('${e.id}')"` : ""}>
        ${e.image_url
          ? `<img src="${e.image_url}" loading="lazy" alt="" style="width: 100%; height: 100%; object-fit: cover;">`
          : `<span style="color: var(--text-muted); font-size: 12px;">No picture</span>`}
      </div>
      <div style="font-size: 12px; margin-top: 6px;">${e.kind === "ring" ? "🔔" : "⚠️"} <strong>${escapeHtml(e.label)}</strong></div>
      <div style="font-size: 11px; color: var(--text-muted);">${escapeHtml(e.dev_name)} &bull; ${formatEventTime(e.ts)}</div>
    </div>`).join("");
}

function openEventPicture(eventId) {
  const e = cameraEvents.find(x => x.id === eventId);
  if (!e || !e.image_url) return;
  cameraViewer.token++;          // stop anything still loading in the viewer
  cameraControlsToken++;
  const panel = cameraEl("camera-controls-panel");
  if (panel) { panel.style.display = "none"; panel.innerHTML = ""; }
  releaseCameraMedia();
  cameraViewer.devId = e.dev_id;
  cameraEl("camera-viewer-title").textContent = `${e.dev_name} \u2022 ${e.label} \u2022 ${formatEventTime(e.ts)}`;
  cameraEl("camera-viewer-img").src = e.image_url;
  setCameraStatus("");
  cameraEl("modal-camera-viewer").style.display = "flex";
}

// Called by app.js for every pushed "camera_event" message
function onCameraEvent(event) {
  if (!event || cameraEvents.some(e => e.id === event.id)) return;
  cameraEvents.unshift(event);
  cameraEvents.length = Math.min(cameraEvents.length, 60);
  renderCameraEvents();
}

async function loadCameraEvents() {
  try {
    const res = await fetch("/api/camera-events");
    if (res.ok) { cameraEvents = await res.json(); renderCameraEvents(); }
  } catch (e) { /* the list stays empty until the next event */ }
}

function initCameraViewer() {
  cameraEl("btn-camera-close").onclick = closeCameraViewer;
  cameraEl("btn-camera-snapshot").onclick = showCameraSnapshot;
  cameraEl("btn-camera-live").onclick = startCameraLive;
  cameraEl("btn-camera-settings").onclick = () => {
    const panel = cameraEl("camera-controls-panel");
    if (panel.style.display === "block") { cameraControlsToken++; panel.style.display = "none"; } else loadCameraControls();
  };
  cameraEl("btn-clear-camera-events").onclick = async () => {
    if (!confirm("Delete the doorbell and camera history?")) return;
    await fetch("/api/camera-events", { method: "DELETE" });
    cameraEvents = [];
    renderCameraEvents();
  };
  loadCameraEvents();
}

document.addEventListener("DOMContentLoaded", initCameraViewer);
