// SmartLife / Tuya Device Cards Component

let discoveredDevicesCache = [];

function initTuyaCards() {
  const scanBtn = document.getElementById("btn-scan-devices");
  const modalScan = document.getElementById("modal-scan-results");
  const btnCloseScan = document.getElementById("btn-close-scan-modal");
  const btnImportAll = document.getElementById("btn-import-all-discovered");

  if (scanBtn) {
    scanBtn.addEventListener("click", () => triggerDeviceScan());
  }

  if (btnCloseScan && modalScan) {
    btnCloseScan.addEventListener("click", () => {
      modalScan.style.display = "none";
    });
  }

  if (btnImportAll) {
    btnImportAll.addEventListener("click", () => importAllDiscoveredDevices());
  }
}

async function triggerDeviceScan() {
  const scanBtns = document.querySelectorAll("#btn-scan-devices, #btn-admin-scan-devices");
  scanBtns.forEach(b => {
    b.textContent = "🔍 Scanning network (6s)...";
    b.disabled = true;
  });

  try {
    const res = await fetch("/api/devices/scan", { method: "POST" });
    const data = await res.json();
    discoveredDevicesCache = data.discovered || [];

    if (discoveredDevicesCache.length === 0) {
      showToast("Scan finished: No Tuya devices found on local network.", 4000);
    } else {
      showToast(`Scan complete: Found ${discoveredDevicesCache.length} device${discoveredDevicesCache.length === 1 ? '' : 's'}!`);
      showDiscoveredDevicesModal(discoveredDevicesCache);
    }
  } catch (err) {
    showToast(`Error scanning devices: ${err.message}`);
  } finally {
    scanBtns.forEach(b => {
      b.textContent = "🔍 Scan Local Devices";
      b.disabled = false;
    });
  }
}

function showDiscoveredDevicesModal(devices) {
  const modal = document.getElementById("modal-scan-results");
  const container = document.getElementById("scan-results-container");
  const countBadge = document.getElementById("scan-found-count");

  if (!modal || !container) return;

  if (countBadge) countBadge.textContent = `${devices.length} Found`;

  container.innerHTML = devices.map((dev, idx) => {
    const isAdded = dev.is_configured;
    const hasKey = Boolean(dev.local_key);

    return `
      <div style="display: flex; justify-content: space-between; align-items: center; padding: 14px 16px; background: rgba(255,255,255,0.03); border: 1px solid var(--border-color); border-radius: 12px; margin-bottom: 10px; flex-wrap: wrap; gap: 10px;">
        <div style="flex: 1; min-width: 220px;">
          <div style="display: flex; align-items: center; gap: 8px;">
            <strong style="font-size: 15px;">${escapeHtml(dev.name)}</strong>
            <span class="badge badge-type">${escapeHtml(dev.type)}</span>
            ${isAdded ? `<span style="color: var(--accent-green); font-size: 11px;">● Configured</span>` : ''}
          </div>
          <div style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">
            IP: <code>${escapeHtml(dev.ip || 'Unknown')}</code> &bull; ID: <code>${escapeHtml(dev.id)}</code> &bull; v${dev.version || 3.3}
          </div>
          <div style="font-size: 11px; color: ${hasKey ? 'var(--accent-green)' : 'var(--accent-amber)'}; margin-top: 2px;">
            ${hasKey ? '🔑 Local Key Available' : '⚠️ No Local Key entered (You can add now and enter key later in Admin)'}
          </div>
        </div>

        <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
          <input type="text" id="scan-key-input-${idx}" placeholder="Local Key (16 char)" value="${dev.local_key || ''}" style="width: 140px; padding: 8px 10px; font-size: 12px; border-radius: 8px; border: 1px solid var(--border-color); background: rgba(0,0,0,0.4); color: #fff;">
          
          <button class="action-btn" style="padding: 8px 14px; font-size: 13px; background: ${isAdded ? 'rgba(255,255,255,0.1)' : 'var(--accent-blue)'};" onclick="importSingleDiscoveredDevice(${idx})">
            ${isAdded ? '🔄 Update' : '➕ Add'}
          </button>

          <button class="action-btn" style="padding: 8px 12px; font-size: 12px; background: rgba(255,255,255,0.08);" onclick="openAddDeviceWithPrefill(${idx})">
            ✏️
          </button>
        </div>
      </div>
    `;
  }).join("");

  modal.style.display = "flex";
}

