(function () {
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

  function findRecentAcceptedRate(record) {
    if (!record || typeof record !== "object") return null;
    const keys = ["recentAcceptedRate", "recent_accepted_rate", "acceptedRate", "accepted_rate"];
    for (const key of keys) {
      const value = record[key];
      if (typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1) {
        return value;
      }
    }
    return null;
  }

  function renderRate(record) {
    const rate = findRecentAcceptedRate(record);
    if (rate === null) {
      return '<span class="muted">Not available yet</span>';
    }
    return escapeHtml((rate * 100).toFixed(2) + "%");
  }

  function renderPendingMetricCards(result) {
    const summary = result && typeof result.summary === "object" && result.summary ? result.summary : {};
    const pendingConfirmation = summary.pendingConfirmation ?? summary.pendingConfirmations ?? result.pendingConfirmation ?? result.pendingConfirmations;
    const pendingPayout = summary.pendingPayout ?? result.pendingPayout;

    const pendingConfirmationText = typeof pendingConfirmation === "number"
      ? formatNumber(pendingConfirmation)
      : "Not available yet";
    const pendingPayoutText = typeof pendingPayout === "number"
      ? formatNumber(pendingPayout)
      : "Not available yet";

    return `<div id="miner-pending-extras" class="miner-summary-grid" style="margin-top: 1rem;">
      <article class="miner-metric-card">
        <span>Pending Confirmation</span>
        <strong>${escapeHtml(pendingConfirmationText)}</strong>
        <p class="metric-note">Wallet-level pending confirmation is shown only when the API exposes a reliable field.</p>
      </article>
      <article class="miner-metric-card">
        <span>Pending Payout</span>
        <strong>${escapeHtml(pendingPayoutText)}</strong>
        <p class="metric-note">Not a balance estimate. This stays unavailable until payout accounting exposes a reliable wallet field.</p>
      </article>
    </div>`;
  }

  function insertPendingCards(result) {
    const container = document.getElementById("miner-result");
    if (!container || !result || !result.found) return;
    const existing = document.getElementById("miner-pending-extras");
    if (existing) existing.remove();
    const summaryGrid = container.querySelector(".miner-summary-grid");
    if (!summaryGrid) return;
    summaryGrid.insertAdjacentHTML("afterend", renderPendingMetricCards(result));
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
      th.textContent = "Accepted Rate";
      headerRow.appendChild(th);
    }

    table.querySelectorAll("tbody tr").forEach((row, index) => {
      const td = document.createElement("td");
      td.setAttribute("data-label", "Accepted Rate");
      td.innerHTML = renderRate(workers[index]);
      row.appendChild(td);
    });

    table.dataset.acceptedRateEnhanced = "true";

    const note = document.createElement("p");
    note.className = "muted table-note";
    note.textContent = "Worker accepted-rate is shown only when a reliable recent accepted-rate field exists. It is not calculated from lifetime totals.";
    table.parentElement.appendChild(note);
  }

  async function loadMinerExtras(wallet) {
    if (!wallet) return;
    try {
      const response = await fetch(`/api/miner/${encodeURIComponent(wallet)}`, { cache: "no-store" });
      if (!response.ok) return;
      const result = await response.json();
      insertPendingCards(result);
      addWorkerAcceptedRateColumn(result);
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
    const schedule = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => loadMinerExtras(currentWallet()), 150);
    };

    const observer = new MutationObserver(schedule);
    observer.observe(target, { childList: true, subtree: true });
    schedule();
  }

  document.addEventListener("DOMContentLoaded", setup);
})();
