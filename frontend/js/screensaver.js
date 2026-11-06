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

  // Start photo carousel
  showNextPhoto();
  clearInterval(photoCarouselInterval);
  photoCarouselInterval = setInterval(showNextPhoto, 15000);

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
  resetIdleTimer();
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
function radioRowHtml(s, playCall) {
  const isFav = radioFavorites.some(f => f.url === s.url);
  return `
    <div style="display: flex; gap: 6px;">
      <button class="nav-btn" style="flex: 1; justify-content: flex-start; text-align: left; min-width: 0;" onclick="${playCall}">
        📻 ${escapeHtml(s.name)}${s.bitrate ? ` <span style="color: var(--text-muted); font-size: 11px;">&nbsp;${s.bitrate}k</span>` : ""}
      </button>
      <button class="nav-btn" style="width: 48px; justify-content: center; font-size: 20px; ${isFav ? "color: #facc15;" : "opacity: 0.55;"}"
        onclick="toggleRadioFavorite(this.dataset.url, this.dataset.name)" data-url="${escapeHtml(s.url)}" data-name="${escapeHtml(s.name)}">${isFav ? "★" : "☆"}</button>
    </div>`;
}

function renderRadioFavorites() {
  const wrap = document.getElementById("radio-favorites-wrap");
  const list = document.getElementById("radio-favorites-list");
  if (!wrap || !list) return;
  wrap.style.display = radioFavorites.length ? "block" : "none";
  list.innerHTML = radioFavorites.map((s, idx) => radioRowHtml(s, `playRadioFavorite(${idx})`)).join("");
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

async function loadRadioStations(query) {
  const statusEl = document.getElementById("radio-status");
  const listEl = document.getElementById("radio-stations-list");
  if (!listEl) return;
  if (statusEl) statusEl.textContent = "Loading stations...";
  try {
    const res = await fetch(`/api/radio/stations?country=BG&q=${encodeURIComponent(query)}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    radioStations = await res.json();
    if (statusEl) statusEl.textContent = `${radioStations.length} station${radioStations.length === 1 ? "" : "s"}`;
    renderRadioStations();
  } catch (e) {
    if (statusEl) statusEl.textContent = "Radio directory unavailable (check the internet connection)";
    listEl.innerHTML = "";
  }
}

function playRadioStation(index) {
  const s = radioStations[index];
  if (!s) return;
  fetch("/api/media/play", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url: s.url, title: s.name, direct: true })
  });
  showToast(`Playing radio: ${s.name}`);
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
