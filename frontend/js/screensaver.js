// Screensaver & Ambient Display Engine

let screensaverTimeout = null;
let photoCarouselInterval = null;
let currentPhotoIndex = 0;
let photosList = [];
let isScreensaverActive = false;
let idleTimeoutMs = 120000; // default 2 minutes

function initScreensaverEngine() {
  const overlay = document.getElementById("screensaver-overlay");
  const manualBtn = document.getElementById("btn-trigger-screensaver");

  if (manualBtn) {
    manualBtn.addEventListener("click", () => startScreensaver());
  }

  if (overlay) {
    overlay.addEventListener("click", () => stopScreensaver());
    overlay.addEventListener("touchstart", () => stopScreensaver());
  }

  // Reset idle timer on any user touch/interaction
  const interactionEvents = ["touchstart", "touchend", "mousedown", "mousemove", "keydown", "click"];
  interactionEvents.forEach(evt => {
    window.addEventListener(evt, () => resetIdleTimer(), { passive: true });
  });

  resetIdleTimer();
  initMediaControls();
}

function updateScreensaverConfig(config) {
  if (!config) return;
  if (config.idle_timeout_seconds) {
    idleTimeoutMs = config.idle_timeout_seconds * 1000;
  }
  if (config.photos && config.photos.length > 0) {
    photosList = config.photos;
  }
  resetIdleTimer();
}

function resetIdleTimer() {
  if (isScreensaverActive) return; // don't restart timer while already in screensaver
  clearTimeout(screensaverTimeout);
  screensaverTimeout = setTimeout(() => {
    startScreensaver();
  }, idleTimeoutMs);
}

function startScreensaver() {
  const overlay = document.getElementById("screensaver-overlay");
  if (!overlay) return;

  isScreensaverActive = true;
  overlay.classList.add("active");

  clearInterval(photoCarouselInterval);
  if (state.screensaver?.mode === "fireplace") {
    overlay.classList.add("fireplace");
    startFireplace();
  } else {
    overlay.classList.remove("fireplace");
    // Start photo carousel
    showNextPhoto();
    photoCarouselInterval = setInterval(showNextPhoto, 15000);
  }

  // If YouTube auto-play configured, trigger preset
  if (state.screensaver?.youtube_audio?.auto_play_on_screensaver && !state.media.is_playing) {
    playPresetStream(0);
  }
}

function stopScreensaver() {
  const overlay = document.getElementById("screensaver-overlay");
  if (!overlay) return;

  isScreensaverActive = false;
  overlay.classList.remove("active");
  clearInterval(photoCarouselInterval);
  stopFireplace();
  resetIdleTimer();
}

// Live fireplace: a low-resolution heat buffer (the classic "fire" cellular effect),
// painted to a small canvas that CSS scales up. Cheap enough for a Raspberry Pi.
const FIRE_W = 192;
const FIRE_H = 108;
let fireTimer = null;
let fireHeat = null;
let fireImage = null;
let firePalette = null;

function buildFirePalette() {
  const pal = new Uint8ClampedArray(256 * 4);
  for (let h = 0; h < 256; h++) {
    pal[h * 4] = h * 3;                    // red rises first
    pal[h * 4 + 1] = (h - 70) * 2.2;       // then orange/yellow
    pal[h * 4 + 2] = (h - 200) * 4;        // only the hottest core turns white
    pal[h * 4 + 3] = h * 2.6;              // cool cells fade to transparent
  }
  return pal;
}

function startFireplace() {
  const canvas = document.getElementById("screensaver-fire-canvas");
  if (!canvas) return;
  canvas.width = FIRE_W;
  canvas.height = FIRE_H;
  const ctx = canvas.getContext("2d");
  fireHeat = new Uint8Array(FIRE_W * FIRE_H);
  fireImage = ctx.createImageData(FIRE_W, FIRE_H);
  firePalette = firePalette || buildFirePalette();

  clearInterval(fireTimer);
  fireTimer = setInterval(() => {
    stepFire(performance.now() / 1000);
    ctx.putImageData(fireImage, 0, 0);
  }, 40); // ~25 fps
}

