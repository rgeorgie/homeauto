// Energy: live power of metering plugs (dashboard tile, card readout, room totals) and the Energy view
// (usage chart, per-device table, cost). The backend keeps the history; this file only draws it.

let energyRange = "day";
let energyData = null;
let energyPrice = { price_per_kwh: 0, currency: "€" };
let energyRefreshTimer = null;

const ENERGY_RANGE_LABEL = { day: "Used (24 h)", week: "Used (7 days)", month: "Used (30 days)", year: "Used (12 months)" };

function formatWatts(w) {
  if (w === null || w === undefined || isNaN(w)) return "-- W";
  return Math.abs(w) >= 1000 ? `${(w / 1000).toFixed(2)} kW` : `${Math.round(w)} W`;
}

function formatKwh(k) {
  if (k === null || k === undefined || isNaN(k)) return "-- kWh";
  return `${k >= 100 ? k.toFixed(0) : k >= 10 ? k.toFixed(1) : k.toFixed(2)} kWh`;
}

function formatCost(kwh) {
  const p = energyPrice.price_per_kwh;
  return p > 0 ? `${(kwh * p).toFixed(2)} ${energyPrice.currency}` : null;
}

// Devices that report power, from the live state pushed every few seconds
function meteringDevices(devices) {
  return (devices || []).filter(d => d.power_w !== undefined && d.power_w !== null);
}

// Total draw of the shown home(s): only devices that are online count
function totalPowerWatts(devices) {
  return meteringDevices(devices).filter(d => d.online).reduce((sum, d) => sum + d.power_w, 0);
}

// Power drawn by the metering devices placed in a room (used for the floor-plan room label)
function roomPowerWatts(devices, roomName) {
  const meters = meteringDevices(devices).filter(d => d.online && (d.room || "").trim() === roomName);
  return meters.length ? meters.reduce((sum, d) => sum + d.power_w, 0) : null;
}

// Called by app.js on every state push
function onEnergyStateUpdate(devices) {
  renderDashboardPower(devices);
}

function renderDashboardPower(devices) {
  const tile = document.getElementById("dashboard-power");
  if (!tile) return;
  const selectedHome = typeof getSelectedHome === "function" ? getSelectedHome() : "__all__";
  const shown = (devices || []).filter(d => selectedHome === "__all__" || d.home === selectedHome);
  const meters = meteringDevices(shown);
  if (meters.length === 0) {
    tile.style.display = "none";
    return;
  }
  const online = meters.filter(d => d.online);
  document.getElementById("dashboard-power-value").textContent = formatWatts(totalPowerWatts(shown));
  const busiest = online.slice().sort((a, b) => b.power_w - a.power_w)[0];
  document.getElementById("dashboard-power-note").textContent = busiest && busiest.power_w > 0
    ? `Most: ${busiest.name} · ${formatWatts(busiest.power_w)}`
    : `${online.length} metering plug${online.length === 1 ? "" : "s"}`;
  tile.style.display = "";
}

function openEnergyView() {
  switchView("energy");
  loadEnergy();
}

// Power readout line for a device card; "" when the device has no meter
function powerReadoutHtml(dev) {
  if (dev.power_w === undefined || dev.power_w === null) return "";
  const parts = [`<span class="power-readout-main">⚡ ${formatWatts(dev.power_w)}</span>`];
  if (dev.voltage_v !== undefined && dev.voltage_v !== null) parts.push(`${Math.round(dev.voltage_v)} V`);
  if (dev.current_a !== undefined && dev.current_a !== null) parts.push(`${dev.current_a.toFixed(2)} A`);
  if (dev.energy_kwh !== undefined && dev.energy_kwh !== null) parts.push(`${formatKwh(dev.energy_kwh)} total`);
  return `<div class="power-readout">${parts.join(" · ")}</div>`;
}

// ---------------- Energy view ----------------