function openAddDeviceWithPrefill(index) {
  const dev = discoveredDevicesCache[index];
  if (!dev) return;

  const modalScan = document.getElementById("modal-scan-results");
  if (modalScan) modalScan.style.display = "none";

  editingDeviceId = null;
  const modalTitle = document.getElementById("modal-device-title");
  if (modalTitle) modalTitle.textContent = `Configure Discovered Device: ${dev.name}`;

  const idInput = document.getElementById("device-id");
  const nameInput = document.getElementById("device-name");
  const ipInput = document.getElementById("device-ip");
  const keyInput = document.getElementById("device-key");
  const verInput = document.getElementById("device-version");
  const typeInput = document.getElementById("device-type");
  const roomInput = document.getElementById("device-room");
  const resEl = document.getElementById("device-test-result");

  if (idInput) idInput.value = dev.id || "";
  if (nameInput) nameInput.value = dev.name || "";
  if (ipInput) ipInput.value = dev.ip || "";
  if (keyInput) keyInput.value = dev.local_key || "";
  if (verInput) verInput.value = dev.version || "3.3";
  if (typeInput) typeInput.value = dev.type || "switch";
  if (roomInput) roomInput.value = dev.room || "";
  const homeInput = document.getElementById("device-home");
  if (homeInput) homeInput.value = dev.home || "";
  if (resEl) resEl.textContent = "";

  const modalForm = document.getElementById("modal-device-form");
  if (modalForm) modalForm.style.display = "flex";
}

async function importSingleDiscoveredDevice(index) {
  const dev = discoveredDevicesCache[index];
  if (!dev) return;

  const keyInput = document.getElementById(`scan-key-input-${index}`);
  if (keyInput && keyInput.value.trim()) {
    dev.local_key = keyInput.value.trim();
  }

  showToast(`Adding ${dev.name} to dashboard...`);
  try {
    const res = await fetch("/api/devices/import-batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ devices: [dev] })
    });
    const data = await res.json();
    if (res.ok) {
      showToast(`🎉 ${dev.name} added to dashboard!`);
      dev.is_configured = true;
      if (data.devices) {
        state.devices = data.devices;
        renderTuyaDevices(state.devices);
      }
      showDiscoveredDevicesModal(discoveredDevicesCache);
      if (typeof loadAdminConfig === "function") loadAdminConfig();
    } else {
      showToast(`Failed: ${data.detail || 'Could not add device'}`);
    }
  } catch (err) {
    showToast(`Error: ${err.message}`);
  }
}

async function importAllDiscoveredDevices() {
  if (!discoveredDevicesCache || discoveredDevicesCache.length === 0) return;

  // Grab any local keys entered in inputs
  discoveredDevicesCache.forEach((dev, idx) => {
    const keyInput = document.getElementById(`scan-key-input-${idx}`);
    if (keyInput && keyInput.value.trim()) {
      dev.local_key = keyInput.value.trim();
    }
  });

  showToast(`Importing ${discoveredDevicesCache.length} devices...`);
  try {
    const res = await fetch("/api/devices/import-batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ devices: discoveredDevicesCache })
    });
    const data = await res.json();
    if (res.ok) {
      showToast(`🎉 Imported ${data.imported_count || discoveredDevicesCache.length} devices! Displaying on screen.`);
      document.getElementById("modal-scan-results").style.display = "none";
      if (data.devices) {
        state.devices = data.devices;
        renderTuyaDevices(state.devices);
      } else {
        const devRes = await fetch("/api/devices");
        if (devRes.ok) {
          state.devices = await devRes.json();
          renderTuyaDevices(state.devices);
        }
      }
      if (typeof loadAdminConfig === "function") loadAdminConfig();
    } else {
      showToast(`Error: ${data.detail || 'Batch import failed'}`);
    }
  } catch (err) {
    showToast(`Import error: ${err.message}`);
  }
}

const HOME_FILTER_KEY = "homeauto.selectedHome";
const ALL_HOMES = "__all__";

function getSelectedHome() {
  return localStorage.getItem(HOME_FILTER_KEY) || ALL_HOMES;
}

function roomLabel(dev) {
  const r = (dev.room || "").trim();
  return !r || r === "Default" ? "No room assigned" : r;
}