function stopFireplace() {
  clearInterval(fireTimer);
  fireTimer = null;
}

function stepFire(t) {
  const w = FIRE_W, h = FIRE_H;
  const heat = fireHeat;

  // Fuel row: a bright centre tapering to the edges, flickering and slowly swaying
  const centre = w / 2 + Math.sin(t * 0.7) * 4;
  const half = w * 0.17;
  const base = (h - 1) * w;
  for (let x = 0; x < w; x++) {
    const d = Math.abs(x - centre) / half;
    heat[base + x] = d >= 1 ? 0 : Math.min(255, 255 * (1 - d * d) * (0.75 + Math.random() * 0.25));
  }

  // Propagate upwards with random cooling and sideways drift (wind follows the sway)
  const wind = Math.sin(t * 0.9) * 0.6;
  for (let y = 1; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const src = heat[y * w + x];
      let dx = ((Math.random() * 3) | 0) - 1 + (Math.random() < Math.abs(wind) ? Math.sign(wind) : 0);
      let dst = x + dx;
      if (dst < 0) dst = 0; else if (dst >= w) dst = w - 1;
      const v = src - ((Math.random() * 9) | 0);
      heat[(y - 1) * w + dst] = v > 0 ? v : 0;
    }
  }

  const px = fireImage.data;
  for (let i = 0, n = w * h; i < n; i++) {
    const p = heat[i] * 4;
    const o = i * 4;
    px[o] = firePalette[p];
    px[o + 1] = firePalette[p + 1];
    px[o + 2] = firePalette[p + 2];
    px[o + 3] = firePalette[p + 3];
  }
}

function showNextPhoto() {
  if (!photosList || photosList.length === 0) return;
  const bg = document.getElementById("screensaver-bg");
  if (!bg) return;

  currentPhotoIndex = (currentPhotoIndex + 1) % photosList.length;
  const nextUrl = photosList[currentPhotoIndex];

  // Preload and smooth crossfade
  const img = new Image();
  img.src = nextUrl;
  img.onload = () => {
    bg.style.backgroundImage = `url('${nextUrl}')`;
    bg.classList.add("visible");
  };
}

// Media Player & YouTube Audio Controls
function initMediaControls() {
  const playBtn = document.getElementById("btn-media-toggle");
  const stopBtn = document.getElementById("btn-media-stop");
  const customUrlInput = document.getElementById("media-custom-url");
  const customPlayBtn = document.getElementById("btn-play-custom-url");
  const volSlider = document.getElementById("media-volume-slider");

  if (playBtn) {
    playBtn.addEventListener("click", () => {
      if (state.media.is_playing) {
        fetch("/api/media/pause", { method: "POST" });
      } else if (state.media.url) {
        fetch("/api/media/play", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url: state.media.url, title: state.media.title, direct: !!state.media.direct })
        });
      } else {
        playPresetStream(0);
      }
    });
  }

  if (stopBtn) {
    stopBtn.addEventListener("click", () => fetch("/api/media/stop", { method: "POST" }));
  }

  if (customPlayBtn && customUrlInput) {
    customPlayBtn.addEventListener("click", () => {
      const url = customUrlInput.value.trim();
      if (url) {
        fetch("/api/media/play", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url, title: "Custom YouTube Audio" })
        });
      }
    });
  }

  if (volSlider) {
    volSlider.addEventListener("input", (e) => {
      const vol = parseInt(e.target.value);
      fetch("/api/media/volume", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ volume: vol })
      });
    });
  }

  initRadio();
}

// Online radio (Bulgarian stations from the radio-browser.info directory)
let radioStations = [];
let radioFavorites = [];
let radioSearchTimer = null;

function initRadio() {
  const search = document.getElementById("radio-search");
  if (!search) return;
  search.addEventListener("input", () => {
    clearTimeout(radioSearchTimer);
    radioSearchTimer = setTimeout(() => loadRadioStations(search.value.trim()), 400);
  });
  loadRadioFavorites().then(() => loadRadioStations(""));
}

