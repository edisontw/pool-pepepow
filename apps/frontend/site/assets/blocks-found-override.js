(function () {
  const PAGE_SIZE = 20;
  const REFRESH_MS = 120000;
  let blockItems = [];
  let blockPage = 0;

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function formatDate(value) {
    if (!value) return "-";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString();
  }

  function formatNumber(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return "-";
    return new Intl.NumberFormat().format(n);
  }

  function firstValue() {
    for (let i = 0; i < arguments.length; i += 1) {
      const value = arguments[i];
      if (value !== null && value !== undefined && value !== "") return value;
    }
    return null;
  }

  function statusLabel(value) {
    if (!value) return "-";
    return String(value).replace(/_/g, " ").replace(/\b\w/g, function (c) { return c.toUpperCase(); });
  }

  function statusClass(value) {
    const raw = String(value || "").toLowerCase();
    if (raw.includes("orphan") || raw.includes("stale") || raw.includes("reject")) return "status-orphan";
    if (raw.includes("immature") || raw.includes("waiting") || raw.includes("unconfirmed")) return "status-immature";
    if (raw.includes("confirmed") || raw.includes("mature") || raw.includes("matched")) return "status-confirmed";
    return "status-candidate";
  }

  function statusBadge(value) {
    const label = statusLabel(value);
    const cls = statusClass(value);
    return '<span class="pool-block-status ' + escapeHtml(cls) + '">' + escapeHtml(label) + '</span>';
  }

  function shortText(value, front, back) {
    const raw = String(value || "");
    const f = front == null ? 10 : front;
    const b = back == null ? 8 : back;
    return raw.length > f + b + 1 ? raw.slice(0, f) + "…" + raw.slice(-b) : raw;
  }

  function explorerBlockUrl(value) {
    if (!value) return "";
    return "https://explorer.pepepow.net/block/" + encodeURIComponent(String(value));
  }

  function explorerLink(url) {
    if (!url) return "";
    return '<a class="explorer-link" href="' + escapeHtml(url) + '" target="_blank" rel="noopener noreferrer" title="Explorer" aria-label="Explorer">↗</a>';
  }

  function candidateValue(value) {
    if (value === null || value === undefined || value === "") return "-";
    const raw = String(value);
    return '<span class="hash-actions"><span class="hash-value mono-compact" title="' + escapeHtml(raw) + '">' + escapeHtml(shortText(raw)) + '</span>' + explorerLink(explorerBlockUrl(raw)) + '</span>';
  }

  function heightValue(value) {
    if (value === null || value === undefined || value === "") return "-";
    return '<span class="mono-compact">' + escapeHtml(String(value)) + '</span>';
  }

  function itemTime(item) {
    return firstValue(item.submitTimestamp, item.foundAt, item.timestamp, item.createdAt, item.updatedAt, item.generatedAt);
  }

  function itemHeight(item) {
    return firstValue(item.matchedHeight, item.height, item.blockHeight, item.block_height);
  }

  function itemConfirmations(item) {
    return firstValue(item.confirmations, item.matchedConfirmations, item.blockConfirmations, item.chainConfirmations, item.confirmationCount);
  }

  function itemStatus(item) {
    return firstValue(item.lifecycleStatus, item.status, item.maturityLabel, item.chainMaturity, item.reviewState);
  }

  function installStyles() {
    if (document.getElementById("pool-found-blocks-style")) return;
    const style = document.createElement("style");
    style.id = "pool-found-blocks-style";
    style.textContent = ".pool-block-status{display:inline-flex;align-items:center;padding:.22rem .55rem;border-radius:999px;font-size:.78rem;font-weight:800;border:1px solid rgba(255,255,255,.12);background:rgba(255,255,255,.06)}.pool-block-status.status-confirmed{color:#81f7b0;border-color:rgba(129,247,176,.35);background:rgba(129,247,176,.12)}.pool-block-status.status-immature{color:#ffd45a;border-color:rgba(255,212,90,.38);background:rgba(255,212,90,.13)}.pool-block-status.status-orphan{color:#ff8a8a;border-color:rgba(255,138,138,.4);background:rgba(255,138,138,.13)}.pool-block-status.status-candidate{color:#8fd7ff;border-color:rgba(143,215,255,.35);background:rgba(143,215,255,.12)}.table-pagination{display:flex;gap:.65rem;align-items:center;justify-content:flex-end;margin-top:.75rem;flex-wrap:wrap}";
    document.head.appendChild(style);
  }

  function renderTable() {
    const target = document.getElementById("accepted-candidates-table");
    if (!target) return;

    if (!Array.isArray(blockItems) || blockItems.length === 0) {
      target.innerHTML = '<div class="muted">No accepted block candidates found in this snapshot window.</div>';
      return;
    }

    const sorted = blockItems.slice().sort(function (a, b) {
      return String(itemTime(b) || "").localeCompare(String(itemTime(a) || ""));
    });
    const totalPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
    blockPage = Math.min(Math.max(blockPage, 0), totalPages - 1);
    const start = blockPage * PAGE_SIZE;
    const visible = sorted.slice(start, start + PAGE_SIZE);

    const rows = visible.map(function (item) {
      return '<tr>' +
        '<td data-label="Time">' + escapeHtml(formatDate(itemTime(item))) + '</td>' +
        '<td data-label="Candidate hash">' + candidateValue(firstValue(item.candidateHash, item.blockHash, item.hash)) + '</td>' +
        '<td data-label="Height">' + heightValue(itemHeight(item)) + '</td>' +
        '<td data-label="Status">' + statusBadge(itemStatus(item)) + '</td>' +
        '<td data-label="Confirms">' + escapeHtml(formatNumber(itemConfirmations(item))) + '</td>' +
        '</tr>';
    }).join("");

    target.innerHTML = '<div class="table-wrap"><table class="pool-found-blocks-table"><thead><tr><th>Time</th><th>Candidate hash</th><th>Height</th><th>Status</th><th>Confirms</th></tr></thead><tbody>' + rows + '</tbody></table></div>' +
      '<div class="table-pagination"><span class="muted">Showing ' + (start + 1) + '-' + Math.min(start + PAGE_SIZE, sorted.length) + ' of ' + sorted.length + '</span>' +
      '<button class="copy-mini" type="button" data-pool-blocks-page="' + (blockPage - 1) + '" ' + (blockPage <= 0 ? "disabled" : "") + '>Prev</button>' +
      '<span class="muted">Page ' + (blockPage + 1) + ' / ' + totalPages + '</span>' +
      '<button class="copy-mini" type="button" data-pool-blocks-page="' + (blockPage + 1) + '" ' + (blockPage >= totalPages - 1 ? "disabled" : "") + '>Next</button></div>';
  }

  async function refreshPoolFoundBlocks() {
    if (document.body.dataset.page !== "blocks") return;
    try {
      const response = await fetch("/api/accepted-candidates", { cache: "no-store" });
      if (!response.ok) return;
      const payload = await response.json();
      blockItems = Array.isArray(payload.items) ? payload.items : [];
      renderTable();
    } catch (_error) {
      // Keep the previous rendered table.
    }
  }

  document.addEventListener("click", function (event) {
    const button = event.target.closest("[data-pool-blocks-page]");
    if (!button || button.disabled) return;
    blockPage = Number(button.getAttribute("data-pool-blocks-page"));
    renderTable();
  });

  document.addEventListener("DOMContentLoaded", function () {
    installStyles();
    window.setTimeout(refreshPoolFoundBlocks, 500);
    window.setInterval(refreshPoolFoundBlocks, REFRESH_MS);
  });
})();