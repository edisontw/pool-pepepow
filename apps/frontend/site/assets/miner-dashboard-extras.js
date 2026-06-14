(function () {
  const EXTRA_REFRESH_MS = 30000;
  const BLOCK_REWARD_PEPEW = 7000 * 0.95 * 0.65;

  function escapeHtml(str) {
    if (typeof str !== "string") return "";
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function formatNumber(value) {
    if (typeof value !== "number" || !Number.isFinite(value)) return "-";
    return new Intl.NumberFormat(undefined, { maximumFractionDigits: 8 }).format(value);
  }

  function formatDateTime(value) {
    if (typeof value !== "string" || !value) return null;
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return null;
    return date.toLocaleString();
  }

  function readCount(record, keys) {
    if (!record || typeof record !== "object") return null;
    for (const key of keys) {
      const value = record[key];
      if (typeof value === "number" && Number.isFinite(value) && value >= 0) return value;
    }
    return null;
  }

  function normalizeStatus(value) {
    return String(value || "").trim().toLowerCase().replace(/_/g, "-");
  }

  function calculatePoolAcceptedRate(record) {
    if (!record || typeof record !== "object") return null;
    const explicitRate = readExplicitAcceptedRate(record);
    if (explicitRate !== null) return explicitRate;
    const accepted = readCount(record, ["acceptedSubmits", "accepted_submits", "acceptedShares", "accepted_shares"]);
    const rejected = readCount(record, ["rejectedSubmits", "rejected_submits", "rejectedShares", "rejected_shares"]);
    if (accepted === null || rejected === null) return null;
    const total = accepted + rejected;
    if (total <= 0) return null;
    return accepted / total;
  }

  function readExplicitAcceptedRate(record) {
    if (!record || typeof record !== "object") return null;
    const keys = ["poolAcceptedRate", "pool_accepted_rate", "recentPoolAcceptedRate", "recent_pool_accepted_rate", "acceptedRate", "accepted_rate", "recentAcceptedRate", "recent_accepted_rate"];
    for (const key of keys) {
      const value = record[key];
      if (typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1) return value;
    }
    return null;
  }

  function renderRate(record) {
    const rate = calculatePoolAcceptedRate(record);
    if (rate === null) return '<span class="muted">Not available yet</span>';
    return escapeHtml((rate * 100).toFixed(2) + "%");
  }

  function renderPoolAcceptedRateNote(record) {
    const accepted = readCount(record, ["acceptedSubmits", "accepted_submits", "acceptedShares", "accepted_shares"]);
    const rejected = readCount(record, ["rejectedSubmits", "rejected_submits", "rejectedShares", "rejected_shares"]);
    if (accepted === null || rejected === null) return "Calculated only when pool-side accepted and rejected submit counters are available.";
    return `Pool-side submits: ${formatNumber(accepted)} accepted / ${formatNumber(rejected)} rejected. Miner local invalid solutions are not included.`;
  }

  function paymentSortKey(item) {
    if (!item || typeof item !== "object") return "";
    return String(item.paidAt || item.timestamp || "");
  }

  function paidRoundKeys(result) {
    const keys = new Set();
    const payments = result && Array.isArray(result.recentPayments) ? result.recentPayments : [];
    for (const payment of payments) {
      if (!payment || typeof payment !== "object") continue;
      const ids = Array.isArray(payment.sourceCandidateIds) ? payment.sourceCandidateIds : [];
      for (const id of ids) keys.add(String(id));
      const heights = Array.isArray(payment.blockHeights) ? payment.blockHeights : [];
      for (const height of heights) keys.add(`height:${height}`);
      if (payment.candidateId) keys.add(String(payment.candidateId));
      if (payment.blockHeight) keys.add(`height:${payment.blockHeight}`);
    }
    return keys;
  }

  function walletRoundShare(round, wallet) {
    if (!round || typeof round !== "object" || !wallet) return null;
    const shares = round.shares;
    if (!shares || typeof shares !== "object") return null;
    const item = shares[wallet];
    return item && typeof item === "object" ? item : null;
  }

  function estimatedWalletReward(round, wallet) {
    const share = walletRoundShare(round, wallet);
    if (!share) return 0;
    const percent = readCount(share, ["sharePercent", "share_percent"]);
    if (percent === null) return 0;
    return BLOCK_REWARD_PEPEW * (percent / 100);
  }

  function roundKey(round) {
    if (!round || typeof round !== "object") return "";
    return String(round.candidateHash || round.roundId || round.candidate_hash || round.round_id || "");
  }

  function roundHeightKey(round) {
    const height = readCount(round, ["matchedHeight", "height"]);
    return height === null ? "" : `height:${height}`;
  }

  function calculateRecentRewardLifecycle(roundsPayload, result, wallet) {
    const items = roundsPayload && Array.isArray(roundsPayload.items) ? roundsPayload.items : [];
    const paidKeys = paidRoundKeys(result);
    const lifecycle = {
      scanned: items.length,
      immatureCount: 0,
      immatureAmount: 0,
      maturedUnpaidCount: 0,
      maturedUnpaidAmount: 0,
      latestImmatureHeight: null,
      latestMaturedUnpaidHeight: null,
    };
    for (const round of items) {
      if (!walletRoundShare(round, wallet)) continue;
      const status = normalizeStatus(round.status || round.roundStatus || round.lifecycleStatus);
      if (status === "orphan" || status === "orphaned") continue;
      const amount = estimatedWalletReward(round, wallet);
      const height = readCount(round, ["matchedHeight", "height"]);
      const key = roundKey(round);
      const hkey = roundHeightKey(round);
      const isPaid = (key && paidKeys.has(key)) || (hkey && paidKeys.has(hkey));

      if (status === "confirmed" || status === "mature") {
        if (!isPaid) {
          lifecycle.maturedUnpaidCount += 1;
          lifecycle.maturedUnpaidAmount += amount;
          if (height !== null) lifecycle.latestMaturedUnpaidHeight = lifecycle.latestMaturedUnpaidHeight === null ? height : Math.max(lifecycle.latestMaturedUnpaidHeight, height);
        }
      } else if (status) {
        lifecycle.immatureCount += 1;
        lifecycle.immatureAmount += amount;
        if (height !== null) lifecycle.latestImmatureHeight = lifecycle.latestImmatureHeight === null ? height : Math.max(lifecycle.latestImmatureHeight, height);
      }
    }
    return lifecycle;
  }

  function renderRecordedPaymentsCard(result) {
    const payments = result && Array.isArray(result.recentPayments) ? result.recentPayments : [];
    const totalPaid = readCount(result, ["totalPaidManual", "total_paid_manual"]);
    if (payments.length === 0 && totalPaid === null) return "";
    const latest = payments.slice().sort((a, b) => paymentSortKey(b).localeCompare(paymentSortKey(a)))[0];
    const latestPaidAt = latest ? formatDateTime(latest.paidAt || latest.timestamp) : null;
    const latestAmount = latest && typeof latest.amount === "number" && Number.isFinite(latest.amount) ? latest.amount : null;
    let note = `${formatNumber(payments.length)} recorded payment${payments.length === 1 ? "" : "s"} shown for this wallet.`;
    if (latestPaidAt) {
      note += ` Latest: ${latestPaidAt}`;
      if (latestAmount !== null) note += `, ${formatNumber(latestAmount)} PEPEW.`;
    }
    return `<article class="miner-metric-card">
      <span>Recorded Payments</span>
      <strong>${totalPaid === null ? escapeHtml(formatNumber(payments.length)) : `${escapeHtml(formatNumber(totalPaid))} PEPEW`}</strong>
      <p class="metric-note">${escapeHtml(note)}</p>
    </article>`;
  }

  function renderRewardLifecycleCards(lifecycle) {
    if (!lifecycle || lifecycle.scanned <= 0) return "";
    const immatureNote = `Recent rounds snapshot only. ${formatNumber(lifecycle.scanned)} rounds scanned.` + (lifecycle.latestImmatureHeight === null ? "" : ` Latest height: ${formatNumber(lifecycle.latestImmatureHeight)}.`);
    const unpaidNote = `Recent confirmed rounds minus recorded payment mappings. ${formatNumber(lifecycle.scanned)} rounds scanned.` + (lifecycle.latestMaturedUnpaidHeight === null ? "" : ` Latest height: ${formatNumber(lifecycle.latestMaturedUnpaidHeight)}.`);
    return `<article class="miner-metric-card">
      <span>Recent Immature Rewards</span>
      <strong>${formatNumber(lifecycle.immatureAmount)} PEPEW</strong>
      <p class="metric-note">${formatNumber(lifecycle.immatureCount)} block${lifecycle.immatureCount === 1 ? "" : "s"}. ${escapeHtml(immatureNote)}</p>
    </article>
    <article class="miner-metric-card">
      <span>Recent Matured Unpaid Rewards</span>
      <strong>${formatNumber(lifecycle.maturedUnpaidAmount)} PEPEW</strong>
      <p class="metric-note">${formatNumber(lifecycle.maturedUnpaidCount)} block${lifecycle.maturedUnpaidCount === 1 ? "" : "s"}. ${escapeHtml(unpaidNote)}</p>
    </article>`;
  }

  function renderPoolAcceptedRateCard(result, lifecycle) {
    const summary = result && typeof result.summary === "object" && result.summary ? result.summary : {};
    return `<div id="miner-pending-extras" class="miner-summary-grid" style="margin-top: 1rem;">
      <article class="miner-metric-card">
        <span>Pool Accepted Rate</span>
        <strong>${renderRate(summary)}</strong>
        <p class="metric-note">${escapeHtml(renderPoolAcceptedRateNote(summary))}</p>
      </article>
      ${renderRecordedPaymentsCard(result)}
      ${renderRewardLifecycleCards(lifecycle)}
    </div>`;
  }

  function insertPoolAcceptedRateCard(result, lifecycle) {
    const container = document.getElementById("miner-result");
    if (!container || !result || !result.found) return;
    const existing = document.getElementById("miner-pending-extras");
    if (existing) existing.remove();
    const summaryGrid = container.querySelector(".miner-summary-grid");
    if (!summaryGrid) return;
    summaryGrid.insertAdjacentHTML("afterend", renderPoolAcceptedRateCard(result, lifecycle));
  }

  function addWorkerAcceptedRateColumn(result) {
    const container = document.getElementById("miner-result");
    const workers = result && Array.isArray(result.workers) ? result.workers : [];
    if (!container || workers.length === 0) return;
    const headings = Array.from(container.querySelectorAll("h3"));
    const workersHeading = headings.find((node) => (node.textContent || "").trim().toLowerCase() === "workers");
    if (!workersHeading) return;
    const table = workersHeading.nextElementSibling && workersHeading.nextElementSibling.querySelector ? workersHeading.nextElementSibling.querySelector("table") : null;
    if (!table || table.dataset.acceptedRateEnhanced === "true") return;
    const headerRow = table.querySelector("thead tr");
    if (headerRow) {
      const th = document.createElement("th");
      th.textContent = "Pool Accepted Rate";
      headerRow.appendChild(th);
    }
    table.querySelectorAll("tbody tr").forEach((row, index) => {
      const td = document.createElement("td");
      td.setAttribute("data-label", "Pool Accepted Rate");
      td.innerHTML = renderRate(workers[index]);
      row.appendChild(td);
    });
    table.dataset.acceptedRateEnhanced = "true";
    const note = document.createElement("p");
    note.className = "muted table-note";
    note.textContent = "Pool Accepted Rate uses pool-side accepted/rejected submit counters only. Miner local invalid solutions are not included.";
    table.parentElement.appendChild(note);
  }

  function syncRewardAnalysisAcceptedRate(result) {
    const summary = result && typeof result.summary === "object" && result.summary ? result.summary : {};
    const container = document.getElementById("miner-reward-analysis");
    if (!container || !result || !result.found) return;
    const rows = Array.from(container.querySelectorAll(".metric-grid > div"));
    const row = rows.find((node) => {
      const label = node.querySelector("span");
      return label && (label.textContent || "").trim().toLowerCase() === "accepted rate";
    });
    if (!row) return;
    const label = row.querySelector("span");
    const value = row.querySelector("strong");
    if (label) label.textContent = "Pool Accepted Rate";
    if (value) {
      value.innerHTML = renderRate(summary);
      value.style.fontWeight = "700";
      value.style.color = "";
      value.style.fontSize = "";
    }
    let note = row.querySelector(".metric-note");
    if (!note) {
      note = document.createElement("p");
      note.className = "metric-note";
      row.appendChild(note);
    }
    note.textContent = renderPoolAcceptedRateNote(summary);
  }

  async function fetchJson(url) {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) return null;
    return response.json();
  }

  async function loadMinerExtras(wallet) {
    if (!wallet) return;
    try {
      const result = await fetchJson(`/api/miner/${encodeURIComponent(wallet)}`);
      if (!result) return;
      let lifecycle = null;
      try {
        const rounds = await fetchJson("/api/rounds");
        lifecycle = calculateRecentRewardLifecycle(rounds, result, wallet);
      } catch (_roundsError) {
        lifecycle = null;
      }
      insertPoolAcceptedRateCard(result, lifecycle);
      addWorkerAcceptedRateColumn(result);
      syncRewardAnalysisAcceptedRate(result);
    } catch (_error) {
      // Optional frontend enhancement only.
    }
  }

  function currentWallet() {
    const input = document.getElementById("wallet-input");
    return input ? input.value.trim() : "";
  }

  function setup() {
    const target = document.getElementById("miner-result");
    if (!target) return;
    let timer = null;
    let activeWallet = "";
    let lastLoadedAt = 0;
    let loading = false;
    const schedule = (force) => {
      window.clearTimeout(timer);
      timer = window.setTimeout(async () => {
        const wallet = currentWallet();
        const walletChanged = wallet !== activeWallet;
        const now = Date.now();
        if (!wallet) return;
        if (loading) return;
        if (!force && !walletChanged && now - lastLoadedAt < EXTRA_REFRESH_MS) return;
        loading = true;
        activeWallet = wallet;
        try {
          await loadMinerExtras(wallet);
          lastLoadedAt = Date.now();
        } finally {
          loading = false;
        }
      }, 250);
    };
    const observer = new MutationObserver(() => schedule(false));
    observer.observe(target, { childList: true, subtree: true });
    schedule(true);
  }

  document.addEventListener("DOMContentLoaded", setup);
})();