async function loadRadioFavorites() {
  try {
    const res = await fetch("/api/radio/favorites");
    if (res.ok) radioFavorites = await res.json();
  } catch (e) {
    console.error("Radio favourites error:", e);
  }
  renderRadioFavorites();
}

// One station row: a play button plus a star that adds/removes it from the favourites
function radioAttr(str) {
  return escapeHtml(str || "").replace(/"/g, "&quot;");
}

function radioRowHtml(s, playCall) {
  const isFav = radioFavorites.some(f => f.url === s.url);
  return `
    <div style="display: flex; gap: 6px;">
      <button class="nav-btn" style="flex: 1; justify-content: flex-start; text-align: left; min-width: 0;" onclick="${playCall}">
        📻 ${escapeHtml(s.name)}${s.bitrate ? ` <span style="color: var(--text-muted); font-size: 11px;">&nbsp;${s.bitrate}k</span>` : ""}
      </button>
      <button class="nav-btn" style="width: 48px; justify-content: center; font-size: 20px; ${isFav ? "color: #facc15;" : "opacity: 0.55;"}"
        onclick="toggleRadioFavorite(this.dataset.url, this.dataset.name)" data-url="${radioAttr(s.url)}" data-name="${radioAttr(s.name)}">${isFav ? "★" : "☆"}</button>
    </div>`;
}

function renderRadioFavorites() {
  renderBannerRadio();
  const wrap = document.getElementById("radio-favorites-wrap");
  const list = document.getElementById("radio-favorites-list");
  if (!wrap || !list) return;
  wrap.style.display = radioFavorites.length ? "block" : "none";
  list.innerHTML = radioFavorites.map((s, idx) => radioRowHtml(s, `playRadioFavorite(${idx})`)).join("");
}

// Dashboard banner: favourite stations as one-tap chips, the playing one highlighted, plus a "running" status line
function renderBannerRadio() {
  const box = document.getElementById("banner-radio");
  const statusEl = document.getElementById("banner-radio-status");
  const chips = document.getElementById("banner-radio-favorites");
  if (!box || !statusEl || !chips) return;

  const media = state.media || {};
  const radioPlaying = !!(media.is_playing && media.direct);
  box.style.display = radioPlaying || radioFavorites.length ? "block" : "none";
  statusEl.textContent = radioPlaying ? `📻 Radio running: ${media.title}` : "📻 Radio stopped";
  statusEl.style.color = radioPlaying ? "#86efac" : "rgba(255,255,255,0.8)";

  // Rebuild only when something changed, so a tap is never lost to the 3-second state refresh
  const sig = JSON.stringify([radioFavorites.map(f => f.url), radioPlaying ? media.url : ""]);
  if (chips.dataset.sig === sig) return;
  chips.dataset.sig = sig;
  chips.innerHTML = radioFavorites.map((s, idx) => {
    const on = radioPlaying && media.url === s.url;
    return `<button class="action-btn" onclick="toggleBannerFavorite(${idx})" style="padding: 8px 14px; font-size: 13px; ${on ? "background: linear-gradient(135deg, #16a34a, #15803d);" : "background: rgba(255,255,255,0.1);"}">${on ? "⏹" : "▶"} ${escapeHtml(s.name)}</button>`;
  }).join("");
}

function toggleBannerFavorite(index) {
  const s = radioFavorites[index];
  if (!s) return;
  const media = state.media || {};
  if (media.is_playing && media.direct && media.url === s.url) {
    fetch("/api/media/stop", { method: "POST" });
  } else {
    playRadioUrl(s.url, s.name);
  }
}

function renderRadioStations() {
  const listEl = document.getElementById("radio-stations-list");
  if (!listEl) return;
  listEl.innerHTML = radioStations.length
    ? radioStations.map((s, idx) => radioRowHtml(s, `playRadioStation(${idx})`)).join("")
    : `<div style="color: var(--text-muted); padding: 10px;">No stations found.</div>`;
}

async function toggleRadioFavorite(url, name) {
  const isFav = radioFavorites.some(f => f.url === url);
  try {
    const res = await fetch(isFav ? "/api/radio/favorites/remove" : "/api/radio/favorites", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, name })
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    radioFavorites = await res.json();
    showToast(isFav ? `Removed from favourites: ${name}` : `Added to favourites: ${name}`);
    renderRadioFavorites();
    renderRadioStations();
  } catch (e) {
    showToast("Could not update favourites", 2000);
  }
}

