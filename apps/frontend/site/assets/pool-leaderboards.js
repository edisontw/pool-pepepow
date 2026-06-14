(function () {
  const REFRESH_MS = 60 * 1000;

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
      shares: numeric(item.shares15m, item.acceptedShares, item.shares, item.shareCount, item.accepted_share_count),
      activeWorkers: numeric(item.activeWorkers, item.workerCount, item.workers)
    }));
  }

  function rows(items, mode) {
    const sorted = items
      .slice()
      .sort((a, b) => mode === "hashrate" ? b.hashrate - a.hashrate : b.shares - a.shares)
      .slice(0, 5);
    if (sorted.length === 0 || sorted.every((item) => (mode === "hashrate" ? item.hashrate : item.shares) <= 0)) {
      return `<div class="leaderboard-empty">No active data in the recent window.</div>`;
    }
    return sorted.map((item, idx) => {
      const value = mode === "hashrate" ? formatHashrate(item.hashrate) : formatNumber(item.shares);
      return `<div class="leaderboard-row">
        <span class="leaderboard-rank">#${idx + 1}</span>
        <strong title="${escapeHtml(item.wallet)}">${escapeHtml(compactWallet(item.wallet))}</strong>
        <span>${escapeHtml(value)}</span>
      </div>`;
    }).join("");
  }

  function render(pool) {
    const target = document.querySelector(".mining-outlook");
    if (!target) return;
    let box = document.getElementById("pool-leaderboards");
    if (!box) {
      box = document.createElement("div");
      box.id = "pool-leaderboards";
      box.className = "leaderboard-grid";
      target.appendChild(box);
    }
    const items = normalize(pool || {});
    box.innerHTML = `
      <section class="leaderboard-card">
        <div class="leaderboard-head"><h4>Live Hashrate Ranking</h4><span>5m estimate</span></div>
        ${rows(items, "hashrate")}
      </section>
      <section class="leaderboard-card">
        <div class="leaderboard-head"><h4>Shares Ranking</h4><span>15m shares</span></div>
        ${rows(items, "shares")}
      </section>`;
  }

  async function fetchPool() {
    const response = await fetch("/api/pool/summary", { cache: "no-store" });
    if (!response.ok) throw new Error("pool summary unavailable");
    return response.json();
  }

  async function refresh() {
    if (document.body.dataset.page !== "dashboard") return;
    try {
      render(await fetchPool());
    } catch (_error) {
      render({ workerDistribution: [] });
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    refresh();
    window.setInterval(refresh, REFRESH_MS);
  });
})();