function updateHomeFilters(devices) {
  const homes = [...new Set(devices.map(d => d.home).filter(Boolean))].sort((a, b) => a.localeCompare(b));
  const hasUnhomed = devices.some(d => !d.home);
  let selected = getSelectedHome();
  if (selected !== ALL_HOMES && !homes.includes(selected)) selected = ALL_HOMES;

  document.querySelectorAll(".home-filter").forEach(sel => {
    // Rebuilding options on every state push would close an open dropdown; only rebuild when the list changed
    const key = homes.join("\u0001") + (hasUnhomed ? "|u" : "");
    if (sel.dataset.homes !== key) {
      sel.dataset.homes = key;
      sel.innerHTML = homes.length === 0
        ? `<option value="${ALL_HOMES}">🏠 No homes synced yet</option>`
        : `<option value="${ALL_HOMES}">🏠 All homes</option>` +
          homes.map(h => `<option value="${escapeHtml(h)}">🏠 ${escapeHtml(h)}</option>`).join("");
      sel.title = homes.length === 0 ? "Admin > Tuya Cloud > Fetch & Sync All Cloud Keys loads your Tuya homes and rooms" : "";
    }
    sel.disabled = homes.length === 0;
    sel.value = selected;
    sel.onchange = () => {
      localStorage.setItem(HOME_FILTER_KEY, sel.value);
      renderTuyaDevices(state.devices);
    };
  });
  return selected;
}

function groupDevicesByRoom(devices) {
  const groups = new Map();
  devices.forEach(d => {
    const room = roomLabel(d);
    if (!groups.has(room)) groups.set(room, []);
    groups.get(room).push(d);
  });
  // Named rooms alphabetically, unassigned devices last
  return [...groups.entries()].sort((a, b) => {
    const ua = a[0] === "No room assigned", ub = b[0] === "No room assigned";
    return ua !== ub ? (ua ? 1 : -1) : a[0].localeCompare(b[0]);
  });
}

function buildRoomGroupsHtml(devices) {
  return groupDevicesByRoom(devices).map(([room, devs]) => `
    <div class="room-group">
      <div class="room-group-title">${escapeHtml(room)} <span style="opacity: 0.6;">(${devs.length})</span></div>
      <div class="dashboard-grid">${devs.sort((a, b) => a.name.localeCompare(b.name)).map(d => createDeviceCardHtml(d)).join("")}</div>
    </div>
  `).join("");
}

function renderTuyaDevices(allDevices) {
  const grid = document.getElementById("devices-grid");
  const quickGrid = document.getElementById("quick-devices-grid");
  if (!grid) return;

  const selectedHome = updateHomeFilters(allDevices || []);
  const devices = (allDevices || []).filter(d => selectedHome === ALL_HOMES || d.home === selectedHome);

  if (!devices || devices.length === 0) {
    grid.innerHTML = `<div class="card" style="text-align: center; color: var(--text-muted); padding: 32px;">
      <div style="font-size: 32px; margin-bottom: 8px;">📡</div>
      <div style="font-size: 16px; font-weight: 600; color: #fff; margin-bottom: 4px;">No SmartLife / Tuya Devices Displayed Yet</div>
      <div>Click <strong>"🔍 Scan Local Devices"</strong> above to auto-discover your devices and add them to the screen!</div>
    </div>`;
    if (quickGrid) quickGrid.innerHTML = grid.innerHTML;
    return;
  }

  const html = buildRoomGroupsHtml(devices);
  grid.innerHTML = html;
  if (quickGrid) quickGrid.innerHTML = html;

  // Bind event listeners for toggles, sliders, and climate steppers
  devices.forEach(dev => {
    // Power Toggle
    const toggleBtn = document.querySelectorAll(`.device-toggle-btn[data-id="${dev.id}"]`);
    toggleBtn.forEach(btn => {
      if (btn.dataset.channel) {
        // One line of a multi-line switch
        const ch = (dev.channels || []).find(c => String(c.index) === btn.dataset.channel);
        btn.onclick = () => toggleDevicePower(dev.id, !(ch && ch.is_on), parseInt(btn.dataset.channel));
      } else {
        btn.onclick = () => toggleDevicePower(dev.id, !dev.is_on);
      }
    });

    // Light Brightness Slider
    const lightSlider = document.querySelectorAll(`.device-brightness-slider[data-id="${dev.id}"]`);
    lightSlider.forEach(s => {
      s.onchange = (e) => setDeviceBrightness(dev.id, parseInt(e.target.value));
    });

    // Climate Temperature Slider
    const tempSlider = document.querySelectorAll(`.device-temp-slider[data-id="${dev.id}"]`);
    tempSlider.forEach(s => {
      s.oninput = (e) => {
        const targetValEl = document.querySelectorAll(`.temp-target-val[data-id="${dev.id}"]`);
        targetValEl.forEach(el => el.textContent = `${parseFloat(e.target.value).toFixed(1)}°C`);
      };
      s.onchange = (e) => setDeviceTemperature(dev.id, parseFloat(e.target.value));
    });

    // Climate Stepper Buttons (+ / -)
    const btnMinus = document.querySelectorAll(`.temp-step-minus[data-id="${dev.id}"]`);
    btnMinus.forEach(btn => {
      btn.onclick = () => stepDeviceTemperature(dev.id, -0.5);
    });

    const btnPlus = document.querySelectorAll(`.temp-step-plus[data-id="${dev.id}"]`);
    btnPlus.forEach(btn => {
      btn.onclick = () => stepDeviceTemperature(dev.id, +0.5);
    });

    // Pet Feeder Feed Button
    const btnFeed = document.querySelectorAll(`.btn-feed-pet[data-id="${dev.id}"]`);
    btnFeed.forEach(btn => {
      btn.onclick = () => triggerPetFeed(dev.id);
    });
  });
}

