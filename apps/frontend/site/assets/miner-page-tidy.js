(function () {
  function walletFromUrl() {
    try {
      const params = new URLSearchParams(window.location.search || "");
      return params.get("wallet") || "";
    } catch (_error) {
      return "";
    }
  }

  function currentWallet() {
    const input = document.getElementById("wallet-input");
    return (input && input.value ? input.value : walletFromUrl()).trim();
  }

  function setWalletFromUrl() {
    const wallet = walletFromUrl().trim();
    if (!wallet) return;
    const input = document.getElementById("wallet-input");
    if (input && !input.value.trim()) input.value = wallet;
  }

  function installStyles() {
    if (document.getElementById("miner-page-tidy-styles")) return;
    const style = document.createElement("style");
    style.id = "miner-page-tidy-styles";
    style.textContent = `
      #miner-result { display: grid; gap: 0.9rem; }
      #miner-result > h2 { margin: 1.1rem 0 0; }
      #miner-result > h3 { margin: 0.65rem 0 -0.15rem; font-size: 1rem; color: rgba(235,245,255,.88); }
      .miner-wallet-context {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        gap: .7rem 1rem;
        align-items: center;
        padding: .8rem .9rem;
        border: 1px solid rgba(255,255,255,.08);
        border-radius: 14px;
        background: rgba(255,255,255,.025);
      }
      .miner-wallet-context .miner-wallet-label {
        display: block;
        margin-bottom: .28rem;
        color: var(--muted);
        font-size: .72rem;
        letter-spacing: .08em;
        text-transform: uppercase;
      }
      .miner-wallet-context .miner-wallet-value {
        display: flex;
        align-items: center;
        gap: .45rem;
        min-width: 0;
      }
      .miner-wallet-context .miner-wallet-value code {
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        font-size: .88rem;
      }
      .miner-mode-list { display: flex; flex-wrap: wrap; gap: .4rem; justify-content: flex-end; }
      .miner-mode-badge {
        display: inline-flex;
        align-items: center;
        min-height: 1.55rem;
        padding: .18rem .5rem;
        border-radius: 999px;
        border: 1px solid rgba(255,255,255,.1);
        background: rgba(255,255,255,.045);
        font-size: .67rem;
        font-weight: 800;
        letter-spacing: .08em;
      }
      .miner-mode-badge[data-mode="solo"] { border-color: rgba(255,205,92,.35); background: rgba(255,205,92,.09); }
      .miner-mode-heading {
        display: flex;
        align-items: center;
        gap: .55rem;
        padding-top: .2rem;
        border-top: 1px solid rgba(255,255,255,.075);
        font-size: 1.12rem;
      }
      .miner-mode-heading:first-of-type { border-top: 0; }
      .miner-mode-heading .miner-mode-badge { flex: 0 0 auto; }
      #miner-result .miner-summary-grid {
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: .6rem;
        margin: 0;
      }
      #miner-result .miner-metric-card {
        min-width: 0;
        padding: .72rem .78rem;
        border-radius: 12px;
      }
      #miner-result .miner-metric-card strong { font-size: clamp(1rem, 2vw, 1.22rem); }
      #miner-result .metric-note { margin-top: .35rem; font-size: .72rem; line-height: 1.35; }
      #miner-result .table-wrap { margin-top: 0; }
      #miner-result table { margin-top: 0; }
      #miner-result .pagination-controls { margin-top: .55rem; }
      .miner-hashrate-panel { margin-top: .95rem !important; }
      #miner-reward-analysis {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(min(100%, 340px), 1fr));
        gap: .8rem;
        margin-top: .9rem;
      }
      #miner-reward-analysis > .panel { margin-top: 0 !important; min-width: 0; }
      @media (max-width: 900px) {
        #miner-result .miner-summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      }
      @media (max-width: 640px) {
        .miner-wallet-context { grid-template-columns: 1fr; }
        .miner-mode-list { justify-content: flex-start; }
        #miner-result .miner-summary-grid { grid-template-columns: 1fr 1fr; }
        #miner-result .miner-metric-card { padding: .65rem; }
        #miner-result > h3 { margin-top: .45rem; }
      }
      @media (max-width: 420px) {
        #miner-result .miner-summary-grid { grid-template-columns: 1fr; }
      }
    `;
    document.head.appendChild(style);
  }

  function removeRedundantWalletColumns(root) {
    if (!root) return;
    root.querySelectorAll("table").forEach(function (table) {
      if (table.dataset.minerTidied === "1") return;
      const headerCells = Array.from(table.querySelectorAll("thead th"));
      const walletIndex = headerCells.findIndex(function (cell) {
        return cell.textContent.trim().toLowerCase() === "wallet";
      });
      if (walletIndex >= 0) {
        table.querySelectorAll("tr").forEach(function (row) {
          const cells = row.children;
          if (cells[walletIndex]) cells[walletIndex].remove();
        });
      }
      Array.from(table.querySelectorAll('td[data-label="TxID"] [data-copy-value]')).forEach(function (button) {
        button.remove();
      });
      table.dataset.minerTidied = "1";
    });
  }

  function decorateModeHeadings(root) {
    let hasPool = false;
    let hasSolo = false;
    root.querySelectorAll("h2").forEach(function (heading) {
      if (heading.dataset.minerModeHeading === "1") {
        const mode = heading.dataset.mode;
        if (mode === "pool") hasPool = true;
        if (mode === "solo") hasSolo = true;
        return;
      }
      const text = heading.textContent.trim().toUpperCase();
      let mode = "";
      let label = "";
      if (text === "POOL MINING") {
        mode = "pool";
        label = "Pool mining";
        hasPool = true;
      } else if (text === "PURE SOLO MINING") {
        mode = "solo";
        label = "Pure SOLO mining";
        hasSolo = true;
      }
      if (!mode) return;
      heading.classList.add("miner-mode-heading");
      heading.dataset.minerModeHeading = "1";
      heading.dataset.mode = mode;
      heading.innerHTML = `<span class="miner-mode-badge" data-mode="${mode}">${mode === "solo" ? "SOLO" : "POOL"}</span><span>${label}</span>`;
    });
    return { hasPool, hasSolo };
  }

  function syncWalletContext(root, modes) {
    const wallet = currentWallet();
    const hasData = modes.hasPool || modes.hasSolo;
    let context = root.querySelector(":scope > .miner-wallet-context");
    if (!wallet || !hasData) {
      if (context) context.remove();
      return;
    }

    const signature = `${wallet}|${modes.hasPool ? 1 : 0}|${modes.hasSolo ? 1 : 0}`;
    if (context && context.dataset.signature === signature) return;
    if (!context) {
      context = document.createElement("div");
      context.className = "miner-wallet-context";
      root.prepend(context);
    }
    context.dataset.signature = signature;

    const badges = [];
    if (modes.hasPool) badges.push('<span class="miner-mode-badge" data-mode="pool">POOL DATA</span>');
    if (modes.hasSolo) badges.push('<span class="miner-mode-badge" data-mode="solo">SOLO DATA</span>');
    const explorer = `https://explorer.pepepow.net/address/${encodeURIComponent(wallet)}`;
    context.innerHTML = `
      <div>
        <span class="miner-wallet-label">Wallet</span>
        <div class="miner-wallet-value">
          <code title="${wallet}">${wallet}</code>
          <button class="copy-mini" type="button" data-copy-value="${wallet}">Copy</button>
          <a class="explorer-link" href="${explorer}" target="_blank" rel="noopener noreferrer" title="Open wallet in explorer" aria-label="Open wallet in explorer">↗</a>
        </div>
      </div>
      <div class="miner-mode-list" aria-label="Mining modes with recorded data">${badges.join("")}</div>`;
  }

  function tidyMinerResult() {
    const root = document.getElementById("miner-result");
    if (!root) return;
    removeRedundantWalletColumns(root);
    const modes = decorateModeHeadings(root);
    syncWalletContext(root, modes);
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelector('[aria-label="Pure SOLO testing notice"]')?.remove();
    setWalletFromUrl();
    installStyles();
    const target = document.getElementById("miner-result");
    if (!target) return;
    const observer = new MutationObserver(function () {
      window.setTimeout(tidyMinerResult, 0);
    });
    observer.observe(target, { childList: true, subtree: true });
    tidyMinerResult();
  });
})();
