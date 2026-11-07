// Push history: what Tuya's message service pushed (rings, SOS presses, doors opening, online / offline, ...).
// The backend keeps the list; new entries arrive over the websocket.

let pushEntries = [];
let pushOpen = false;

function formatPushTime(ts) {
  const d = new Date(ts * 1000);
  const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  return d.toDateString() === new Date().toDateString() ? time : `${d.toLocaleDateString([], { month: "short", day: "numeric" })} ${time}`;
}

function renderPushHistory() {
  const list = document.getElementById("push-history-list");
  if (!list) return;
  document.getElementById("push-history-count").textContent = pushEntries.length ? `(${pushEntries.length})` : "";
  document.getElementById("push-history-arrow").textContent = pushOpen ? "▾" : "▸";
  document.getElementById("btn-clear-push-history").style.display = pushOpen && pushEntries.length ? "inline-block" : "none";
  list.style.display = pushOpen ? "block" : "none";
  if (!pushOpen) return;
  list.innerHTML = pushEntries.length
    ? pushEntries.map(e => `
        <div style="display: flex; gap: 12px; padding: 6px 0; border-top: 1px solid var(--border-color);">
          <span style="color: var(--text-muted); min-width: 118px;">${escapeHtml(formatPushTime(e.ts))}</span>
          <span style="font-weight: 600; min-width: 130px;">${escapeHtml(e.dev_name)}</span>
          <span>${escapeHtml(e.text)}</span>
        </div>`).join("")
    : `<div style="color: var(--text-muted); padding: 6px 0;">Nothing pushed yet. Needs "Instant updates" (realtime_messages) to be on.</div>`;
}

// Called by app.js for every pushed "push_event" message
function onPushEvent(entry) {
  if (!entry || pushEntries.some(e => e.id === entry.id)) return;
  pushEntries.unshift(entry);
  pushEntries.length = Math.min(pushEntries.length, 200);
  renderPushHistory();
}

async function loadPushHistory() {
  try {
    const res = await fetch("/api/push-history");
    if (res.ok) { pushEntries = await res.json(); renderPushHistory(); }
  } catch (e) { /* stays empty until the next push */ }
}

function initPushHistory() {
  const toggle = document.getElementById("btn-toggle-push-history");
  if (!toggle) return;
  toggle.onclick = () => { pushOpen = !pushOpen; renderPushHistory(); };
  document.getElementById("btn-clear-push-history").onclick = async () => {
    if (!confirm("Delete the push history?")) return;
    await fetch("/api/push-history", { method: "DELETE" });
    pushEntries = [];
    renderPushHistory();
  };
  loadPushHistory();
}

document.addEventListener("DOMContentLoaded", initPushHistory);
