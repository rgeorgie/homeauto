// Admin Web Panel Controller

let adminConfig = null;
let editingDeviceId = null;

document.addEventListener("DOMContentLoaded", () => {
  initAdminPanel();
});

function initAdminPanel() {
  const adminTabBtns = document.querySelectorAll(".admin-tab-btn");
  adminTabBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      adminTabBtns.forEach(b => b.classList.remove("active"));
      document.querySelectorAll(".admin-subview").forEach(v => v.classList.remove("active"));

      btn.classList.add("active");
      const target = document.getElementById(`admin-subview-${btn.dataset.tab}`);
      if (target) target.classList.add("active");
    });
  });

  // Load config on startup
  loadAdminConfig();

  // Save full config button
  const saveAllBtn = document.getElementById("btn-save-all-config");
  if (saveAllBtn) {
    saveAllBtn.addEventListener("click", () => saveFullConfig());
  }

  // Add Device Modal triggers
  const btnAddDevice = document.getElementById("btn-admin-add-device");
  const modalDevice = document.getElementById("modal-device-form");
  const btnCloseModal = document.getElementById("btn-close-device-modal");
  const formDevice = document.getElementById("form-device");
  const btnTestDevice = document.getElementById("btn-test-device-form");

  if (btnAddDevice && modalDevice) {
    btnAddDevice.addEventListener("click", () => {
      editingDeviceId = null;
      document.getElementById("modal-device-title").textContent = "Add SmartLife / Tuya Device";
      formDevice.reset();
      document.getElementById("device-version").value = "3.3";
      document.getElementById("device-test-result").textContent = "";
      modalDevice.style.display = "flex";
    });
  }

  if (btnCloseModal && modalDevice) {
    btnCloseModal.addEventListener("click", () => {
      modalDevice.style.display = "none";
    });
  }

  if (btnTestDevice) {
    btnTestDevice.addEventListener("click", async () => {
      const devId = document.getElementById("device-id").value.trim();
      const ip = document.getElementById("device-ip").value.trim();
      const localKey = document.getElementById("device-key").value.trim();
      const version = parseFloat(document.getElementById("device-version").value || "3.3");

      const resEl = document.getElementById("device-test-result");
      resEl.textContent = "Testing local connection...";
      resEl.style.color = "var(--text-muted)";

      try {
        const res = await fetch("/api/devices/test", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: devId, ip, local_key: localKey, version })
        });
        const data = await res.json();
        if (data.success) {
          resEl.textContent = `✅ Connected successfully! (DPS: ${JSON.stringify(data.dps)})`;
          resEl.style.color = "var(--accent-green)";
        } else {
          resEl.textContent = `❌ Connection failed: ${data.error || 'Device not reachable'}`;
          resEl.style.color = "var(--accent-red)";
        }
      } catch (err) {
        resEl.textContent = `❌ Request error: ${err.message}`;
        resEl.style.color = "var(--accent-red)";
      }
    });
  }

  if (formDevice) {
    formDevice.addEventListener("submit", async (e) => {
      e.preventDefault();
      const devData = {
        id: document.getElementById("device-id").value.trim(),
        name: document.getElementById("device-name").value.trim(),
        ip: document.getElementById("device-ip").value.trim(),
        local_key: document.getElementById("device-key").value.trim(),
        version: parseFloat(document.getElementById("device-version").value || "3.3"),
        type: document.getElementById("device-type").value,
        category: document.getElementById("device-category")?.value.trim() || "cz",
        room: document.getElementById("device-room").value.trim(),
        home: document.getElementById("device-home").value.trim(),
        stream_url: document.getElementById("device-stream-url")?.value.trim() || ""
      };

      try {
        let res;
        if (editingDeviceId) {
          res = await fetch(`/api/config/devices/${editingDeviceId}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(devData)
          });
        } else {
          res = await fetch("/api/config/devices", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(devData)
          });
        }

        if (res.ok) {
          showToast(editingDeviceId ? "Device updated successfully" : "Device added successfully");
          modalDevice.style.display = "none";
          await loadAdminConfig();
        } else {
          const err = await res.json();
          showToast(`Error: ${err.detail || 'Failed to save device'}`);
        }
      } catch (err) {
        showToast(`Save error: ${err.message}`);
      }
    });
  }

  // Location Auto-Detect
  const btnDetectLoc = document.getElementById("btn-detect-location");
  if (btnDetectLoc) {
    btnDetectLoc.addEventListener("click", async () => {
      btnDetectLoc.textContent = "Detecting...";
      try {
        const res = await fetch("/api/weather/detect-location", { method: "POST" });
        const data = await res.json();
        if (data.success) {
          document.getElementById("weather-lat").value = data.latitude;
          document.getElementById("weather-lon").value = data.longitude;
          showToast(`Location detected: ${data.city}, ${data.country} (${data.latitude}, ${data.longitude})`);
        } else {
          showToast("Could not auto-detect location");
        }
      } catch (e) {
        showToast("Error detecting location");
      } finally {
        btnDetectLoc.textContent = "📍 Auto-Detect Location";
      }
    });
  }

  // Test Kodi JSON-RPC
  const btnTestKodi = document.getElementById("btn-test-kodi-config");
  if (btnTestKodi) {
    btnTestKodi.addEventListener("click", async () => {
      const host = document.getElementById("kodi-host").value.trim();
      const port = parseInt(document.getElementById("kodi-port").value || "8080");
      const user = document.getElementById("kodi-user").value.trim();
      const pass = document.getElementById("kodi-pass").value.trim();

      const resEl = document.getElementById("kodi-test-result");
      resEl.textContent = "Pinging Kodi JSON-RPC...";
      resEl.style.color = "var(--text-muted)";

      try {
        const res = await fetch("/api/kodi/test", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ host, port, user, password: pass })
        });
        const data = await res.json();
        if (data.success) {
          resEl.textContent = "✅ Kodi responded with PONG!";
          resEl.style.color = "var(--accent-green)";
        } else {
          resEl.textContent = `❌ Kodi unreachable: ${data.error}`;
          resEl.style.color = "var(--accent-red)";
        }
      } catch (err) {
        resEl.textContent = `❌ Error: ${err.message}`;
        resEl.style.color = "var(--accent-red)";
      }
    });
  }

  // Fetch & Sync Cloud Keys button
  const btnSyncKeys = document.getElementById("btn-sync-cloud-keys");
  if (btnSyncKeys) {
    btnSyncKeys.addEventListener("click", async () => {
      // First save current credentials
      const accessId = document.getElementById("tuya-cloud-id").value.trim();
      const accessSecret = document.getElementById("tuya-cloud-secret").value.trim();
      const endpoint = document.getElementById("tuya-cloud-endpoint").value.trim();

      if (!accessId || !accessSecret) {
        showToast("Please enter your Tuya Access ID and Access Secret first.");
        return;
      }

      btnSyncKeys.textContent = "⏳ Fetching keys from Tuya Cloud...";
      btnSyncKeys.disabled = true;

      try {
        // Save full config first so backend has latest credentials
        await saveFullConfig();

        const res = await fetch("/api/tuya/cloud/sync-keys", { method: "POST" });
        const data = await res.json();

        if (data.success) {
          if (data.total_cloud_found === 0) {
            showToast("⚠️ Cloud connected, but 0 devices found in this Cloud Project. Link your SmartLife app under Devices > Link Tuya App Account on iot.tuya.com.", 6000);
          } else {
            showToast(`🎉 Success! Found ${data.total_cloud_found} cloud devices and updated ${data.keys_updated} device keys!`, 5000);
          }
          if (data.homes_matched > 0) {
            showToast(`🏠 Home/room loaded for ${data.homes_matched} devices`, 4000);
          } else {
            showToast(`⚠️ No homes/rooms received from Tuya: ${(data.location_errors || ["unknown reason"])[0]}`, 9000);
          }
          await loadAdminConfig();
        } else {
          showToast(`Cloud sync error: ${data.error || 'Failed to fetch keys'}`);
        }
      } catch (err) {
        showToast(`Request error: ${err.message}`);
      } finally {
        btnSyncKeys.textContent = "🔑 Fetch & Sync All Cloud Keys";
        btnSyncKeys.disabled = false;
      }
    });
  }

  // Add YouTube Preset Stream
  const btnAddPreset = document.getElementById("btn-add-yt-preset");
  if (btnAddPreset) {
    btnAddPreset.addEventListener("click", () => {
      const title = prompt("Enter stream title (e.g. Chillhop Beats):");
      if (!title) return;
      const url = prompt("Enter YouTube URL:");
      if (!url) return;

      if (!adminConfig.screensaver.youtube_audio.preset_streams) {
        adminConfig.screensaver.youtube_audio.preset_streams = [];
      }
      adminConfig.screensaver.youtube_audio.preset_streams.push({ title, url });
      renderPresetStreamsTable(adminConfig.screensaver.youtube_audio.preset_streams);
    });
  }

  // YAML Editor initialization
  initYamlEditor();

  // Server Hub restart
  const btnRestartServer = document.getElementById("btn-restart-server-hub");
  if (btnRestartServer) {
    btnRestartServer.addEventListener("click", async () => {
      if (!confirm("Are you sure you want to restart the HomeAuto Server backend?")) return;
      btnRestartServer.textContent = "Restarting...";
      try {
        await fetch("/api/pi/restart-app", { method: "POST" });
        showToast("Restart command sent. Reconnecting in 3 seconds...");
        setTimeout(() => window.location.reload(), 3000);
      } catch (e) {
        showToast(`Restart error: ${e.message}`);
      }
    });
  }
}

async function initYamlEditor() {
  const yamlArea = document.getElementById("yaml-editor-textarea");
  const btnSaveYaml = document.getElementById("btn-yaml-save");
  const btnReloadYaml = document.getElementById("btn-yaml-reload");
  const btnDownloadYaml = document.getElementById("btn-yaml-download");
  const inputUploadYaml = document.getElementById("input-yaml-upload");
  const statusMsg = document.getElementById("yaml-status-msg");

  async function loadYaml() {
    if (!yamlArea) return;
    try {
      const res = await fetch("/api/config/raw");
      if (res.ok) {
        const data = await res.json();
        yamlArea.value = data.yaml || "";
        if (statusMsg) statusMsg.textContent = "Loaded config.yaml from server";
      }
    } catch (e) {
      if (statusMsg) statusMsg.textContent = "Error loading config.yaml";
    }
  }

  // Load when user clicks on YAML tab
  const tabYamlBtn = document.querySelector(".admin-tab-btn[data-tab='yaml']");
  if (tabYamlBtn) {
    tabYamlBtn.addEventListener("click", () => loadYaml());
  }

  if (btnReloadYaml) {
    btnReloadYaml.addEventListener("click", () => loadYaml());
  }

  if (btnSaveYaml && yamlArea) {
    btnSaveYaml.addEventListener("click", async () => {
      const yamlContent = yamlArea.value;
      if (!yamlContent.trim()) {
        showToast("YAML configuration cannot be empty");
        return;
      }
      btnSaveYaml.textContent = "Saving...";
      btnSaveYaml.disabled = true;
      try {
        const res = await fetch("/api/config/raw", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ yaml: yamlContent })
        });
        const data = await res.json();
        if (res.ok) {
          showToast("🎉 Raw YAML saved and hot-reloaded successfully!");
          if (statusMsg) {
            statusMsg.textContent = "✅ Saved & applied successfully";
            statusMsg.style.color = "var(--accent-green)";
          }
          await loadAdminConfig();
        } else {
          showToast(`Validation error: ${data.detail || 'Invalid YAML'}`);
          if (statusMsg) {
            statusMsg.textContent = `❌ ${data.detail || 'Invalid YAML'}`;
            statusMsg.style.color = "var(--accent-red)";
          }
        }
      } catch (err) {
        showToast(`Save error: ${err.message}`);
      } finally {
        btnSaveYaml.textContent = "💾 Save & Apply YAML";
        btnSaveYaml.disabled = false;
      }
    });
  }

  if (btnDownloadYaml && yamlArea) {
    btnDownloadYaml.addEventListener("click", () => {
      const blob = new Blob([yamlArea.value || ""], { type: "text/yaml;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `homeauto-config-${new Date().toISOString().slice(0, 10)}.yaml`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    });
  }

  if (inputUploadYaml && yamlArea) {
    inputUploadYaml.addEventListener("change", (e) => {
      const file = e.target.files?.[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = (event) => {
        yamlArea.value = event.target.result;
        showToast(`Loaded ${file.name} into editor. Click "Save & Apply YAML" to activate.`);
      };
      reader.readAsText(file);
    });
  }
}

async function loadAdminConfig() {
  try {
    const res = await fetch("/api/config");
    if (res.ok) {
      adminConfig = await res.json();
      populateAdminFields(adminConfig);
    }
  } catch (err) {
    console.error("Failed to load admin config:", err);
  }
}

function populateAdminFields(cfg) {
  if (!cfg) return;

  // Tuya Devices Table
  renderAdminDevicesTable(cfg.tuya?.devices || []);

  // Tuya Cloud
  const realtimeBox = document.getElementById("tuya-realtime");
  if (realtimeBox) realtimeBox.checked = Boolean(cfg.tuya?.realtime_messages);
  if (cfg.tuya?.cloud) {
    document.getElementById("tuya-cloud-id").value = cfg.tuya.cloud.access_id || "";
    document.getElementById("tuya-cloud-secret").value = cfg.tuya.cloud.access_secret || "";
    document.getElementById("tuya-cloud-endpoint").value = cfg.tuya.cloud.endpoint || "https://openapi.tuyaeu.com";
    document.getElementById("tuya-cloud-uid").value = cfg.tuya.cloud.user_id || "";
  }

  // Bluetooth
  if (cfg.bluetooth_audio) {
    document.getElementById("bt-enabled").checked = Boolean(cfg.bluetooth_audio.enabled);
    document.getElementById("bt-mac").value = cfg.bluetooth_audio.target_mac || "";
    document.getElementById("bt-name").value = cfg.bluetooth_audio.device_name || "Surround Sound";
    document.getElementById("bt-auto-reconnect").checked = Boolean(cfg.bluetooth_audio.auto_reconnect);
    document.getElementById("bt-interval").value = cfg.bluetooth_audio.reconnect_interval_seconds || 15;
    document.getElementById("bt-default-vol").value = cfg.bluetooth_audio.default_volume || 70;
  }

  // Kodi
  if (cfg.kodi) {
    document.getElementById("kodi-enabled").checked = Boolean(cfg.kodi.enabled);
    document.getElementById("kodi-host").value = cfg.kodi.host || "127.0.0.1";
    document.getElementById("kodi-port").value = cfg.kodi.port || 8080;
    document.getElementById("kodi-user").value = cfg.kodi.user || "kodi";
    document.getElementById("kodi-pass").value = cfg.kodi.password || "";
    document.getElementById("kodi-cmd").value = cfg.kodi.launch_command || "kodi-standalone";
  }

  // Screensaver
  if (cfg.screensaver) {
    document.getElementById("ss-enabled").checked = Boolean(cfg.screensaver.enabled);
    document.getElementById("ss-mode").value = cfg.screensaver.mode || "photos";
    document.getElementById("ss-idle").value = cfg.screensaver.idle_timeout_seconds || 120;
    document.getElementById("ss-transition").value = cfg.screensaver.photo_transition_seconds || 15;
    document.getElementById("ss-photo-dir").value = cfg.screensaver.photo_directory || "./frontend/assets/photos";
    const fpDir = document.getElementById("ss-fireplace-dir");
    if (fpDir) fpDir.value = cfg.screensaver.fireplace_directory || "./frontend/assets/fireplace";
    document.getElementById("ss-unsplash").checked = Boolean(cfg.screensaver.use_unsplash_random);

    if (cfg.screensaver.youtube_audio) {
      document.getElementById("ss-yt-autoplay").checked = Boolean(cfg.screensaver.youtube_audio.auto_play_on_screensaver);
      const outMode = document.getElementById("ss-yt-output-mode");
      if (outMode) outMode.value = cfg.screensaver.youtube_audio.output_mode || "auto";
      document.getElementById("ss-yt-vol").value = cfg.screensaver.youtube_audio.volume || 50;
      renderPresetStreamsTable(cfg.screensaver.youtube_audio.preset_streams || []);
    }

    if (cfg.screensaver.widgets) {
      document.getElementById("ss-w-clock").checked = Boolean(cfg.screensaver.widgets.show_clock);
      document.getElementById("ss-w-weather").checked = Boolean(cfg.screensaver.widgets.show_weather);
      document.getElementById("ss-w-devices").checked = Boolean(cfg.screensaver.widgets.show_device_summaries);
      document.getElementById("ss-w-telemetry").checked = Boolean(cfg.screensaver.widgets.show_system_telemetry);
    }
  }

  // Weather
  if (cfg.weather) {
    document.getElementById("weather-lat").value = cfg.weather.latitude || 51.5074;
    document.getElementById("weather-lon").value = cfg.weather.longitude || -0.1278;
    document.getElementById("weather-units").value = cfg.weather.units || "celsius";
  }

  // Server
  if (cfg.server) {
    document.getElementById("server-port").value = cfg.server.port || 80;
    document.getElementById("server-host").value = cfg.server.host || "0.0.0.0";
    const remoteAdmin = document.getElementById("server-remote-admin");
    if (remoteAdmin) remoteAdmin.checked = cfg.server.allow_remote_admin !== false;
    const debugBox = document.getElementById("server-debug");
    if (debugBox) debugBox.checked = Boolean(cfg.server.debug);
  }
}

function renderAdminDevicesTable(devices) {
  const tbody = document.getElementById("admin-devices-tbody");
  if (!tbody) return;

  if (!devices || devices.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 24px;">No Tuya devices configured yet. Click "+ Add New Device" above.</td></tr>`;
    return;
  }

  tbody.innerHTML = devices.map(dev => `
    <tr>
      <td><strong>${escapeHtml(dev.name)}</strong></td>
      <td><code>${escapeHtml(dev.id)}</code></td>
      <td>${escapeHtml(dev.ip || 'Auto / Cloud')}</td>
      <td><span class="badge badge-type">${escapeHtml(dev.type)}</span></td>
      <td>${dev.home ? escapeHtml(dev.home) + ' / ' : ''}${escapeHtml(roomLabel(dev))}</td>
      <td>v${dev.version || 3.3}</td>
      <td>
        <div style="display: flex; gap: 8px;">
          <button class="action-btn" style="padding: 6px 12px; font-size: 12px;" onclick="testDeviceRow('${dev.id}', '${dev.ip}', '${dev.local_key}', ${dev.version})">⚡ Test</button>
          <button class="action-btn" style="padding: 6px 12px; font-size: 12px; background: rgba(255,255,255,0.1);" onclick="editDeviceRow('${dev.id}')">✏️ Edit</button>
          <button class="action-btn" style="padding: 6px 12px; font-size: 12px; background: rgba(239, 68, 68, 0.2); color: var(--accent-red);" onclick="deleteDeviceRow('${dev.id}')">🗑️</button>
        </div>
      </td>
    </tr>
  `).join("");
}

function renderPresetStreamsTable(presets) {
  const container = document.getElementById("admin-yt-presets-list");
  if (!container) return;

  if (!presets || presets.length === 0) {
    container.innerHTML = `<div style="color: var(--text-muted); padding: 10px;">No preset streams added yet.</div>`;
    return;
  }

  container.innerHTML = presets.map((p, idx) => `
    <div style="display: flex; justify-content: space-between; align-items: center; padding: 10px 14px; background: rgba(255,255,255,0.03); border-radius: 10px; margin-bottom: 8px;">
      <div>
        <div style="font-weight: 600;">${escapeHtml(p.title)}</div>
        <div style="font-size: 12px; color: var(--text-muted);">${escapeHtml(p.url)}</div>
      </div>
      <button class="action-btn" style="padding: 6px 12px; font-size: 12px; background: rgba(239, 68, 68, 0.2); color: var(--accent-red);" onclick="removePresetStream(${idx})">
        Remove
      </button>
    </div>
  `).join("");
}

function removePresetStream(index) {
  if (adminConfig?.screensaver?.youtube_audio?.preset_streams) {
    adminConfig.screensaver.youtube_audio.preset_streams.splice(index, 1);
    renderPresetStreamsTable(adminConfig.screensaver.youtube_audio.preset_streams);
  }
}

async function testDeviceRow(id, ip, key, version) {
  showToast(`Testing device ${id}...`);
  try {
    const res = await fetch("/api/devices/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, ip, local_key: key, version: version || 3.3 })
    });
    const data = await res.json();
    if (data.success) {
      showToast(`✅ Device ${id} is Online and responding!`);
    } else {
      showToast(`❌ Device ${id} error: ${data.error}`);
    }
  } catch (err) {
    showToast(`Test error: ${err.message}`);
  }
}

function editDeviceRow(id) {
  const dev = adminConfig?.tuya?.devices?.find(d => d.id === id);
  if (!dev) return;

  editingDeviceId = id;
  document.getElementById("modal-device-title").textContent = `Edit Device: ${dev.name}`;
  document.getElementById("device-id").value = dev.id;
  document.getElementById("device-name").value = dev.name;
  document.getElementById("device-ip").value = dev.ip || "";
  document.getElementById("device-key").value = dev.local_key || "";
  document.getElementById("device-version").value = dev.version || "3.3";
  document.getElementById("device-type").value = dev.type || "switch";
  const catInput = document.getElementById("device-category");
  if (catInput) catInput.value = dev.category || "cz";
  document.getElementById("device-room").value = dev.room || "";
  document.getElementById("device-home").value = dev.home || "";
  const streamInput = document.getElementById("device-stream-url");
  if (streamInput) streamInput.value = dev.stream_url || "";
  document.getElementById("device-test-result").textContent = "";

  document.getElementById("modal-device-form").style.display = "flex";
}

async function deleteDeviceRow(id) {
  if (!confirm(`Are you sure you want to delete device ${id}?`)) return;

  try {
    const res = await fetch(`/api/config/devices/${id}`, { method: "DELETE" });
    if (res.ok) {
      showToast("Device deleted");
      await loadAdminConfig();
    } else {
      showToast("Failed to delete device");
    }
  } catch (err) {
    showToast(`Delete error: ${err.message}`);
  }
}

async function saveFullConfig() {
  const saveBtn = document.getElementById("btn-save-all-config");
  if (saveBtn) saveBtn.textContent = "Saving...";

  const payload = {
    server: {
      host: document.getElementById("server-host").value.trim() || "0.0.0.0",
      port: parseInt(document.getElementById("server-port").value || "80"),
      debug: Boolean(document.getElementById("server-debug")?.checked),
      allow_remote_admin: Boolean(document.getElementById("server-remote-admin")?.checked)
    },
    tuya: {
      mode: "local",
      realtime_messages: Boolean(document.getElementById("tuya-realtime")?.checked),
      cloud: {
        access_id: document.getElementById("tuya-cloud-id").value.trim(),
        access_secret: document.getElementById("tuya-cloud-secret").value.trim(),
        endpoint: document.getElementById("tuya-cloud-endpoint").value.trim() || "https://openapi.tuyaeu.com",
        user_id: document.getElementById("tuya-cloud-uid").value.trim()
      },
      devices: adminConfig?.tuya?.devices || []
    },
    bluetooth_audio: {
      enabled: document.getElementById("bt-enabled").checked,
      target_mac: document.getElementById("bt-mac").value.trim(),
      device_name: document.getElementById("bt-name").value.trim() || "Surround Sound",
      auto_reconnect: document.getElementById("bt-auto-reconnect").checked,
      reconnect_interval_seconds: parseInt(document.getElementById("bt-interval").value || "15"),
      default_volume: parseInt(document.getElementById("bt-default-vol").value || "70")
    },
    kodi: {
      enabled: document.getElementById("kodi-enabled").checked,
      host: document.getElementById("kodi-host").value.trim() || "127.0.0.1",
      port: parseInt(document.getElementById("kodi-port").value || "8080"),
      user: document.getElementById("kodi-user").value.trim() || "kodi",
      password: document.getElementById("kodi-pass").value.trim(),
      launch_command: document.getElementById("kodi-cmd").value.trim() || "kodi-standalone",
      auto_switch_display: true
    },
    screensaver: {
      enabled: document.getElementById("ss-enabled").checked,
      mode: document.getElementById("ss-mode").value,
      idle_timeout_seconds: parseInt(document.getElementById("ss-idle").value || "120"),
      photo_transition_seconds: parseInt(document.getElementById("ss-transition").value || "15"),
      photo_directory: document.getElementById("ss-photo-dir").value.trim() || "./frontend/assets/photos",
      fireplace_directory: document.getElementById("ss-fireplace-dir")?.value.trim() || "./frontend/assets/fireplace",
      use_unsplash_random: document.getElementById("ss-unsplash").checked,
      youtube_audio: {
        enabled: true,
        output_mode: document.getElementById("ss-yt-output-mode")?.value || "auto",
        auto_play_on_screensaver: document.getElementById("ss-yt-autoplay").checked,
        volume: parseInt(document.getElementById("ss-yt-vol").value || "50"),
        preset_streams: adminConfig?.screensaver?.youtube_audio?.preset_streams || []
      },
      widgets: {
        show_clock: document.getElementById("ss-w-clock").checked,
        show_weather: document.getElementById("ss-w-weather").checked,
        show_device_summaries: document.getElementById("ss-w-devices").checked,
        show_system_telemetry: document.getElementById("ss-w-telemetry").checked
      }
    },
    weather: {
      latitude: parseFloat(document.getElementById("weather-lat").value || "51.5074"),
      longitude: parseFloat(document.getElementById("weather-lon").value || "-0.1278"),
      units: document.getElementById("weather-units").value || "celsius"
    }
  };

  try {
    const res = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (res.ok) {
      showToast("🎉 Configuration saved and hot-reloaded successfully!");
      await loadAdminConfig();
    } else {
      const err = await res.json();
      showToast(`Error: ${err.detail || 'Failed to save config'}`);
    }
  } catch (err) {
    showToast(`Save error: ${err.message}`);
  } finally {
    if (saveBtn) saveBtn.textContent = "💾 Save All Configuration & Apply";
  }
}


// ---------------------------------------------------------------------------
// Raspberry Pi controls (Wi-Fi, Bluetooth, desktop, power) - only usable on the Pi's own screen
// ---------------------------------------------------------------------------

async function piApi(path, body) {
  const opts = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const res = await fetch(`/api/pi/${path}`, opts);
  let data = {};
  try { data = await res.json(); } catch (e) { /* non-JSON error page */ }
  if (res.status === 403) {
    const note = document.getElementById("pi-remote-note");
    const controls = document.getElementById("pi-controls");
    if (note) note.style.display = "block";
    if (controls) controls.style.display = "none";
    throw new Error("Only available on the Raspberry Pi's own screen");
  }
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
  return data;
}

async function piAction(path, body, busyBtn) {
  if (busyBtn) busyBtn.disabled = true;
  try {
    const data = await piApi(path, body);
    showToast(data.message || (data.ok ? "Done" : "Failed"), data.ok ? 3000 : 6000);
    return data;
  } catch (e) {
    showToast(e.message, 5000);
    return null;
  } finally {
    if (busyBtn) busyBtn.disabled = false;
  }
}

async function refreshPiStatus() {
  try {
    const st = await piApi("status");
    const wifiBox = document.getElementById("pi-wifi-toggle");
    const btBox = document.getElementById("pi-bt-toggle");
    const cur = document.getElementById("pi-wifi-current");
    wifiBox.disabled = !st.wifi.available;
    wifiBox.checked = Boolean(st.wifi.enabled);
    cur.textContent = !st.wifi.available ? `(${st.wifi.message})` : st.wifi.ssid ? `· ${st.wifi.ssid} (${st.wifi.signal}%)` : st.wifi.enabled ? "· not connected" : "· off";
    btBox.disabled = !st.bluetooth.available;
    btBox.checked = Boolean(st.bluetooth.powered);
    document.getElementById("pi-bt-note").textContent = st.bluetooth.available
      ? "Turning it off disconnects the speaker used for audio."
      : st.bluetooth.message;
  } catch (e) { /* 403 already handled in piApi */ }
}

function renderWifiList(networks) {
  const list = document.getElementById("pi-wifi-list");
  list.innerHTML = networks.length ? "" : `<div class="form-hint">No networks found</div>`;
  networks.forEach(n => {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "device-toggle-btn" + (n.in_use ? " is-on" : "");
    row.style.cssText = "padding: 10px 14px; font-size: 14px; justify-content: space-between;";
    const name = document.createElement("span");
    name.textContent = `${n.secured ? "🔒" : "🔓"} ${n.ssid}`;
    const sig = document.createElement("span");
    sig.textContent = `${n.signal}%`;
    row.append(name, sig);
    row.onclick = () => {
      document.getElementById("pi-wifi-ssid").value = n.ssid;
      document.getElementById("pi-wifi-password").focus();
    };
    list.appendChild(row);
  });
}

function initPiControls() {
  const tab = document.querySelector('.admin-tab-btn[data-tab="pi"]');
  if (!tab) return;
  tab.addEventListener("click", () => refreshPiStatus());

  document.getElementById("pi-wifi-toggle").addEventListener("change", async (e) => {
    const box = e.target;
    const want = box.checked;
    if (!want && !confirm("Turn Wi-Fi off? If this Pi is only connected by Wi-Fi it will disappear from the network.")) { box.checked = true; return; }
    const r = await piAction("wifi/power", { on: want }, box);
    if (!r || !r.ok) box.checked = !want;
    refreshPiStatus();
  });

  document.getElementById("pi-wifi-scan").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    btn.textContent = "🔍 Scanning...";
    const r = await piAction("wifi/scan", {}, btn);
    btn.textContent = "🔍 Scan networks";
    if (r && r.ok) renderWifiList(r.networks || []);
  });

  document.getElementById("pi-wifi-connect").addEventListener("click", async (e) => {
    const ssid = document.getElementById("pi-wifi-ssid").value.trim();
    const pw = document.getElementById("pi-wifi-password");
    if (!ssid) { showToast("Pick or type a network name first"); return; }
    showToast(`Connecting to ${ssid}...`);
    const r = await piAction("wifi/connect", { ssid, password: pw.value }, e.currentTarget);
    if (r && r.ok) pw.value = "";
    refreshPiStatus();
  });

  document.getElementById("pi-bt-toggle").addEventListener("change", async (e) => {
    const box = e.target;
    const want = box.checked;
    const r = await piAction("bluetooth/power", { on: want }, box);
    if (!r || !r.ok) box.checked = !want;
    refreshPiStatus();
  });

  document.getElementById("pi-open-desktop").addEventListener("click", async (e) => {
    const minutes = parseInt(document.getElementById("pi-desktop-minutes").value, 10);
    if (!confirm(`Close the dashboard and show the desktop? It comes back automatically in ${minutes} min.`)) return;
    await piAction("desktop", { minutes }, e.currentTarget);
  });

  document.getElementById("pi-restart-kiosk").addEventListener("click", (e) => piAction("restart-kiosk", {}, e.currentTarget));
  document.getElementById("pi-restart-app").addEventListener("click", (e) => {
    if (confirm("Restart HomeAuto? The dashboard reloads in a few seconds.")) piAction("restart-app", {}, e.currentTarget);
  });
  document.getElementById("pi-reboot").addEventListener("click", (e) => {
    if (confirm("Reboot the Raspberry Pi now?")) piAction("power", { action: "reboot" }, e.currentTarget);
  });
  document.getElementById("pi-shutdown").addEventListener("click", (e) => {
    if (confirm("Shut down the Raspberry Pi? It must be unplugged and plugged back in to start again.")) piAction("power", { action: "shutdown" }, e.currentTarget);
  });
}

document.addEventListener("DOMContentLoaded", initPiControls);
