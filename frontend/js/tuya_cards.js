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
  if (roomInput) roomInput.value = dev.room || "Living Room";
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

function renderTuyaDevices(devices) {
  const grid = document.getElementById("devices-grid");
  const quickGrid = document.getElementById("quick-devices-grid");
  if (!grid) return;

  if (!devices || devices.length === 0) {
    grid.innerHTML = `<div class="card" style="grid-column: 1/-1; text-align: center; color: var(--text-muted); padding: 32px;">
      <div style="font-size: 32px; margin-bottom: 8px;">📡</div>
      <div style="font-size: 16px; font-weight: 600; color: #fff; margin-bottom: 4px;">No SmartLife / Tuya Devices Displayed Yet</div>
      <div>Click <strong>"🔍 Scan Local Devices"</strong> above to auto-discover your 10 devices and add them to the screen!</div>
    </div>`;
    if (quickGrid) quickGrid.innerHTML = grid.innerHTML;
    return;
  }

  const html = devices.map(dev => createDeviceCardHtml(dev)).join("");
  grid.innerHTML = html;
  if (quickGrid) quickGrid.innerHTML = html;

  // Bind event listeners for toggles and sliders
  devices.forEach(dev => {
    const toggleBtn = document.querySelectorAll(`.device-toggle-btn[data-id="${dev.id}"]`);
    toggleBtn.forEach(btn => {
      btn.onclick = () => toggleDevicePower(dev.id, !dev.is_on);
    });

    const slider = document.querySelectorAll(`.device-brightness-slider[data-id="${dev.id}"]`);
    slider.forEach(s => {
      s.onchange = (e) => setDeviceBrightness(dev.id, parseInt(e.target.value));
    });
  });
}

function createDeviceCardHtml(dev) {
  const isLight = dev.type === "light" || dev.type === "bulb";
  const icon = isLight ? "💡" : (dev.type === "socket" ? "🔌" : (dev.type === "climate" ? "🌡️" : "⚡"));
  
  let statusBadge = `<span style="color: var(--accent-green); font-size: 12px;">● Online</span>`;
  if (!dev.online) {
    if (dev.error && dev.error.includes("Local key")) {
      statusBadge = `<span style="color: var(--accent-amber); font-size: 12px;">⚠️ Key Required</span>`;
    } else {
      statusBadge = `<span style="color: var(--text-muted); font-size: 12px;">○ Offline</span>`;
    }
  }

  return `
    <div class="card" id="card-${dev.id}">
      <div>
        <div class="card-header">
          <div>
            <div class="card-title">${escapeHtml(dev.name)}</div>
            <div class="card-subtitle">${escapeHtml(dev.room || 'Default')} &bull; ${statusBadge}</div>
          </div>
          <div class="card-icon">${icon}</div>
        </div>

        <button class="device-toggle-btn ${dev.is_on ? 'is-on' : ''}" data-id="${dev.id}">
          ${dev.is_on ? '⚡ ON' : '○ OFF'}
        </button>
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

async function toggleDevicePower(deviceId, newState) {
  try {
    const res = await fetch(`/api/devices/${deviceId}/power`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_on: newState })
    });
    if (res.ok) {
      showToast(`Device turned ${newState ? 'ON' : 'OFF'}`);
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

function updateAmbientDeviceSummary(devices) {
  const summaryEl = document.getElementById("ss-active-devices");
  if (!summaryEl) return;
  const activeCount = devices.filter(d => d.is_on).length;
  summaryEl.textContent = `${activeCount} Active Device${activeCount === 1 ? '' : 's'}`;
}

function escapeHtml(str) {
  if (!str) return "";
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
