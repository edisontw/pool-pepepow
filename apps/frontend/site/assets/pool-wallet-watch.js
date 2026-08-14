(function () {
  const SNAPSHOT_URL = "/pool-wallet-monitor.json";
  const POOL_WALLET = "PKTwq3nHNxwcVgDX4QwVxQGX5DYjJB8nho";
  const SOLO_ENDPOINT = "stratum+tcp://pool.pepepow.net:39334";

  function setText(id, value) {
    const node = document.getElementById(id);
    if (node) node.textContent = value;
  }

  function ensureSoloEndpoint() {
    if (document.getElementById("solo-stratum-endpoint")) return;
    const poolEndpoint = document.getElementById("stratum-endpoint");
    const poolCard = poolEndpoint && poolEndpoint.closest(".connection-card");
    if (!poolCard || !poolCard.parentElement) return;

    const soloCard = document.createElement("div");
    soloCard.className = "connection-card";
    soloCard.style.marginTop = ".65rem";
    soloCard.innerHTML = `<div><span>SOLO Stratum endpoint</span><strong><code id="solo-stratum-endpoint">${SOLO_ENDPOINT}</code></strong></div><button class="button compact-copy" type="button" data-copy-value="${SOLO_ENDPOINT}">Copy SOLO endpoint</button>`;
    poolCard.insertAdjacentElement("afterend", soloCard);
  }

  function ensureMaintenanceNotice() {
    if (document.getElementById("pool-maintenance-notice")) return;
    ensurePoolWalletWatchStyles();
    const main = document.querySelector("main.page-grid");
    if (!main) return;

    const notice = document.createElement("section");
    notice.id = "pool-maintenance-notice";
    notice.className = "panel pool-maintenance-notice";
    notice.setAttribute("role", "status");
    notice.setAttribute("aria-live", "polite");
    notice.innerHTML = `
      <p class="eyebrow">Maintenance Notice</p>
      <h2>Pool wallet temporarily under maintenance</h2>
      <p>Payment processing may be temporarily unavailable or delayed while wallet maintenance is in progress. Mining services and pool status are being monitored. Updates will be posted here.</p>
    `;
    main.insertBefore(notice, main.firstChild);
  }

  function ensurePoolWalletWatchStyles() {
    if (document.getElementById("pool-wallet-watch-style")) return;
    const style = document.createElement("style");
    style.id = "pool-wallet-watch-style";
    style.textContent = `
      .pool-maintenance-notice{grid-column:1/-1!important;display:grid;gap:.45rem;padding:1rem 1.15rem!important;border:1px solid rgba(255,212,90,.5)!important;background:linear-gradient(135deg,rgba(255,212,90,.16),rgba(255,118,118,.09))!important;box-shadow:0 0 0 1px rgba(255,212,90,.08) inset}
      .pool-maintenance-notice .eyebrow{margin:0;color:#ffe08a}
      .pool-maintenance-notice h2{margin:0;font-size:clamp(1.15rem,2.4vw,1.55rem);line-height:1.2}
      .pool-maintenance-notice p:last-child{margin:0;color:rgba(238,245,248,.88);line-height:1.5}
      .pool-wallet-watch{display:grid;gap:.6rem;overflow:hidden;padding:1.1rem!important}
      .pool-wallet-watch .eyebrow{margin-bottom:-.28rem;font-size:.65rem;letter-spacing:.12em}
      .pool-wallet-watch h3{margin:0;font-size:clamp(.92rem,1.3vw,1.05rem);line-height:1.2}
      .pool-wallet-watch-hero{display:grid;gap:.35rem;padding:.85rem .95rem;border-radius:14px;border:1px solid rgba(129,247,176,.25);background:linear-gradient(135deg,rgba(129,247,176,.12),rgba(55,196,255,.06))}
      .pool-wallet-watch-hero-top{display:flex;align-items:center;justify-content:space-between;gap:.5rem;flex-wrap:wrap}
      .pool-wallet-watch-status{width:fit-content;padding:.22rem .55rem;border-radius:999px;background:rgba(238,245,248,.09);color:rgba(235,245,255,.8);font-size:.6rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase}
      .pool-wallet-watch-diff{font-size:.72rem;color:var(--muted);font-weight:700}
      .pool-wallet-watch-main{font-size:clamp(1.25rem,3.2vw,1.65rem);line-height:1.1;letter-spacing:.015em;word-break:break-word}
      .pool-wallet-watch-sub{font-size:.72rem;color:var(--muted)}
      .pool-wallet-watch-stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.45rem;margin-top:.2rem}
      .pool-wallet-watch-stat{display:grid;gap:.15rem;padding:.55rem .6rem;border-radius:10px;background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.06)}
      .pool-wallet-watch-stat span{color:var(--muted);font-size:.56rem;font-weight:800;letter-spacing:.06em;text-transform:uppercase}
      .pool-wallet-watch-stat strong{font-size:.74rem;line-height:1.2}
      .pool-wallet-watch-body{display:grid;grid-template-columns:minmax(0,1fr);gap:.5rem}
      .pool-wallet-watch-address-card,.pool-wallet-watch-summary{display:grid;gap:.25rem;padding:.6rem .65rem;border-radius:11px;background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.075)}
      .pool-wallet-watch-address-card span,.pool-wallet-watch-summary span{color:var(--muted);font-size:.55rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase}
      .pool-wallet-watch-address-card code{display:block;white-space:normal;overflow-wrap:anywhere;font-size:clamp(.64rem,1.5vw,.76rem);line-height:1.32;font-weight:800;color:rgba(238,245,248,.92)}
      .pool-wallet-watch-summary strong{font-size:.74rem;line-height:1.25}
      .pool-wallet-watch-summary p{margin:0;color:var(--muted);font-size:.65rem;line-height:1.35}
      .pool-wallet-watch-details-toggle{border:none;background:none;padding:0;color:var(--accent-alt);font-size:.65rem;font-weight:700;cursor:pointer;text-align:left;display:inline-flex;align-items:center;gap:.3rem}
      .pool-wallet-watch-details{display:none;grid-template-columns:repeat(2,minmax(0,1fr));gap:.45rem;padding:.65rem;border-radius:11px;background:rgba(0,0,0,.2);border:1px solid rgba(255,255,255,.05)}
      .pool-wallet-watch-details.is-open{display:grid}
      .pool-wallet-watch-detail-item{display:grid;gap:.1rem}
      .pool-wallet-watch-detail-item span{color:var(--muted);font-size:.55rem;text-transform:uppercase;letter-spacing:.05em}
      .pool-wallet-watch-detail-item strong{font-size:.72rem}
      .pool-wallet-watch-note{margin:0;color:rgba(190,205,216,.88);font-size:.68rem;line-height:1.4}
      .pool-wallet-watch-actions{display:flex;align-items:center;justify-content:space-between;gap:.45rem;flex-wrap:wrap;margin-top:-.05rem}
      .pool-wallet-watch-actions a{display:inline-flex;align-items:center;justify-content:center;min-height:1.62rem;padding:.32rem .55rem;border-radius:8px;border:1px solid rgba(55,196,255,.32);background:rgba(55,196,255,.08);color:var(--accent-alt);font-size:.62rem;font-weight:800;text-decoration:none}
      .pool-wallet-watch.is-ok .pool-wallet-watch-status{background:rgba(129,247,176,.18);color:#a8ffc8}
      .pool-wallet-watch.is-guarded .pool-wallet-watch-status{background:rgba(255,212,90,.18);color:#ffe08a}
      .pool-wallet-watch.is-alert .pool-wallet-watch-status{background:rgba(255,118,118,.18);color:#ffb0b0}
      @media(min-width:720px){.pool-wallet-watch-body{grid-template-columns:minmax(0,.95fr) minmax(0,1.05fr)}}
      @media(max-width:480px){.pool-wallet-watch-stats{grid-template-columns:1fr}}
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
      <p class="eyebrow">Pool Wallet Health</p>
      <h3 id="pool-wallet-watch-title">24h Wallet Reconciliation</h3>
      <article class="pool-wallet-watch-hero" aria-live="polite">
        <div class="pool-wallet-watch-hero-top">
          <span class="pool-wallet-watch-status" id="pool-wallet-watch-status">Waiting for monitor</span>
          <span class="pool-wallet-watch-diff" id="pool-wallet-watch-diff">Difference -</span>
        </div>
        <strong class="pool-wallet-watch-main" id="pool-wallet-watch-main">-</strong>
        <span class="pool-wallet-watch-sub" id="pool-wallet-watch-expected">Expected: -</span>
        <div class="pool-wallet-watch-stats">
          <div class="pool-wallet-watch-stat">
            <span>Pool + SOLO Rewards</span>
            <strong id="pool-wallet-watch-rewards">-</strong>
          </div>
          <div class="pool-wallet-watch-stat">
            <span>Miner Payouts</span>
            <strong id="pool-wallet-watch-payouts">-</strong>
          </div>
          <div class="pool-wallet-watch-stat">
            <span>Immature Rewards</span>
            <strong id="pool-wallet-watch-immature">-</strong>
          </div>
        </div>
      </article>
      <div class="pool-wallet-watch-body">
        <article class="pool-wallet-watch-address-card">
          <span>Pool reward address received</span>
          <strong id="pool-wallet-watch-addr-received">-</strong>
          <code id="pool-wallet-watch-address">${POOL_WALLET}</code>
        </article>
        <article class="pool-wallet-watch-summary">
          <span>Status</span>
          <strong id="pool-wallet-watch-headline">Loading wallet health...</strong>
          <p id="pool-wallet-watch-sub-status">Fetching latest 24h reconciliation snapshot...</p>
        </article>
      </div>
      <button type="button" class="pool-wallet-watch-details-toggle" id="pool-wallet-watch-toggle">▶ View reconciliation breakdown</button>
      <div class="pool-wallet-watch-details" id="pool-wallet-watch-details-box">
        <div class="pool-wallet-watch-detail-item"><span>Pool Rewards</span><strong id="detail-pool-rewards">-</strong></div>
        <div class="pool-wallet-watch-detail-item"><span>SOLO Rewards</span><strong id="detail-solo-rewards">-</strong></div>
        <div class="pool-wallet-watch-detail-item"><span>Pool Payouts</span><strong id="detail-pool-payouts">-</strong></div>
        <div class="pool-wallet-watch-detail-item"><span>SOLO Payouts</span><strong id="detail-solo-payouts">-</strong></div>
        <div class="pool-wallet-watch-detail-item"><span>Transaction Fees</span><strong id="detail-fees">-</strong></div>
        <div class="pool-wallet-watch-detail-item"><span>Unrecorded Sends</span><strong id="detail-unrecorded">-</strong></div>
      </div>
      <p class="pool-wallet-watch-note" id="pool-wallet-watch-note">Server-side monitor snapshot is loading.</p>
      <div class="pool-wallet-watch-actions">
        <span class="muted" style="font-size:0.62rem;" id="pool-wallet-watch-timestamp">Updated -</span>
        <a id="pool-wallet-watch-explorer" href="https://explorer.pepepow.net/address/${POOL_WALLET}" target="_blank" rel="noopener noreferrer">Open explorer ↗</a>
      </div>
    `;

    if (poolPositioning && poolPositioning.nextSibling) {
      target.insertBefore(root, poolPositioning.nextSibling);
    } else if (poolPositioning) {
      target.appendChild(root);
    } else {
      target.appendChild(root);
    }

    const toggleBtn = document.getElementById("pool-wallet-watch-toggle");
    const detailsBox = document.getElementById("pool-wallet-watch-details-box");
    if (toggleBtn && detailsBox) {
      toggleBtn.addEventListener("click", () => {
        const isOpen = detailsBox.classList.toggle("is-open");
        toggleBtn.textContent = isOpen ? "▼ Hide reconciliation breakdown" : "▶ View reconciliation breakdown";
      });
    }

    return root;
  }

  function formatPepew(value, decimals = 0) {
    if (typeof value !== "number" || !Number.isFinite(value)) return "-";
    const maxFrac = Math.abs(value) >= 1000000 ? 0 : decimals;
    return new Intl.NumberFormat(undefined, {
      maximumFractionDigits: maxFrac
    }).format(value);
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
    if (status === "critical") return "Discrepancy";
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
    ensureMaintenanceNotice();
    ensureSoloEndpoint();
    const root = ensurePoolWalletWatchCard();
    if (!root) return;

    try {
      const response = await fetch(SNAPSHOT_URL, { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      const status = typeof data.status === "string" ? data.status : "unknown";

      const actualDelta = typeof data.actualLiquidityChange === "number"
        ? data.actualLiquidityChange
        : (typeof data.deltaBalance === "number" ? data.deltaBalance : null);

      const expectedDelta = typeof data.expectedLiquidityChange === "number" ? data.expectedLiquidityChange : null;
      const diff = typeof data.reconciliationDifference === "number" ? data.reconciliationDifference : 0.0;

      const poolRewards = typeof data.poolRewardsReceived === "number" ? data.poolRewardsReceived : 0.0;
      const soloRewards = typeof data.soloRewardsReceived === "number" ? data.soloRewardsReceived : 0.0;
      const totalRewards = poolRewards + soloRewards;

      const poolPayouts = typeof data.poolExternalPayouts === "number" ? data.poolExternalPayouts : 0.0;
      const soloPayouts = typeof data.soloExternalPayouts === "number" ? data.soloExternalPayouts : 0.0;
      const totalPayouts = poolPayouts + soloPayouts;

      const immatureTotal = typeof data.immatureRewardTotal === "number" ? data.immatureRewardTotal : 0.0;
      const fees = typeof data.transactionFees === "number" ? data.transactionFees : 0.0;
      const unrecordedSends = typeof data.unrecordedExternalTransactions === "number" ? data.unrecordedExternalTransactions : 0;

      const addrReceived = typeof data.poolRewardAddressReceived24h === "number"
        ? data.poolRewardAddressReceived24h
        : (typeof data.primaryWindowDeltaTotalReceived === "number" ? data.primaryWindowDeltaTotalReceived : data.deltaTotalReceived);

      const headline = data.headline || statusLabel(status);
      const summary = data.summary || (status === "ok" ? "No unexplained wallet movement detected." : "Reconciliation complete.");
      const updatedAt = data.generatedAt || null;
      const explorerUrl = data.explorerWalletUrl || `https://explorer.pepepow.net/address/${POOL_WALLET}`;
      const wallet = data.poolRewardAddress || data.poolWallet || data.wallet || POOL_WALLET;

      root.classList.remove("is-ok", "is-guarded", "is-alert");
      const cls = statusClass(status);
      if (cls) root.classList.add(cls);

      setText("pool-wallet-watch-status", statusLabel(status));
      setText("pool-wallet-watch-diff", `Difference ${Math.abs(diff).toFixed(3)} PEPEW`);
      setText("pool-wallet-watch-main", actualDelta !== null ? `Actual: ${actualDelta >= 0 ? "+" : ""}${formatPepew(actualDelta)} PEPEW` : "-");
      setText("pool-wallet-watch-expected", expectedDelta !== null ? `Expected: ${expectedDelta >= 0 ? "+" : ""}${formatPepew(expectedDelta)} PEPEW` : "Expected: -");

      setText("pool-wallet-watch-rewards", `+${formatPepew(totalRewards)} PEPEW`);
      setText("pool-wallet-watch-payouts", `-${formatPepew(totalPayouts)} PEPEW`);
      setText("pool-wallet-watch-immature", `${formatPepew(immatureTotal)} PEPEW`);

      setText("pool-wallet-watch-addr-received", addrReceived !== null ? `+${formatPepew(addrReceived)} PEPEW (24h)` : "-");
      setText("pool-wallet-watch-address", wallet);

      setText("pool-wallet-watch-headline", headline);
      setText("pool-wallet-watch-sub-status", status === "ok" ? "Wallet accounting reconciled." : summary);
      setText("pool-wallet-watch-note", summary);
      setText("pool-wallet-watch-timestamp", `last 24h · Updated ${formatAge(updatedAt)}`);

      // Details breakdown
      setText("detail-pool-rewards", `+${formatPepew(poolRewards, 2)} PEPEW`);
      setText("detail-solo-rewards", `+${formatPepew(soloRewards, 2)} PEPEW`);
      setText("detail-pool-payouts", `-${formatPepew(poolPayouts, 2)} PEPEW`);
      setText("detail-solo-payouts", `-${formatPepew(soloPayouts, 2)} PEPEW`);
      setText("detail-fees", `${fees.toFixed(6)} PEPEW`);
      setText("detail-unrecorded", `${unrecordedSends} txs`);

      updateExplorerLink(explorerUrl);
    } catch (error) {
      root.classList.remove("is-ok", "is-guarded");
      root.classList.add("is-alert");
      setText("pool-wallet-watch-status", "Waiting for monitor");
      setText("pool-wallet-watch-diff", "Difference -");
      setText("pool-wallet-watch-main", "-");
      setText("pool-wallet-watch-expected", "Expected: -");
      setText("pool-wallet-watch-headline", "No server snapshot yet");
      setText("pool-wallet-watch-sub-status", "Run live-stratum pool wallet monitor to publish the snapshot.");
      setText("pool-wallet-watch-note", "Server-side monitor snapshot is not available yet.");
      updateExplorerLink(`https://explorer.pepepow.net/address/${POOL_WALLET}`);
      console.warn("Pool wallet monitor snapshot unavailable:", error);
    }
  }

  document.addEventListener("DOMContentLoaded", loadPoolWalletWatch);
})();
