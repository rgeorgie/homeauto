// Bluetooth Surround Sound Management Component

// Kiosk-only Pi: the page comes from a remote server, but the speaker is paired to the Pi itself.
// kiosk.sh opens the page with ?kiosk=1 (remembered in localStorage). In that case every Bluetooth call goes to the
// Pi agent (backend/pi_agent.py) on the Pi's loopback - never to the server, which has no access to the Pi's Bluetooth.
// If the page itself is served from the Pi (all-in-one install), the server IS the Pi and is used directly.
const BT_AGENT_BASE = "http://127.0.0.1:8765";
const BT_PAGE_IS_LOCAL = ["127.0.0.1", "localhost", "::1", "[::1]"].includes(location.hostname);
if (new URLSearchParams(location.search).get("kiosk") === "1") {
  try { localStorage.setItem("homeauto_kiosk", "1"); } catch (e) { /* storage unavailable */ }
}
const BT_USE_AGENT = !BT_PAGE_IS_LOCAL && (() => {
  try { return localStorage.getItem("homeauto_kiosk") === "1"; } catch (e) { return false; }
})();
const BT_AGENT_HINT = "Pi Bluetooth agent not reachable - on the Pi run: systemctl --user status homeauto-agent";

function btUsesAgent() {
  return BT_USE_AGENT;
}

function btUrl(path) {
  return (BT_USE_AGENT ? BT_AGENT_BASE : "") + path;
}

function renderBtAgentDown() {
  const badgeEl = document.getElementById("bt-status-badge");
  if (badgeEl) {
    badgeEl.textContent = "Pi Bluetooth agent not running";
    badgeEl.className = "status-pill disconnected";
  }
}

async function btAgentLoop() {
  try {
    const res = await fetch(BT_AGENT_BASE + "/api/bluetooth", { signal: AbortSignal.timeout(4000) });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    state.bluetooth = await res.json();
    renderBluetoothStatus(state.bluetooth);
  } catch (e) {
    renderBtAgentDown();
  }
  setTimeout(btAgentLoop, 5000);
}

function initBluetoothController() {
  if (BT_USE_AGENT) btAgentLoop();

  const scanBtn = document.getElementById("btn-scan-bluetooth");
  const disconnectBtn = document.getElementById("btn-bt-disconnect");
  const volSlider = document.getElementById("bt-volume-slider");

  if (scanBtn) {
    scanBtn.addEventListener("click", async () => {
      scanBtn.textContent = "Scanning Bluetooth...";
      scanBtn.disabled = true;
      try {
        const res = await fetch(btUrl("/api/bluetooth/scan"));
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const devices = await res.json();
        renderBtDevicesList(devices);
      } catch (e) {
        showToast(BT_USE_AGENT ? BT_AGENT_HINT : "Error scanning Bluetooth devices");
      } finally {
        scanBtn.textContent = "🔍 Scan Paired Devices";
        scanBtn.disabled = false;
      }
    });
  }

  if (disconnectBtn) {
    disconnectBtn.addEventListener("click", async () => {
      await fetch(btUrl("/api/bluetooth/disconnect"), { method: "POST" });
      showToast("Bluetooth disconnected");
    });
  }

  if (volSlider) {
    volSlider.addEventListener("input", (e) => {
      const vol = parseInt(e.target.value);
      fetch(btUrl("/api/bluetooth/volume"), {
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
        const res = await fetch(btUrl("/api/bluetooth/test-sound"), { method: "POST" });
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
    const res = await fetch(btUrl("/api/bluetooth/connect"), {
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
    showToast(BT_USE_AGENT ? BT_AGENT_HINT : "Error connecting to Bluetooth");
  }
}