function playRadioFavorite(index) {
  const s = radioFavorites[index];
  if (s) playRadioUrl(s.url, s.name);
}

let radioLoadSeq = 0;

async function loadRadioStations(query) {
  const statusEl = document.getElementById("radio-status");
  const listEl = document.getElementById("radio-stations-list");
  if (!listEl) return;
  const seq = ++radioLoadSeq; // a slow older search must not overwrite a newer one
  if (statusEl) statusEl.textContent = "Loading stations...";
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 20000);
  try {
    const res = await fetch(`/api/radio/stations?country=BG&q=${encodeURIComponent(query)}`, { signal: ctrl.signal });
    if (!res.ok) {
      let detail = "";
      try { detail = (await res.json()).detail || ""; } catch (_) {}
      throw new Error(detail || `HTTP ${res.status}`);
    }
    const stations = await res.json();
    if (seq !== radioLoadSeq) return;
    radioStations = stations;
    if (statusEl) statusEl.textContent = `${radioStations.length} station${radioStations.length === 1 ? "" : "s"}`;
    renderRadioStations();
  } catch (e) {
    if (seq !== radioLoadSeq) return;
    const reason = e.name === "AbortError" ? "no answer from the server" : e.message;
    if (statusEl) statusEl.textContent = `Radio directory unavailable: ${reason}`;
    listEl.innerHTML = "";
  } finally {
    clearTimeout(timer);
  }
}

function playRadioUrl(url, name) {
  fetch("/api/media/play", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, title: name, direct: true })
  });
  showToast(`Playing radio: ${name}`);
}

function playRadioStation(index) {
  const s = radioStations[index];
  if (s) playRadioUrl(s.url, s.name);
}

function playPresetStream(index) {
  const presets = state.media?.presets || state.screensaver?.youtube_audio?.preset_streams;
  if (presets && presets[index]) {
    const p = presets[index];
    fetch("/api/media/play", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: p.url, title: p.title })
    });
    showToast(`Playing stream: ${p.title}`);
  }
}

function renderMediaStatus(media) {
  const titleEl = document.getElementById("media-track-title");
  const statusEl = document.getElementById("media-play-status");
  const toggleBtn = document.getElementById("btn-media-toggle");
  const volSlider = document.getElementById("media-volume-slider");

  if (titleEl) titleEl.textContent = media.title || "No stream playing";
  if (statusEl) statusEl.textContent = media.is_playing ? "Playing" : "Stopped";
  if (toggleBtn) toggleBtn.textContent = media.is_playing ? "⏸ Pause" : "▶ Play";
  if (volSlider && media.volume !== undefined) volSlider.value = media.volume;

  renderBannerRadio();

  // Screensaver: show what is playing (hidden when nothing plays)
  const nowCard = document.getElementById("ss-now-playing");
  if (nowCard) {
    nowCard.style.display = media.is_playing && media.title ? "flex" : "none";
    const nowTitle = document.getElementById("ss-now-playing-title");
    const nowIcon = document.getElementById("ss-now-playing-icon");
    if (nowTitle) nowTitle.textContent = media.title || "";
    if (nowIcon) nowIcon.textContent = media.direct ? "📻" : "🎵";
  }

  // Render presets list
  const presetContainer = document.getElementById("media-presets-list");
  if (presetContainer && media.presets) {
    presetContainer.innerHTML = media.presets.map((p, idx) => `
      <button class="nav-btn" style="width: 100%; justify-content: flex-start; margin-bottom: 8px;" onclick="playPresetStream(${idx})">
        🎵 ${escapeHtml(p.title)}
      </button>
    `).join("");
  }
}
