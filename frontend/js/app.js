// Core HomeAuto Client Application
const state = {
  devices: [],
  bluetooth: { connected: false, name: "Surround Sound", volume: 70 },
  kodi: { online: false, playing: false, item: null },
  system: { cpu_percent: 0, cpu_temp: 0, memory_percent: 0 },
  media: { is_playing: false, title: "", url: "", presets: [] },
  screensaver: null,
  weather: null,
  ws: null
};

document.addEventListener("DOMContentLoaded", () => {
  initDragScroll();
  initClock();
  initNavigation();
  initWebSocket();
  initWeather();
  initScreensaverEngine();
  initKodiController();
  initBluetoothController();
  initTuyaCards();
});

// Drag-to-scroll fallback: some touchscreens reach the browser as a mouse, so a swipe
// is a click-drag and never scrolls. Real touch input is left to the browser.
function initDragScroll() {
  const THRESHOLD = 8;
  let drag = null;
  let suppressClick = false;

  const scrollableParent = (el) => {
    for (; el && el !== document.body; el = el.parentElement) {
      const oy = getComputedStyle(el).overflowY;
      if ((oy === "auto" || oy === "scroll") && el.scrollHeight > el.clientHeight) return el;
    }
    return document.scrollingElement;
  };

  document.addEventListener("pointerdown", (e) => {
    if (e.pointerType !== "mouse" || e.button !== 0) return;
    if (e.target.closest("input, select, textarea, .touch-slider")) return;
    drag = { x: e.clientX, y: e.clientY, target: scrollableParent(e.target), moved: false,
             left: 0, top: 0 };
    drag.left = drag.target.scrollLeft;
    drag.top = drag.target.scrollTop;
  });

  document.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.x;
    const dy = e.clientY - drag.y;
    if (!drag.moved && Math.hypot(dx, dy) < THRESHOLD) return;
    drag.moved = true;
    drag.target.scrollLeft = drag.left - dx;
    drag.target.scrollTop = drag.top - dy;
  });

  const end = () => {
    if (drag && drag.moved) {
      suppressClick = true;
      setTimeout(() => { suppressClick = false; }, 0);
    }
    drag = null;
  };
  document.addEventListener("pointerup", end);
  document.addEventListener("pointercancel", end);

  // A scroll-swipe must not also press the button it ended on
  document.addEventListener("click", (e) => {
    if (suppressClick) { e.stopPropagation(); e.preventDefault(); }
  }, true);
}

// Navigation Router
function initNavigation() {
  const navButtons = document.querySelectorAll(".nav-btn");
  navButtons.forEach(btn => {
    btn.addEventListener("click", () => {
      const targetView = btn.dataset.view;
      switchView(targetView);
    });
  });
}

function switchView(viewId) {
  document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));
  document.querySelectorAll(".view-section").forEach(v => v.classList.remove("active"));

  const targetBtn = document.querySelector(`.nav-btn[data-view="${viewId}"]`);
  const targetSection = document.getElementById(`view-${viewId}`);

  if (targetBtn) targetBtn.classList.add("active");
  if (targetSection) targetSection.classList.add("active");
}

// Clock & Date updater
function initClock() {
  function updateTime() {
    const now = new Date();
    const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const dateStr = now.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' });

    const headerTime = document.getElementById("header-time");
    const headerDate = document.getElementById("header-date");
    if (headerTime) headerTime.textContent = timeStr;
    if (headerDate) headerDate.textContent = dateStr;

    const ssTime = document.getElementById("ss-clock");
    const ssDate = document.getElementById("ss-date");
    if (ssTime) ssTime.textContent = timeStr;
    if (ssDate) ssDate.textContent = dateStr;
  }
  updateTime();
  setInterval(updateTime, 1000);
}

