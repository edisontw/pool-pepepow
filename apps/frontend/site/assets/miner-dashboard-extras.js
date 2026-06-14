(function () {
  const EXTRA_REFRESH_MS = 30000;

  function escapeHtml(str) {
    if (typeof str !== "string") return "";
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function formatNumber(value) {
    if (typeof value !== "number" || !Number.isFinite(value)) return "-";
    return new Intl.NumberFormat().format(value);
  }

  function readCount(record, keys) {
    if (!record || typeof record !== "object") return null;
    for (const key of keys) {
      const value = record[key];
      if (typeof value === "number" && Number.isFinite(value) && value >= 0) {
        return value;
      }
    }
    return null;
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
      if (typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1) {
        return value;
      }
    }
    return null;
  }

  function renderRate(record) {
    const rate = calculatePoolAcceptedRate(record);
    if (rate === null) {
      return '<span class="muted">Not available yet</span>';
    }
    return escapeHtml((rate * 100).toFixed(2) + "%");
  }

  function renderPoolAcceptedRateNote(record) {
    const accepted = readCount(record, ["acceptedSubmits", "accepted_submits", "acceptedShares", "accepted_shares"]);
    const rejected = readCount(record, ["rejectedSubmits", "rejected_submits", "rejectedShares", "rejected_shares"]);
    if (accepted === null || rejected === null) {
      return "Calculated only when pool-side accepted and rejected submit counters are available.";
    }
    return `Pool-side submits: ${formatNumber(accepted)} accepted / ${formatNumber(rejected)} rejected. Miner local invalid solutions are not included.`;
  }

  function normalizeStatus(value) {
    return String(value || "").trim().toLowerCase().replace(/_/g, "-");
  }

  function roundHasWallet(round, wallet) {
    if (!round || typeof round !== "object" || !wallet) return false;
    const shares = round.shares;
    return shares && typeof shares === "object" && Object.prototype.hasOwnProperty.call(shares, wallet);
  }

  function isConfirmedRound(round) {
    const status = normalizeStatus(round.status || round.roundStatus || round.lifecycleStatus);
    return status === "confirmed" || status === "mature" || status === "paid" || status === "paid-manual";
  }

  function isOrphanRound(round) {
    const status = normalizeStatus(round.status || round.roundStatus || round.lifecycleStatus);
    return status === "orphan" || status === "orphaned";
  }

  function calculatePendingConfirmation(roundsPayload, wallet) {
    const items = roundsPayload && Array.isArray(roundsPayload.items) ? roundsPayload.items : [];
    let count = 0;
    let latestHeight = null;
    for (const round of items) {
      if (!roundHasWallet(round, wallet)) continue;
      if (isConfirmedRound(round) || isOrphanRound(round)) continue;
      count += 1;
      const height = readCount(round, ["matchedHeight", "height"]);
      if (height !== null) latestHeight = latestHeight === null ? height : Math.max(latestHeight, height);
    }
    return { count, latestHeight, scanned: items.length };
  }

  function renderPendingMetricCards(result, pendingInfo) {
    const summary = result && typeof result.summary === "object" && result.summary ? result.summary : {};
    const explicitPendingConfirmation = summary.pendingConfirmation ?? summary.pendingConfirmations ?? result.pendingConfirmation ?? result.pendingConfirmations;
    const pendingPayout = summary.pendingPayout ?? result.pendingPayout;

    let pendingConfirmationText = "Not available yet";
    let pendingConfirmationNote = "Wallet-level pending confirmation is shown only when round attribution data is available.";
    if (typeof explicitPendingConfirmation === "number") {
      pendingConfirmationText = formatNumber(explicitPendingConfirmation);
      pendingConfirmationNote = "API-provided wallet-level pending confirmation count.";
    } else if (pendingInfo && typeof pendingInfo.count === "number") {
      pendingConfirmationText = formatNumber(pendingInfo.count);
      pendingConfirmationNote = `Read-only count from recent rounds involving this wallet. ${formatNumber(pendingInfo.scanned)} recent rounds scanned.`;
      if (typeof pendingInfo.latestHeight === "number") {
        pendingConfirmationNote += ` Latest pending height: ${formatNumber(pendingInfo.latestHeight)}.`;
      }
    }

    const pendingPayoutText = typeof pendingPayout === "number"
      ? formatNumber(pendingPayout)
      : "Not available yet";

    return `<div id="miner-pending-extras" class="miner-summary-grid" style="margin-top: 1rem;">
      <article class="miner-metric-card">
        <span>Pool Accepted Rate</span>
        <strong>${renderRate(summary)}</strong>
        <p class="metric-note">${escapeHtml(renderPoolAcceptedRateNote(summary))}</p>
      </article>
      <article class="miner-metric-card">
        <span>Pending Confirmation</span>
        <strong>${escapeHtml(pendingConfirmationText)}</strong>
        <p class="metric-note">${escapeHtml(pendingConfirmationNote)}</p>
      </article>
      <article class="miner-metric-card">
        <span>Pending Payout</span>
        <strong>${escapeHtml(pendingPayoutText)}</strong>
        <p class="metric-note">Not a balance estimate. This stays unavailable until payout accounting exposes a reliable wallet field.</p>
      </article>
    </div>`;
  }

  function insertPendingCards(result, pendingInfo) {
    const container = document.getElementById("miner-result");
    if (!container || !result || !result.found) return;
    const existing = document.getElementById("miner-pending-extras");
    if (existing) existing.remove();
    const summaryGrid = container.querySelector(".miner-summary-grid");
    if (!summaryGrid) return;
    summaryGrid.insertAdjacentHTML("afterend", renderPendingMetricCards(result, pendingInfo));
  }

  function addWorkerAcceptedRateColumn(result) {
    const container = document.getElementById("miner-result");
    const workers = result && Array.isArray(result.workers) ? result.workers : [];
    if (!container || workers.length === 0) return;

    const headings = Array.from(container.querySelectorAll("h3"));
    const workersHeading = headings.find((node) => (node.textContent || "").trim().toLowerCase() === "workers");
    if (!workersHeading) return;

    const table = workersHeading.nextElementSibling && workersHeading.nextElementSibling.querySelector
      ? workersHeading.nextElementSibling.querySelector("table")
      : null;
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
      let pendingInfo = null;
      try {
        const rounds = await fetchJson("/api/rounds");
        pendingInfo = calculatePendingConfirmation(rounds, wallet);
      } catch (_roundsError) {
        pendingInfo = null;
      }
      insertPendingCards(result, pendingInfo);
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
