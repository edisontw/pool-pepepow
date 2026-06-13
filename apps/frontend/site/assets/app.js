(function () {
  const DEFAULT_CONFIG = {
    apiBaseUrl: "/api",
    refreshIntervalMs: 60000,
    stratumHost: "stratum+tcp://pool.pepepow.net:39333"
  };

  const FRONTEND_BUILD = "dashboard-fix-v7";
  console.log("PEPEPOW Frontend Build:", FRONTEND_BUILD);

  function readPoolHashrateHps(pool) {
    if (!pool || typeof pool !== "object") {
      return null;
    }

    const candidateKeys = [
      "poolHashrate",
      "pool_hashrate",
      "hashrate",
      "estimatedHashrate",
      "estimated_hashrate",
      "hashrateHps",
      "hashrate_hps",
      "hashRate",
      "hash_rate",
      "currentHashrate",
      "current_hashrate",
      "shareDerivedHashrate",
      "share_derived_hashrate"
    ];

    function parseValueToHps(val) {
      if (typeof val === "number") {
        if (!isNaN(val) && isFinite(val)) {
          return val;
        }
        return null;
      }
      if (typeof val === "string") {
        const cleaned = val.trim().toLowerCase();
        const num = parseFloat(cleaned);
        if (isNaN(num)) {
          return null;
        }
        if (cleaned.includes("mh/s") || cleaned.includes("mh")) {
          return num * 1000000;
        }
        if (cleaned.includes("kh/s") || cleaned.includes("kh")) {
          return num * 1000;
        }
        if (cleaned.includes("gh/s") || cleaned.includes("gh")) {
          return num * 1000000000;
        }
        if (cleaned.includes("th/s") || cleaned.includes("th")) {
          return num * 1000000000000;
        }
        return num;
      }
      return null;
    }

    for (const key of candidateKeys) {
      if (key in pool && pool[key] !== null && pool[key] !== undefined) {
        const hps = parseValueToHps(pool[key]);
        if (hps !== null) {
          return hps;
        }
      }
    }

    if (pool.rolling && typeof pool.rolling === "object") {
      for (const windowKey of ["5m", "15m", "1m"]) {
        const windowObj = pool.rolling[windowKey];
        if (windowObj && typeof windowObj === "object") {
          for (const key of candidateKeys) {
            if (key in windowObj && windowObj[key] !== null && windowObj[key] !== undefined) {
              const hps = parseValueToHps(windowObj[key]);
              if (hps !== null) {
                return hps;
              }
            }
          }
        }
      }
    }

    return null;
  }

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

  // ---- Miner Reward Analysis helpers ----

  /**
   * Read the miner-side hashrate from the miner API response summary.
   * Returns H/s as a number, or null if unavailable.
   */
  function readMinerHashrateHps(minerData) {
    const summary = (minerData && typeof minerData === "object") ? (minerData.summary || minerData) : null;
    if (!summary) return null;

    const candidateKeys = [
      "hashrate", "hashrateHps", "hashrate_hps",
      "estimatedHashrate", "estimated_hashrate",
      "shareDerivedHashrate", "share_derived_hashrate"
    ];

    for (const key of candidateKeys) {
      const val = summary[key];
      if (val === null || val === undefined) continue;
      if (typeof val === "number" && isFinite(val) && val >= 0) return val;
    }
    return null;
  }

  /**
   * Compute estimated reward per hour/day/week given miner hashrate and network/pool context.
   * Returns { rewardPerHour, rewardPerDay, rewardPerWeek } or null if inputs are invalid.
   */
  function calculateRewards(hashrateHps, network, pool) {
    if (typeof hashrateHps !== "number" || !isFinite(hashrateHps) || hashrateHps <= 0) return null;
    const netHash = network ? network.networkHashrate : null;
    if (typeof netHash !== "number" || netHash <= 0) return null;

    const BLOCK_TIME_SECONDS = 20;
    const TOTAL_BLOCK_REWARD = 7000;
    const DEVELOPER_FEE_RATIO = 0.05;
    const MINER_REWARD_RATIO = 0.65;
    const poolFeeRatio = (pool && typeof pool.feePercent === "number" && isFinite(pool.feePercent) && pool.feePercent > 0)
      ? pool.feePercent / 100
      : 0;

    const blocksPerDay = 86400 / BLOCK_TIME_SECONDS;
    const minerRewardPerBlock = TOTAL_BLOCK_REWARD * (1 - DEVELOPER_FEE_RATIO) * MINER_REWARD_RATIO * (1 - poolFeeRatio);

    const rewardPerDay = (hashrateHps / netHash) * blocksPerDay * minerRewardPerBlock;
    return {
      rewardPerHour: rewardPerDay / 24,
      rewardPerDay,
      rewardPerWeek: rewardPerDay * 7
    };
  }

  /**
   * SOURCE GUARD: Do not compute accepted rate from lifetime rejected totals.
   * Only return a rate if a reliable recent accepted-rate field is present in minerData.
   * Returns a number 0-1, or null.
   */
  function chooseMinerAcceptedRate(minerData) {
    const summary = (minerData && typeof minerData === "object") ? (minerData.summary || minerData) : null;
    if (!summary) return null;

    // Only use explicit recent accepted-rate fields – never compute from lifetime totals.
    const recentFields = ["recentAcceptedRate", "recent_accepted_rate", "acceptedRate", "accepted_rate"];
    for (const key of recentFields) {
      const val = summary[key];
      if (typeof val === "number" && isFinite(val) && val >= 0 && val <= 1) return val;
    }
    return null;
  }

  /**
   * Render Miner Reward Analysis into #miner-reward-analysis.
   * Only called after a successful wallet lookup.
   */
  function renderMinerRewardAnalysis(minerResult, wallet, pool, network, price) {
    const container = document.getElementById("miner-reward-analysis");
    if (!container) return;

    if (!minerResult || !minerResult.found) {
      container.innerHTML = "";
      return;
    }

    const summary = minerResult.summary || {};
    const hashrateHps = readMinerHashrateHps(minerResult);
    const rewards = calculateRewards(hashrateHps, network, pool);
    const acceptedRate = chooseMinerAcceptedRate(minerResult);
    const pepewPrice = (price && typeof price.price === "number") ? price.price : null;

    const activeWorkers = formatNumber(summary.activeWorkers);
    const acceptedShares = formatNumber(summary.acceptedShares);
    const hashrateStr = hashrateHps !== null ? formatHashrate(hashrateHps) : "Unavailable";

    let rows = "";
    rows += `<div><span>Wallet</span><strong>${escapeHtml(wallet)}</strong></div>`;
    rows += `<div><span>Estimated Hashrate</span><strong>${escapeHtml(hashrateStr)}</strong></div>`;
    rows += `<div><span>Active Workers</span><strong>${escapeHtml(activeWorkers)}</strong></div>`;
    rows += `<div><span>Accepted Shares</span><strong>${escapeHtml(acceptedShares)}</strong></div>`;

    if (acceptedRate !== null) {
      const ratePct = (acceptedRate * 100).toFixed(2) + "%";
      const rateNote = acceptedRate < 0.995
        ? " (below 99.5% — may reduce estimated rewards slightly)"
        : "";
      rows += `<div><span>Accepted Rate (recent)</span><strong>${escapeHtml(ratePct + rateNote)}</strong></div>`;
    } else {
      rows += `<div style="grid-column: 1 / -1;"><span>Accepted Rate</span><strong style="font-weight:400; color: var(--muted); font-size:0.9em;">Accepted-rate impact is not shown because no reliable recent accepted-rate field is available.</strong></div>`;
    }

    if (rewards) {
      const pepewHour = formatNumber(Math.round(rewards.rewardPerHour * 100) / 100);
      const pepewDay  = formatNumber(Math.round(rewards.rewardPerDay  * 100) / 100);
      const pepewWeek = formatNumber(Math.round(rewards.rewardPerWeek * 100) / 100);
      rows += `<div><span>Estimated PEPEW / Hour</span><strong>${escapeHtml(pepewHour)}</strong></div>`;
      rows += `<div><span>Estimated PEPEW / Day</span><strong>${escapeHtml(pepewDay)}</strong></div>`;
      rows += `<div><span>Estimated PEPEW / Week</span><strong>${escapeHtml(pepewWeek)}</strong></div>`;

      if (pepewPrice !== null) {
        const usdtDay  = "$" + (rewards.rewardPerDay  * pepewPrice).toFixed(2);
        const usdtWeek = "$" + (rewards.rewardPerWeek * pepewPrice).toFixed(2);
        rows += `<div><span>Estimated USDT / Day</span><strong>${escapeHtml(usdtDay)}</strong></div>`;
        rows += `<div><span>Estimated USDT / Week</span><strong>${escapeHtml(usdtWeek)}</strong></div>`;
      }
    } else {
      rows += `<div style="grid-column: 1 / -1;"><span>Estimated Rewards</span><strong style="font-weight:400; color: var(--muted); font-size:0.9em;">Reward estimates unavailable — network hashrate or miner hashrate data is missing. May fluctuate with pool luck and current network hashrate.</strong></div>`;
    }

    container.innerHTML = `
      <section class="panel" style="margin-top: 1.25rem;">
        <p class="eyebrow">Wallet-Specific</p>
        <h3>Miner Reward Analysis</h3>
        <div class="metric-grid">
          ${rows}
        </div>
        <p class="muted small-gap" style="font-size: 0.82rem; margin-top: 1rem; line-height: 1.4;">
          * Estimated only. Based on current activity: observed hashrate, current network hashrate, and pool settings.
            Actual results may fluctuate with pool luck, network hashrate changes, and accepted share activity.
            Not a guaranteed or pending payout figure.
        </p>
      </section>`;
  }

  function updateCalculator(network, pepewUsdtPrice, pool) {
    const hashrateInput = document.getElementById("calc-hashrate");
    const unitSelect = document.getElementById("calc-unit");
    if (!hashrateInput || !unitSelect) return;

    const hashrateVal = parseFloat(hashrateInput.value);
    const unitVal = unitSelect.value;

    const netHash = network ? network.networkHashrate : null;
    const isNetValid = (typeof netHash === "number" && netHash > 0);

    if (isNaN(hashrateVal) || hashrateVal < 0 || !isNetValid) {
      setText("calc-pepew-hour", "-");
      setText("calc-pepew-day", "-");
      setText("calc-pepew-week", "-");
      setText("calc-usdt-day", "Price unavailable");
      setText("calc-usdt-week", "Price unavailable");

      return;
    }

    let userHashrateHps = hashrateVal;
    if (unitVal === "KH") {
      userHashrateHps = hashrateVal * 1000;
    } else if (unitVal === "MH") {
      userHashrateHps = hashrateVal * 1000000;
    }

    const BLOCK_TIME_SECONDS = 20;
    const TOTAL_BLOCK_REWARD = 7000;
    const DEVELOPER_FEE_RATIO = 0.05;
    const MINER_REWARD_RATIO = 0.65;
    const poolFeeRatio = (pool && typeof pool.feePercent === "number" && isFinite(pool.feePercent) && pool.feePercent > 0)
      ? pool.feePercent / 100
      : 0;

    const blocksPerDay = 86400 / BLOCK_TIME_SECONDS;
    const minerRewardPerBlock = TOTAL_BLOCK_REWARD * (1 - DEVELOPER_FEE_RATIO) * MINER_REWARD_RATIO * (1 - poolFeeRatio);

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
    setText("pool-hashrate", formatHashrate(readPoolHashrateHps(pool)));
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
    const poolHash = readPoolHashrateHps(pool);

    const isNetValid = (typeof netHash === "number" && netHash > 0);
    const isPoolValid = (typeof poolHash === "number" && isFinite(poolHash) && poolHash >= 0);

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
    // Fetch miner data plus supporting context in parallel
    const [result, pool, network, priceData] = await Promise.all([
      fetchJson(`${config.apiBaseUrl}/miner/${encodeURIComponent(wallet)}`),
      fetchJson(`${config.apiBaseUrl}/pool/summary`).catch(() => ({})),
      fetchJson(`${config.apiBaseUrl}/network/summary`).catch(() => ({})),
      fetchJson(`${config.apiBaseUrl}/price/pepew-usdt`).catch(() => null)
    ]);

    let htmlContent = "";

    if (!result.found) {
      htmlContent += `<div class="empty-state"><strong>No active miner data found for ${escapeHtml(wallet)}.</strong><p class="muted">Miner statistics are generated from active share submissions and are only retained while there is active mining activity within the snapshot tracking window. If you just started mining, it may take up to a minute for your first accepted share to appear here.</p><a class="button" href="/connect.html">How to start mining</a></div>`;
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
          note: "Pool-side estimate from accepted shares, not the miner's exact local GPU hashrate."
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
      { key: "paidAt", label: "Paid", render: (_val, item) => formatDate(item.paidAt || item.timestamp) },
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

    // Render wallet-specific Miner Reward Analysis (only after successful lookup)
    renderMinerRewardAnalysis(result, wallet, pool, network, priceData);
  }

  // ---- Miner wallet persistence (isolated to renderMiner) ----

  const MINER_LOOKUP_STORAGE_KEY = "pepepow_miner_lookup_wallet";

  function safeGetLastMinerLookupWallet() {
    try {
      const value = localStorage.getItem(MINER_LOOKUP_STORAGE_KEY);
      return value && isLikelyPepepowAddress(value) ? value : "";
    } catch (_error) {
      return "";
    }
  }

  function safeSetLastMinerLookupWallet(wallet) {
    try {
      if (wallet && isLikelyPepepowAddress(wallet)) {
        localStorage.setItem(MINER_LOOKUP_STORAGE_KEY, wallet);
      }
    } catch (_error) {
      // Ignore storage failures.
    }
  }

  function safeClearLastMinerLookupWallet() {
    try {
      localStorage.removeItem(MINER_LOOKUP_STORAGE_KEY);
    } catch (_error) {
      // Ignore storage failures.
    }
  }

  async function renderMiner(config) {
    const form = document.getElementById("miner-form");
    const input = document.getElementById("wallet-input");

    if (!form || !input) {
      return;
    }

    const savedWallet = safeGetLastMinerLookupWallet();
    if (!input.value.trim() && savedWallet) {
      input.value = savedWallet;
    }

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const wallet = input.value.trim();
      if (!wallet) {
        safeClearLastMinerLookupWallet();
        setHtml("miner-result", '<div class="empty-state"><strong>Enter a PEPEPOW wallet address to check miner status.</strong><p class="muted">Data will appear after the pool receives accepted shares.</p><a class="button" href="/connect.html">How to start mining</a></div>');
        return;
      }
      safeSetLastMinerLookupWallet(wallet);
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