function deviceLocation(dev) {
  const room = escapeHtml(roomLabel(dev));
  return dev.home ? `${escapeHtml(dev.home)} / ${room}` : room;
}

// Card layout for a device. The stored type wins; category codes / names are only a fallback for generic "switch" devices.
function deviceKind(dev) {
  const t = dev.type;
  if (t === "bulb") return "light";
  if (t === "pet") return "pet_feeder";
  if (["sensor", "climate", "pet_feeder", "light"].includes(t)) return t;
  if (t && t !== "switch") return t; // socket, curtain, fan...
  const cat = dev.category;
  if (["cwf", "cwyq", "cwwsq", "cwsb", "pet", "cw", "cww"].includes(cat)) return "pet_feeder";
  if (["wsdcg", "cg", "th01", "thp", "hjjcy", "mcs", "pir", "ywbj", "rqbj", "sj"].includes(cat)) return "sensor";
  if (["wk", "wkf", "rs", "qn", "tc", "wkjsq"].includes(cat)) return "climate";
  const words = (dev.name || "").toLowerCase().match(/[a-z0-9]+/g) || [];
  if (words.some(w => ["thermostat", "heater", "trv", "radiator", "boiler"].includes(w))) return "climate";
  if (words.some(w => ["feeder", "fountain", "waterer"].includes(w))) return "pet_feeder";
  return "switch";
}

