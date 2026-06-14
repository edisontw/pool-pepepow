(function () {
  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function formatNumber(value, digits) {
    const n = Number(value);
    if (!Number.isFinite(n)) return "-";
    return new Intl.NumberFormat(undefined, { maximumFractionDigits: digits == null ? 6 : digits }).format(n);
  }

  function statusLabel(value) {
    if (!value) return "-";
    return String(value).replace(/_/g, " ").replace(/\b\w/g, function (c) { return c.toUpperCase(); });
  }

  function shortText(value) {
    const raw = String(value || "");
    return raw.length > 18 ? raw.slice(0, 8) + "…" + raw.slice(-6) : raw;
  }

  function readPercent(data) {
    if (!data || typeof data !== "object") return null;
    const direct = Number(data.sharePercent);
    if (Number.isFinite(direct)) return direct;
    const snake = Number(data.share_percent);
    if (Number.isFinite(snake)) return snake;
    return null;
  }

  function readScore(data) {
    if (!data || typeof data !== "object") return null;
    const direct = Number(data.shareScore);
    if (Number.isFinite(direct)) return direct;
    const snake = Number(data.share_score);
    if (Number.isFinite(snake)) return snake;
    return null;
  }

  function renderShareSummary(round) {
    const shares = round && round.shares && typeof round.shares === "object" ? round.shares : null;
    if (!shares || Object.keys(shares).length === 0) {
      const status = statusLabel(round.roundStatus || round.lifecycleStatus || round.status);
      return '<span class="muted">No attributed shares in current snapshot · ' + escapeHtml(status) + '</span>';
    }

    const entries = Object.entries(shares)
      .map(function (entry) {
        return { wallet: entry[0], data: entry[1], pct: readPercent(entry[1]), score: readScore(entry[1]) };
      })
      .filter(function (item) { return item.pct !== null; })
      .sort(function (a, b) { return b.pct - a.pct; })
      .slice(0, 3);

    if (entries.length === 0) {
      return '<span class="muted">Share attribution present, percent unavailable</span>';
    }

    return entries.map(function (item) {
      const score = item.score === null ? "" : ' <span class="muted">score ' + escapeHtml(formatNumber(item.score, 4)) + '</span>';
      return '<div style="margin-bottom:.2rem;"><span title="' + escapeHtml(item.wallet) + '">' + escapeHtml(shortText(item.wallet)) + '</span>: <strong>' + item.pct.toFixed(2) + '%</strong>' + score + '</div>';
    }).join("");
  }

  function renderTable(items) {
    if (!Array.isArray(items) || items.length === 0) {
      return '<div class="muted">No round attribution snapshot is currently available.</div>';
    }
    const rows = items.slice(0, 50).map(function (round) {
      return '<tr>' +
        '<td data-label="Candidate hash">' + escapeHtml(shortText(round.candidateHash || round.roundId || "-")) + '</td>' +
        '<td data-label="Height">' + escapeHtml(round.matchedHeight || round.height || "-") + '</td>' +
        '<td data-label="Round Status / Review State">' + escapeHtml(statusLabel(round.roundStatus || round.lifecycleStatus || round.status)) + '</td>' +
        '<td data-label="Shares">' + formatNumber(round.totalShareCount, 0) + '</td>' +
        '<td data-label="Score">' + formatNumber(round.totalShareScore, 4) + '</td>' +
        '<td data-label="Wallets">' + formatNumber(round.walletCount, 0) + '</td>' +
        '<td data-label="Confirmations">' + formatNumber(round.confirmations, 0) + '</td>' +
        '<td data-label="Observed Share %">' + renderShareSummary(round) + '</td>' +
        '</tr>';
    }).join("");
    return '<div class="table-wrap"><table><thead><tr><th>Candidate hash</th><th>Height</th><th>Round Status / Review State</th><th>Shares</th><th>Score</th><th>Wallets</th><th>Confirmations</th><th>Observed Share %</th></tr></thead><tbody>' + rows + '</tbody></table></div>';
  }

  async function refreshRoundsTable() {
    if (document.body.dataset.page !== "blocks") return;
    const target = document.getElementById("rounds-table");
    if (!target) return;
    try {
      const response = await fetch("/api/rounds", { cache: "no-store" });
      if (!response.ok) return;
      const payload = await response.json();
      target.innerHTML = renderTable(payload.items || []);
    } catch (_error) {
      // Keep the base table.
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    window.setTimeout(refreshRoundsTable, 800);
    window.setInterval(refreshRoundsTable, 60000);
  });
})();
