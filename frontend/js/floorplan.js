// Floor plan: admin editor (draw rooms, place devices) and read-only dashboard view.
// One plan per Tuya home. Coordinates are fractions (0-1) of the plan size so the layout scales.

let floorplan = { homes: {} };
let floorplanEditorInitialized = false;
let floorplanPendingDeviceId = null;
let floorplanEditorSignature = "";
let floorDeviceOpenId = null; // device whose card is open in the popup
let floorplanPendingKind = "lamp"; // how the pending switch/relay will be shown: "lamp" or "vent"

const PLAN_KIND_ICON = { lamp: "💡", vent: "🌀" };
const PLAN_STRIP_ICON = "🔌";
const PLAN_PANEL_ICON = "🔘";

const FLOORPLAN_MIN_SIZE = 0.03;

// Home being edited. Always a single real home: never "all homes", which would mix rooms.
let floorplanHome = "";

function knownHomes() {
  return [...new Set((state.devices || []).map(d => d.home).filter(Boolean))].sort((a, b) => a.localeCompare(b));
}

// Picks the editor's home: keeps the current one if still valid, else the shared filter, else the first home
function resolveFloorplanHome() {
  const homes = knownHomes();
  if (floorplanHome && homes.includes(floorplanHome)) return floorplanHome;
  const shared = getSelectedHome();
  floorplanHome = homes.includes(shared) ? shared : (homes[0] || "");
  return floorplanHome;
}

function currentHomeName() {
  return resolveFloorplanHome();
}

function currentHomePlan() {
  const home = currentHomeName();
  if (!home) return null;
  if (!floorplan.homes[home]) floorplan.homes[home] = { rooms: [], devices: {} };
  return floorplan.homes[home];
}

function homeDevices() {
  const home = currentHomeName();
  if (!home) return [];
  return (state.devices || []).filter(d => d.home === home);
}

// Power strip: Tuya category "pc", or a device with USB outputs (channel labels "USB n")
function isPowerStrip(dev) {
  const channels = Array.isArray(dev.channels) ? dev.channels : [];
  if (dev.category === "pc" || channels.some(ch => /^USB/i.test(ch.label || ""))) return true;
  return !dev.category && /strip/i.test(dev.name || "");
}

// Smart control panels and power strips keep one point with their full button card, instead of per-channel lamps / vents
function isSingleItemDevice(dev) {
  return isPowerStrip(dev) || /smart.*panel/i.test(dev.name || "");
}

// Placeable items. A plain device is one point; each channel of a multi-gang switch is its own point
// (e.g. "Light Living room · Line 1" and "· Line 2") so each can be placed and shown as a lamp.
// Point key: device id, or "device id#channel index" for a channel.
function homePoints() {
  const points = [];
  homeDevices().forEach(dev => {
    const channels = Array.isArray(dev.channels) ? dev.channels : [];
    if (channels.length > 1 && !isSingleItemDevice(dev)) {
      channels.forEach(ch => points.push({
        key: `${dev.id}#${ch.index}`, dev, channel: ch.index,
        name: `${dev.name} · ${ch.label || "Line " + ch.index}`, isOn: !!ch.is_on
      }));
    } else {
      // Power strips are shown as a strip icon, not as lamp/vent, and open their card on tap
      const isStrip = isPowerStrip(dev);
      const isPanel = isSingleItemDevice(dev) && !isStrip;
      const switchKind = ["switch", "light", "socket"].includes(deviceKind(dev));
      points.push({ key: dev.id, dev, channel: null, name: dev.name, isOn: !!dev.is_on,
        isStrip, isPanel,
        isSwitch: !isStrip && !isPanel && (switchKind || channels.length > 1),
        // A single-output relay toggles on tap; strips and panels open their card
        relay: !isStrip && !isPanel && switchKind && channels.length <= 1 });
    }
  });
  return points;
}

function floorplanDeviceSignature() {
  return `${currentHomeName()}#` + homeDevices().map(d => `${d.id}|${d.name}|${d.room}|${(d.channels || []).length}`).join(";");
}

