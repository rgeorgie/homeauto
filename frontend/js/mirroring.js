// Screen mirroring (AirPlay via RPiPlay) - dashboard button.
// Only offered on the Pi's own screen: the all-in-one install (page served from localhost) or a kiosk-only install,
// where the request goes to the local Pi agent (see bt_audio.js: btUrl / BT_USE_AGENT / BT_PAGE_IS_LOCAL).
// Starting the mirroring service closes the kiosk browser so the mirrored screen is visible; it comes back
// when the mirroring stops (see the homeauto-rpiplay.service installed by install.sh).
document.addEventListener("DOMContentLoaded", () => {
  const btn = document.getElementById("btn-start-mirroring");
  if (!btn) return;
  if (!BT_USE_AGENT && !BT_PAGE_IS_LOCAL) {
    btn.style.display = "none";
    return;
  }
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    showToast("Starting screen mirroring...", 3000);
    try {
      const res = await fetch(btUrl("/api/pi/rpiplay/start"), { method: "POST", signal: AbortSignal.timeout(20000) });
      const data = await res.json().catch(() => ({}));
      if (res.status === 404 && BT_USE_AGENT) {
        showToast("The Pi agent is outdated - on the Pi run: systemctl --user restart homeauto-agent", 8000);
      } else {
        showToast(data.message || data.detail || (data.ok ? "Screen mirroring started" : `Could not start screen mirroring (HTTP ${res.status})`), data.ok ? 5000 : 10000);
      }
    } catch (e) {
      showToast(BT_USE_AGENT ? BT_AGENT_HINT : `Could not start screen mirroring: ${e.message}`, 6000);
    } finally {
      btn.disabled = false;
    }
  });
});
