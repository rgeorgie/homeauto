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
          body: JSON.stringify({ url: state.media.url, title: state.media.title })
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
