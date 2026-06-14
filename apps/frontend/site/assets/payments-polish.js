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

  function formatNumber(value) {
    if (typeof value !== "number" || !Number.isFinite(value)) return String(value ?? "-");
    return new Intl.NumberFormat().format(value);
  }

  function sourceCandidates(item) {
    const candidates = item.sourceCandidateIds || item.source_candidate_ids || item.candidates || [];
    return Array.isArray(candidates) ? candidates.filter(Boolean).map(String) : [];
  }

  function candidateDisplay(item, candidatesByHeight) {
    const direct = item.candidateHash || item.candidate_hash || item.blockHash || item.block_hash || item.candidateId || item.candidate_id;
    if (direct) {
      return `<span class="hash-actions"><span class="hash-value mono-compact" title="${escapeHtml(direct)}">${escapeHtml(shortHash(direct))}</span></span>`;
    }

    const sources = sourceCandidates(item);
    if (sources.length === 1) {
      const raw = sources[0];
      return `<span class="hash-actions"><span class="hash-value mono-compact" title="${escapeHtml(raw)}">${escapeHtml(shortHash(raw))}</span></span>`;
    }
    if (sources.length > 1) {
      const title = sources.join("\n");
      return `<span class="payment-source-list" title="${escapeHtml(title)}"><strong>${sources.length} candidates</strong><code>${escapeHtml(shortHash(sources[0]))}</code></span>`;
    }

    const heights = [];
    if (Array.isArray(item.blockHeights)) heights.push(...item.blockHeights);
    if (item.blockHeight !== undefined && item.blockHeight !== null) heights.push(item.blockHeight);
    if (item.height !== undefined && item.height !== null) heights.push(item.height);
    const matched = heights.map((h) => candidatesByHeight.get(String(h))).filter(Boolean);
    if (matched.length === 1) return candidateDisplay(matched[0], candidatesByHeight);
    if (matched.length > 1) return `<span class="payment-source-list"><strong>${matched.length} candidates</strong></span>`;

    return "-";
  }

  function buildCandidateHeightMap(payloads) {
    const map = new Map();
    for (const payload of payloads) {
      const items = payload && Array.isArray(payload.items) ? payload.items : [];
      for (const item of items) {
        if (!item || typeof item !== "object") continue;
        const heights = [item.blockHeight, item.height, item.matchedHeight, item.block_height].filter((v) => v !== undefined && v !== null && v !== "");
        for (const h of heights) map.set(String(h), item);
      }
    }
    return map;
  }

  function polishPaymentsTable(items, candidatesByHeight) {
    const table = document.querySelector("#payments-table table");
    if (!table || !Array.isArray(items) || table.dataset.polished === "1") return;
    table.dataset.polished = "1";
    table.classList.add("payments-table-wide");
    const rows = Array.from(table.querySelectorAll("tbody tr"));
    rows.forEach((row, idx) => {
      const item = items[idx];
      if (!item) return;
      const candidateCell = row.querySelector('td[data-label="Candidate hash"]');
      if (candidateCell && candidateCell.textContent.trim() === "-") {
        candidateCell.innerHTML = candidateDisplay(item, candidatesByHeight);
      }
      const amountCell = row.querySelector('td[data-label="Amount"]');
      if (amountCell) {
        amountCell.innerHTML = `<span class="payment-amount">${escapeHtml(formatNumber(item.amount))}</span>`;
      }
    });
  }

  async function fetchJson(url) {
    try {
      const response = await fetch(url, { cache: "no-store" });
      return response.ok ? response.json() : { items: [] };
    } catch (_error) {
      return { items: [] };
    }
  }

  async function run() {
    if (document.body.dataset.page !== "payments") return;
    const [payments, accepted, rounds] = await Promise.all([
      fetchJson("/api/payments"),
      fetchJson("/api/accepted-candidates"),
      fetchJson("/api/rounds")
    ]);
    const items = Array.isArray(payments.items) ? payments.items : [];
    const candidatesByHeight = buildCandidateHeightMap([accepted, rounds]);
    window.setTimeout(() => polishPaymentsTable(items, candidatesByHeight), 900);
  }

  document.addEventListener("DOMContentLoaded", run);
})();
