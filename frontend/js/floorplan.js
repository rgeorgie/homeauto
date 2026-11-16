// Floor plan: admin editor (draw rooms, place devices) and read-only dashboard view.
// Coordinates are fractions (0-1) of the plan size so the layout scales to any screen.

let floorplan = { rooms: [], devices: {} };
let floorplanEditorInitialized = false;
let floorplanPendingDeviceId = null;
let floorplanEditorSignature = "";

const FLOORPLAN_MIN_SIZE = 0.03;

function floorplanDeviceSignature() {
  return (state.devices || []).map(d => `${d.id}|${d.name}|${d.room}`).join(";");
}

function floorplanRoomNames() {
  const names = new Set();
  (state.devices || []).forEach(d => {
    const r = (d.room || "").trim();
    if (r && r !== "Default") names.add(r);
  });
  floorplan.rooms.forEach(r => names.add(r.name));
  return [...names].sort((a, b) => a.localeCompare(b));
}

function floorplanDeviceStateClass(dev) {
  if (!dev || !dev.online) return "offline";
  return dev.is_on ? "on" : "off";
}

async function loadFloorplan() {
  try {
    const res = await fetch("/api/floorplan");
    if (res.ok) floorplan = await res.json();
  } catch (err) {
    console.error("Floor plan load failed:", err);
  }
  renderFloorplanEditor();
  renderDashboardFloorplan();
}

// Called on every device state push: the editor is rebuilt only when the device list changes,
// so an in-progress drag or room draw is not interrupted by the 3-second state refresh.
function onFloorplanStateUpdate() {
  if (floorplanDeviceSignature() !== floorplanEditorSignature) renderFloorplanEditor();
  renderDashboardFloorplan();
}

function onFloorplanUpdated(data) {
  floorplan = data;
  renderFloorplanEditor();
  renderDashboardFloorplan();
}

async function saveFloorplanToServer() {
  try {
    const res = await fetch("/api/floorplan", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(floorplan)
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    showToast("Floor plan saved");
  } catch (err) {
    showToast(`Floor plan save error: ${err.message}`);
  }
}

// ---------------- Admin editor ----------------

function initFloorplanEditor() {
  if (floorplanEditorInitialized) return;
  floorplanEditorInitialized = true;

  const canvas = document.getElementById("floorplan-editor");
  if (!canvas) return;

  document.getElementById("btn-floorplan-save")?.addEventListener("click", () => saveFloorplanToServer());
  document.getElementById("btn-floorplan-clear")?.addEventListener("click", () => {
    if (!confirm("Clear the whole floor plan?")) return;
    floorplan = { rooms: [], devices: {} };
    renderFloorplanEditor();
    renderDashboardFloorplan();
  });

  // Empty-canvas press: either places the selected device or starts drawing a room
  canvas.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || e.target !== canvas) return;

    if (floorplanPendingDeviceId) {
      const p = toPlanCoords(canvas, e);
      floorplan.devices[floorplanPendingDeviceId] = { x: p.x, y: p.y };
      floorplanPendingDeviceId = null;
      renderFloorplanEditor();
      renderDashboardFloorplan();
      return;
    }

    const roomName = document.getElementById("floorplan-room-select")?.value;
    if (!roomName) {
      showToast("Add a device with a room name first");
      return;
    }

    const start = toPlanCoords(canvas, e);
    const draft = { name: roomName, x: start.x, y: start.y, w: 0, h: 0 };
    const preview = document.createElement("div");
    preview.className = "floorplan-room floorplan-room-draft";
    canvas.appendChild(preview);
    canvas.setPointerCapture(e.pointerId);

    const move = (ev) => {
      const p = toPlanCoords(canvas, ev);
      draft.x = Math.min(start.x, p.x);
      draft.y = Math.min(start.y, p.y);
      draft.w = Math.abs(p.x - start.x);
      draft.h = Math.abs(p.y - start.y);
      positionBox(preview, draft);
    };
    const up = () => {
      canvas.removeEventListener("pointermove", move);
      canvas.removeEventListener("pointerup", up);
      canvas.removeEventListener("pointercancel", up);
      preview.remove();
      if (draft.w >= FLOORPLAN_MIN_SIZE && draft.h >= FLOORPLAN_MIN_SIZE) {
        // One rectangle per room name: a redraw replaces the previous one
        floorplan.rooms = floorplan.rooms.filter(r => r.name !== draft.name);
        floorplan.rooms.push(draft);
        renderFloorplanEditor();
        renderDashboardFloorplan();
      }
    };
    canvas.addEventListener("pointermove", move);
    canvas.addEventListener("pointerup", up);
    canvas.addEventListener("pointercancel", up);
    move(e);
  });
}

function toPlanCoords(canvas, e) {
  const rect = canvas.getBoundingClientRect();
  const clamp = (v) => Math.min(1, Math.max(0, v));
  return {
    x: clamp((e.clientX - rect.left) / rect.width),
    y: clamp((e.clientY - rect.top) / rect.height)
  };
}

function positionBox(el, box) {
  el.style.left = `${box.x * 100}%`;
  el.style.top = `${box.y * 100}%`;
  el.style.width = `${box.w * 100}%`;
  el.style.height = `${box.h * 100}%`;
}

