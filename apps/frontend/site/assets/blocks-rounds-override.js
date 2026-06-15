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

  function formatDate(value) {
    if (!value) return "-";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString();
  }

  function statusLabel(value) {
    if (!value) return "-";
    return String(value).replace(/_/g, " ").replace(/\b\w/g, function (c) { return c.toUpperCase(); });
  }

  function shortText(value, front, back) {
    const raw = String(value || "");
    const f = front == null ? 8 : front;
    const b = back == null ? 6 : back;
    return raw.length > f + b + 1 ? raw.slice(0, f) + "…" + raw.slice(-b) : raw;
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
    return '<span class="hash-actions"><span class="hash-value mono-compact" title="' + escapeHtml(raw) + '">' + escapeHtml(shortText(raw, 10, 8)) + '</span>' + explorerLink(explorerBlockUrl(raw)) + '</span>';
  }

  function addressText(value) {
    if (!value) return "-";
    const raw = String(value);
    return '<span class="hash-value mono-compact" title="' + escapeHtml(raw) + '">' + escapeHtml(shortText(raw, 7, 5)) + '</span>';
  }

  function renderShareSummary(round) {
    const shares = round && round.shares && typeof round.shares === "object" ? round.shares : null;
    if (!shares || Object.keys(shares).length === 0) {
      const status = statusLabel(round.roundStatus || round.lifecycleStatus || round.status);
      return '<span class="muted">No attributed shares · ' + escapeHtml(status) + '</span>';
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
      return '<div class="round-share-line">' + addressText(item.wallet) + ': <strong>' + item.pct.toFixed(2) + '%</strong>' + score + '</div>';
    }).join("");
  }

  function roundTime(round) {
    return round.submitTimestamp || round.foundAt || round.timestamp || round.createdAt || round.updatedAt || round.generatedAt;
  }

  function sortByTimeDesc(items) {
    return items.slice().sort(function (a, b) {
      return String(roundTime(b) || "").localeCompare(String(roundTime(a) || ""));
    });
  }

  function renderTable(items) {
    if (!Array.isArray(items) || items.length === 0) {
      return '<div class="muted">No round attribution snapshot is currently available.</div>';
    }
    const rows = sortByTimeDesc(items).slice(0, 50).map(function (round) {
      const status = statusLabel(round.roundStatus || round.lifecycleStatus || round.status);
      return '<tr>' +
        '<td data-label="Candidate">' + blockValue(round.candidateHash || round.roundId || "-") + '</td>' +
        '<td data-label="Time">' + escapeHtml(formatDate(roundTime(round))) + '</td>' +
        '<td data-label="Height">' + blockValue(round.matchedHeight || round.height || "-") + '</td>' +
        '<td data-label="Status">' + escapeHtml(status) + '</td>' +
        '<td data-label="Shares">' + formatNumber(round.totalShareCount, 0) + '</td>' +
        '<td data-label="Score">' + formatNumber(round.totalShareScore, 4) + '</td>' +
        '<td data-label="Wallets">' + formatNumber(round.walletCount, 0) + '</td>' +
        '<td data-label="Confirms">' + formatNumber(round.confirmations, 0) + '</td>' +
        '<td data-label="Top attribution">' + renderShareSummary(round) + '</td>' +
        '</tr>';
    }).join("");
    return '<div class="table-wrap"><table class="round-attribution-table"><thead><tr><th>Candidate</th><th>Time</th><th>Height</th><th>Status</th><th>Shares</th><th>Score</th><th>Wallets</th><th>Confirms</th><th>Top attribution</th></tr></thead><tbody>' + rows + '</tbody></table></div>';
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