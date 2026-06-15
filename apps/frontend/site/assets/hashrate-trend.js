(function () {
  const STORAGE_KEY = "pepepow_hashrate_history_v2";
  const LEGACY_POOL_KEY = "pepepow_pool_hashrate_history_v1";
  const DISTRIBUTION_CACHE_KEY = "pepepow_worker_distribution_cache_v1";
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

  function formatNumber(value) {
    if (typeof value !== "number" || !Number.isFinite(value)) return "-";
    return new Intl.NumberFormat().format(value);
  }

  function formatTimeLabel(ms) {
    const date = new Date(ms);
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function shortName(value) {
    const raw = String(value || "unknown");
    if (raw.length <= 18) return raw;
    return `${raw.slice(0, 7)}…${raw.slice(-5)}`;
  }

  function numberValue(...values) {
    for (const value of values) {
      if (typeof value === "number" && Number.isFinite(value)) return value;
      if (typeof value === "string" && value.trim() !== "") {
        const parsed = Number(value);
        if (Number.isFinite(parsed)) return parsed;
      }
    }
    return 0;
  }

  function readPoolHashrateHps(pool) {
    if (!pool || typeof pool !== "object") return null;
    const keys = [
      "poolHashrate", "pool_hashrate", "hashrate", "estimatedHashrate",
      "estimated_hashrate", "hashrateHps", "hashrate_hps", "hashRate",
      "hash_rate", "currentHashrate", "current_hashrate",
      "shareDerivedHashrate", "share_derived_hashrate"
    ];

    function parseValue(value) {
      if (typeof value === "number" && Number.isFinite(value)) return value;
      if (typeof value !== "string") return null;
      const cleaned = value.trim().toLowerCase();
      const num = Number.parseFloat(cleaned);
      if (!Number.isFinite(num)) return null;
      if (cleaned.includes("th/s") || cleaned.includes("th")) return num * 1000000000000;
      if (cleaned.includes("gh/s") || cleaned.includes("gh")) return num * 1000000000;
      if (cleaned.includes("mh/s") || cleaned.includes("mh")) return num * 1000000;
      if (cleaned.includes("kh/s") || cleaned.includes("kh")) return num * 1000;
      return num;
    }

    for (const key of keys) {
      if (pool[key] !== null && pool[key] !== undefined) {
        const parsed = parseValue(pool[key]);
        if (parsed !== null) return parsed;
      }
    }
    return null;
  }

  function readNetworkHashrateHps(network) {
    if (!network || typeof network !== "object") return null;
    const value = network.networkHashrate ?? network.network_hashrate ?? network.hashrate;
    return typeof value === "number" && Number.isFinite(value) ? value : null;
  }

  function loadHistory() {
    try {
      const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
      if (parsed && Array.isArray(parsed.pool) && Array.isArray(parsed.network)) return parsed;
    } catch (_error) {}

    let legacyPool = [];
    try {
      const legacy = JSON.parse(localStorage.getItem(LEGACY_POOL_KEY) || "[]");
      legacyPool = Array.isArray(legacy) ? legacy : [];
    } catch (_error) {
      legacyPool = [];
    }
    return { pool: legacyPool, network: [] };
  }

  function saveHistory(history) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(history));
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

  function normalizeHistory(history) {
    return {
      pool: normalizeSeries(history && history.pool),
      network: normalizeSeries(history && history.network)
    };
  }

  function normalizeDistribution(pool) {
    const source = Array.isArray(pool.workerDistribution) ? pool.workerDistribution : [];
    const map = new Map();
    for (const item of source) {
      if (!item || typeof item !== "object") continue;
      const wallet = String(item.wallet || item.address || item.miner || item.username || item.name || "unknown");
      const current = map.get(wallet) || { wallet, hashrate: 0, shares: 0, workers: 0 };
      current.hashrate += numberValue(item.hashrate, item.hashrateHps, item.hashrate_hps, item.estimatedHashrate);
      current.shares += numberValue(item.acceptedShares, item.shares, item.shareCount, item.accepted_share_count, item.shares15m);
      current.workers += numberValue(item.workers, item.workerCount, item.activeWorkers) || 1;
      map.set(wallet, current);
    }
    return Array.from(map.values()).filter((item) => item.wallet && item.wallet !== "unknown");
  }

  function loadDistributionCache() {
    try {
      const cached = JSON.parse(localStorage.getItem(DISTRIBUTION_CACHE_KEY) || "null");
      if (!cached || !Array.isArray(cached.items)) return [];
      if (typeof cached.t !== "number" || Date.now() - cached.t > MAX_AGE_MS) return [];
      return cached.items.filter((item) => item && typeof item === "object");
    } catch (_error) {
      return [];
    }
  }

  function saveDistributionCache(items) {
    if (!Array.isArray(items) || items.length === 0) return;
    try {
      localStorage.setItem(DISTRIBUTION_CACHE_KEY, JSON.stringify({ t: Date.now(), items }));
    } catch (_error) {}
  }

  function leaderboardRows(items, mode, emptyText) {
    const sorted = items
      .slice()
      .sort((a, b) => mode === "hashrate" ? b.hashrate - a.hashrate : b.shares - a.shares)
      .slice(0, 5);
    if (sorted.length === 0 || sorted.every((item) => (mode === "hashrate" ? item.hashrate : item.shares) <= 0)) {
      return `<div class="leaderboard-empty">${escapeHtml(emptyText || "No active ranking data available.")}</div>`;
    }
    return sorted.map((item, idx) => {
      const value = mode === "hashrate" ? formatHashrate(item.hashrate) : formatNumber(item.shares);
      return `<div class="leaderboard-row">
        <span class="leaderboard-rank">#${idx + 1}</span>
        <strong title="${escapeHtml(item.wallet)}">${escapeHtml(shortName(item.wallet))}</strong>
        <span>${escapeHtml(value)}</span>
      </div>`;
    }).join("");
  }

  function renderLeaderboards(pool) {
    const target = document.querySelector(".mining-outlook");
    if (!target) return;
    let box = document.getElementById("pool-leaderboards");
    if (!box) {
      box = document.createElement("div");
      box.id = "pool-leaderboards";
      box.className = "leaderboard-grid";
      target.appendChild(box);
    }
    let items = normalizeDistribution(pool || {});
    let label = "recent window";
    let emptyText = "No active ranking data available.";
    if (items.length === 0 || items.every((item) => item.hashrate <= 0 && item.shares <= 0)) {
      const cached = loadDistributionCache();
      if (cached.length > 0) {
        items = cached;
        label = "cached recent window";
      } else {
        emptyText = "Waiting for worker distribution data.";
      }
    } else {
      saveDistributionCache(items);
    }
    box.innerHTML = `
      <section class="leaderboard-card">
        <div class="leaderboard-head"><h4>Live Hashrate Ranking</h4><span>${escapeHtml(label)}</span></div>
        ${leaderboardRows(items, "hashrate", emptyText)}
      </section>
      <section class="leaderboard-card">
        <div class="leaderboard-head"><h4>Shares Ranking</h4><span>${escapeHtml(label)}</span></div>
        ${leaderboardRows(items, "shares", emptyText)}
      </section>`;
  }

  function renderChart(containerId, title, points, statusText) {
    const container = document.getElementById(containerId);
    if (!container) return;

    if (!Array.isArray(points) || points.length === 0) {
      container.innerHTML = `<div class="trend-empty"><strong>${escapeHtml(title)}</strong><p class="muted">Waiting for the first lightweight one-minute sample.</p></div>`;
      return;
    }

    const width = 640;
    const height = 240;
    const padLeft = 70;
    const padRight = 18;
    const padTop = 20;
    const padBottom = 40;
    const values = points.map((point) => point.h);
    const rawMin = Math.min(...values);
    const rawMax = Math.max(...values);
    const max = Math.max(rawMax, 1);
    const min = Math.max(0, rawMin === rawMax ? rawMin * 0.9 : rawMin);
    const span = Math.max(max - min, max * 0.1, 1);
    const firstT = points[0].t;
    const lastT = points[points.length - 1].t;
    const timeSpan = Math.max(lastT - firstT, 1);
    const chartW = width - padLeft - padRight;
    const chartH = height - padTop - padBottom;
    const xy = points.map((point) => {
      const x = padLeft + ((point.t - firstT) / timeSpan) * chartW;
      const y = padTop + (1 - ((point.h - min) / span)) * chartH;
      return { x, y };
    });

    const path = xy.map((point, idx) => `${idx === 0 ? "M" : "L"}${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(" ");
    const fillPath = `${path} L${xy[xy.length - 1].x.toFixed(1)} ${height - padBottom} L${xy[0].x.toFixed(1)} ${height - padBottom} Z`;
    const latest = points[points.length - 1];
    const rangeMinutes = Math.max(1, Math.round((lastT - firstT) / 60000));
    const sampleLabel = statusText || `${points.length} / ${rangeMinutes} min`;
    const mid = min + span / 2;
    const yTop = padTop;
    const yMid = padTop + chartH / 2;
    const yBottom = height - padBottom;
    const xMid = padLeft + chartW / 2;

    container.innerHTML = `
      <div class="trend-title-row">
        <h4>${escapeHtml(title)}</h4>
        <span>${escapeHtml(sampleLabel)}</span>
      </div>
      <div class="trend-meta trend-meta-compact">
        <span><b>Latest</b> ${escapeHtml(formatHashrate(latest.h))}</span>
        <span><b>Peak</b> ${escapeHtml(formatHashrate(max))}</span>
        <span><b>Low</b> ${escapeHtml(formatHashrate(rawMin))}</span>
      </div>
      <svg class="hashrate-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(title)} chart">
        <line x1="${padLeft}" y1="${yTop}" x2="${width - padRight}" y2="${yTop}" class="trend-grid-line"></line>
        <line x1="${padLeft}" y1="${yMid}" x2="${width - padRight}" y2="${yMid}" class="trend-grid-line"></line>
        <line x1="${padLeft}" y1="${yBottom}" x2="${width - padRight}" y2="${yBottom}" class="trend-axis"></line>
        <line x1="${padLeft}" y1="${padTop}" x2="${padLeft}" y2="${yBottom}" class="trend-axis"></line>
        <text x="${padLeft - 8}" y="${yTop + 4}" text-anchor="end" class="trend-axis-label">${escapeHtml(formatHashrate(max))}</text>
        <text x="${padLeft - 8}" y="${yMid + 4}" text-anchor="end" class="trend-axis-label">${escapeHtml(formatHashrate(mid))}</text>
        <text x="${padLeft - 8}" y="${yBottom + 4}" text-anchor="end" class="trend-axis-label">${escapeHtml(formatHashrate(min))}</text>
        <text x="${padLeft}" y="${height - 12}" text-anchor="start" class="trend-axis-label">${escapeHtml(formatTimeLabel(firstT))}</text>
        <text x="${xMid}" y="${height - 12}" text-anchor="middle" class="trend-axis-label">${escapeHtml(formatTimeLabel(firstT + timeSpan / 2))}</text>
        <text x="${width - padRight}" y="${height - 12}" text-anchor="end" class="trend-axis-label">${escapeHtml(formatTimeLabel(lastT))}</text>
        <path d="${fillPath}" class="trend-fill"></path>
        <path d="${path}" class="trend-line"></path>
      </svg>`;
  }

  function renderAll(history, statusText) {
    renderChart("pool-hashrate-trend-chart", "Pool Hashrate", history.pool, statusText);
    renderChart("network-hashrate-trend-chart", "Network Hashrate", history.network, statusText);
    renderChart("hashrate-trend-chart", "Pool Hashrate", history.pool, statusText);
  }

  function installStyles() {
    if (document.getElementById("hashrate-trend-styles")) return;
    const style = document.createElement("style");
    style.id = "hashrate-trend-styles";
    style.textContent = `
      .hashrate-trend-panel { grid-column: 1 / -1; }
      .trend-chart-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; margin-top: 1rem; }
      .trend-chart { display: grid; gap: 0.55rem; min-width: 0; }
      .trend-title-row { display: flex; justify-content: space-between; align-items: center; gap: 0.75rem; }
      .trend-title-row h4 { margin: 0; font-size: 1rem; }
      .trend-title-row span { color: var(--muted); font-size: 0.76rem; white-space: nowrap; }
      .trend-meta-compact { display: flex; flex-wrap: wrap; gap: 0.45rem; }
      .trend-meta-compact span { display: inline-flex; gap: 0.25rem; padding: 0.26rem 0.45rem; border-radius: 999px; background: rgba(255,255,255,0.035); border: 1px solid rgba(255,255,255,0.06); color: var(--muted); font-size: 0.72rem; }
      .trend-meta-compact b { color: rgba(235,245,255,0.82); font-weight: 700; }
      .hashrate-svg { width: 100%; min-height: 210px; border-radius: 14px; background: rgba(255,255,255,0.025); border: 1px solid rgba(255,255,255,0.06); }
      .trend-axis, .trend-grid-line { stroke: rgba(255,255,255,0.16); stroke-width: 1; }
      .trend-grid-line { stroke-dasharray: 4 5; opacity: 0.7; }
      .trend-axis-label { fill: rgba(235,245,255,0.62); font-size: 11px; }
      .trend-fill { fill: rgba(55,196,255,0.11); }
      .trend-line { fill: none; stroke: rgba(55,196,255,0.95); stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; }
      .trend-empty { padding: 1rem; border-radius: 14px; background: rgba(255,255,255,0.035); border: 1px dashed rgba(255,255,255,0.16); }
      .leaderboard-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; margin-top: 1rem; }
      .leaderboard-card { display: grid; gap: 0.45rem; padding: 0.9rem; border-radius: 14px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.07); }
      .leaderboard-head { display: flex; justify-content: space-between; align-items: baseline; gap: 0.75rem; margin-bottom: 0.25rem; }
      .leaderboard-head h4 { margin: 0; font-size: 1rem; }
      .leaderboard-head span { color: var(--muted); font-size: 0.72rem; }
      .leaderboard-row { display: grid; grid-template-columns: 2.6rem minmax(0, 1fr) auto; gap: 0.6rem; align-items: center; padding: 0.5rem 0; border-top: 1px solid rgba(255,255,255,0.06); }
      .leaderboard-rank { color: var(--accent); font-weight: 800; }
      .leaderboard-row strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .leaderboard-row > span:last-child { color: var(--text); font-variant-numeric: tabular-nums; white-space: nowrap; }
      .leaderboard-empty { color: var(--muted); padding: 0.65rem 0; }
      @media (max-width: 920px) { .trend-chart-grid, .leaderboard-grid { grid-template-columns: 1fr; } }
    `;
    document.head.appendChild(style);
  }

  async function fetchJson(url) {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) throw new Error("request failed");
    return response.json();
  }

  async function loadApiHistory(apiBaseUrl) {
    const payload = await fetchJson(`${apiBaseUrl}/hashrate/history`);
    return normalizeHistory(payload || {});
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

  async function sampleAndRender(apiBaseUrl) {
    let history;
    try {
      history = await loadApiHistory(apiBaseUrl);
      const [pool, network] = await Promise.all([
        fetchJson(`${apiBaseUrl}/pool/summary`),
        fetchJson(`${apiBaseUrl}/network/summary`)
      ]);
      history.pool = appendPoint(history.pool, readPoolHashrateHps(pool));
      history.network = appendPoint(history.network, readNetworkHashrateHps(network));
      history = normalizeHistory(history);
      saveHistory(history);
      renderAll(history, "api history");
      renderLeaderboards(pool);
    } catch (_error) {
      history = normalizeHistory(loadHistory());
      renderAll(history, "offline cache");
      renderLeaderboards({ workerDistribution: loadDistributionCache() });
    }
  }

  document.addEventListener("DOMContentLoaded", async () => {
    if (!document.getElementById("pool-hashrate-trend-chart") && !document.getElementById("network-hashrate-trend-chart") && !document.getElementById("hashrate-trend-chart")) return;
    installStyles();
    const config = await loadRuntimeConfig();
    renderAll(normalizeHistory(loadHistory()), "loading");
    renderLeaderboards({ workerDistribution: loadDistributionCache() });
    await sampleAndRender(config.apiBaseUrl || "/api");
    window.setInterval(() => sampleAndRender(config.apiBaseUrl || "/api"), SAMPLE_INTERVAL_MS);
  });
})();
