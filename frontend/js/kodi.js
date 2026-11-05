// Kodi Integration & Touch Remote Controller

function initKodiController() {
  const launchBtn = document.getElementById("btn-launch-kodi");
  const playPauseBtn = document.getElementById("btn-kodi-playpause");
  const stopBtn = document.getElementById("btn-kodi-stop");

  if (launchBtn) {
    launchBtn.addEventListener("click", async () => {
      launchBtn.textContent = "Launching Kodi...";
      try {
        const res = await fetch("/api/kodi/launch", { method: "POST" });
        if (res.ok) {
          showToast("Kodi started successfully");
        } else {
          showToast("Failed to launch Kodi");
        }
      } catch (e) {
        showToast("Error starting Kodi");
      } finally {
        launchBtn.textContent = "🎬 Launch Kodi on TV/Screen";
      }
    });
  }

  if (playPauseBtn) {
    playPauseBtn.addEventListener("click", () => fetch("/api/kodi/play_pause", { method: "POST" }));
  }

  if (stopBtn) {
    stopBtn.addEventListener("click", () => fetch("/api/kodi/stop", { method: "POST" }));
  }

  // D-Pad Remote buttons
  const dpadButtons = document.querySelectorAll(".dpad-btn[data-action]");
  dpadButtons.forEach(btn => {
    btn.addEventListener("click", () => {
      const action = btn.dataset.action;
      sendKodiInput(action);
    });
  });
}

async function sendKodiInput(action) {
  try {
    await fetch("/api/kodi/input", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action })
    });
  } catch (e) {
    console.debug("Kodi input error:", e);
  }
}

function renderKodiStatus(kodi) {
  const statusBadge = document.getElementById("kodi-status-badge");
  const nowPlayingEl = document.getElementById("kodi-now-playing");
  const bannerTitle = document.getElementById("kodi-banner-title");

  if (statusBadge) {
    statusBadge.textContent = kodi.online ? (kodi.playing ? "▶ Playing" : "● Online") : "○ Offline";
    statusBadge.style.color = kodi.online ? "var(--accent-green)" : "var(--text-muted)";
  }

  let title = "Nothing Playing";
  if (kodi.item) {
    title = kodi.item.title || kodi.item.label || "Media Playing";
    if (kodi.item.showtitle) {
      title = `${kodi.item.showtitle} - S${kodi.item.season}E${kodi.item.episode}: ${title}`;
    }
  }

  if (nowPlayingEl) nowPlayingEl.textContent = title;
  if (bannerTitle) bannerTitle.textContent = kodi.online ? (kodi.playing ? `Kodi: ${title}` : "Kodi Ready") : "Kodi Offline";
}
