(function () {
  const SNAPSHOT_URL = "/pool-wallet-monitor.json";
  const POOL_WALLET = "PKTwq3nHNxwcVgDX4QwVxQGX5DYjJB8nho";

  function setText(id, value) {
    const node = document.getElementById(id);
    if (node) node.textContent = value;
  }

  function setHtml(id, value) {
    const node = document.getElementById(id);
    if (node) node.innerHTML = value;
  }

  function ensurePoolWalletWatchStyles() {
    if (document.getElementById("pool-wallet-watch-style")) return;
    const style = document.createElement("style");
    style.id = "pool-wallet-watch-style";
    style.textContent = `
      .pool-wallet-watch{display:grid;gap:.55rem;overflow:hidden;padding:1rem!important}
      .pool-wallet-watch .eyebrow{margin-bottom:-.28rem;font-size:.62rem;letter-spacing:.1em}
      .pool-wallet-watch h3{margin:0;font-size:clamp(.86rem,1.25vw,.98rem);line-height:1.15}
      .pool-wallet-watch-hero{display:grid;gap:.24rem;padding:.72rem .78rem;border-radius:12px;border:1px solid rgba(129,247,176,.2);background:linear-gradient(135deg,rgba(129,247,176,.11),rgba(55,196,255,.05))}
      .pool-wallet-watch-status{width:fit-content;padding:.18rem .42rem;border-radius:999px;background:rgba(238,245,248,.09);color:rgba(235,245,255,.78);font-size:.56rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase}
      .pool-wallet-watch-main{font-size:clamp(1.18rem,3vw,1.55rem);line-height:1.05;letter-spacing:.015em;word-break:break-word}
      .pool-wallet-watch-body{display:grid;grid-template-columns:minmax(0,1fr);gap:.5rem}
      .pool-wallet-watch-address-card,.pool-wallet-watch-summary{display:grid;gap:.24rem;padding:.58rem .62rem;border-radius:11px;background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.075)}
      .pool-wallet-watch-address-card span,.pool-wallet-watch-summary span{color:var(--muted);font-size:.55rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase}
      .pool-wallet-watch-address-card code{display:block;white-space:normal;overflow-wrap:anywhere;font-size:clamp(.64rem,1.5vw,.76rem);line-height:1.32;font-weight:800;color:rgba(238,245,248,.92)}
      .pool-wallet-watch-summary strong{font-size:.72rem;line-height:1.22}
      .pool-wallet-watch-summary p{margin:0;color:var(--muted);font-size:.64rem;line-height:1.35}
      .pool-wallet-watch-note{margin:0;color:rgba(190,205,216,.84);font-size:.64rem;line-height:1.35}
      .pool-wallet-watch-actions{display:flex;align-items:center;justify-content:flex-start;gap:.45rem;flex-wrap:wrap;margin-top:-.1rem}
      .pool-wallet-watch-actions a{display:inline-flex;align-items:center;justify-content:center;min-height:1.62rem;padding:.32rem .55rem;border-radius:8px;border:1px solid rgba(55,196,255,.32);background:rgba(55,196,255,.08);color:var(--accent-alt);font-size:.62rem;font-weight:800;text-decoration:none}
      .pool-wallet-watch.is-ok .pool-wallet-watch-status{background:rgba(129,247,176,.16);color:#a8ffc8}
      .pool-wallet-watch.is-guarded .pool-wallet-watch-status{background:rgba(255,212,90,.16);color:#ffe08a}
      .pool-wallet-watch.is-alert .pool-wallet-watch-status{background:rgba(255,118,118,.15);color:#ffb0b0}
      @media(min-width:720px){.pool-wallet-watch-body{grid-template-columns:minmax(0,.92fr) minmax(0,1.08fr)}}
    `;
    document.head.appendChild(style);
  }

  function ensurePoolWalletWatchCard() {
    ensurePoolWalletWatchStyles();
    let root = document.getElementById("pool-wallet-watch-card");
    if (root) return root;

    const poolPositioning = document.querySelector(".pool-about");
    const target = poolPositioning?.parentElement || document.querySelector(".dashboard-right") || document.querySelector("main.page-grid");
    if (!target) return null;

    root = document.createElement("section");
    root.id = "pool-wallet-watch-card";
    root.className = "panel pool-wallet-watch";
    root.setAttribute("aria-labelledby", "pool-wallet-watch-title");
    root.innerHTML = `
      <p class="eyebrow">Pool Wallet Watch</p>
      <h3 id="pool-wallet-watch-title">24h Pool Wallet Growth</h3>
      <article class="pool-wallet-watch-hero" aria-live="polite">
        <span class="pool-wallet-watch-status" id="pool-wallet-watch-status">Waiting for monitor</span>
        <strong class="pool-wallet-watch-main" id="pool-wallet-watch-main">-</strong>
      </article>
      <div class="pool-wallet-watch-body">
        <article class="pool-wallet-watch-address-card">
          <span>Pool reward wallet</span>
          <code id="pool-wallet-watch-address">${POOL_WALLET}</code>
        </article>
        <article class="pool-wallet-watch-summary">
          <span>Status</span>
          <strong id="pool-wallet-watch-headline">Loading wallet monitor...</strong>
          <p id="pool-wallet-watch-sub">Fetching latest 24h wallet growth snapshot...</p>
        </article>
      </div>
      <p class="pool-wallet-watch-note" id="pool-wallet-watch-note">Server-side monitor snapshot is loading.</p>
      <div class="pool-wallet-watch-actions"><a id="pool-wallet-watch-explorer" href="https://explorer.pepepow.net/address/${POOL_WALLET}" target="_blank" rel="noopener noreferrer">Open explorer ↗</a></div>
    `;

    if (poolPositioning && poolPositioning.nextSibling) {
      target.insertBefore(root, poolPositioning.nextSibling);
    } else if (poolPositioning) {
      target.appendChild(root);
    } else {
      target.appendChild(root);
    }
    return root;
  }

  function formatPepew(value) {
    if (typeof value !== "number" || !Number.isFinite(value)) return "-";
    return new Intl.NumberFormat(undefined, {
      maximumFractionDigits: Math.abs(value) >= 1000000 ? 0 : 3
    }).format(value);
  }

  function formatWindow(hours, sampleHours) {
    const labelHours = typeof hours === "number" && Number.isFinite(hours) ? hours : 24;
    const label = Number.isInteger(labelHours) ? `${labelHours}h` : `${labelHours.toFixed(1)}h`;
    if (typeof sampleHours === "number" && Number.isFinite(sampleHours) && sampleHours > 0 && sampleHours < labelHours * 0.75) {
      return `last ${sampleHours.toFixed(sampleHours >= 10 ? 0 : 1)}h sample`;
    }
    return `last ${label}`;
  }

  function formatAge(value) {
    if (!value) return "-";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "-";
    const minutes = Math.max(0, Math.round((Date.now() - date.getTime()) / 60000));
    if (minutes < 1) return "just now";
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.round(minutes / 60);
    return `${hours}h ago`;
  }

  function statusLabel(status) {
    if (status === "ok") return "OK";
    if (status === "warning") return "Watch";
    if (status === "critical") return "Check needed";
    return "Waiting for monitor";
  }

  function statusClass(status) {
    if (status === "ok") return "is-ok";
    if (status === "warning") return "is-guarded";
    if (status === "critical") return "is-alert";
    return "";
  }

  function updateExplorerLink(url) {
    const link = document.getElementById("pool-wallet-watch-explorer");
    if (link && url) link.href = url;
  }

  async function loadPoolWalletWatch() {
    const root = ensurePoolWalletWatchCard();
    if (!root) return;

    try {
      const response = await fetch(SNAPSHOT_URL, { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      const status = typeof data.status === "string" ? data.status : "unknown";
      const windowDelta = typeof data.primaryWindowDeltaTotalReceived === "number" ? data.primaryWindowDeltaTotalReceived : null;
      const windowHours = typeof data.primaryWindowHours === "number" ? data.primaryWindowHours : 24;
      const sampleHours = typeof data.primaryWindowSampleHours === "number" ? data.primaryWindowSampleHours : null;
      const fallbackDelta = typeof data.deltaTotalReceived === "number" ? data.deltaTotalReceived : null;
      const displayDelta = windowDelta !== null ? windowDelta : fallbackDelta;
      const headline = data.headline || statusLabel(status);
      const summary = data.summary || "Pool wallet monitor has no summary yet.";
      const updatedAt = data.generatedAt || null;
      const explorerUrl = data.explorerWalletUrl || `https://explorer.pepepow.net/address/${POOL_WALLET}`;
      const wallet = data.poolWallet || POOL_WALLET;
      const windowLabel = windowDelta !== null ? formatWindow(windowHours, sampleHours) : "latest sample";

      root.classList.remove("is-ok", "is-guarded", "is-alert");
      const cls = statusClass(status);
      if (cls) root.classList.add(cls);

      setText("pool-wallet-watch-status", statusLabel(status));
      setText("pool-wallet-watch-headline", headline);
      setText("pool-wallet-watch-address", wallet);
      setText("pool-wallet-watch-main", displayDelta !== null ? `${displayDelta >= 0 ? "+" : ""}${formatPepew(displayDelta)} PEPEW` : "No previous sample");
      setText("pool-wallet-watch-sub", `${windowLabel} · Updated ${formatAge(updatedAt)}`);
      setText("pool-wallet-watch-note", summary);
      updateExplorerLink(explorerUrl);
    } catch (error) {
      root.classList.remove("is-ok", "is-guarded");
      root.classList.add("is-alert");
      setText("pool-wallet-watch-status", "Waiting for monitor");
      setText("pool-wallet-watch-headline", "No server snapshot yet");
      setText("pool-wallet-watch-address", POOL_WALLET);
      setText("pool-wallet-watch-main", "-");
      setText("pool-wallet-watch-sub", "Run live-stratum pool wallet monitor to publish the snapshot.");
      setText("pool-wallet-watch-note", "Server-side monitor snapshot is not available yet.");
      updateExplorerLink(`https://explorer.pepepow.net/address/${POOL_WALLET}`);
      console.warn("Pool wallet monitor snapshot unavailable:", error);
    }
  }

  document.addEventListener("DOMContentLoaded", loadPoolWalletWatch);
})();
