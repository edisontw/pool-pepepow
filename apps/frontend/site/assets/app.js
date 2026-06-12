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

  function explorerBlockUrl(hashOrHeight) {
    if (hashOrHeight === null || hashOrHeight === undefined || hashOrHeight === "") return "";
    return `https://explorer.pepepow.net/block/${encodeURIComponent(String(hashOrHeight))}`;
  }

  function explorerTxUrl(txid) {
    if (!txid) return "";
    return `https://explorer.pepepow.net/tx/${encodeURIComponent(String(txid))}`;
  }

  function explorerAddressUrl(address) {
    if (!address) return "";
    return `https://explorer.pepepow.net/address/${encodeURIComponent(String(address))}`;
  }

  function isLikelyPepepowAddress(value) {
    return typeof value === "string" && /^P[1-9A-HJ-NP-Za-km-z]{25,60}$/.test(value);
  }

  function isLikelyHash64(value) {
    return typeof value === "string" && /^[0-9a-fA-F]{64}$/.test(value);
  }

  function copyButton(value, label = "Copy") {
    if (!value) return "";
    return `<button class="copy-mini" type="button" data-copy-value="${escapeHtml(value)}">${label}</button>`;
  }

  function renderExplorerLink(url, label = "Explorer") {
    if (!url) return "";
    return `<a class="explorer-link" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer" title="${escapeHtml(label)}" aria-label="${escapeHtml(label)}">\u2197</a>`;
  }

  function renderValueWithCopyAndExplorer(value, type) {
    if (!value) return "-";
    const raw = String(value);
    let url = "";

    if (type === "txid" && isLikelyHash64(raw)) {
      url = explorerTxUrl(raw);
    } else if (type === "address" && isLikelyPepepowAddress(raw)) {
      url = explorerAddressUrl(raw);
    } else if (type === "block" && (isLikelyHash64(raw) || /^\d+$/.test(raw))) {
      url = explorerBlockUrl(raw);
    } else if (type === "auto-address" && isLikelyPepepowAddress(raw)) {
      url = explorerAddressUrl(raw);
    } else if (type === "auto-block" && isLikelyHash64(raw)) {
      url = explorerBlockUrl(raw);
    }

    return `<span class="hash-actions"><span class="hash-value mono-compact" title="${escapeHtml(raw)}">${escapeHtml(shortenText(raw, 12, 10))}</span>${copyButton(raw)}${renderExplorerLink(url)}</span>`;
  }

  function renderHash(value) {
    return renderValueWithCopyAndExplorer(value, "auto-block");
  }

  function renderStatusLabel(value) {
    if (!value) return "-";
    return String(value).replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
  }

  function renderMinerSummaryMetrics(metrics) {
    return `<div class="miner-summary-grid">${metrics.map((metric) => {
      const note = metric.note
        ? `<p class="metric-note">${escapeHtml(metric.note)}</p>`
        : "";
      return `<article class="miner-metric-card">
        <span>${escapeHtml(metric.label)}</span>
        <strong>${escapeHtml(metric.value)}</strong>
        ${note}
      </article>`;
    }).join("")}</div>`;
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

  function chooseRecentAcceptedRate(pool) {
    // SOURCE GUARD: Do not use global pool-wide rolling shares (e.g. pool.rolling['15m'])
    // as they include low-difficulty-share noise and do not represent the actual miner accepted rate.
    // Return null since no reliable recent accepted rate field is available in the dashboard pool summary.
    return null;
  }

  function updateRewardIntelligence(rewardPerDay, rewardPerWeek, usdtPerDayVal, price, network, pool) {
    const intelMessage = document.getElementById("intel-message");
    if (!intelMessage) return;

    const netHash = network.networkHashrate;
    const poolHash = pool.poolHashrate;

    const isNetValid = (typeof netHash === "number" && netHash > 0);
    const isPoolValid = (typeof poolHash === "number" && poolHash >= 0);

    if (!isNetValid) {
      intelMessage.innerHTML = "<p>Current reward outlook is unavailable until network hashrate data is available.</p>";
      return;
    }

    const poolShare = isPoolValid ? (poolHash / netHash) : 0;

    let baseMsg = "";
    if (poolShare < 0.05) {
      baseMsg = "Short-term rewards may fluctuate because pool share is small compared with total network hashrate.";
    } else if (poolShare <= 0.15) {
      baseMsg = "Moderate pool share provides moderate reward visibility and moderate variance in block finding frequency.";
    } else {
      baseMsg = "Improved pool share offers improved reward visibility and lower variance for consistent block rewards.";
    }

    let acceptedRateMsg = "";
    let acceptedRatePercentStr = "";
    let isAcceptedRateBelowThreshold = false;

    const acceptedRate = chooseRecentAcceptedRate(pool);
    if (acceptedRate !== null) {
      if (acceptedRate < 0.995) {
        isAcceptedRateBelowThreshold = true;
        acceptedRatePercentStr = (acceptedRate * 100).toFixed(2) + "%";
        acceptedRateMsg = ` Accepted rate is below 99.5% (currently ${acceptedRatePercentStr}), which may have a small measurable impact on estimated rewards.`;
      }
    }

    let calculatorMsg = "";
    const hashrateInput = document.getElementById("calc-hashrate");
    const unitSelect = document.getElementById("calc-unit");

    if (hashrateInput && unitSelect && rewardPerDay !== null) {
      const hashrateVal = parseFloat(hashrateInput.value);
      const unitVal = unitSelect.value;

      if (!isNaN(hashrateVal) && hashrateVal > 0) {
        const dailyPepewStr = formatNumber(Math.round(rewardPerDay * 100) / 100);
        const weeklyPepewStr = formatNumber(Math.round(rewardPerWeek * 100) / 100);

        calculatorMsg = `<p style="margin-top: 0.85rem; padding-top: 0.85rem; border-top: 1px solid rgba(255, 255, 255, 0.08);">Based on your input hashrate of <strong>${hashrateVal} ${unitVal}/s</strong>:`;
        calculatorMsg += `<br>&bull; Estimated daily PEPEW: <strong>${dailyPepewStr} PEPEW</strong>`;
        calculatorMsg += `<br>&bull; Estimated weekly PEPEW: <strong>${weeklyPepewStr} PEPEW</strong>`;

        if (usdtPerDayVal !== null) {
          calculatorMsg += `<br>&bull; Estimated daily USDT: <strong>$${usdtPerDayVal.toFixed(2)} USDT</strong>`;
        }

        if (isAcceptedRateBelowThreshold) {
          calculatorMsg += `<br><span style="color: var(--muted); font-size: 0.9em;">&bull; Note: The pool's recent accepted rate of ${acceptedRatePercentStr} may have a small measurable impact on this estimate.</span>`;
        }
        calculatorMsg += "</p>";
      }
    }

    intelMessage.innerHTML = `<p>${baseMsg}${acceptedRateMsg}</p>${calculatorMsg}`;
  }

  function updateCalculator(network, pepewUsdtPrice, pool) {
    const hashrateInput = document.getElementById("calc-hashrate");
    const unitSelect = document.getElementById("calc-unit");
    if (!hashrateInput || !unitSelect) return;

    const hashrateVal = parseFloat(hashrateInput.value);
    const unitVal = unitSelect.value;

    const netHash = network.networkHashrate;
    const isNetValid = (typeof netHash === "number" && netHash > 0);

    if (isNaN(hashrateVal) || hashrateVal < 0 || !isNetValid) {
      setText("calc-pepew-hour", "-");
      setText("calc-pepew-day", "-");
      setText("calc-pepew-week", "-");
      setText("calc-usdt-day", "Price unavailable");
      setText("calc-usdt-week", "Price unavailable");
      updateRewardIntelligence(null, null, null, null, network, pool);
      return;
    }

    let userHashrateHps = hashrateVal;
    if (unitVal === "KH") {
      userHashrateHps = hashrateVal * 1000;
    } else if (unitVal === "MH") {
      userHashrateHps = hashrateVal * 1000000;
    }

    const BLOCK_TIME_SECONDS = 20;
    const MINER_REWARD_RATIO = 0.65;
    const DEFAULT_BLOCK_REWARD = 16000;

    const currentBlockReward = (typeof network.reward === "number" && network.reward > 0) ? network.reward : DEFAULT_BLOCK_REWARD;
    const blocksPerDay = 86400 / BLOCK_TIME_SECONDS;
    const minerRewardPerBlock = currentBlockReward * MINER_REWARD_RATIO;

    const rewardPerDay = (userHashrateHps / netHash) * blocksPerDay * minerRewardPerBlock;
    const rewardPerHour = rewardPerDay / 24;
    const rewardPerWeek = rewardPerDay * 7;

    setText("calc-pepew-hour", formatNumber(Math.round(rewardPerHour * 100) / 100));
    setText("calc-pepew-day", formatNumber(Math.round(rewardPerDay * 100) / 100));
    setText("calc-pepew-week", formatNumber(Math.round(rewardPerWeek * 100) / 100));

    let usdtPerDayStr = "Price unavailable";
    let usdtPerWeekStr = "Price unavailable";
    let usdtPerDayVal = null;

    if (pepewUsdtPrice !== null) {
      const usdtPerDay = rewardPerDay * pepewUsdtPrice;
      const usdtPerWeek = rewardPerWeek * pepewUsdtPrice;
      usdtPerDayStr = "$" + usdtPerDay.toFixed(2);
      usdtPerWeekStr = "$" + usdtPerWeek.toFixed(2);
      usdtPerDayVal = usdtPerDay;
    }

    setText("calc-usdt-day", usdtPerDayStr);
    setText("calc-usdt-week", usdtPerWeekStr);

    updateRewardIntelligence(rewardPerDay, rewardPerWeek, usdtPerDayVal, pepewUsdtPrice, network, pool);
  }

  async function renderDashboard(config) {
    renderDeploymentBaselineNote(null);
    fetchOptionalHealth(config).then(renderDeploymentBaselineNote);

    // Shared object to keep track of loaded values dynamically
    const dashboardData = {
      network: null,
      pool: null,
      price: null
    };

    // Initialize DOM state immediately with neutral/fallback/default values
    const hashrateInput = document.getElementById("calc-hashrate");
    const unitSelect = document.getElementById("calc-unit");

    // Load values defensively from localStorage
    let storedHashrate = localStorage.getItem("calc_hashrate");
    let storedUnit = localStorage.getItem("calc_unit");

    let parsedHashrate = parseFloat(storedHashrate);
    if (isNaN(parsedHashrate) || parsedHashrate < 0) {
      parsedHashrate = 100;
    }
    if (storedUnit !== "H" && storedUnit !== "KH" && storedUnit !== "MH") {
      storedUnit = "KH";
    }

    if (hashrateInput) {
      hashrateInput.value = parsedHashrate;
    }
    if (unitSelect) {
      unitSelect.value = storedUnit;
    }

    // Set immediate Reward Intelligence neutral fallback text
    updateRewardIntelligence(null, null, null, null, null, null);

    // Bind event listeners immediately so user can interact right away
    if (hashrateInput && unitSelect) {
      const runCalc = () => {
        // Store values on change/input
        localStorage.setItem("calc_hashrate", hashrateInput.value);
        localStorage.setItem("calc_unit", unitSelect.value);
        updateCalculator(dashboardData.network, dashboardData.price, dashboardData.pool);
      };
      hashrateInput.addEventListener("input", runCalc);
      unitSelect.addEventListener("change", runCalc);
    }

    // Run initial calculator update (will render neutral/empty/fallback status)
    updateCalculator(null, null, null);

    // Fetch APIs in parallel, catching errors gracefully so we never crash/block
    let pool = {};
    let network = {};
    let blocks = { items: [] };
    let payments = { items: [] };
    let priceData = null;

    try {
      const [poolRes, networkRes, blocksRes, paymentsRes, priceRes] = await Promise.all([
        fetchJson(`${config.apiBaseUrl}/pool/summary`).catch(() => ({})),
        fetchJson(`${config.apiBaseUrl}/network/summary`).catch(() => ({})),
        fetchJson(`${config.apiBaseUrl}/blocks`).catch(() => ({ items: [] })),
        fetchJson(`${config.apiBaseUrl}/payments`).catch(() => ({ items: [] })),
        fetchJson(`${config.apiBaseUrl}/price/pepew-usdt`).catch(() => null)
      ]);
      pool = poolRes;
      network = networkRes;
      blocks = blocksRes;
      payments = paymentsRes;
      priceData = priceRes;
    } catch (_err) {
      // Gracefully continue with defaults
    }

    // Update shared dashboardData object
    dashboardData.network = network;
    dashboardData.pool = pool;
    dashboardData.price = (priceData && typeof priceData.price === "number") ? priceData.price : null;

    const algoDisplay = (pool.algorithm && pool.algorithm.includes("hoohash")) ? "hoohash-pepew / hoohashv110-pepew" : (pool.algorithm || "hoohashv110-pepew");
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

    const stratumEndpoint = pool.stratum ? `stratum+tcp://${pool.stratum.host}:${pool.stratum.port}` : "stratum+tcp://pool.pepepow.net:39333";
    setText("stratum-endpoint", stratumEndpoint);

    // PEPEPOW Mining Radar
    const netHash = network.networkHashrate;
    const poolHash = pool.poolHashrate;

    const isNetValid = (typeof netHash === "number" && netHash > 0);
    const isPoolValid = (typeof poolHash === "number" && poolHash >= 0);

    setText("radar-network-hashrate", isNetValid ? formatHashrate(netHash) : "Unavailable");
    setText("radar-pool-hashrate", isPoolValid ? formatHashrate(poolHash) : "Unavailable");

    if (isNetValid && isPoolValid) {
      const poolShare = poolHash / netHash;
      const unseenHashrate = Math.max(netHash - poolHash, 0);

      let visibility = "Unavailable";
      let variance = "Unavailable";

      if (poolShare < 0.05) {
        visibility = "Low";
        variance = "High";
      } else if (poolShare < 0.15) {
        visibility = "Medium";
        variance = "Medium";
      } else {
        visibility = "Good";
        variance = "Lower";
      }

      setText("radar-pool-share", (poolShare * 100).toFixed(2) + "%");
      setText("radar-unseen-hashrate", formatHashrate(unseenHashrate));
      setText("radar-visibility-signal", visibility);
      setText("radar-reward-variance", variance);
    } else {
      setText("radar-pool-share", "Unavailable");
      setText("radar-unseen-hashrate", "Unavailable");
      setText("radar-visibility-signal", "Unavailable");
      setText("radar-reward-variance", "Unavailable");
    }

    // Run calculator update now that summary/network/price data is loaded
    updateCalculator(dashboardData.network, dashboardData.price, dashboardData.pool);

    setHtml(
      "recent-blocks",
      renderCards(blocks.items.slice(0, 3), [
        { key: "height", label: "Height", render: (val) => renderValueWithCopyAndExplorer(val, "block") },
        { key: "hash", label: "Block hash", render: (val) => renderValueWithCopyAndExplorer(val, "block") },
        { key: "status", label: "Status", render: renderStatusLabel },
        { key: "foundAt", label: "Time", render: formatDate }
      ], "No network blocks tracked in this snapshot window yet.")
    );

    setHtml(
      "recent-payments",
      renderCards(payments.items.slice(0, 3), [
        { key: "wallet", label: "Wallet", render: (val) => renderValueWithCopyAndExplorer(val, "address") },
        { key: "txid", label: "TxID", render: (val) => renderValueWithCopyAndExplorer(val, "txid") },
        { key: "amount", label: "Amount", render: formatNumber },
        { key: "paidAt", label: "Time", render: formatDate }
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
        { key: "height", label: "Height", render: (val) => renderValueWithCopyAndExplorer(val, "block") },
        { key: "hash", label: "Block hash", render: (val) => renderValueWithCopyAndExplorer(val, "block") },
        { key: "status", label: "Status", render: renderStatusLabel },
        { key: "foundAt", label: "Time", render: formatDate },
        { key: "confirmations", label: "Confirms", render: formatNumber }
      ], "No network blocks tracked in this snapshot window yet.", { limit: 50 })
    );
    setHtml(
      "accepted-candidates-table",
      renderTable(candidates.items, [
        { key: "jobId", label: "Job ID" },
        { key: "submitTimestamp", label: "Time", render: formatDate },
        { key: "candidateHash", label: "Candidate hash", render: (val) => renderValueWithCopyAndExplorer(val, "block") },
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
          label: "Height",
          render: (val) => (val ? renderValueWithCopyAndExplorer(val, "block") : "-")
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
        { key: "candidateHash", label: "Candidate hash", render: (val) => renderValueWithCopyAndExplorer(val, "block") },
        {
          key: "matchedHeight",
          label: "Height",
          render: (val) => (val ? renderValueWithCopyAndExplorer(val, "block") : "-")
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
                return `${escapeHtml(short)}\u00a0${pct}%`;
              })
              .join(" / ");

            const detailLines = entries.map(([wallet, d]) => {
              const pct = d.sharePercent.toFixed(2);
              const score = typeof d.shareScore === "number" ? d.shareScore.toFixed(2) : "-";

              let line = `<div style="margin-bottom: 0.15rem;">
                ${renderValueWithCopyAndExplorer(wallet, "address")}:
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
                    return `${escapeHtml(wName)}&nbsp;(${wPct}%&nbsp;total,&nbsp;${wWalletPct}%&nbsp;of&nbsp;wallet)`;
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
        ? `<h3>Most recent recorded payment</h3><div class="kv-list"><div><span>Time</span><strong>${formatDate(latest.paidAt)}</strong></div><div><span>Wallet</span><strong>${renderValueWithCopyAndExplorer(latest.wallet, "address")}</strong></div><div><span>Amount</span><strong>${formatNumber(latest.amount)}</strong></div><div><span>Height</span><strong>${latest.blockHeight ? renderValueWithCopyAndExplorer(latest.blockHeight, "block") : "-"}</strong></div><div><span>TxID</span><strong>${renderValueWithCopyAndExplorer(latest.txid, "txid")}</strong></div></div>`
        : ""
    );

    setHtml(
      "payments-table",
      renderTable(payments.items, [
        { key: "wallet", label: "Wallet", render: (val) => renderValueWithCopyAndExplorer(val, "address") },
        { key: "blockHeight", label: "Height", render: (val) => (val ? renderValueWithCopyAndExplorer(val, "block") : "-") },
        { key: "candidateHash", label: "Candidate hash", render: (val) => renderValueWithCopyAndExplorer(val, "block") },
        { key: "amount", label: "Amount", render: formatNumber },
        { key: "paidAt", label: "Time", render: formatDate },
        { key: "confirmations", label: "Confirms", render: formatNumber },
        { key: "txid", label: "TxID", render: (val) => renderValueWithCopyAndExplorer(val, "txid") }
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

      htmlContent += renderMinerSummaryMetrics([
        {
          label: "Active Workers",
          value: formatNumber(summary.activeWorkers)
        },
        {
          label: "Estimated Hashrate",
          value: formatHashrate(summary.hashrate),
          note: "Pool-side estimate from accepted shares, not the miner’s exact local GPU hashrate."
        },
        {
          label: "Accepted Shares",
          value: formatNumber(summary.acceptedShares),
          note: "Shares accepted by the pool. This does not imply a confirmed block or recorded payment."
        },
        {
          label: "Last Share",
          value: formatDate(summary.lastShareAt)
        }
      ]);

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
        label: "TxID",
        render: (val) => renderValueWithCopyAndExplorer(val, "txid")
      },
      { key: "blockHeight", label: "Height", render: (val) => (val ? renderValueWithCopyAndExplorer(val, "block") : "-") },
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
