(function () {
  const REFRESH_MS = 60 * 1000;
  const CACHE_KEY = "pepepow_combined_leaderboard_v1";
  const CACHE_MAX_AGE_MS = 15 * 60 * 1000;
  let cachedLeaderboardItems = [];
  let cachedLastPoolBlockText = "";
  let cachedLastPoolBlockHtml = "";

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function formatNumber(value) {
    const n = Number(value);
    return Number.isFinite(n) ? new Intl.NumberFormat().format(n) : "-";
  }

  function formatDate(value) {
    if (!value) return "-";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString();
  }

  function formatHashrate(value) {
    const n = Number(value);
    if (!Number.isFinite(n) || n < 0) return "-";
    const units = ["H/s", "KH/s", "MH/s", "GH/s", "TH/s"];
    let scaled = n;
    let unit = units[0];
    for (const candidate of units) {
      unit = candidate;
      if (scaled < 1000 || candidate === units[units.length - 1]) break;
      scaled /= 1000;
    }
    if (unit === "H/s") return `${scaled.toFixed(0)} H/s`;
    return `${scaled.toFixed(scaled >= 100 ? 0 : scaled >= 10 ? 1 : 2)} ${unit}`;
  }

  function compactWallet(value) {
    const raw = String(value || "unknown");
    return raw.length > 18 ? `${raw.slice(0, 7)}…${raw.slice(-5)}` : raw;
  }

  function minerLookupUrl(wallet) {
    return `/miner.html?wallet=${encodeURIComponent(String(wallet || ""))}`;
  }

  function numeric(...values) {
    for (const value of values) {
      const n = Number(value);
      if (Number.isFinite(n)) return n;
    }
    return 0;
  }

  function distributionSource(summary) {
    if (!summary || typeof summary !== "object") return [];
    if (Array.isArray(summary.workerDistribution)) return summary.workerDistribution;
    if (summary.pool && typeof summary.pool === "object" && Array.isArray(summary.pool.workerDistribution)) {
      return summary.pool.workerDistribution;
    }
    return [];
  }

  function normalize(summary, miningMode) {
    return distributionSource(summary).map((item) => ({
      wallet: String(item.wallet || item.address || item.miner || item.username || item.name || "unknown"),
      miningMode,
      hashrate: numeric(item.hashrate, item.hashrateHps, item.hashrate_hps, item.estimatedHashrate),
      shares: numeric(item.acceptedShares, item.totalAcceptedShares, item.shareCount, item.shares, item.accepted_share_count, item.shares15m),
      activeWorkers: numeric(item.activeWorkers, item.workerCount, item.workers)
    })).filter((item) => item.wallet && item.wallet !== "unknown");
  }

  function loadCache() {
    try {
      const cached = JSON.parse(localStorage.getItem(CACHE_KEY) || "null");
      if (!cached || !Array.isArray(cached.items) || typeof cached.t !== "number") return [];
      if (Date.now() - cached.t > CACHE_MAX_AGE_MS) return [];
      return cached.items.filter((item) => item && typeof item === "object");
    } catch (_error) {
      return [];
    }
  }

  function saveCache(items) {
    if (!Array.isArray(items) || items.length === 0) return;
    try {
      localStorage.setItem(CACHE_KEY, JSON.stringify({ t: Date.now(), items }));
    } catch (_error) {}
  }

  function installStyles() {
    if (document.getElementById("combined-leaderboard-styles")) return;
    const style = document.createElement("style");
    style.id = "combined-leaderboard-styles";
    style.textContent = `
      #pool-leaderboards .leaderboard-row { grid-template-columns: 2.6rem 3.5rem minmax(0, 1fr) auto; }
      #pool-leaderboards .leaderboard-mode { display: inline-flex; justify-content: center; padding: .2rem .35rem; border-radius: 999px; font-size: .65rem; font-weight: 800; letter-spacing: .05em; border: 1px solid rgba(255,255,255,.12); color: var(--muted); }
      #pool-leaderboards .leaderboard-mode.is-solo { border-color: rgba(255,212,90,.35); color: #ffd45a; background: rgba(255,212,90,.08); }
      #pool-leaderboards .leaderboard-mode.is-pool { border-color: rgba(55,196,255,.3); color: var(--accent-alt); background: rgba(55,196,255,.07); }
      #pool-leaderboards .leaderboard-wallet { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      #pool-leaderboards .leaderboard-value { color: var(--text); font-variant-numeric: tabular-nums; white-space: nowrap; }
      @media (max-width: 520px) { #pool-leaderboards .leaderboard-row { grid-template-columns: 2.2rem 3.25rem minmax(0, 1fr) auto; gap: .4rem; } }
    `;
    document.head.appendChild(style);
  }

  function rows(items, mode) {
    const sorted = items.slice().sort((a, b) => mode === "hashrate" ? b.hashrate - a.hashrate : b.shares - a.shares).slice(0, 5);
    if (sorted.length === 0 || sorted.every((item) => (mode === "hashrate" ? item.hashrate : item.shares) <= 0)) {
      return `<div class="leaderboard-empty">No active POOL or SOLO data available.</div>`;
    }
    return sorted.map((item, idx) => {
      const value = mode === "hashrate" ? formatHashrate(item.hashrate) : formatNumber(item.shares);
      const wallet = escapeHtml(item.wallet);
      const compact = escapeHtml(compactWallet(item.wallet));
      const lookupUrl = escapeHtml(minerLookupUrl(item.wallet));
      const modeLabel = item.miningMode === "solo" ? "SOLO" : "POOL";
      return `<div class="leaderboard-row">
        <span class="leaderboard-rank">#${idx + 1}</span>
        <span class="leaderboard-mode is-${escapeHtml(item.miningMode)}">${modeLabel}</span>
        <a class="leaderboard-wallet" href="${lookupUrl}" title="Miner lookup: ${wallet}">${compact}</a>
        <span class="leaderboard-value">${escapeHtml(value)}</span>
      </div>`;
    }).join("");
  }

  function renderItems(items, label) {
    const target = document.querySelector(".mining-outlook");
    if (!target) return;
    let box = document.getElementById("pool-leaderboards");
    if (!box) {
      box = document.createElement("div");
      box.id = "pool-leaderboards";
      box.className = "leaderboard-grid";
      target.appendChild(box);
    }
    box.innerHTML = `<section class="leaderboard-card"><div class="leaderboard-head"><h4>Live Hashrate Ranking</h4><span>${escapeHtml(label)}</span></div>${rows(items, "hashrate")}</section><section class="leaderboard-card"><div class="leaderboard-head"><h4>Shares Ranking</h4><span>${escapeHtml(label)}</span></div>${rows(items, "shares")}</section>`;
  }

  function renderLoading() {
    const target = document.querySelector(".mining-outlook");
    if (!target) return;
    let box = document.getElementById("pool-leaderboards");
    if (!box) {
      box = document.createElement("div");
      box.id = "pool-leaderboards";
      box.className = "leaderboard-grid";
      target.appendChild(box);
    }
    box.innerHTML = `<section class="leaderboard-card"><div class="leaderboard-head"><h4>Live Hashrate Ranking</h4><span>POOL + SOLO</span></div><div class="leaderboard-empty">Loading ranking snapshot...</div></section><section class="leaderboard-card"><div class="leaderboard-head"><h4>Shares Ranking</h4><span>POOL + SOLO</span></div><div class="leaderboard-empty">Loading ranking snapshot...</div></section>`;
  }

  async function fetchJson(url) {
    if (window.PepepowUI && typeof window.PepepowUI.fetchJson === "function") {
      return window.PepepowUI.fetchJson(url);
    }
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) throw new Error("request failed");
    return response.json();
  }

  async function refreshLeaderboards() {
    if (!["home", "dashboard"].includes(document.body.dataset.page || "")) return;
    try {
      const [pool, solo] = await Promise.all([
        fetchJson("/api/pool/summary").catch(() => ({})),
        fetchJson("/api/solo/summary").catch(() => ({}))
      ]);
      const items = [...normalize(pool, "pool"), ...normalize(solo, "solo")];
      if (items.length === 0) {
        if (cachedLeaderboardItems.length > 0) renderItems(cachedLeaderboardItems, "POOL + SOLO · cached");
        return;
      }
      cachedLeaderboardItems = items;
      saveCache(items);
      renderItems(items, "POOL + SOLO · recent accepted shares");
    } catch (_error) {
      if (cachedLeaderboardItems.length > 0) renderItems(cachedLeaderboardItems, "POOL + SOLO · cached");
    }
  }

  function observedPoolBlockItems(payload) {
    const items = payload && Array.isArray(payload.items) ? payload.items : [];
    return items.filter((item) => {
      const status = String(item.lifecycleStatus || "").toLowerCase().replace(/_/g, "-");
      return status && status !== "orphan" && status !== "orphaned";
    });
  }

  function setLastPoolBlockSummary({ height, status, time }) {
    const node = document.getElementById("last-block-time");
    if (!node) return;
    const heightText = height > 0 ? formatNumber(height) : "Observed";
    const statusText = String(status || "observed").replace(/_/g, " ");
    const timeText = time || "-";
    cachedLastPoolBlockText = height > 0 ? `${heightText} · ${statusText} · ${timeText}` : `${statusText} · ${timeText}`;
    cachedLastPoolBlockHtml = `<span class="block-confirmed-summary"><span class="block-confirmed-height">${escapeHtml(heightText)}</span><span class="block-status-badge">${escapeHtml(statusText)}</span><span class="block-confirmed-time">${escapeHtml(timeText)}</span></span>`;
    node.innerHTML = cachedLastPoolBlockHtml;
    node.dataset.poolObservedBlock = cachedLastPoolBlockText;
  }

  function restoreLastPoolBlockText() {
    const node = document.getElementById("last-block-time");
    if (!node || !cachedLastPoolBlockText || !cachedLastPoolBlockHtml) return;
    const current = node.textContent ? node.textContent.trim() : "";
    if (!current || current === "-" || node.innerHTML !== cachedLastPoolBlockHtml) {
      node.innerHTML = cachedLastPoolBlockHtml;
      node.dataset.poolObservedBlock = cachedLastPoolBlockText;
    }
  }

  async function refreshLastObservedPoolBlock() {
    if (!["home", "dashboard"].includes(document.body.dataset.page || "")) return;
    const node = document.getElementById("last-block-time");
    if (!node) return;
    try {
      const payload = await fetchJson("/api/accepted-candidates");
      const observed = observedPoolBlockItems(payload).sort((a, b) => numeric(b.matchedHeight, Date.parse(b.submitTimestamp)) - numeric(a.matchedHeight, Date.parse(a.submitTimestamp)));
      if (observed.length === 0) { restoreLastPoolBlockText(); return; }
      const latest = observed[0];
      setLastPoolBlockSummary({
        height: numeric(latest.matchedHeight),
        status: String(latest.lifecycleStatus || "observed").replace(/_/g, " "),
        time: formatDate(latest.submitTimestamp)
      });
    } catch (_error) {
      restoreLastPoolBlockText();
    }
  }

  function installLastPoolBlockGuard() {
    const node = document.getElementById("last-block-time");
    if (!node) return;
    const observer = new MutationObserver(() => restoreLastPoolBlockText());
    observer.observe(node, { childList: true, characterData: true, subtree: true });
  }

  async function refresh() {
    await Promise.all([refreshLeaderboards(), refreshLastObservedPoolBlock()]);
  }

  document.addEventListener("DOMContentLoaded", () => {
    installStyles();
    installLastPoolBlockGuard();
    cachedLeaderboardItems = loadCache();
    if (cachedLeaderboardItems.length > 0) renderItems(cachedLeaderboardItems, "POOL + SOLO · cached");
    else renderLoading();
    refresh();
    window.setInterval(refresh, REFRESH_MS);
  });
})();