// WebSocket Connection
function initWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/ws`;

  function connect() {
    state.ws = new WebSocket(wsUrl);

    state.ws.onopen = () => {
      console.log("Connected to HomeAuto WebSocket hub.");
      updateStatusPill(true);
    };

    state.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === "state_update" || msg.type === "initial_state") {
          applyStateUpdate(msg.data);
        }
      } catch (err) {
        console.error("WebSocket message parse error:", err);
      }
    };

    state.ws.onclose = () => {
      console.warn("WebSocket disconnected. Reconnecting in 3s...");
      updateStatusPill(false);
      setTimeout(connect, 3000);
    };

    state.ws.onerror = (err) => {
      console.error("WebSocket error:", err);
      state.ws.close();
    };
  }

  connect();
}

function updateStatusPill(online) {
  const dot = document.getElementById("ws-status-dot");
  const text = document.getElementById("ws-status-text");
  if (dot && text) {
    dot.className = `status-dot ${online ? '' : 'disconnected'}`;
    text.textContent = online ? "Online" : "Connecting...";
  }
}

function applyStateUpdate(data) {
  if (data.devices) {
    state.devices = data.devices;
    renderTuyaDevices(state.devices);
    if (typeof checkDoorbellRings === "function") checkDoorbellRings(state.devices);
    updateAmbientDeviceSummary(state.devices);
  }
  if (data.bluetooth) {
    state.bluetooth = data.bluetooth;
    renderBluetoothStatus(state.bluetooth);
  }
  if (data.kodi) {
    state.kodi = data.kodi;
    renderKodiStatus(state.kodi);
  }
  if (data.system) {
    state.system = data.system;
    renderSystemTelemetry(state.system);
  }
  if (data.media) {
    state.media = data.media;
    renderMediaStatus(state.media);
  }
  if (data.screensaver) {
    state.screensaver = data.screensaver;
    updateScreensaverConfig(state.screensaver);
  }
}

// Weather fetcher
async function initWeather() {
  async function fetchWeather() {
    try {
      const res = await fetch("/api/weather");
      if (res.ok) {
        state.weather = await res.json();
        renderWeather(state.weather);
      }
    } catch (e) {
      console.debug("Weather load error:", e);
    }
  }
  fetchWeather();
  setInterval(fetchWeather, 600000); // 10 mins
}

function renderWeather(w) {
  if (!w) return;
  const tempEls = document.querySelectorAll(".live-weather-temp");
  tempEls.forEach(el => el.textContent = `${Math.round(w.temperature)}${w.units || '°C'}`);

  const descEls = document.querySelectorAll(".live-weather-desc");
  descEls.forEach(el => el.textContent = `Humidity: ${w.humidity}% | Wind: ${w.wind_speed} km/h`);
}

function renderSystemTelemetry(sys) {
  const cpuEl = document.getElementById("telemetry-cpu");
  const tempEl = document.getElementById("telemetry-temp");
  const memEl = document.getElementById("telemetry-mem");
  const ipEl = document.getElementById("telemetry-ip");

  if (cpuEl) cpuEl.textContent = `${sys.cpu_percent}%`;
  if (tempEl) tempEl.textContent = `${sys.cpu_temp}°C`;
  if (memEl) memEl.textContent = `${sys.memory_percent}% (${sys.memory_used_mb}MB)`;
  if (ipEl) ipEl.textContent = sys.local_ip || "127.0.0.1";

  // Screensaver ambient system badge
  const ssTemp = document.getElementById("ss-cpu-temp");
  if (ssTemp) ssTemp.textContent = `${sys.cpu_temp}°C`;
}

// Toast Alert Utility
function showToast(message, duration = 3000) {
  let container = document.getElementById("toast-container");
  if (!container) {
    container = document.createElement("div");
    container.id = "toast-container";
    container.className = "toast-container";
    document.body.appendChild(container);
  }

  const toast = document.createElement("div");
  toast.className = "toast";
  toast.textContent = message;
  container.appendChild(toast);

  setTimeout(() => {
    toast.remove();
  }, duration);
}
