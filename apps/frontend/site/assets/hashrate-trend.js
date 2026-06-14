(function () {
  const STORAGE_KEY = "pepepow_pool_hashrate_history_v1";
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

  function readHashrateHps(pool) {
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

  function loadHistory() {
    try {
      const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
      return Array.isArray(parsed) ? parsed : [];
    } catch (_error) {
      return [];
    }
  }

  function saveHistory(points) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(points));
    } catch (_error) {
      // Ignore storage quota/private mode failures.
    }
  }

  function normalizeHistory(points) {
    const cutoff = Date.now() - MAX_AGE_MS;
    return points
      .filter((point) => point && typeof point.t === "number" && typeof point.h === "number")
      .filter((point) => Number.isFinite(point.t) && Number.isFinite(point.h) && point.t >= cutoff)
      .sort((a, b) => a.t - b.t)
      .slice(-MAX_POINTS);
  }

  function appendPoint(points, hashrate) {
    if (typeof hashrate !== "number" || !Number.isFinite(hashrate) || hashrate < 0) {
      return normalizeHistory(points);
    }
    const now = Date.now();
    const normalized = normalizeHistory(points);
    const last = normalized[normalized.length - 1];
    if (last && now - last.t < SAMPLE_INTERVAL_MS * 0.75) {
      last.t = now;
      last.h = hashrate;
      return normalized;
    }
    normalized.push({ t: now, h: hashrate });
    return normalizeHistory(normalized);
  }

  function renderTrend(points, statusText) {
    const container = document.getElementById("hashrate-trend-chart");
    if (!container) return;

    if (!Array.isArray(points) || points.length === 0) {
      container.innerHTML = `
        <div class="trend-empty">
          <strong>No hashrate samples yet.</strong>
          <p class="muted">This browser stores lightweight one-minute samples while the page is open.</p>
        </div>`;
      return;
    }

    const width = 640;
    const height = 210;
    const pad = 28;
    const values = points.map((point) => point.h);
    const min = Math.min(...values, 0);
    const max = Math.max(...values, 1);
    const span = Math.max(max - min, 1);
    const firstT = points[0].t;
    const lastT = points[points.length - 1].t;
    const timeSpan = Math.max(lastT - firstT, 1);

    const xy = points.map((point) => {
      const x = pad + ((point.t - firstT) / timeSpan) * (width - pad * 2);
      const y = height - pad - ((point.h - min) / span) * (height - pad * 2);
      return { x, y };
    });

    const path = xy.map((point, idx) => `${idx === 0 ? "M" : "L"}${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(" ");
    const fillPath = `${path} L${xy[xy.length - 1].x.toFixed(1)} ${height - pad} L${xy[0].x.toFixed(1)} ${height - pad} Z`;
    const latest = points[points.length - 1];
    const rangeMinutes = Math.max(1, Math.round((lastT - firstT) / 60000));
    const label = statusText || `${points.length} sample${points.length === 1 ? "" : "s"} / ${rangeMinutes} min`;

    container.innerHTML = `
      <div class="trend-meta">
        <div><span>Latest</span><strong>${escapeHtml(formatHashrate(latest.h))}</strong></div>
        <div><span>Peak</span><strong>${escapeHtml(formatHashrate(max))}</strong></div>
        <div><span>Samples</span><strong>${escapeHtml(label)}</strong></div>
      </div>
      <svg class="hashrate-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Pool hashrate trend chart">
        <line x1="${pad}" y1="${height - pad}" x2="${width - pad}" y2="${height - pad}" class="trend-axis"></line>
        <line x1="${pad}" y1="${pad}" x2="${pad}" y2="${height - pad}" class="trend-axis"></line>
        <path d="${fillPath}" class="trend-fill"></path>
        <path d="${path}" class="trend-line"></path>
      </svg>
      <p class="muted trend-note">Client-side retained samples only. No raw logs are scanned and no backend history job is required.</p>`;
  }

  function installStyles() {
    if (document.getElementById("hashrate-trend-styles")) return;
    const style = document.createElement("style");
    style.id = "hashrate-trend-styles";
    style.textContent = `
      .hashrate-trend-panel { grid-column: 1 / -1; }
      .trend-chart { display: grid; gap: 0.9rem; }
      .trend-meta { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0.75rem; }
      .trend-meta div { padding: 0.75rem; border-radius: 12px; background: rgba(255,255,255,0.035); border: 1px solid rgba(255,255,255,0.07); }
      .trend-meta span { display: block; color: var(--muted); font-size: 0.72rem; letter-spacing: 0.08em; text-transform: uppercase; }
      .trend-meta strong { display: block; margin-top: 0.2rem; font-size: 1rem; }
      .hashrate-svg { width: 100%; min-height: 190px; border-radius: 14px; background: rgba(255,255,255,0.025); border: 1px solid rgba(255,255,255,0.06); }
      .trend-axis { stroke: rgba(255,255,255,0.16); stroke-width: 1; }
      .trend-fill { fill: rgba(55,196,255,0.11); }
      .trend-line { fill: none; stroke: rgba(55,196,255,0.95); stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; }
      .trend-note { font-size: 0.82rem; margin: 0; }
      .trend-empty { padding: 1rem; border-radius: 14px; background: rgba(255,255,255,0.035); border: 1px dashed rgba(255,255,255,0.16); }
      @media (max-width: 640px) { .trend-meta { grid-template-columns: 1fr; } }
    `;
    document.head.appendChild(style);
  }

  async function fetchPoolSummary(apiBaseUrl) {
    const response = await fetch(`${apiBaseUrl}/pool/summary`, { cache: "no-store" });
    if (!response.ok) throw new Error("pool summary unavailable");
    return response.json();
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
    let history = loadHistory();
    try {
      const pool = await fetchPoolSummary(apiBaseUrl);
      history = appendPoint(history, readHashrateHps(pool));
      saveHistory(history);
      renderTrend(history);
    } catch (_error) {
      renderTrend(normalizeHistory(history), "offline cache");
    }
  }

  document.addEventListener("DOMContentLoaded", async () => {
    const container = document.getElementById("hashrate-trend-chart");
    if (!container) return;
    installStyles();
    const config = await loadRuntimeConfig();
    renderTrend(normalizeHistory(loadHistory()), "loading");
    await sampleAndRender(config.apiBaseUrl || "/api");
    window.setInterval(() => sampleAndRender(config.apiBaseUrl || "/api"), SAMPLE_INTERVAL_MS);
  });
})();