function createDeviceCardHtml(dev) {
  const kind = deviceKind(dev);
  const isSensor = kind === "sensor";
  const isLight = kind === "light";
  const isClimate = kind === "climate";
  const isPetFeeder = kind === "pet_feeder";

  let icon = "⚡";
  if (isPetFeeder) icon = "🐾";
  else if (isSensor) icon = "📟";
  else if (isClimate) icon = "🌡️";
  else if (isLight) icon = "💡";
  else if (dev.type === "socket") icon = "🔌";
  
  let statusBadge = `<span style="color: var(--accent-green); font-size: 12px;">● Online</span>`;
  if (!dev.online) {
    if (dev.error && dev.error.includes("Local key")) {
      statusBadge = `<span style="color: var(--accent-amber); font-size: 12px;">⚠️ Key Required</span>`;
    } else {
      statusBadge = `<span style="color: var(--text-muted); font-size: 12px;" title="${escapeHtml(dev.error || '')}">○ Offline${dev.error ? ' (' + escapeHtml(String(dev.error).slice(0, 40)) + ')' : ''}</span>`;
    }
  }

  // --- 0. SENSOR CARD (read-only readings, no controls) ---
  if (isSensor) {
    const has = v => v !== undefined && v !== null;
    const readings = [];
    const batteryReading = () => has(dev.battery)
      ? `<div><div class="sensor-label">Battery</div><div class="sensor-value">🔋 ${dev.battery}%</div></div>`
      : dev.battery_state ? `<div><div class="sensor-label">Battery</div><div class="sensor-value">🔋 ${escapeHtml(dev.battery_state)}</div></div>` : "";
    if (dev.is_motion_sensor || dev.category === "pir") {
      // Motion detector: only the motion state and the battery level
      const known = dev.motion === true || dev.motion === false;
      const detected = dev.motion === true;
      const stateText = !known ? "Unknown" : detected ? "Motion detected" : "Clear";
      const stateColor = !dev.online || !known ? "var(--text-muted)" : detected ? "var(--accent-amber)" : "var(--accent-green)";
      readings.push(`<div><div class="sensor-label">Motion</div><div class="sensor-value" style="color: ${stateColor}; font-size: 22px;">${detected ? "🚶" : "✓"} ${stateText}</div></div>`);
      readings.push(batteryReading());
    } else {
      if (has(dev.current_temperature)) readings.push(`<div><div class="sensor-label">Temperature</div><div class="sensor-value">${parseFloat(dev.current_temperature).toFixed(1)}°C</div></div>`);
      if (has(dev.humidity)) readings.push(`<div><div class="sensor-label">Humidity</div><div class="sensor-value">💧 ${dev.humidity}%</div></div>`);
      readings.push(batteryReading());
    }
    const body = readings.filter(Boolean).length
      ? `<div class="sensor-readings">${readings.join("")}</div>`
      : `<div style="color: var(--text-muted); font-size: 13px; margin-top: 14px;">${dev.online ? "No readings reported yet" : "Waiting for the sensor to report"}</div>`;
    return `
      <div class="card" id="card-${dev.id}">
        <div>
          <div class="card-header">
            <div>
              <div class="card-title">${escapeHtml(dev.name)}</div>
              <div class="card-subtitle">${deviceLocation(dev)} &bull; ${statusBadge}</div>
            </div>
            <div class="card-icon">${icon}</div>
          </div>
          ${body}
        </div>
      </div>
    `;
  }

  // --- 1. CLIMATE / HEATING THERMOSTAT CARD ---
  if (isClimate) {
    const hasCurrent = dev.current_temperature !== undefined && dev.current_temperature !== null;
    const currentTempDisplay = hasCurrent ? `${parseFloat(dev.current_temperature).toFixed(1)}°C` : `<span style="opacity: 0.5; font-size: 26px;">--.-°C</span>`;
    
    const hasTarget = dev.target_temperature !== undefined && dev.target_temperature !== null;
    const targetTempDisplay = hasTarget ? `${parseFloat(dev.target_temperature).toFixed(1)}°C` : `21.0°C`;
    const targetSliderVal = hasTarget ? parseFloat(dev.target_temperature).toFixed(1) : "21.0";

    const humidityBadge = (dev.humidity !== undefined && dev.humidity !== null) ? `<span style="background: rgba(59, 130, 246, 0.2); color: #60a5fa; font-size: 11px; padding: 2px 8px; border-radius: 6px; margin-left: 6px;">💧 ${dev.humidity}%</span>` : '';
    const batteryBadge = (dev.battery !== undefined && dev.battery !== null) ? `<span style="background: rgba(34, 197, 94, 0.2); color: #4ade80; font-size: 11px; padding: 2px 8px; border-radius: 6px; margin-left: 6px;">🔋 ${dev.battery}%</span>` : '';

    return `
      <div class="card" id="card-${dev.id}" style="border-color: rgba(251, 146, 60, 0.3);">
        <div>
          <div class="card-header">
            <div>
              <div class="card-title">${escapeHtml(dev.name)} ${humidityBadge} ${batteryBadge}</div>
              <div class="card-subtitle">${deviceLocation(dev)} &bull; ${statusBadge}</div>
            </div>
            <div class="card-icon" style="background: rgba(251, 146, 60, 0.15);">🔥</div>
          </div>

          <!-- Current Room Temperature Display -->
          <div class="climate-current-temp">
            <div>
              <div style="font-size: 11px; text-transform: uppercase; color: var(--text-muted); letter-spacing: 0.5px;">Current Temp</div>
              <div class="climate-temp-big">${currentTempDisplay}</div>
            </div>
            <button class="device-toggle-btn ${dev.is_on ? 'is-on' : ''}" data-id="${dev.id}" style="width: auto; padding: 10px 18px; font-size: 14px;">
              ${dev.is_on ? '🔥 Heating' : '❄️ Off'}
            </button>
          </div>

          <!-- Target Desired Temperature Stepper -->
          <div style="margin-top: 14px;">
            <div style="font-size: 12px; color: var(--text-muted); margin-bottom: 4px;">Desired Setpoint:</div>
            
            <div class="temp-stepper">
              <button class="temp-btn temp-step-minus" data-id="${dev.id}">−</button>
              
              <div class="temp-target-display">
                <div class="temp-target-val" data-id="${dev.id}">${targetTempDisplay}</div>
              </div>

              <button class="temp-btn temp-step-plus" data-id="${dev.id}">+</button>
            </div>

            <!-- Touch Range Slider -->
            <div class="slider-container" style="margin-top: 10px;">
              <input type="range" min="5.0" max="35.0" step="0.5" value="${targetSliderVal}" class="touch-slider device-temp-slider" data-id="${dev.id}" style="accent-color: #fb923c;">
            </div>
          </div>
        </div>
      </div>
    `;
  }

  // --- 2. PET FEEDER / PET WATERER CARD ---
  if (isPetFeeder) {
    const lastFed = dev.last_fed || "Today";
    const records = dev.feeding_records || [];
    const recordsHtml = records.length
      ? records.map(r => `<div style="display: flex; justify-content: space-between; padding: 4px 0; border-top: 1px solid var(--border-color);"><span>${escapeHtml(r.time)}</span><span>${r.portions} portion${r.portions === 1 ? "" : "s"}</span></div>`).join("")
      : `<div style="padding: 4px 0; border-top: 1px solid var(--border-color); color: var(--text-muted);">No feedings recorded today</div>`;
    const recordsNote = dev.feeding_source === "homeauto" ? " (HomeAuto only)" : "";
    return `
      <div class="card" id="card-${dev.id}" style="border-color: rgba(168, 85, 247, 0.35);">
        <div>
          <div class="card-header">
            <div>
              <div class="card-title">${escapeHtml(dev.name)}</div>
              <div class="card-subtitle">${deviceLocation(dev)} &bull; ${statusBadge}</div>
            </div>
            <div class="card-icon" style="background: rgba(168, 85, 247, 0.15);">🐾</div>
          </div>

          <div style="background: rgba(255, 255, 255, 0.04); padding: 12px 16px; border-radius: 12px; margin: 12px 0; border: 1px solid var(--border-color); display: flex; justify-content: space-between; align-items: center;">
            <div>
              <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase;">Status</div>
              <div style="font-size: 16px; font-weight: 700; color: #c084fc;">Ready to Dispense</div>
            </div>
            <div style="font-size: 12px; color: var(--text-muted);">
              Last fed: <strong style="color: #fff;">${lastFed}</strong>
            </div>
          </div>
          <div style="font-size: 12px;">
            <div style="color: var(--text-muted); text-transform: uppercase; font-size: 11px; margin-bottom: 4px;">
              Today's feedings &bull; ${dev.feeding_total || 0} total${recordsNote}
            </div>
            <div style="max-height: 120px; overflow-y: auto;">${recordsHtml}</div>
          </div>

          <div style="display: flex; gap: 10px; margin-top: 14px;">
            <button class="action-btn btn-feed-pet" data-id="${dev.id}" style="flex: 1; justify-content: center; background: linear-gradient(135deg, #a855f7, #7e22ce); font-size: 15px;">
              🍖 Dispense 1 Portion
            </button>
          </div>
        </div>
      </div>
    `;
  }

  // --- 3. LIGHT / SWITCH / SOCKET CARD ---
  const channels = !isLight && Array.isArray(dev.channels) ? dev.channels : [];
  return `
    <div class="card" id="card-${dev.id}">
      <div>
        <div class="card-header">
          <div>
            <div class="card-title">${escapeHtml(dev.name)}</div>
            <div class="card-subtitle">${deviceLocation(dev)} &bull; ${statusBadge}</div>
          </div>
          <div class="card-icon">${icon}</div>
        </div>

        ${channels.length > 1 ? `
          <div style="display: flex; flex-direction: column; gap: 8px;">
            ${channels.map(ch => `
              <button class="device-toggle-btn ${ch.is_on ? 'is-on' : ''}" data-id="${dev.id}" data-channel="${ch.index}">
                ${ch.is_on ? '⚡' : '○'} Line ${ch.index} &bull; ${ch.is_on ? 'ON' : 'OFF'}
              </button>
            `).join("")}
          </div>
        ` : `
          <button class="device-toggle-btn ${dev.is_on ? 'is-on' : ''}" data-id="${dev.id}">
            ${dev.is_on ? '⚡ ON' : '○ OFF'}
          </button>
        `}
      </div>

      ${isLight ? `
        <div class="slider-container">
          <div class="slider-label">
            <span>Brightness</span>
            <span>${dev.brightness || 100}%</span>
          </div>
          <input type="range" min="1" max="100" value="${dev.brightness || 100}" class="touch-slider device-brightness-slider" data-id="${dev.id}">
        </div>
      ` : ''}
    </div>
  `;
}

