(function () {
  const MAX_AGE_MS = 24 * 60 * 60 * 1000;
  const SAMPLE_INTERVAL_MS = 60 * 1000;
  const MAX_POINTS = 1440;

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function formatHashrate(value) {
    if (typeof value !== "number" || !Number.isFinite(value)) return "-";
    const units = ["H/s", "KH/s", "MH/s", "GH/s", "TH/s"];
    let scaled = value;
    let unit = units[0];
    for (const candidate of units) {
      unit = candidate;
      if (scaled < 1000 || candidate === units[units.length - 1]) break;
      scaled /= 1000;
    }
    if (unit === "H/s") return `${scaled.toFixed(0)} H/s`;
    return `${scaled.toFixed(scaled >= 100 ? 0 : scaled >= 10 ? 1 : 2)} ${unit}`;
  }

  function formatTimeLabel(ms) {
    const date = new Date(ms);
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function storageKey(wallet) {
    return `pepepow_miner_hashrate_${wallet}`;
  }

  function loadSeries(wallet) {
    try {
      const parsed = JSON.parse(localStorage.getItem(storageKey(wallet)) || "[]");
      return Array.isArray(parsed) ? parsed : [];
    } catch (_error) {
      return [];
    }
  }

  function saveSeries(wallet, points) {
    try {
      localStorage.setItem(storageKey(wallet), JSON.stringify(points));
    } catch (_error) {}
  }

  function normalizeSeries(points) {
    const cutoff = Date.now() - MAX_AGE_MS;
    return (Array.isArray(points) ? points : [])
      .filter((point) => point && typeof point.t === "number" && typeof point.h === "number")
      .filter((point) => Number.isFinite(point.t) && Number.isFinite(point.h) && point.t >= cutoff)
      .sort((a, b) => a.t - b.t)
      .slice(-MAX_POINTS);
  }

  function appendPoint(points, hashrate) {
    const normalized = normalizeSeries(points);
    if (typeof hashrate !== "number" || !Number.isFinite(hashrate) || hashrate < 0) return normalized;
    const now = Date.now();
    const last = normalized[normalized.length - 1];
    if (last && now - last.t < SAMPLE_INTERVAL_MS * 0.75) {
      last.t = now;
      last.h = hashrate;
      return normalized;
    }
    normalized.push({ t: now, h: hashrate });
    return normalizeSeries(normalized);
  }

  function installStyles() {
    if (document.getElementById("miner-hashrate-styles")) return;
    const style = document.createElement("style");
    style.id = "miner-hashrate-styles";
    style.textContent = `
      .miner-hashrate-panel { margin-top: 1rem; }
      .miner-hashrate-chart { display: grid; gap: 0.55rem; }
      .miner-chart-head { display: flex; justify-content: space-between; align-items: center; gap: 0.75rem; }
      .miner-chart-head h3 { margin: 0; }
      .miner-chart-head span { color: var(--muted); font-size: 0.78rem; }
      .miner-chart-meta { display: flex; flex-wrap: wrap; gap: 0.45rem; }
      .miner-chart-meta span { display: inline-flex; gap: 0.25rem; padding: 0.26rem 0.45rem; border-radius: 999px; background: rgba(255,255,255,0.035); border: 1px solid rgba(255,255,255,0.06); color: var(--muted); font-size: 0.72rem; }
      .miner-chart-meta b { color: rgba(235,245,255,0.82); }
      .miner-hashrate-svg { width: 100%; min-height: 220px; border-radius: 14px; background: rgba(255,255,255,0.025); border: 1px solid rgba(255,255,255,0.06); }
      .miner-axis, .miner-grid-line { stroke: rgba(255,255,255,0.16); stroke-width: 1; }
      .miner-grid-line { stroke-dasharray: 4 5; opacity: 0.7; }
      .miner-axis-label { fill: rgba(235,245,255,0.62); font-size: 11px; }
      .miner-fill { fill: rgba(129,247,176,0.10); }
      .miner-line { fill: none; stroke: rgba(129,247,176,0.95); stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; }
    `;
    document.head.appendChild(style);
  }

  function renderChart(points, wallet) {
    const container = document.getElementById("miner-hashrate-chart");
    if (!container) return;
    const series = normalizeSeries(points);
    if (series.length === 0) {
      container.innerHTML = `<div class="empty-state"><strong>Miner hashrate trend</strong><p class="muted">Lookup a wallet and keep this page open to collect one-minute samples.</p></div>`;
      return;
    }

    const width = 640;
    const height = 240;
    const padLeft = 70;
    const padRight = 18;
    const padTop = 20;
    const padBottom = 40;
    const values = series.map((point) => point.h);
    const rawMin = Math.min(...values);
    const rawMax = Math.max(...values);
    const max = Math.max(rawMax, 1);
    const min = Math.max(0, rawMin === rawMax ? rawMin * 0.9 : rawMin);
    const span = Math.max(max - min, max * 0.1, 1);
    const firstT = series[0].t;
    const lastT = series[series.length - 1].t;
    const timeSpan = Math.max(lastT - firstT, 1);
    const chartW = width - padLeft - padRight;
    const chartH = height - padTop - padBottom;
    const xy = series.map((point) => ({
      x: padLeft + ((point.t - firstT) / timeSpan) * chartW,
      y: padTop + (1 - ((point.h - min) / span)) * chartH
    }));
    const path = xy.map((point, idx) => `${idx === 0 ? "M" : "L"}${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(" ");
    const fillPath = `${path} L${xy[xy.length - 1].x.toFixed(1)} ${height - padBottom} L${xy[0].x.toFixed(1)} ${height - padBottom} Z`;
    const latest = series[series.length - 1];
    const mid = min + span / 2;
    const yTop = padTop;
    const yMid = padTop + chartH / 2;
    const yBottom = height - padBottom;
    const xMid = padLeft + chartW / 2;
    const sampleLabel = `${series.length} sample${series.length === 1 ? "" : "s"}`;

    container.innerHTML = `
      <div class="miner-chart-head"><h3>Miner Hashrate Trend</h3><span>${escapeHtml(sampleLabel)}</span></div>
      <div class="miner-chart-meta">
        <span><b>Latest</b> ${escapeHtml(formatHashrate(latest.h))}</span>
        <span><b>Peak</b> ${escapeHtml(formatHashrate(max))}</span>
        <span><b>Wallet</b> ${escapeHtml(wallet.slice(0, 6) + "…" + wallet.slice(-4))}</span>
      </div>
      <svg class="miner-hashrate-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Miner hashrate trend chart">
        <line x1="${padLeft}" y1="${yTop}" x2="${width - padRight}" y2="${yTop}" class="miner-grid-line"></line>
        <line x1="${padLeft}" y1="${yMid}" x2="${width - padRight}" y2="${yMid}" class="miner-grid-line"></line>
        <line x1="${padLeft}" y1="${yBottom}" x2="${width - padRight}" y2="${yBottom}" class="miner-axis"></line>
        <line x1="${padLeft}" y1="${padTop}" x2="${padLeft}" y2="${yBottom}" class="miner-axis"></line>
        <text x="${padLeft - 8}" y="${yTop + 4}" text-anchor="end" class="miner-axis-label">${escapeHtml(formatHashrate(max))}</text>
        <text x="${padLeft - 8}" y="${yMid + 4}" text-anchor="end" class="miner-axis-label">${escapeHtml(formatHashrate(mid))}</text>
        <text x="${padLeft - 8}" y="${yBottom + 4}" text-anchor="end" class="miner-axis-label">${escapeHtml(formatHashrate(min))}</text>
        <text x="${padLeft}" y="${height - 12}" text-anchor="start" class="miner-axis-label">${escapeHtml(formatTimeLabel(firstT))}</text>
        <text x="${xMid}" y="${height - 12}" text-anchor="middle" class="miner-axis-label">${escapeHtml(formatTimeLabel(firstT + timeSpan / 2))}</text>
        <text x="${width - padRight}" y="${height - 12}" text-anchor="end" class="miner-axis-label">${escapeHtml(formatTimeLabel(lastT))}</text>
        <path d="${fillPath}" class="miner-fill"></path>
        <path d="${path}" class="miner-line"></path>
      </svg>`;
  }

  async function loadRuntimeConfig() {
    try {
      const response = await fetch("/runtime-config.json", { cache: "no-store" });
      if (!response.ok) return { apiBaseUrl: "/api" };
      const payload = await response.json();
      return { apiBaseUrl: payload.apiBaseUrl || "/api" };
    } catch (_error) {
      return { apiBaseUrl: "/api" };
    }
  }

  async function sampleWallet(apiBaseUrl, wallet) {
    if (!wallet) return;
    try {
      const url = `${apiBaseUrl}/miner/${encodeURIComponent(wallet)}`;
      const payload = window.PepepowUI && typeof window.PepepowUI.fetchJson === "function"
        ? await window.PepepowUI.fetchJson(url)
        : await fetch(url, { cache: "no-store" }).then((response) => response.ok ? response.json() : null);
      if (!payload) return;
      const hashrate = payload && payload.summary && typeof payload.summary.hashrate === "number" ? payload.summary.hashrate : null;
      let series = loadSeries(wallet);
      series = appendPoint(series, hashrate);
      saveSeries(wallet, series);
      renderChart(series, wallet);
    } catch (_error) {
      renderChart(loadSeries(wallet), wallet);
    }
  }

  document.addEventListener("DOMContentLoaded", async () => {
    if (document.body.dataset.page !== "miner") return;
    installStyles();
    const config = await loadRuntimeConfig();
    const input = document.getElementById("wallet-input");
    const form = document.getElementById("miner-form");
    let activeWallet = input ? input.value.trim() : "";

    function resample() {
      activeWallet = input ? input.value.trim() : activeWallet;
      if (activeWallet) sampleWallet(config.apiBaseUrl || "/api", activeWallet);
    }

    if (form) {
      form.addEventListener("submit", () => window.setTimeout(resample, 900));
    }
    if (activeWallet) window.setTimeout(resample, 900);
    window.setInterval(resample, SAMPLE_INTERVAL_MS);
  });
})();