function floorplanRoomNames() {
  const names = new Set();
  homeDevices().forEach(d => {
    const r = (d.room || "").trim();
    if (r && r !== "Default") names.add(r);
  });
  ((currentHomePlan() || {}).rooms || []).forEach(r => names.add(r.name));
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

// Called on every device state push: the editor is rebuilt only when the device list or home changes,
// so an in-progress drag or room draw is not interrupted by the 3-second state refresh.
function onFloorplanStateUpdate() {
  if (floorplanDeviceSignature() !== floorplanEditorSignature) renderFloorplanEditor();
  renderDashboardFloorplan();
  if (floorDeviceOpenId) renderFloorDevice();
}

function onFloorplanUpdated(data) {
  floorplan = data;
  renderFloorplanEditor();
  renderDashboardFloorplan();
}

async function saveFloorplanToServer() {
  if (!currentHomeName()) {
    showToast("Select a home first");
    return;
  }
  try {
    const res = await fetch("/api/floorplan", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(floorplan)
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    showToast(`Floor plan saved for ${currentHomeName()}`);
  } catch (err) {
    showToast(`Floor plan save error: ${err.message}`);
  }
}

// ---------------- Admin editor ----------------

function initFloorplanEditor() {
  if (floorplanEditorInitialized) return;
  floorplanEditorInitialized = true;
  initFloorDeviceModal();

  const canvas = document.getElementById("floorplan-editor");
  if (!canvas) return;

  document.getElementById("btn-floorplan-save")?.addEventListener("click", () => saveFloorplanToServer());
  document.getElementById("btn-floorplan-clear")?.addEventListener("click", () => {
    const plan = currentHomePlan();
    if (!plan) return;
    if (!confirm(`Clear the floor plan for ${currentHomeName()}?`)) return;
    plan.rooms = [];
    plan.devices = {};
    renderFloorplanEditor();
    renderDashboardFloorplan();
  });

  // Empty-canvas press: either places the selected device or starts drawing a room
  canvas.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || e.target !== canvas) return;
    const plan = currentHomePlan();
    if (!plan) return;

    if (floorplanPendingDeviceId) {
      const p = toPlanCoords(canvas, e);
      plan.devices[floorplanPendingDeviceId] = { x: p.x, y: p.y, kind: floorplanPendingKind };
      floorplanPendingDeviceId = null;
      renderFloorplanEditor();
      renderDashboardFloorplan();
      return;
    }

    const roomName = document.getElementById("floorplan-room-select")?.value;
    if (!roomName) {
      showToast("This home has no device rooms yet");
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
        plan.rooms = plan.rooms.filter(r => r.name !== draft.name);
        plan.rooms.push(draft);
        renderFloorplanEditor();
        renderDashboardFloorplan();
      }
    };
    canvas.addEventListener("pointermove", move);
    canvas.addEventListener("pointerup", up);
    canvas.addEventListener("pointercancel", up);
    move(e);
  });

  // The editor's own home dropdown. It also updates the shared filter so the dashboard matches.
  document.getElementById("floorplan-home-select")?.addEventListener("change", (e) => {
    floorplanHome = e.target.value;
    localStorage.setItem(HOME_FILTER_KEY, floorplanHome);
    floorplanPendingDeviceId = null;
    renderTuyaDevices(state.devices);
    renderFloorplanEditor();
    renderDashboardFloorplan();
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

function renderHomeSelect() {
  const select = document.getElementById("floorplan-home-select");
  if (!select) return;
  const homes = knownHomes();
  const current = currentHomeName();
  const key = homes.join("\u0001");
  if (select.dataset.homes !== key) {
    select.dataset.homes = key;
    select.replaceChildren(...homes.map(h => new Option(h, h)));
  }
  select.disabled = homes.length === 0;
  if (current && homes.includes(current)) select.value = current;
}

function renderFloorplanEditor() {
  const canvas = document.getElementById("floorplan-editor");
  if (!canvas) return;
  floorplanEditorSignature = floorplanDeviceSignature();
  renderHomeSelect();

  const plan = currentHomePlan();
  const hint = document.getElementById("floorplan-home-hint");
  if (hint) hint.style.display = plan ? "none" : "";

  const select = document.getElementById("floorplan-room-select");
  if (select) {
    const names = floorplanRoomNames();
    const current = select.value;
    select.replaceChildren(...names.map(n => new Option(n, n)));
    if (names.includes(current)) select.value = current;
  }

  canvas.replaceChildren();
  if (!plan) {
    renderUnplacedDevices();
    return;
  }

  plan.rooms.forEach(room => {
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

  homePoints().forEach(pt => {
    const pos = plan.devices[pt.key];
    if (!pos) return;
    canvas.appendChild(createPlacedDeviceEl(canvas, pt, pos));
  });

  renderUnplacedDevices();
}

function createPlacedDeviceEl(canvas, pt, pos) {
  const el = floorplanItemEl(pt, pos);
  el.style.left = `${pos.x * 100}%`;
  el.style.top = `${pos.y * 100}%`;
  el.addEventListener("pointerdown", (e) => startMoveDevice(e, canvas, pt.key, el));
  return el;
}

// What a placed item looks like on the plan. Switches show only their chosen icon,
// sensors show only their state, and doorbells / cameras show only their icon.
// Shared by the editor and the dashboard so both stay the same.
function floorplanItemEl(pt, pos) {
  const el = document.createElement("div");
  const dev = pt.dev;
  const kind = deviceKind(dev);
  el.title = pt.name;

  if (kind === "sensor" && (dev.contact_open === true || dev.contact_open === false)) {
    // Door / window: only open or closed
    el.className = `floorplan-device floorplan-state ${dev.online ? (dev.contact_open ? "warn" : "on") : "offline"}`;
    el.textContent = dev.online ? (dev.contact_open ? "🚪 Open" : "🚪 Closed") : "⚠️";
    return el;
  }
  if (kind === "sensor" && (dev.is_motion_sensor || dev.category === "pir")) {
    // Motion sensor: only motion (red) or no motion (green)
    el.className = `floorplan-device floorplan-state ${dev.online ? (dev.motion === true ? "alert" : "on") : "offline"}`;
    el.textContent = dev.online ? (dev.motion === true ? "🚶 Motion" : "✓ No motion") : "⚠️";
    return el;
  }
  if (isDoorbell(dev)) {
    el.className = `floorplan-device ${dev.online ? "on" : "offline"}`;
    el.textContent = "🔔";
    return el;
  }
  if (kind === "camera") {
    el.className = `floorplan-device ${dev.online ? "on" : "offline"}`;
    el.textContent = "📷";
    return el;
  }
  if (pt.isStrip) {
    el.className = `floorplan-device ${pt.isOn ? "on" : (dev.online ? "off" : "offline")}`;
    el.textContent = PLAN_STRIP_ICON;
    return el;
  }
  if (pt.isPanel) {
    // Smart control panel: always a switch, never lamp or vent
    el.className = `floorplan-device ${pt.isOn ? "on" : (dev.online ? "off" : "offline")}`;
    el.textContent = PLAN_PANEL_ICON;
    return el;
  }
  if (pt.channel !== null || pt.isSwitch) {
    // Lamp or vent icon, chosen before placing, with the on/off state as the color
    el.className = `floorplan-device ${pt.isOn ? "on" : (dev.online ? "off" : "offline")}`;
    el.textContent = PLAN_KIND_ICON[pos.kind || "lamp"];
    return el;
  }
  el.className = `floorplan-device ${pt.isOn ? "on" : (dev.online ? "off" : "offline")}`;
  el.textContent = floorplanDeviceLabel(dev);
  return el;
}

function isDoorbell(dev) {
  return /doorbell|bell/i.test(dev.name || "") || dev.category === "spxl";
}

function startMoveDevice(e, canvas, key, el) {
  if (e.button !== 0) return;
  e.preventDefault();
  e.stopPropagation();
  const plan = currentHomePlan();
  if (!plan) return;
  canvas.setPointerCapture(e.pointerId);
  const move = (ev) => {
    const p = toPlanCoords(canvas, ev);
    plan.devices[key] = { ...plan.devices[key], x: p.x, y: p.y };
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
  const plan = currentHomePlan();
  const unplaced = homePoints().filter(pt => !(plan && plan.devices[pt.key]));
  if (unplaced.length === 0) {
    const empty = document.createElement("div");
    empty.className = "floorplan-empty";
    empty.textContent = plan ? "All devices are placed" : "Select a home to see its devices";
    list.replaceChildren(empty);
    return;
  }
  list.replaceChildren(...unplaced.map(pt => {
    const row = document.createElement("div");
    row.className = "floorplan-chip-row";

    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "floorplan-chip" + (floorplanPendingDeviceId === pt.key ? " active" : "");
    chip.textContent = `${pt.name}${pt.dev.room ? ` · ${pt.dev.room}` : ""}`;
    chip.addEventListener("click", () => {
      floorplanPendingDeviceId = floorplanPendingDeviceId === pt.key ? null : pt.key;
      renderUnplacedDevices();
    });
    row.appendChild(chip);

    // Switches, relays and channels: choose how they are shown before placing
    if (pt.isSwitch || pt.channel !== null) {
      const kinds = document.createElement("div");
      kinds.className = "floorplan-kind-picker";
      Object.entries(PLAN_KIND_ICON).forEach(([kind, icon]) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "floorplan-kind-btn" + (floorplanPendingKind === kind ? " active" : "");
        btn.textContent = `${icon} ${kind === "lamp" ? "Lamp" : "Vent"}`;
        btn.addEventListener("click", () => {
          floorplanPendingKind = kind;
          renderUnplacedDevices();
        });
        kinds.appendChild(btn);
      });
      row.appendChild(kinds);
    }
    return row;
  }));
}

// ---------------- Dashboard (read-only) ----------------

function renderDashboardFloorplan() {
  const container = document.getElementById("dashboard-floorplan");
  if (!container) return;
  const plan = currentHomePlan();
  if (!plan || plan.rooms.length === 0) {
    container.style.display = "none";
    container.replaceChildren();
    return;
  }
  container.style.display = "";

  const canvas = document.createElement("div");
  canvas.className = "floorplan-canvas readonly";
  plan.rooms.forEach(room => {
    const el = document.createElement("div");
    el.className = "floorplan-room";
    positionBox(el, room);
    const label = document.createElement("div");
    label.className = "floorplan-room-label";
    label.textContent = floorplanRoomLabel(room, plan);
    el.appendChild(label);
    canvas.appendChild(el);
  });
  homePoints().forEach(pt => {
    const pos = plan.devices[pt.key];
    if (!pos) return;
    const el = floorplanItemEl(pt, pos);
    el.style.left = `${pos.x * 100}%`;
    el.style.top = `${pos.y * 100}%`;
    el.addEventListener("click", () => {
      if (pt.channel !== null) {
        // A channel is a relay: tap toggles it directly
        toggleDevicePower(pt.dev.id, !pt.isOn, pt.channel);
      } else if (pt.relay) {
        // A single-output relay: tap toggles it directly
        toggleDevicePower(pt.dev.id, !pt.isOn);
      } else {
        openFloorDevice(pt.dev.id);
      }
    });
    canvas.appendChild(el);
  });
  container.replaceChildren(canvas);
}

// Room label: the room name plus a temperature from a sensor or thermostat placed in that room
function floorplanRoomLabel(room, plan) {
  const sensor = homeDevices().find(d => plan.devices[d.id] && d.current_temperature != null
    && (d.room || "").trim() === room.name);
  return sensor ? `${room.name} · ${parseFloat(sensor.current_temperature).toFixed(1)}°C` : room.name;
}

// Chip text: the device name plus its current reading, so the plan is useful at a glance
function floorplanDeviceLabel(dev) {
  if (!dev.online) return `${dev.name} · offline`;
  if (dev.contact_open === true || dev.contact_open === false) return `${dev.name} · ${dev.contact_open ? "Open" : "Closed"}`;
  if (dev.is_motion_sensor || dev.category === "pir") {
    return `${dev.name} · ${dev.motion === true ? "Motion" : "Clear"}`;
  }
  if (dev.current_temperature !== undefined && dev.current_temperature !== null) {
    const heat = dev.target_temperature !== undefined && dev.target_temperature !== null
      ? ` → ${parseFloat(dev.target_temperature).toFixed(1)}°C` : "";
    return `${dev.name} · ${parseFloat(dev.current_temperature).toFixed(1)}°C${heat}`;
  }
  if (dev.type === "sensor" || dev.type === "climate" || dev.type === "camera") return dev.name;
  return `${dev.name} · ${dev.is_on ? "ON" : "OFF"}`;
}

// ---------------- Device popup (real controls, same as the device list) ----------------

function openFloorDevice(devId) {
  floorDeviceOpenId = devId;
  renderFloorDevice();
  document.getElementById("modal-floor-device").style.display = "flex";
}

function closeFloorDevice() {
  floorDeviceOpenId = null;
  document.getElementById("modal-floor-device").style.display = "none";
}

// Renders the device's standard card and binds its controls. Called on every state push while open.
function renderFloorDevice() {
  const dev = (state.devices || []).find(d => d.id === floorDeviceOpenId);
  const body = document.getElementById("floor-device-body");
  if (!body) return;
  if (!dev) {
    closeFloorDevice();
    return;
  }
  body.innerHTML = createDeviceCardHtml(dev);
  bindDeviceControls([dev]);
}

function initFloorDeviceModal() {
  document.getElementById("btn-floor-device-close")?.addEventListener("click", closeFloorDevice);
  document.getElementById("modal-floor-device")?.addEventListener("click", (e) => {
    if (e.target.id === "modal-floor-device") closeFloorDevice();
  });
}
