(function () {
  const DEFAULT_CONFIG = {
    apiBaseUrl: "/api",
    refreshIntervalMs: 60000,
    stratumHost: "stratum+tcp://pool.example.com:3333"
  };

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

  function renderCards(items, fields) {
    if (!Array.isArray(items) || items.length === 0) {
      return '<div class="muted">No items available.</div>';
    }

    return items
      .map((item) => {
        const body = fields
          .map((field) => {
            const rawValue = typeof field.render === "function"
              ? field.render(item[field.key], item)
              : item[field.key];
            return `<div><span>${field.label}</span> <strong>${rawValue ?? "-"}</strong></div>`;
          })
          .join("");

        return `<article class="item-card">${body}</article>`;
      })
      .join("");
  }

  function renderTable(items, columns) {
    if (!Array.isArray(items) || items.length === 0) {
      return '<div class="muted">No items available.</div>';
    }

    const head = columns.map((column) => `<th>${column.label}</th>`).join("");
    const rows = items
      .map((item) => {
        const cells = columns
          .map((column) => {
            const rawValue = typeof column.render === "function"
              ? column.render(item[column.key], item)
              : item[column.key];
            return `<td>${rawValue ?? "-"}</td>`;
          })
          .join("");
        return `<tr>${cells}</tr>`;
      })
      .join("");

    return `<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table></div>`;
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

    setText("algorithm", pool.algorithm);
    setText("pool-status", pool.poolStatus);
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
        { key: "status", label: "Status" },
        { key: "foundAt", label: "Found", render: formatDate }
      ])
    );

    setHtml(
      "recent-payments",
      renderCards(payments.items.slice(0, 3), [
        { key: "wallet", label: "Wallet" },
        { key: "amount", label: "Amount", render: formatNumber },
        { key: "paidAt", label: "Paid", render: formatDate }
      ])
    );
  }

  async function renderBlocks(config) {
    const blocks = await fetchJson(`${config.apiBaseUrl}/blocks`);
    setHtml(
      "blocks-table",
      renderTable(blocks.items, [
        { key: "height", label: "Height", render: formatNumber },
        { key: "hash", label: "Hash" },
        { key: "status", label: "Status" },
        { key: "foundAt", label: "Found", render: formatDate },
        { key: "confirmations", label: "Confirms", render: formatNumber }
      ])
    );
  }

  async function renderPayments(config) {
    const payments = await fetchJson(`${config.apiBaseUrl}/payments`);
    setHtml(
      "payments-table",
      renderTable(payments.items, [
        { key: "wallet", label: "Wallet" },
        { key: "amount", label: "Amount", render: formatNumber },
        { key: "paidAt", label: "Paid", render: formatDate },
        { key: "confirmations", label: "Confirms", render: formatNumber },
        { key: "txid", label: "TXID" }
      ])
    );
  }

  async function lookupMiner(config, wallet) {
    const result = await fetchJson(
      `${config.apiBaseUrl}/miner/${encodeURIComponent(wallet)}`
    );

    if (!result.found) {
      setHtml(
        "miner-result",
        `<div class="muted">No miner data found for <strong>${wallet}</strong>.</div>`
      );
      return;
    }

    const summary = result.summary || {};
    const workers = Array.isArray(result.workers) ? result.workers : [];
    const payments = Array.isArray(result.payments) ? result.payments : [];

    setHtml(
      "miner-result",
      [
        renderCards(
          [
            {
              label: "Hashrate",
              value: formatHashrate(summary.hashrate)
            },
            {
              label: "Pending Balance",
              value: formatNumber(summary.pendingBalance)
            },
            {
              label: "Total Paid",
              value: formatNumber(summary.totalPaid)
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
        ),
        "<h3>Workers</h3>",
        renderTable(workers, [
          { key: "name", label: "Worker" },
          { key: "hashrate", label: "Hashrate", render: formatHashrate },
          { key: "lastShareAt", label: "Last Share", render: formatDate }
        ]),
        "<h3>Recent Payments</h3>",
        renderTable(payments, [
          { key: "amount", label: "Amount", render: formatNumber },
          { key: "paidAt", label: "Paid", render: formatDate },
          { key: "confirmations", label: "Confirms", render: formatNumber },
          { key: "txid", label: "TXID" }
        ])
      ].join("")
    );
  }

  async function renderMiner(config) {
    const form = document.getElementById("miner-form");
    const input = document.getElementById("wallet-input");

    if (!form || !input) {
      return;
    }

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      setHtml("miner-result", '<div class="muted">Loading miner data...</div>');
      try {
        await lookupMiner(config, input.value.trim());
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
      `./miner --algo ${pool.algorithm} --server ${endpoint} --user YOUR_WALLET.worker01 --pass x`;

    setText("connect-algorithm", pool.algorithm);
    setText("connect-endpoint", endpoint);
    setText("sample-command", sampleCommand);
  }

  async function run() {
    setActiveNav();
    const page = document.body.dataset.page;
    const config = await loadRuntimeConfig();

    try {
      if (page === "dashboard") {
        await renderDashboard(config);
      } else if (page === "blocks") {
        await renderBlocks(config);
      } else if (page === "payments") {
        await renderPayments(config);
      } else if (page === "miner") {
        await renderMiner(config);
      } else if (page === "connect") {
        await renderConnect(config);
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