async function toggleDevicePower(deviceId, newState, channel) {
  try {
    const res = await fetch(`/api/devices/${deviceId}/power`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(channel ? { is_on: newState, channel } : { is_on: newState })
    });
    if (res.ok) {
      showToast(`${channel ? `Line ${channel}` : "Device"} turned ${newState ? 'ON' : 'OFF'}`);
    } else {
      showToast("Device command failed", 2000);
    }
  } catch (e) {
    showToast("Network error communicating with device");
  }
}

async function setDeviceBrightness(deviceId, brightness) {
  try {
    await fetch(`/api/devices/${deviceId}/brightness`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ brightness })
    });
  } catch (e) {
    console.error("Brightness error:", e);
  }
}

async function setDeviceTemperature(deviceId, targetTemp) {
  const rounded = parseFloat(targetTemp).toFixed(1);
  const targetValEl = document.querySelectorAll(`.temp-target-val[data-id="${deviceId}"]`);
  targetValEl.forEach(el => el.textContent = `${rounded}°C`);

  const slider = document.querySelectorAll(`.device-temp-slider[data-id="${deviceId}"]`);
  slider.forEach(s => s.value = rounded);

  try {
    const res = await fetch(`/api/devices/${deviceId}/temperature`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ temperature: parseFloat(rounded) })
    });
    if (res.ok) {
      showToast(`Target set to ${rounded}°C`);
      const dev = state.devices.find(d => d.id === deviceId);
      if (dev) dev.target_temperature = parseFloat(rounded);
    }
  } catch (e) {
    showToast("Failed to set temperature");
  }
}

