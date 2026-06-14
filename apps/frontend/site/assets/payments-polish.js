(function () {
  function shortHash(value) {
    const raw = String(value || "");
    return raw.length > 20 ? `${raw.slice(0, 10)}…${raw.slice(-8)}` : raw;
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function candidateDisplay(item) {
    const direct = item.candidateHash || item.candidateId || item.candidate_hash;
    if (direct) {
      return `<span class="hash-actions"><span class="hash-value mono-compact" title="${escapeHtml(direct)}">${escapeHtml(shortHash(direct))}</span></span>`;
    }
    const sources = Array.isArray(item.sourceCandidateIds) ? item.sourceCandidateIds : [];
    if (sources.length === 1) {
      const raw = sources[0];
      return `<span class="hash-actions"><span class="hash-value mono-compact" title="${escapeHtml(raw)}">${escapeHtml(shortHash(raw))}</span></span>`;
    }
    if (sources.length > 1) {
      const title = sources.join("\n");
      return `<span class="payment-source-list" title="${escapeHtml(title)}"><strong>${sources.length} candidates</strong><code>${escapeHtml(shortHash(sources[0]))}</code></span>`;
    }
    return "-";
  }

  function formatNumber(value) {
    if (typeof value !== "number" || !Number.isFinite(value)) return String(value ?? "-");
    return new Intl.NumberFormat().format(value);
  }

  function polishPaymentsTable(items) {
    const table = document.querySelector("#payments-table table");
    if (!table || !Array.isArray(items)) return;
    table.classList.add("payments-table-wide");
    const rows = Array.from(table.querySelectorAll("tbody tr"));
    rows.forEach((row, idx) => {
      const item = items[idx];
      if (!item) return;
      const candidateCell = row.querySelector('td[data-label="Candidate hash"]');
      if (candidateCell && candidateCell.textContent.trim() === "-") {
        candidateCell.innerHTML = candidateDisplay(item);
      }
      const amountCell = row.querySelector('td[data-label="Amount"]');
      if (amountCell) {
        amountCell.innerHTML = `<span class="payment-amount">${escapeHtml(formatNumber(item.amount))}</span>`;
      }
    });
  }

  async function run() {
    if (document.body.dataset.page !== "payments") return;
    try {
      const response = await fetch("/api/payments", { cache: "no-store" });
      if (!response.ok) return;
      const payload = await response.json();
      const items = Array.isArray(payload.items) ? payload.items : [];
      const apply = () => polishPaymentsTable(items);
      apply();
      const target = document.getElementById("payments-table");
      if (target) {
        new MutationObserver(apply).observe(target, { childList: true, subtree: true });
      }
    } catch (_error) {
      // Leave default rendering intact.
    }
  }

  document.addEventListener("DOMContentLoaded", run);
})();
