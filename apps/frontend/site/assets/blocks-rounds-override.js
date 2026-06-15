(function () {
  const PAGE_SIZE = 20;
  const REFRESH_MS = 120000;
  let roundItems = [];
  let roundPage = 0;

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
    if (raw.includes("confirmed") || raw.includes("mature") || raw.includes("matched") || raw.includes("payable")) return "status-confirmed";
    return "status-candidate";
  }

  function statusBadge(value) {
    const label = statusLabel(value);
    return '<span class="pool-block-status ' + escapeHtml(statusClass(value)) + '">' + escapeHtml(label) + '</span>';
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

  function candidateValue(value) {
    if (value === null || value === undefined || value === "") return "-";
    const raw = String(value);
    return '<span class="hash-actions"><span class="hash-value mono-compact" title="' + escapeHtml(raw) + '">' + escapeHtml(shortText(raw, 10, 8)) + '</span>' + explorerLink(explorerBlockUrl(raw)) + '</span>';
  }

  function heightValue(value) {
    if (value === null || value === undefined || value === "") return "-";
    return '<span class="mono-compact">' + escapeHtml(String(value)) + '</span>';
  }

  function addressText(value) {
    if (!value) return "-";
    const raw = String(value);
    return '<span class="hash-value mono-compact" title="' + escapeHtml(raw) + '">' + escapeHtml(shortText(raw, 7, 5)) + '</span>';
  }

  function renderShareSummary(round) {
    const shares = round && round.shares && typeof round.shares === "object" ? round.shares : null;
    if (!shares || Object.keys(shares).length === 0) {
      return '<span class="muted">No attributed shares</span>';
    }

    const entries = Object.entries(shares)
      .map(function (entry) {
        return { wallet: entry[0], data: entry[1], pct: readPercent(entry[1]), score: readScore(entry[1]) };
      })
      .filter(function (item) { return item.pct !== null; })
      .sort(function (a, b) { return b.pct - a.pct; })
      .slice(0, 3);

    if (entries.length === 0) return '<span class="muted">Share attribution present, percent unavailable</span>';

    return entries.map(function (item) {
      const score = item.score === null ? "" : ' <span class="muted">score ' + escapeHtml(formatNumber(item.score, 4)) + '</span>';
      return '<div class="round-share-line">' + addressText(item.wallet) + ': <strong>' + item.pct.toFixed(2) + '%</strong>' + score + '</div>';
    }).join("");
  }

  function roundTime(round) {
    return firstValue(round.submitTimestamp, round.foundAt, round.timestamp, round.createdAt, round.updatedAt, round.generatedAt);
  }

  function roundHeight(round) {
    return firstValue(round.matchedHeight, round.height, round.blockHeight, round.block_height);
  }

  function roundConfirmations(round) {
    return firstValue(round.confirmations, round.matchedConfirmations, round.blockConfirmations, round.chainConfirmations, round.confirmationCount);
  }

  function roundStatus(round) {
    return firstValue(round.roundStatus, round.lifecycleStatus, round.status, round.maturityLabel, round.reviewState);
  }

  function installStyles() {
    if (document.getElementById("round-attribution-style")) return;
    const style = document.createElement("style");
    style.id = "round-attribution-style";
    style.textContent = ".pool-block-status{display:inline-flex;align-items:center;padding:.22rem .55rem;border-radius:999px;font-size:.78rem;font-weight:800;border:1px solid rgba(255,255,255,.12);background:rgba(255,255,255,.06)}.pool-block-status.status-confirmed{color:#81f7b0;border-color:rgba(129,247,176,.35);background:rgba(129,247,176,.12)}.pool-block-status.status-immature{color:#ffd45a;border-color:rgba(255,212,90,.38);background:rgba(255,212,90,.13)}.pool-block-status.status-orphan{color:#ff8a8a;border-color:rgba(255,138,138,.4);background:rgba(255,138,138,.13)}.pool-block-status.status-candidate{color:#8fd7ff;border-color:rgba(143,215,255,.35);background:rgba(143,215,255,.12)}.table-pagination{display:flex;gap:.65rem;align-items:center;justify-content:flex-end;margin-top:.75rem;flex-wrap:wrap}";
    document.head.appendChild(style);
  }

  function renderTable() {
    const target = document.getElementById("rounds-table");
    if (!target) return;

    if (!Array.isArray(roundItems) || roundItems.length === 0) {
      target.innerHTML = '<div class="muted">No round attribution snapshot is currently available.</div>';
      return;
    }

    const sorted = roundItems.slice().sort(function (a, b) {
      return String(roundTime(b) || "").localeCompare(String(roundTime(a) || ""));
    });
    const totalPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
    roundPage = Math.min(Math.max(roundPage, 0), totalPages - 1);
    const start = roundPage * PAGE_SIZE;
    const visible = sorted.slice(start, start + PAGE_SIZE);

    const rows = visible.map(function (round) {
      return '<tr>' +
        '<td data-label="Time">' + escapeHtml(formatDate(roundTime(round))) + '</td>' +
        '<td data-label="Candidate hash">' + candidateValue(firstValue(round.candidateHash, round.roundId)) + '</td>' +
        '<td data-label="Height">' + heightValue(roundHeight(round)) + '</td>' +
        '<td data-label="Status">' + statusBadge(roundStatus(round)) + '</td>' +
        '<td data-label="Shares">' + formatNumber(round.totalShareCount, 0) + '</td>' +
        '<td data-label="Top attribution">' + renderShareSummary(round) + '</td>' +
        '<td data-label="Confirms">' + formatNumber(roundConfirmations(round), 0) + '</td>' +
        '</tr>';
    }).join("");

    target.innerHTML = '<div class="table-wrap"><table class="round-attribution-table"><thead><tr><th>Time</th><th>Candidate hash</th><th>Height</th><th>Status</th><th>Shares</th><th>Top attribution</th><th>Confirms</th></tr></thead><tbody>' + rows + '</tbody></table></div>' +
      '<div class="table-pagination"><span class="muted">Showing ' + (start + 1) + '-' + Math.min(start + PAGE_SIZE, sorted.length) + ' of ' + sorted.length + '</span>' +
      '<button class="copy-mini" type="button" data-rounds-page="' + (roundPage - 1) + '" ' + (roundPage <= 0 ? "disabled" : "") + '>Prev</button>' +
      '<span class="muted">Page ' + (roundPage + 1) + ' / ' + totalPages + '</span>' +
      '<button class="copy-mini" type="button" data-rounds-page="' + (roundPage + 1) + '" ' + (roundPage >= totalPages - 1 ? "disabled" : "") + '>Next</button></div>';
  }

  async function refreshRoundsTable() {
    if (document.body.dataset.page !== "blocks") return;
    try {
      const response = await fetch("/api/rounds", { cache: "no-store" });
      if (!response.ok) return;
      const payload = await response.json();
      roundItems = Array.isArray(payload.items) ? payload.items : [];
      renderTable();
    } catch (_error) {
      // Keep the previous rendered table.
    }
  }

  document.addEventListener("click", function (event) {
    const button = event.target.closest("[data-rounds-page]");
    if (!button || button.disabled) return;
    roundPage = Number(button.getAttribute("data-rounds-page"));
    renderTable();
  });

  document.addEventListener("DOMContentLoaded", function () {
    installStyles();
    window.setTimeout(refreshRoundsTable, 800);
    window.setInterval(refreshRoundsTable, REFRESH_MS);
  });
})();