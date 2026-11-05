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

  const testSoundBtn = document.getElementById("btn-test-bt-sound");
  if (testSoundBtn) {
    testSoundBtn.addEventListener("click", async () => {
      showToast("Playing test audio chime on soundbar...");
      try {
        const res = await fetch("/api/bluetooth/test-sound", { method: "POST" });
        const data = await res.json();
        if (data.status === "ok" || data.success) {
          showToast(`🔊 Chime played via ${data.method || 'soundbar sink'}!`);
        } else {
          showToast(`Audio output error: ${data.error || 'Check soundbar connection'}`);
        }
      } catch (err) {
        showToast("Error testing sound: " + err.message);
      }
    });
  }
}

function renderBluetoothStatus(bt) {
  const nameEl = document.getElementById("bt-device-name");
  const badgeEl = document.getElementById("bt-status-badge");
  const volSlider = document.getElementById("bt-volume-slider");
  const volLabel = document.getElementById("bt-volume-label");
  const sinkEl = document.getElementById("bt-active-sink-label");

  if (nameEl) nameEl.textContent = bt.name || "Surround Sound";
  if (badgeEl) {
    const isBtActive = bt.is_bt_sink_active || (bt.connected && bt.active_sink && bt.active_sink.toLowerCase().includes('bluez'));
    if (bt.connected && isBtActive) {
      badgeEl.textContent = "🔊 Soundbar Active";
      badgeEl.className = "status-pill";
    } else if (bt.connected) {
      badgeEl.textContent = "Connected (HDMI Output)";
      badgeEl.className = "status-pill";
    } else {
      badgeEl.textContent = "Disconnected";
      badgeEl.className = "status-pill disconnected";
    }
  }
  if (sinkEl && bt.active_sink) {
    sinkEl.textContent = bt.active_sink;
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
