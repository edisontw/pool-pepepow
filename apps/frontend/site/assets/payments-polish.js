(function () {
  const PAGE_SIZE = 20;
  let paymentItems = [];
  let paymentPage = 0;

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

  function formatDate(value) {
    if (!value) return "-";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString();
  }

  function explorerBlockUrl(value) {
    if (value === null || value === undefined || value === "") return "";
    return `https://explorer.pepepow.net/block/${encodeURIComponent(String(value))}`;
  }

  function explorerTxUrl(value) {
    if (!value) return "";
    return `https://explorer.pepepow.net/tx/${encodeURIComponent(String(value))}`;
  }

  function explorerAddressUrl(value) {
    if (!value) return "";
    return `https://explorer.pepepow.net/address/${encodeURIComponent(String(value))}`;
  }

  function minerLookupUrl(value) {
    if (!value) return "";
    return `/miner.html?wallet=${encodeURIComponent(String(value))}`;
  }

  function isHash64(value) {
    return typeof value === "string" && /^[0-9a-fA-F]{64}$/.test(value);
  }

  function isPepepowAddress(value) {
    return typeof value === "string" && /^P[1-9A-HJ-NP-Za-km-z]{25,60}$/.test(value);
  }

  function explorerLink(url, label) {
    if (!url) return "";
    return `<a class="explorer-link" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer" title="${escapeHtml(label || "Explorer")}" aria-label="${escapeHtml(label || "Explorer")}">↗</a>`;
  }

  function copyButton(value) {
    if (!value) return "";
    return `<button class="copy-mini" type="button" data-copy-value="${escapeHtml(value)}">Copy</button>`;
  }

  function minerLookupButton(value) {
    if (!value) return "";
    return `<a class="copy-mini" href="${escapeHtml(minerLookupUrl(value))}" title="Open Miner Lookup for this wallet">Miner Lookup</a>`;
  }

  function valueWithActions(value, type) {
    if (value === null || value === undefined || value === "") return "-";
    const raw = String(value);
    let url = "";
    if (type === "txid" && isHash64(raw)) url = explorerTxUrl(raw);
    if (type === "address" && isPepepowAddress(raw)) url = explorerAddressUrl(raw);
    if (type === "block" && (isHash64(raw) || /^\d+$/.test(raw))) url = explorerBlockUrl(raw);
    const action = type === "address" && isPepepowAddress(raw) ? minerLookupButton(raw) : copyButton(raw);
    return `<span class="hash-actions"><span class="hash-value mono-compact" title="${escapeHtml(raw)}">${escapeHtml(shortHash(raw))}</span>${action}${explorerLink(url)}</span>`;
  }

  function blockDisplay(item) {
    if (item.blockHeightRange) return escapeHtml(String(item.blockHeightRange));
    if (Array.isArray(item.blockHeights) && item.blockHeights.length > 0) {
      const sorted = item.blockHeights
        .map((v) => Number(v))
        .filter((v) => Number.isFinite(v))
        .sort((a, b) => a - b);
      if (sorted.length === 1) return valueWithActions(sorted[0], "block");
      if (sorted.length > 1) return `${escapeHtml(String(sorted[0]))}&ndash;${escapeHtml(String(sorted[sorted.length - 1]))}`;
    }
    const height = item.blockHeight ?? item.height ?? item.matchedHeight ?? item.block_height;
    return height !== null && height !== undefined && height !== "" ? valueWithActions(height, "block") : "-";
  }

  function renderPaymentsTable() {
    const target = document.getElementById("payments-table");
    if (!target) return;

    if (!Array.isArray(paymentItems) || paymentItems.length === 0) {
      target.innerHTML = '<div class="muted">No manual payment records are currently available in the public snapshot.</div>';
      return;
    }

    const totalPages = Math.max(1, Math.ceil(paymentItems.length / PAGE_SIZE));
    paymentPage = Math.min(Math.max(paymentPage, 0), totalPages - 1);
    const start = paymentPage * PAGE_SIZE;
    const visible = paymentItems.slice(start, start + PAGE_SIZE);

    const rows = visible.map((item) => `<tr>
      <td data-label="Time">${escapeHtml(formatDate(item.paidAt || item.timestamp))}</td>
      <td data-label="Wallet">${valueWithActions(item.wallet, "address")}</td>
      <td data-label="Amount"><span class="payment-amount">${escapeHtml(formatNumber(item.amount))}</span></td>
      <td data-label="TxID">${valueWithActions(item.txid, "txid")}</td>
      <td data-label="Blocks">${blockDisplay(item)}</td>
      <td data-label="Confirms">${escapeHtml(formatNumber(item.confirmations))}</td>
    </tr>`).join("");

    target.innerHTML = `<div class="table-wrap"><table class="payments-table-wide" data-polished="1">
      <thead><tr><th>Time</th><th>Wallet</th><th>Amount</th><th>TxID</th><th>Blocks</th><th>Confirms</th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>
    <div class="table-pagination" style="display:flex;gap:.65rem;align-items:center;justify-content:flex-end;margin-top:.75rem;flex-wrap:wrap;">
      <span class="muted">Showing ${start + 1}-${Math.min(start + PAGE_SIZE, paymentItems.length)} of ${paymentItems.length}</span>
      <button class="copy-mini" type="button" data-payment-page="${paymentPage - 1}" ${paymentPage <= 0 ? "disabled" : ""}>Prev</button>
      <span class="muted">Page ${paymentPage + 1} / ${totalPages}</span>
      <button class="copy-mini" type="button" data-payment-page="${paymentPage + 1}" ${paymentPage >= totalPages - 1 ? "disabled" : ""}>Next</button>
    </div>`;
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
    const payments = await fetchJson("/api/payments");
    paymentItems = Array.isArray(payments.items) ? payments.items : [];
    paymentItems.sort((a, b) => String(b.paidAt || b.timestamp || "").localeCompare(String(a.paidAt || a.timestamp || "")));

    document.addEventListener("click", (event) => {
      const button = event.target.closest("[data-payment-page]");
      if (!button || button.disabled) return;
      paymentPage = Number(button.getAttribute("data-payment-page"));
      renderPaymentsTable();
    });

    renderPaymentsTable();
  }

  document.addEventListener("DOMContentLoaded", run);
})();