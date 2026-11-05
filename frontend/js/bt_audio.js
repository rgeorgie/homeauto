// Bluetooth Surround Sound Management Component

function initBluetoothController() {
  const scanBtn = document.getElementById("btn-scan-bluetooth");
  const disconnectBtn = document.getElementById("btn-bt-disconnect");
  const volSlider = document.getElementById("bt-volume-slider");

  if (scanBtn) {
    scanBtn.addEventListener("click", async () => {
      scanBtn.textContent = "Scanning Bluetooth...";
      scanBtn.disabled = true;
      try {
        const res = await fetch("/api/bluetooth/scan");
        const devices = await res.json();
        renderBtDevicesList(devices);
      } catch (e) {
        showToast("Error scanning Bluetooth devices");
      } finally {
        scanBtn.textContent = "🔍 Scan Paired Devices";
        scanBtn.disabled = false;
      }
    });
  }

  if (disconnectBtn) {
    disconnectBtn.addEventListener("click", async () => {
      await fetch("/api/bluetooth/disconnect", { method: "POST" });
      showToast("Bluetooth disconnected");
    });
  }

  if (volSlider) {
    volSlider.addEventListener("input", (e) => {
      const vol = parseInt(e.target.value);
      fetch("/api/bluetooth/volume", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ volume: vol })
      });
    });
  }
}

function renderBluetoothStatus(bt) {
  const nameEl = document.getElementById("bt-device-name");
  const badgeEl = document.getElementById("bt-status-badge");
  const volSlider = document.getElementById("bt-volume-slider");
  const volLabel = document.getElementById("bt-volume-label");

  if (nameEl) nameEl.textContent = bt.name || "Surround Sound";
  if (badgeEl) {
    badgeEl.textContent = bt.connected ? "Connected" : "Disconnected";
    badgeEl.className = `status-pill ${bt.connected ? '' : 'disconnected'}`;
  }
  if (volSlider && bt.volume !== undefined) volSlider.value = bt.volume;
  if (volLabel && bt.volume !== undefined) volLabel.textContent = `${bt.volume}%`;
}

function renderBtDevicesList(devices) {
  const container = document.getElementById("bt-devices-list");
  if (!container) return;

  if (!devices || devices.length === 0) {
    container.innerHTML = `<div style="color: var(--text-muted); padding: 12px;">No paired Bluetooth devices found. Pair via bluetoothctl or Pi settings.</div>`;
    return;
  }

  container.innerHTML = devices.map(d => `
    <div style="display: flex; justify-content: space-between; align-items: center; padding: 12px; background: rgba(255,255,255,0.03); border-radius: 12px; margin-bottom: 8px;">
      <div>
        <div style="font-weight: 600;">${escapeHtml(d.name)}</div>
        <div style="font-size: 12px; color: var(--text-muted);">${escapeHtml(d.mac)}</div>
      </div>
      <button class="action-btn" style="padding: 8px 16px; font-size: 13px;" onclick="connectBtDevice('${d.mac}')">
        Connect
      </button>
    </div>
  `).join("");
}

async function connectBtDevice(mac) {
  showToast("Connecting to Bluetooth speaker...");
  try {
    const res = await fetch("/api/bluetooth/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mac })
    });
    const data = await res.json();
    if (data.connected) {
      showToast("Surround sound connected!");
    } else {
      showToast("Connection failed. Ensure speaker is in pairing mode.");
    }
  } catch (e) {
    showToast("Error connecting to Bluetooth");
  }
}