function stepDeviceTemperature(deviceId, stepDelta) {
  const dev = state.devices.find(d => d.id === deviceId);
  const currentTarget = (dev && dev.target_temperature !== undefined && dev.target_temperature !== null) ? dev.target_temperature : 21.0;
  const newTarget = Math.max(5.0, Math.min(35.0, currentTarget + stepDelta));
  setDeviceTemperature(deviceId, newTarget);
}

async function triggerPetFeed(deviceId) {
  const btns = document.querySelectorAll(`.btn-feed-pet[data-id="${deviceId}"]`);
  btns.forEach(b => {
    b.textContent = "⏳ Dispensing...";
    b.disabled = true;
  });

  try {
    const res = await fetch(`/api/devices/${deviceId}/feed`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ portions: 1 })
    });
    if (res.ok) {
      showToast("🍖 Food dispensed successfully for your pet!");
      const dev = state.devices.find(d => d.id === deviceId);
      if (dev) {
        dev.last_fed = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        renderTuyaDevices(state.devices);
      }
    } else {
      showToast("Failed to dispense food", 3000);
    }
  } catch (err) {
    showToast("Error communicating with Pet Feeder", 3000);
  } finally {
    btns.forEach(b => {
      b.textContent = "🍖 Dispense 1 Portion";
      b.disabled = false;
    });
  }
}

function updateAmbientDeviceSummary(devices) {
  const summaryEl = document.getElementById("ss-active-devices");
  if (!summaryEl) return;
  const activeCount = devices.filter(d => d.is_on && deviceKind(d) !== "sensor").length;
  summaryEl.textContent = `${activeCount} Active Device${activeCount === 1 ? '' : 's'}`;
}

function escapeHtml(str) {
  if (!str) return "";
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