function renderFloorplanEditor() {
  const canvas = document.getElementById("floorplan-editor");
  if (!canvas) return;
  floorplanEditorSignature = floorplanDeviceSignature();
  const names = floorplanRoomNames();

  const select = document.getElementById("floorplan-room-select");
  if (select) {
    const current = select.value;
    select.replaceChildren(...names.map(n => new Option(n, n)));
    if (names.includes(current)) select.value = current;
  }

  canvas.replaceChildren();
  floorplan.rooms.forEach(room => {
    const el = document.createElement("div");
    el.className = "floorplan-room";
    positionBox(el, room);
    const label = document.createElement("div");
    label.className = "floorplan-room-label";
    label.textContent = room.name;
    el.appendChild(label);
    const handle = document.createElement("div");
    handle.className = "floorplan-resize-handle";
    el.appendChild(handle);
    handle.addEventListener("pointerdown", (e) => startResizeRoom(e, canvas, room));
    canvas.appendChild(el);
  });

  (state.devices || []).forEach(dev => {
    const pos = floorplan.devices[dev.id];
    if (!pos) return;
    canvas.appendChild(createPlacedDeviceEl(canvas, dev, pos));
  });

  renderUnplacedDevices();
}

function createPlacedDeviceEl(canvas, dev, pos) {
  const el = document.createElement("div");
  el.className = `floorplan-device ${floorplanDeviceStateClass(dev)}`;
  el.textContent = dev.name;
  el.title = dev.name;
  el.style.left = `${pos.x * 100}%`;
  el.style.top = `${pos.y * 100}%`;
  el.addEventListener("pointerdown", (e) => startMoveDevice(e, canvas, dev.id, el));
  return el;
}

function startMoveDevice(e, canvas, devId, el) {
  if (e.button !== 0) return;
  e.preventDefault();
  e.stopPropagation();
  canvas.setPointerCapture(e.pointerId);
  const move = (ev) => {
    const p = toPlanCoords(canvas, ev);
    floorplan.devices[devId] = { x: p.x, y: p.y };
    el.style.left = `${p.x * 100}%`;
    el.style.top = `${p.y * 100}%`;
  };
  const up = () => {
    canvas.removeEventListener("pointermove", move);
    canvas.removeEventListener("pointerup", up);
    canvas.removeEventListener("pointercancel", up);
    renderDashboardFloorplan();
  };
  canvas.addEventListener("pointermove", move);
  canvas.addEventListener("pointerup", up);
  canvas.addEventListener("pointercancel", up);
}

function startResizeRoom(e, canvas, room) {
  if (e.button !== 0) return;
  e.preventDefault();
  e.stopPropagation();
  canvas.setPointerCapture(e.pointerId);
  const move = (ev) => {
    const p = toPlanCoords(canvas, ev);
    room.w = Math.max(FLOORPLAN_MIN_SIZE, Math.min(1 - room.x, p.x - room.x));
    room.h = Math.max(FLOORPLAN_MIN_SIZE, Math.min(1 - room.y, p.y - room.y));
    renderFloorplanEditor();
  };
  const up = () => {
    canvas.removeEventListener("pointermove", move);
    canvas.removeEventListener("pointerup", up);
    canvas.removeEventListener("pointercancel", up);
    renderDashboardFloorplan();
  };
  canvas.addEventListener("pointermove", move);
  canvas.addEventListener("pointerup", up);
  canvas.addEventListener("pointercancel", up);
}

function renderUnplacedDevices() {
  const list = document.getElementById("floorplan-unplaced");
  if (!list) return;
  const unplaced = (state.devices || []).filter(d => !floorplan.devices[d.id]);
  if (unplaced.length === 0) {
    const empty = document.createElement("div");
    empty.className = "floorplan-empty";
    empty.textContent = "All devices are placed";
    list.replaceChildren(empty);
    return;
  }
  list.replaceChildren(...unplaced.map(dev => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "floorplan-chip" + (floorplanPendingDeviceId === dev.id ? " active" : "");
    chip.textContent = `${dev.name}${dev.room ? ` · ${dev.room}` : ""}`;
    chip.addEventListener("click", () => {
      floorplanPendingDeviceId = floorplanPendingDeviceId === dev.id ? null : dev.id;
      renderUnplacedDevices();
    });
    return chip;
  }));
}

// ---------------- Dashboard (read-only) ----------------

function renderDashboardFloorplan() {
  const container = document.getElementById("dashboard-floorplan");
  if (!container) return;
  if (floorplan.rooms.length === 0) {
    container.style.display = "none";
    container.replaceChildren();
    return;
  }
  container.style.display = "";

  const canvas = document.createElement("div");
  canvas.className = "floorplan-canvas readonly";
  floorplan.rooms.forEach(room => {
    const el = document.createElement("div");
    el.className = "floorplan-room";
    positionBox(el, room);
    const label = document.createElement("div");
    label.className = "floorplan-room-label";
    label.textContent = room.name;
    el.appendChild(label);
    canvas.appendChild(el);
  });
  (state.devices || []).forEach(dev => {
    const pos = floorplan.devices[dev.id];
    if (!pos) return;
    const el = document.createElement("div");
    el.className = `floorplan-device ${floorplanDeviceStateClass(dev)}`;
    el.textContent = dev.name;
    el.title = dev.name;
    el.style.left = `${pos.x * 100}%`;
    el.style.top = `${pos.y * 100}%`;
    canvas.appendChild(el);
  });
  container.replaceChildren(canvas);
}
