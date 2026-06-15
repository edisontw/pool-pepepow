(function () {
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

  function statusLabel(value) {
    if (!value) return "-";
    return String(value).replace(/_/g, " ").replace(/\b\w/g, function (c) { return c.toUpperCase(); });
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

  function blockValue(value) {
    if (value === null || value === undefined || value === "") return "-";
    const raw = String(value);
    return '<span class="hash-actions"><span class="hash-value mono-compact" title="' + escapeHtml(raw) + '">' + escapeHtml(shortText(raw)) + '</span>' + explorerLink(explorerBlockUrl(raw)) + '</span>';
  }

  function itemTime(item) {
    return item.submitTimestamp || item.foundAt || item.timestamp || item.createdAt || item.updatedAt || item.generatedAt;
  }

  function renderTable(items) {
    if (!Array.isArray(items) || items.length === 0) {
      return '<div class="muted">No accepted block candidates found in this snapshot window.</div>';
    }

    const rows = items.slice()
      .sort(function (a, b) { return String(itemTime(b) || "").localeCompare(String(itemTime(a) || "")); })
      .slice(0, 50)
      .map(function (item) {
        return '<tr>' +
          '<td data-label="Time">' + escapeHtml(formatDate(itemTime(item))) + '</td>' +
          '<td data-label="Candidate hash">' + blockValue(item.candidateHash || item.blockHash || item.hash || "-") + '</td>' +
          '<td data-label="Height">' + blockValue(item.matchedHeight || item.height || item.blockHeight || "-") + '</td>' +
          '<td data-label="Status">' + escapeHtml(statusLabel(item.lifecycleStatus || item.status || item.maturityLabel)) + '</td>' +
          '<td data-label="Confirms">' + escapeHtml(formatNumber(item.confirmations)) + '</td>' +
          '<td data-label="Job ID">' + escapeHtml(shortText(item.jobId || "-", 8, 6)) + '</td>' +
          '</tr>';
      }).join("");

    return '<div class="table-wrap"><table class="pool-found-blocks-table"><thead><tr><th>Time</th><th>Candidate hash</th><th>Height</th><th>Status</th><th>Confirms</th><th>Job ID</th></tr></thead><tbody>' + rows + '</tbody></table></div>';
  }

  async function refreshPoolFoundBlocks() {
    if (document.body.dataset.page !== "blocks") return;
    const target = document.getElementById("accepted-candidates-table");
    if (!target) return;
    try {
      const response = await fetch("/api/accepted-candidates", { cache: "no-store" });
      if (!response.ok) return;
      const payload = await response.json();
      target.innerHTML = renderTable(payload.items || []);
    } catch (_error) {
      // Keep the base table.
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    window.setTimeout(refreshPoolFoundBlocks, 500);
    window.setInterval(refreshPoolFoundBlocks, 60000);
  });
})();