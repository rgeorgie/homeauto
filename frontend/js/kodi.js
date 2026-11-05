// Kodi Integration & Touch Remote Controller

function initKodiController() {
  const launchBtn = document.getElementById("btn-launch-kodi");
  const playPauseBtn = document.getElementById("btn-kodi-playpause");
  const stopBtn = document.getElementById("btn-kodi-stop");

  if (launchBtn) {
    launchBtn.addEventListener("click", async () => {
      launchBtn.textContent = "Launching Kodi (up to 20s)...";
      launchBtn.disabled = true;
      if (await kodiPost("/api/kodi/launch")) showToast("Kodi started and responding");
      launchBtn.textContent = "🎬 Launch Kodi on TV/Screen";
      launchBtn.disabled = false;
    });
  }

  if (playPauseBtn) {
    playPauseBtn.addEventListener("click", () => kodiPost("/api/kodi/play_pause"));
  }

  if (stopBtn) {
    stopBtn.addEventListener("click", () => kodiPost("/api/kodi/stop"));
  }

  // D-Pad + Back/Home/Menu remote buttons
  const dpadButtons = document.querySelectorAll("#view-kodi [data-action]");
  dpadButtons.forEach(btn => {
    btn.addEventListener("click", () => {
      const action = btn.dataset.action;
      sendKodiInput(action);
    });
  });
}

async function kodiPost(url, body) {
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {})
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.status === "failed") {
      showToast(`Kodi: ${data.error || data.detail || "command failed"}`, 5000);
      return false;
    }
    return true;
  } catch (e) {
    showToast("Kodi: cannot reach HomeAuto server", 4000);
    return false;
  }
}

function sendKodiInput(action) {
  return kodiPost("/api/kodi/input", { action });
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
