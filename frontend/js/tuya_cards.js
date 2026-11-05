// SmartLife / Tuya Device Cards Component

function initTuyaCards() {
  const scanBtn = document.getElementById("btn-scan-devices");
  if (scanBtn) {
    scanBtn.addEventListener("click", async () => {
      scanBtn.textContent = "Scanning network...";
      scanBtn.disabled = true;
      try {
        const res = await fetch("/api/devices/scan", { method: "POST" });
        const data = await res.json();
        showToast(`Scan complete: Found ${data.local.length} local and ${data.cloud.length} cloud devices.`);
      } catch (err) {
        showToast("Error scanning devices");
      } finally {
        scanBtn.textContent = "🔍 Scan Local Devices";
        scanBtn.disabled = false;
      }
    });
  }
}

function renderTuyaDevices(devices) {
  const grid = document.getElementById("devices-grid");
  const quickGrid = document.getElementById("quick-devices-grid");
  if (!grid) return;

  if (!devices || devices.length === 0) {
    grid.innerHTML = `<div class="card" style="grid-column: 1/-1; text-align: center; color: var(--text-muted);">
      No Tuya/SmartLife devices configured. Add devices in <code>config.yaml</code> or click Scan.
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
  const icon = isLight ? "💡" : (dev.type === "socket" ? "🔌" : "⚡");
  const statusBadge = dev.online ? `<span style="color: var(--accent-green); font-size: 12px;">● Online</span>` : `<span style="color: var(--text-muted); font-size: 12px;">○ Offline</span>`;

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