async function loadEnergy() {
  try {
    const res = await fetch(`/api/energy?range=${energyRange}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    energyData = await res.json();
    energyPrice = { price_per_kwh: energyData.price_per_kwh, currency: energyData.currency };
    renderEnergyView();
  } catch (e) {
    console.debug("Energy load error:", e);
  }
}

function renderEnergyView() {
  const d = energyData;
  if (!d) return;
  const hasMeters = d.live.length > 0;
  document.getElementById("energy-empty").style.display = hasMeters ? "none" : "block";
  document.getElementById("energy-content").style.display = hasMeters ? "" : "none";
  if (!hasMeters) return;

  document.getElementById("energy-now").textContent = formatWatts(d.total_w);
  document.getElementById("energy-used-label").textContent = ENERGY_RANGE_LABEL[d.range] || "Used";
  document.getElementById("energy-used").textContent = formatKwh(d.total_kwh);
  const cost = formatCost(d.total_kwh);
  document.getElementById("energy-cost-card").style.display = cost ? "" : "none";
  if (cost) document.getElementById("energy-cost").textContent = cost;

  renderEnergyChart(d);
  renderEnergyDevices(d);
}

function energyBucketLabel(ts, range) {
  const dt = new Date(ts * 1000);
  if (range === "day") return dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (range === "year") return dt.toLocaleDateString([], { month: "short" });
  return dt.toLocaleDateString([], { day: "numeric", month: "short" });
}

// Bar chart drawn as SVG: one bar per bucket, a few labels on the time axis
function renderEnergyChart(d) {
  const el = document.getElementById("energy-chart");
  const series = d.series || [];
  const W = 900, H = 240, padL = 46, padR = 8, padT = 10, padB = 28;
  const max = Math.max(...series.map(s => s.kwh), 0.001);
  const niceMax = niceCeil(max);
  const bw = (W - padL - padR) / Math.max(series.length, 1);
  const y = v => padT + (H - padT - padB) * (1 - v / niceMax);

  let svg = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" class="energy-svg" role="img" aria-label="Energy usage">`;
  for (let i = 0; i <= 4; i++) {
    const v = niceMax * i / 4;
    svg += `<line x1="${padL}" x2="${W - padR}" y1="${y(v)}" y2="${y(v)}" class="energy-grid"/>`;
    svg += `<text x="${padL - 6}" y="${y(v) + 4}" text-anchor="end" class="energy-axis">${v >= 10 ? v.toFixed(0) : v.toFixed(v < 1 ? 2 : 1)}</text>`;
  }
  series.forEach((s, i) => {
    const h = Math.max(0, (H - padT - padB) * s.kwh / niceMax);
    if (h > 0) {
      svg += `<rect x="${padL + i * bw + 1}" y="${H - padB - h}" width="${Math.max(bw - 2, 1)}" height="${h}" rx="2" class="energy-bar"><title>${energyBucketLabel(s.ts, d.range)}: ${formatKwh(s.kwh)}</title></rect>`;
    }
  });
  const every = Math.max(1, Math.ceil(series.length / 8));
  series.forEach((s, i) => {
    if (i % every === 0) {
      svg += `<text x="${padL + i * bw + bw / 2}" y="${H - 8}" text-anchor="middle" class="energy-axis">${energyBucketLabel(s.ts, d.range)}</text>`;
    }
  });
  svg += `</svg><div class="energy-unit">kWh per ${d.range === "day" ? "hour" : d.range === "week" ? "6 hours" : d.range === "month" ? "day" : "month"}</div>`;
  el.innerHTML = svg;
}

// Rounds up to a "nice" axis maximum (1, 2, 2.5, 5, 10 x 10^n)
function niceCeil(v) {
  const exp = Math.pow(10, Math.floor(Math.log10(v)));
  const f = v / exp;
  const nice = f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10;
  return nice * exp;
}

function renderEnergyDevices(d) {
  const el = document.getElementById("energy-devices");
  const liveById = new Map(d.live.map(x => [x.id, x]));
  const used = new Map(d.devices.map(x => [x.id, x]));
  // every metering device, also those without usage in this range yet
  const rows = d.live.map(l => ({ ...l, kwh: used.has(l.id) ? used.get(l.id).kwh : 0 }));
  d.devices.forEach(h => { if (!liveById.has(h.id)) rows.push({ ...h, power_w: null, online: false }); });
  rows.sort((a, b) => b.kwh - a.kwh || (b.power_w || 0) - (a.power_w || 0));
  const total = Math.max(d.total_kwh, 0.0001);
  const showCost = energyPrice.price_per_kwh > 0;

  el.innerHTML = `<table class="energy-table">
    <thead><tr><th>Device</th><th>Room</th><th class="num">Now</th><th class="num">Used</th>${showCost ? '<th class="num">Cost</th>' : ""}<th class="share">Share</th></tr></thead>
    <tbody>${rows.map(r => `
      <tr>
        <td>${escapeHtml(r.name || r.id)}</td>
        <td class="muted">${escapeHtml(roomLabel(r))}</td>
        <td class="num">${r.online === false ? '<span class="muted">offline</span>' : formatWatts(r.power_w)}</td>
        <td class="num">${formatKwh(r.kwh)}</td>
        ${showCost ? `<td class="num">${formatCost(r.kwh)}</td>` : ""}
        <td class="share"><div class="energy-share"><div style="width: ${Math.round(100 * r.kwh / total)}%"></div></div></td>
      </tr>`).join("")}
    </tbody></table>`;
}

function initEnergyView() {
  document.querySelectorAll(".energy-range-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      energyRange = btn.dataset.range;
      document.querySelectorAll(".energy-range-btn").forEach(b => b.classList.toggle("active", b === btn));
      loadEnergy();
    });
  });
  // The nav button opens the view: load it, and keep it fresh while it is on screen
  const navBtn = document.querySelector('.nav-btn[data-view="energy"]');
  if (navBtn) navBtn.addEventListener("click", loadEnergy);
  clearInterval(energyRefreshTimer);
  energyRefreshTimer = setInterval(() => {
    const view = document.getElementById("view-energy");
    if (view && view.classList.contains("active")) loadEnergy();
  }, 15000);
}

document.addEventListener("DOMContentLoaded", initEnergyView);
