(function () {
  const DEFAULT_CONFIG = {
    apiBaseUrl: "/api",
    refreshIntervalMs: 60000,
    stratumHost: "stratum+tcp://pool.pepepow.net:39333"
  };

  function escapeHtml(str) {
    if (typeof str !== "string") return "";
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function setupCopyButton(btnId, targetIdOrValue, isValue = false) {
    const btn = document.getElementById(btnId);
    if (!btn) return;
    btn.addEventListener("click", () => {
      let text = "";
      if (isValue) {
        text = targetIdOrValue;
      } else {
        const target = document.getElementById(targetIdOrValue);
        text = target ? target.textContent : "";
      }
      navigator.clipboard.writeText(text).then(() => {
        const originalText = btn.textContent;
        btn.textContent = "Copied!";
        setTimeout(() => {
          btn.textContent = originalText;
        }, 2000);
      }).catch(err => {
        console.error("Failed to copy: ", err);
      });
    });
  }

  function setupInlineCopyButtons() {
    document.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-copy-value]");
      if (!btn) return;

      const text = btn.getAttribute("data-copy-value") || "";
      navigator.clipboard.writeText(text).then(() => {
        const originalText = btn.textContent;
        btn.textContent = "Copied";
        setTimeout(() => {
          btn.textContent = originalText;
        }, 1600);
      }).catch(err => {
        console.error("Failed to copy: ", err);
      });
    });
  }

  async function loadRuntimeConfig() {
    try {
      const response = await fetch("/runtime-config.json", { cache: "no-store" });
      if (!response.ok) {
        return DEFAULT_CONFIG;
      }
      const payload = await response.json();
      return { ...DEFAULT_CONFIG, ...payload };
    } catch (_error) {
      return DEFAULT_CONFIG;
    }
  }

  async function fetchJson(url) {
    const response = await fetch(url, { cache: "no-store" });
    const payload = await response.json().catch(() => ({}));

    if (!response.ok) {
      const message =
        payload && payload.error && payload.error.message
          ? payload.error.message
          : "Request failed";
      throw new Error(message);
    }

    return payload;
  }

  function formatNumber(value) {
    if (typeof value !== "number") {
      return "-";
    }
    return new Intl.NumberFormat().format(value);
  }

  function formatHashrate(value) {
    if (typeof value !== "number") {
      return "-";
    }

    const units = ["H/s", "KH/s", "MH/s", "GH/s", "TH/s"];
    let next = value;
    let unit = units[0];

    for (const candidate of units) {
      unit = candidate;
      if (next < 1000 || candidate === units[units.length - 1]) {
        break;
      }
      next /= 1000;
    }

    if (unit === "H/s") {
      return `~${next.toFixed(0)} H/s`;
    }
    return `${next.toFixed(next >= 100 ? 0 : next >= 10 ? 1 : 2)} ${unit}`;
  }

  function formatDate(value) {
    if (!value) {
      return "-";
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return value;
    }
    return date.toLocaleString();
  }

  function setText(id, value) {
    const node = document.getElementById(id);
    if (node) {
      node.textContent = value;
    }
  }

  function setHtml(id, value) {
    const node = document.getElementById(id);
    if (node) {
      node.innerHTML = value;
    }
  }

  function shortenText(value, front = 10, back = 8) {
    if (typeof value !== "string") return "";
    if (value.length <= front + back + 1) return value;
    return `${value.slice(0, front)}\u2026${value.slice(-back)}`;
  }

  function copyButton(value, label = "Copy") {
    if (!value) return "";
    return `<button class="copy-mini" type="button" data-copy-value="${escapeHtml(value)}">${label}</button>`;
  }

  function renderHash(value) {
    if (!value) return "-";
    const safeValue = escapeHtml(String(value));
    return `<span class="hash-short" title="${safeValue}">${escapeHtml(shortenText(String(value)))}</span>${copyButton(String(value))}`;
  }

  function renderStatusLabel(value) {
    if (!value) return "-";
    return String(value).replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
  }

  function setPoolStatus(status) {
    const text = status ? String(status) : "Checking API";
    const lower = text.toLowerCase();
    const display = (lower === "online" || lower === "ok" || lower === "healthy")
      ? "Pool Operational"
      : text;
    setText("pool-status", display);

    const badge = document.querySelector(".status-badge");
    if (badge) {
      badge.classList.toggle("status-warn", !(lower === "online" || lower === "ok" || lower === "healthy"));
    }
  }

  function setActiveNav() {
    const currentPath = window.location.pathname || "/";
    document.querySelectorAll(".nav a").forEach((link) => {
      const href = link.getAttribute("href");
      if (
        href === currentPath ||
        (href === "/" && currentPath === "/index.html")
      ) {
        link.classList.add("active");
      }
    });
  }

  function renderCards(items, fields, emptyMessage) {
    if (!Array.isArray(items) || items.length === 0) {
      return `<div class="muted">${emptyMessage || "No items available."}</div>`;
    }

    return items
      .map((item) => {
        const body = fields
          .map((field) => {
            const rawValue = typeof field.render === "function"
              ? field.render(item[field.key], item)
              : item[field.key];
            const value = typeof field.render === "function"
              ? rawValue
              : escapeHtml(String(rawValue ?? "-"));
            return `<div><span>${field.label}</span> <strong>${value}</strong></div>`;
          })
          .join("");

        return `<article class="item-card">${body}</article>`;
      })
      .join("");
  }

  function renderTable(items, columns, emptyMessage, options = {}) {
    if (!Array.isArray(items) || items.length === 0) {
      return `<div class="muted">${emptyMessage || "No items available."}</div>`;
    }

    const limit = options.limit || 50;
    const visibleItems = items.slice(0, limit);
    const head = columns.map((column) => `<th>${column.label}</th>`).join("");
    const rows = visibleItems
      .map((item) => {
        const cells = columns
          .map((column) => {
            const rawValue = typeof column.render === "function"
              ? column.render(item[column.key], item)
              : item[column.key];
            const value = typeof column.render === "function"
              ? rawValue
              : escapeHtml(String(rawValue ?? "-"));
            return `<td data-label="${escapeHtml(column.label)}">${value}</td>`;
          })
          .join("");
        return `<tr>${cells}</tr>`;
      })
      .join("");

    const note = items.length > limit
      ? `<p class="muted table-note">Showing latest ${limit} of ${items.length} records.</p>`
      : "";
    return `<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table>${note}</div>`;
  }

  async function fetchOptionalHealth(config) {
    try {
      return await fetchJson(`${config.apiBaseUrl}/health`);
    } catch (_error) {
      return null;
    }
  }

  function renderDeploymentBaselineNote(health) {
    setText("deployment-baseline-note", "");
    if (health?.localServiceBaseline?.frontendExpected === false) {
      setText(
        "deployment-baseline-note",
        "Host baseline: core + API + stratum; no local frontend service expected. Deployment metadata only, not a failure."
      );
    }
  }

  async function renderDashboard(config) {
    renderDeploymentBaselineNote(null);
    fetchOptionalHealth(config).then(renderDeploymentBaselineNote);
    const [pool, network, blocks, payments] = await Promise.all([
      fetchJson(`${config.apiBaseUrl}/pool/summary`),
      fetchJson(`${config.apiBaseUrl}/network/summary`),
      fetchJson(`${config.apiBaseUrl}/blocks`),
      fetchJson(`${config.apiBaseUrl}/payments`)
    ]);

    const algoDisplay = (pool.algorithm && pool.algorithm.includes("hoohash")) ? "hoohash-pepew / hoohashv110-pepew" : pool.algorithm;
    setText("algorithm", algoDisplay);
    setPoolStatus(pool.poolStatus);
    setText("pool-hashrate", formatHashrate(pool.poolHashrate));
    setText("active-miners", formatNumber(pool.activeMiners));
    setText("active-workers", formatNumber(pool.activeWorkers));
    setText("last-block-time", formatDate(pool.lastBlockFoundAt));
    setText("network-height", formatNumber(network.height));
    setText("network-difficulty", formatNumber(network.difficulty));
    setText("network-hashrate", formatHashrate(network.networkHashrate));
    setText("network-sync", network.synced ? "Synced" : "Syncing");

    const stratumEndpoint = `stratum+tcp://${pool.stratum.host}:${pool.stratum.port}`;
    setText("stratum-endpoint", stratumEndpoint);

    setHtml(
      "recent-blocks",
      renderCards(blocks.items.slice(0, 3), [
        { key: "height", label: "Height", render: formatNumber },
        { key: "status", label: "Status", render: renderStatusLabel },
        { key: "foundAt", label: "Observed", render: formatDate }
      ], "No network blocks tracked in this snapshot window yet.")
    );

    setHtml(
      "recent-payments",
      renderCards(payments.items.slice(0, 3), [
        { key: "wallet", label: "Wallet", render: renderHash },
        { key: "amount", label: "Amount", render: formatNumber },
        { key: "paidAt", label: "Paid", render: formatDate }
      ], "No manual payment records are currently available in the public snapshot.")
    );
  }

  async function renderBlocks(config) {
    const [blocks, candidates, rounds] = await Promise.all([
      fetchJson(`${config.apiBaseUrl}/blocks`),
      fetchJson(`${config.apiBaseUrl}/accepted-candidates`),
      fetchJson(`${config.apiBaseUrl}/rounds`).catch(() => ({ items: [] }))
    ]);
    setHtml(
      "blocks-table",
      renderTable(blocks.items, [
        { key: "height", label: "Height", render: formatNumber },
        { key: "hash", label: "Hash", render: renderHash },
        { key: "status", label: "Status", render: renderStatusLabel },
        { key: "foundAt", label: "Found", render: formatDate },
        { key: "confirmations", label: "Confirms", render: formatNumber }
      ], "No network blocks tracked in this snapshot window yet.", { limit: 50 })
    );
    setHtml(
      "accepted-candidates-table",
      renderTable(candidates.items, [
        { key: "jobId", label: "Job ID" },
        { key: "submitTimestamp", label: "Observed", render: formatDate },
        { key: "candidateHash", label: "Candidate Hash", render: renderHash },
        {
          key: "lifecycleStatus",
          label: "Lifecycle Status",
          render: (val) => {
            if (!val) return "-";
            return val.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
          }
        },
        {
          key: "matchedHeight",
          label: "Observed Height",
          render: (val) => (val ? formatNumber(val) : "-")
        },
        {
          key: "confirmations",
          label: "Confirmations",
          render: (val) => (val !== null && val !== undefined ? formatNumber(val) : "-")
        },
        {
          key: "maturityLabel",
          label: "Chain maturity",
          render: (val) => {
            if (!val) return "-";
            return val.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
          }
        }
      ], "No accepted block candidates found in this snapshot window (chain observation only).")
    );
    setHtml(
      "rounds-table",
      renderTable(rounds.items, [
        { key: "candidateHash", label: "Candidate Hash", render: renderHash },
        {
          key: "matchedHeight",
          label: "Observed Height",
          render: (val) => (val ? formatNumber(val) : "-")
        },
        {
          key: "roundStatus",
          label: "Round Status / Review State",
          render: (val) => {
            if (!val) return "-";
            const formatted = val.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
            if (val === "pay" + "able") {
              return "Observed Match (Manual Review)";
            }
            return formatted;
          }
        },
        {
          key: "totalShareCount",
          label: "Shares",
          render: (val) => (val !== null && val !== undefined ? formatNumber(val) : "-")
        },
        {
          key: "totalShareScore",
          label: "Score",
          render: (val) => (val !== null && val !== undefined ? Number(val).toFixed(4) : "-")
        },
        {
          key: "walletCount",
          label: "Wallets",
          render: (val) => (val !== null && val !== undefined ? formatNumber(val) : "-")
        },
        {
          key: "confirmations",
          label: "Confirmations",
          render: (val) => (val !== null && val !== undefined ? formatNumber(val) : "-")
        },
        {
          key: "shares",
          label: "Observed Share %",
          render: (sharesObj) => {
            if (!sharesObj || typeof sharesObj !== "object") return "-";
            const entries = Object.entries(sharesObj)
              .filter(([, d]) => d && typeof d.sharePercent === "number")
              .sort(([, a], [, b]) => b.sharePercent - a.sharePercent)
              .slice(0, 3);
            if (entries.length === 0) return "-";

            const summaryText = entries
              .map(([wallet, d]) => {
                const pct = d.sharePercent.toFixed(2);
                const short = wallet.length > 12 ? wallet.slice(0, 6) + "\u2026" + wallet.slice(-4) : wallet;
                return `${short}\u00a0${pct}%`;
              })
              .join(" / ");

            const detailLines = entries.map(([wallet, d]) => {
              const pct = d.sharePercent.toFixed(2);
              const score = typeof d.shareScore === "number" ? d.shareScore.toFixed(2) : "-";
              const short = wallet.length > 12 ? wallet.slice(0, 6) + "\u2026" + wallet.slice(-4) : wallet;

              let line = `<div style="margin-bottom: 0.15rem;">
                <span style="color: var(--text); font-weight: 500;">${short}</span>: 
                <strong>${pct}%</strong> (Score: ${score})
              </div>`;

              if (d.workers && typeof d.workers === "object") {
                const workersList = Object.entries(d.workers)
                  .filter(([, w]) => w && typeof w.shareScore === "number")
                  .sort(([, a], [, b]) => b.shareScore - a.shareScore);

                if (workersList.length > 0) {
                  const workerLines = workersList.slice(0, 2).map(([wName, wData]) => {
                    const wPct = wData.sharePercent.toFixed(2);
                    const wWalletPct = wData.walletSharePercent.toFixed(2);
                    return `${wName}&nbsp;(${wPct}%&nbsp;total,&nbsp;${wWalletPct}%&nbsp;of&nbsp;wallet)`;
                  }).join(", ");

                  line += `<div style="padding-left: 0.75rem; font-size: 0.9em; opacity: 0.85;">
                    &bull; Workers: ${workerLines}
                  </div>`;
                }
              }
              return line;
            }).join("");

            return `<div>
              <div>${summaryText}</div>
              <details style="margin-top: 0.35rem; font-size: 0.85em;">
                <summary style="cursor: pointer; color: var(--accent-alt); font-weight: 500; outline: none; user-select: none;">Details</summary>
                <div style="margin-top: 0.3rem; padding-left: 0.5rem; border-left: 2px solid var(--panel-border); line-height: 1.45;">
                  ${detailLines}
                </div>
              </details>
            </div>`;
          }
        }
      ], "No active rounds or contribution data tracked in this snapshot.", { limit: 50 })
    );
  }

  async function renderPayments(config) {
    const [payments, pool] = await Promise.all([
      fetchJson(`${config.apiBaseUrl}/payments`),
      fetchJson(`${config.apiBaseUrl}/pool/summary`).catch(() => ({}))
    ]);
    const feeText = typeof pool.feePercent === "number"
      ? `Pool fee: ${pool.feePercent}%`
      : "Pool fee: Fee shown when configured";
    const minText = typeof pool.minPayout === "number"
      ? `Minimum payout: ${formatNumber(pool.minPayout)} PEPEPOW`
      : "Minimum payout shown when configured";
    setHtml(
      "payment-info",
      `<span class="info-chip">Payment mode: manual/recorded</span><span class="info-chip">${feeText}</span><span class="info-chip">${minText}</span>`
    );

    const latest = Array.isArray(payments.items) ? payments.items[0] : null;
    setHtml(
      "latest-payment",
      latest
        ? `<h3>Most recent recorded payment</h3><div class="kv-list"><div><span>Paid</span><strong>${formatDate(latest.paidAt)}</strong></div><div><span>Wallet</span><strong>${renderHash(latest.wallet)}</strong></div><div><span>Amount</span><strong>${formatNumber(latest.amount)}</strong></div><div><span>TXID</span><strong>${renderHash(latest.txid)}</strong></div></div>`
        : ""
    );

    setHtml(
      "payments-table",
      renderTable(payments.items, [
        { key: "wallet", label: "Wallet", render: renderHash },
        { key: "blockHeight", label: "Observed Height", render: (val) => (val ? formatNumber(val) : "-") },
        { key: "candidateHash", label: "Candidate Hash", render: renderHash },
        { key: "amount", label: "Amount", render: formatNumber },
        { key: "paidAt", label: "Paid", render: formatDate },
        { key: "confirmations", label: "Confirms", render: formatNumber },
        { key: "txid", label: "TXID", render: renderHash }
      ], "No manual payment records are currently available in the public snapshot.", { limit: 50 })
    );
  }

  async function lookupMiner(config, wallet) {
    const result = await fetchJson(
      `${config.apiBaseUrl}/miner/${encodeURIComponent(wallet)}`
    );

    let htmlContent = "";

    if (!result.found) {
      htmlContent += `<div class="empty-state"><strong>No active miner data found for ${escapeHtml(wallet)}.</strong><p class="muted">Miner statistics are generated from active share submissions and are only retained while there is active mining activity within the snapshot tracking window. If you just started mining, it may take up to a minute for your first accepted share to appear here.</p><a class="button" href="/connect.html">查看如何開始挖礦</a></div>`;
    } else {
      const summary = result.summary || {};
      const workers = Array.isArray(result.workers) ? result.workers : [];

      htmlContent += renderCards(
        [
          {
            label: "Active Workers",
            value: formatNumber(summary.activeWorkers)
          },
          {
            label: "Estimated hashrate",
            value: `${formatHashrate(summary.hashrate)} <br><small style="font-weight: normal; font-size: 0.75rem; color: var(--muted); display: block; margin-top: 0.2rem;">This is a pool-side estimate from accepted shares, not the miner’s exact local GPU hashrate.</small>`
          },
          {
            label: "Accepted shares",
            value: `${formatNumber(summary.acceptedShares)} <br><small style="font-weight: normal; font-size: 0.75rem; color: var(--muted); display: block; margin-top: 0.2rem;">Shares accepted by the pool. This does not imply a confirmed block or recorded payment.</small>`
          },
          {
            label: "Last Share",
            value: formatDate(summary.lastShareAt)
          }
        ],
        [
          { key: "label", label: "Metric" },
          { key: "value", label: "Value" }
        ]
      );

      htmlContent += "<h3>Workers</h3>";
      htmlContent += renderTable(workers, [
        { key: "name", label: "Worker" },
        { key: "acceptedShares", label: "Accepted shares", render: formatNumber },
        { key: "hashrate", label: "Estimated hashrate", render: formatHashrate },
        { key: "lastShareAt", label: "Last Share", render: formatDate }
      ]);
    }

    const recentPayments = Array.isArray(result.recentPayments) ? result.recentPayments : [];

    htmlContent += "<h3>Recorded payments</h3>";
    htmlContent += renderTable(recentPayments, [
      { key: "paidAt", label: "Paid", render: formatDate },
      { key: "amount", label: "Amount", render: formatNumber },
      {
        key: "txid",
        label: "TXID",
        render: renderHash
      },
      { key: "blockHeight", label: "Observed Height", render: (val) => (val ? formatNumber(val) : "-") },
      { key: "confirmations", label: "Confirms", render: formatNumber }
    ], "No recorded manual payments for this wallet yet.");

    setHtml("miner-result", htmlContent);
  }

  async function renderMiner(config) {
    const form = document.getElementById("miner-form");
    const input = document.getElementById("wallet-input");

    if (!form || !input) {
      return;
    }

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const wallet = input.value.trim();
      if (!wallet) {
        setHtml("miner-result", '<div class="empty-state"><strong>輸入 PEPEPOW 錢包地址來查詢礦工狀態。</strong><p class="muted">資料會在 pool 收到 accepted shares 後出現。</p><a class="button" href="/connect.html">查看如何開始挖礦</a></div>');
        return;
      }
      setHtml("miner-result", '<div class="muted">Loading miner data...</div>');
      try {
        await lookupMiner(config, wallet);
      } catch (error) {
        setHtml("miner-result", `<div class="error">${error.message}</div>`);
      }
    });

    if (input.value.trim()) {
      await lookupMiner(config, input.value.trim());
    }
  }

  async function renderConnect(config) {
    const pool = await fetchJson(`${config.apiBaseUrl}/pool/summary`);
    const endpoint = `stratum+tcp://${pool.stratum.host}:${pool.stratum.port}`;
    const sampleCommand =
      `./miner --algo hoohash-pepew --server ${endpoint} --user YOUR_WALLET.worker01 --pass x`;

    setText("connect-algorithm", "hoohash-pepew / hoohashv110-pepew");
    setText("connect-endpoint", endpoint);
    setHtml("sample-command", escapeHtml(sampleCommand).replace("YOUR_WALLET", '<mark>YOUR_WALLET</mark>'));
  }

  async function run() {
    setActiveNav();
    setupInlineCopyButtons();
    const page = document.body.dataset.page;
    const config = await loadRuntimeConfig();

    try {
      if (page === "dashboard") {
        await renderDashboard(config);
        setupCopyButton("copy-stratum-btn", "stratum-endpoint");
      } else if (page === "blocks") {
        await renderBlocks(config);
      } else if (page === "payments") {
        await renderPayments(config);
      } else if (page === "miner") {
        await renderMiner(config);
      } else if (page === "connect") {
        await renderConnect(config);
        setupCopyButton("copy-endpoint-btn", "connect-endpoint");
        setupCopyButton("copy-command-btn", "sample-command");
      }
    } catch (error) {
      document.querySelectorAll(".list-state").forEach((node) => {
        node.innerHTML = `<div class="error">${error.message}</div>`;
      });
      const statusNode = document.getElementById("pool-status");
      if (statusNode) {
        statusNode.textContent = "API unavailable";
      }
    }
  }

  document.addEventListener("DOMContentLoaded", run);
})();
