(function () {
  const REFRESH_MS = 60 * 1000;
  const MAX_MINER_LOOKUPS = 20;
  const BLOCK_TIME_SECONDS = 20;
  const TOTAL_BLOCK_REWARD = 6500;
  const DEVELOPER_FEE_RATIO = 0.05;
  const MINER_REWARD_RATIO = 0.65;
  const NON_ORPHAN_RATE = 0.75;
  let cachedLeaderboardItems = [];
  let cachedShareLabel = "accepted shares";
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

  function normalize(pool) {
    const source = Array.isArray(pool.workerDistribution) ? pool.workerDistribution : [];
    return source.map((item) => ({
      wallet: String(item.wallet || item.address || item.miner || item.username || item.name || "unknown"),
      hashrate: numeric(item.hashrate, item.hashrateHps, item.hashrate_hps, item.estimatedHashrate),
      shares: numeric(item.totalAcceptedShares, item.acceptedShares, item.shareCount, item.shares, item.accepted_share_count, item.shares15m),
      activeWorkers: numeric(item.activeWorkers, item.workerCount, item.workers)
    })).filter((item) => item.wallet && item.wallet !== "unknown");
  }

  function rows(items, mode) {
    const sorted = items.slice().sort((a, b) => mode === "hashrate" ? b.hashrate - a.hashrate : b.shares - a.shares).slice(0, 5);
    if (sorted.length === 0 || sorted.every((item) => (mode === "hashrate" ? item.hashrate : item.shares) <= 0)) return `<div class="leaderboard-empty">No active data available.</div>`;
    return sorted.map((item, idx) => {
      const value = mode === "hashrate" ? formatHashrate(item.hashrate) : formatNumber(item.shares);
      const wallet = escapeHtml(item.wallet);
      const compact = escapeHtml(compactWallet(item.wallet));
      const lookupUrl = escapeHtml(minerLookupUrl(item.wallet));
      return `<div class="leaderboard-row">
        <span class="leaderboard-rank">#${idx + 1}</span>
        <a class="leaderboard-wallet" href="${lookupUrl}" title="Miner lookup: ${wallet}">${compact}</a>
        <span class="leaderboard-value">${escapeHtml(value)}</span>
      </div>`;
    }).join("");
  }

  function renderItems(items, shareLabel) {
    const target = document.querySelector(".mining-outlook");
    if (!target) return;
    let box = document.getElementById("pool-leaderboards");
    if (!box) {
      box = document.createElement("div");
      box.id = "pool-leaderboards";
      box.className = "leaderboard-grid";
      target.appendChild(box);
    }
    box.innerHTML = `<section class="leaderboard-card"><div class="leaderboard-head"><h4>Live Hashrate Ranking</h4><span>recent window</span></div>${rows(items, "hashrate")}</section><section class="leaderboard-card"><div class="leaderboard-head"><h4>Shares Ranking</h4><span>${escapeHtml(shareLabel)}</span></div>${rows(items, "shares")}</section>`;
  }

  async function fetchJson(url) {
    if (window.PepepowUI && typeof window.PepepowUI.fetchJson === "function") {
      return window.PepepowUI.fetchJson(url);
    }
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) throw new Error("request failed");
    return response.json();
  }

  async function enrichTotalSharesFromMinerApi(items) {
    const candidates = items.filter((item) => item.wallet && item.wallet !== "unknown").sort((a, b) => b.hashrate - a.hashrate).slice(0, MAX_MINER_LOOKUPS);
    if (candidates.length === 0) return items;
    const results = await Promise.all(candidates.map(async (item) => {
      try {
        const payload = await fetchJson(`/api/miner/${encodeURIComponent(item.wallet)}`);
        const summary = payload && payload.summary ? payload.summary : {};
        return [item.wallet, numeric(summary.acceptedShares, summary.shareCount, item.shares)];
      } catch (_error) {
        return [item.wallet, item.shares];
      }
    }));
    const sharesByWallet = new Map(results);
    return items.map((item) => ({ ...item, shares: sharesByWallet.get(item.wallet) || item.shares }));
  }

  function useCachedLeaderboard() {
    if (cachedLeaderboardItems.length === 0) return false;
    renderItems(cachedLeaderboardItems, `${cachedShareLabel} · cached`);
    return true;
  }

  async function refreshLeaderboards() {
    if (!["home", "dashboard"].includes(document.body.dataset.page || "")) return;
    try {
      const pool = await fetchJson("/api/pool/summary");
      const items = normalize(pool || {});
      if (items.length === 0) { useCachedLeaderboard(); return; }
      renderItems(items, "loading totals");
      const enriched = await enrichTotalSharesFromMinerApi(items);
      cachedLeaderboardItems = enriched;
      cachedShareLabel = "accepted shares";
      renderItems(enriched, cachedShareLabel);
    } catch (_error) {
      useCachedLeaderboard();
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
      const height = numeric(latest.matchedHeight);
      const status = String(latest.lifecycleStatus || "observed").replace(/_/g, " ");
      const time = formatDate(latest.submitTimestamp);
      setLastPoolBlockSummary({ height, status, time });
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

  function setText(id, value) {
    const node = document.getElementById(id);
    if (node) node.textContent = value;
  }

  function unitToHps(value, unit) {
    let hps = Number(value);
    if (!Number.isFinite(hps) || hps < 0) return null;
    if (unit === "KH") hps *= 1000;
    if (unit === "MH") hps *= 1000000;
    return hps;
  }

  function poolFeeRatio(pool) {
    return pool && typeof pool.feePercent === "number" && Number.isFinite(pool.feePercent) && pool.feePercent > 0
      ? pool.feePercent / 100
      : 0;
  }

  function relabelOrphanAdjustedCalculator() {
    [
      ["calc-pepew-hour", "Orphan-adjusted PEPEW / Hour"],
      ["calc-pepew-day", "Orphan-adjusted PEPEW / Day"],
      ["calc-pepew-week", "Orphan-adjusted PEPEW / Week"],
      ["calc-usdt-day", "Orphan-adjusted USDT / Day"],
      ["calc-usdt-week", "Orphan-adjusted USDT / Week"]
    ].forEach(([id, label]) => {
      const labelNode = document.getElementById(id)?.closest("div")?.querySelector("span");
      if (labelNode) labelNode.textContent = label;
    });

    const warning = document.querySelector(".estimate-warning");
    if (warning) {
      warning.innerHTML = "⚠️ <strong>Orphan-adjusted theoretical estimate.</strong> Uses current block reward 6500 × 95% developer-fee remainder × 65% miner share × pool fee × 75% non-orphan rate. Actual recorded payments can still differ because of pool luck, network hashrate changes, and payment timing.";
    }
  }

  async function refreshOrphanAdjustedCalculator() {
    if (!["home", "dashboard"].includes(document.body.dataset.page || "")) return;
    const hashrateInput = document.getElementById("calc-hashrate");
    const unitSelect = document.getElementById("calc-unit");
    if (!hashrateInput || !unitSelect) return;
    relabelOrphanAdjustedCalculator();

    const userHashrateHps = unitToHps(hashrateInput.value, unitSelect.value);
    if (!userHashrateHps) return;

    try {
      const [network, pool, price] = await Promise.all([
        fetchJson("/api/network/summary").catch(() => null),
        fetchJson("/api/pool/summary").catch(() => null),
        fetchJson("/api/price/pepew-usdt").catch(() => null)
      ]);
      const netHashrate = network && typeof network.networkHashrate === "number" ? network.networkHashrate : null;
      if (!netHashrate || netHashrate <= 0) return;

      const minerRewardPerBlock = TOTAL_BLOCK_REWARD * (1 - DEVELOPER_FEE_RATIO) * MINER_REWARD_RATIO * (1 - poolFeeRatio(pool)) * NON_ORPHAN_RATE;
      const rewardPerDay = (userHashrateHps / netHashrate) * (86400 / BLOCK_TIME_SECONDS) * minerRewardPerBlock;
      const rewardPerHour = rewardPerDay / 24;
      const rewardPerWeek = rewardPerDay * 7;

      setText("calc-pepew-hour", formatNumber(Math.round(rewardPerHour * 100) / 100));
      setText("calc-pepew-day", formatNumber(Math.round(rewardPerDay * 100) / 100));
      setText("calc-pepew-week", formatNumber(Math.round(rewardPerWeek * 100) / 100));

      if (price && typeof price.price === "number") {
        setText("calc-usdt-day", "$" + (rewardPerDay * price.price).toFixed(2));
        setText("calc-usdt-week", "$" + (rewardPerWeek * price.price).toFixed(2));
      }
    } catch (_error) {
      relabelOrphanAdjustedCalculator();
    }
  }

  function installOrphanAdjustedCalculator() {
    if (!["home", "dashboard"].includes(document.body.dataset.page || "")) return;
    const hashrateInput = document.getElementById("calc-hashrate");
    const unitSelect = document.getElementById("calc-unit");
    if (hashrateInput) hashrateInput.addEventListener("input", () => window.setTimeout(refreshOrphanAdjustedCalculator, 0));
    if (unitSelect) unitSelect.addEventListener("change", () => window.setTimeout(refreshOrphanAdjustedCalculator, 0));
    relabelOrphanAdjustedCalculator();
    refreshOrphanAdjustedCalculator();
    window.setTimeout(refreshOrphanAdjustedCalculator, 1500);
    window.setTimeout(refreshOrphanAdjustedCalculator, 4500);
  }

  async function refresh() {
    await Promise.all([refreshLeaderboards(), refreshLastObservedPoolBlock(), refreshOrphanAdjustedCalculator()]);
  }

  document.addEventListener("DOMContentLoaded", () => {
    installLastPoolBlockGuard();
    installOrphanAdjustedCalculator();
    refresh();
    window.setTimeout(refreshLastObservedPoolBlock, 1500);
    window.setInterval(refresh, REFRESH_MS);
  });
})();
