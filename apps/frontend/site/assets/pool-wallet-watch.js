(function () {
  const WALLET = "PKTwq3nHNxwcVgDX4QwVxQGX5DYjJB8nho";
  const ADDRESS_API = `https://explorer.pepepow.net/ext/getaddress/${encodeURIComponent(WALLET)}`;
  const BALANCE_API = `https://explorer.pepepow.net/ext/getbalance/${encodeURIComponent(WALLET)}`;
  const HEIGHT_API = "https://explorer.pepepow.net/api/getblockcount";
  const ADDRESS_PAGE = `https://explorer.pepepow.net/address/${encodeURIComponent(WALLET)}`;
  const STATE_KEY = "pepepow.poolWalletWatch.v1";
  const NO_GROWTH_WARNING_MS = 3 * 60 * 60 * 1000;

  function setText(id, value) {
    const node = document.getElementById(id);
    if (node) node.textContent = value;
  }

  function setHtml(id, value) {
    const node = document.getElementById(id);
    if (node) node.innerHTML = value;
  }

  function asNumber(value) {
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (typeof value === "string") {
      const cleaned = value.replace(/,/g, "").trim();
      if (!cleaned) return null;
      const parsed = Number(cleaned);
      return Number.isFinite(parsed) ? parsed : null;
    }
    return null;
  }

  function firstNumber(obj, keys) {
    if (!obj || typeof obj !== "object") return null;
    for (const key of keys) {
      const parsed = asNumber(obj[key]);
      if (parsed !== null) return parsed;
    }
    return null;
  }

  function formatPepew(value) {
    if (typeof value !== "number" || !Number.isFinite(value)) return "-";
    return new Intl.NumberFormat(undefined, {
      maximumFractionDigits: value >= 1000000 ? 0 : 3
    }).format(value);
  }

  function formatDelta(value) {
    if (typeof value !== "number" || !Number.isFinite(value)) return "";
    if (Math.abs(value) < 0.000001) return "0";
    const sign = value > 0 ? "+" : "";
    return `${sign}${formatPepew(value)}`;
  }

  function formatTime(value) {
    if (!value) return "-";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "-";
    return date.toLocaleString();
  }

  async function fetchJsonOrText(url) {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const text = await response.text();
    try {
      return JSON.parse(text);
    } catch (_error) {
      return text.trim();
    }
  }

  function readStoredState() {
    try {
      const raw = window.localStorage.getItem(STATE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (_error) {
      return null;
    }
  }

  function writeStoredState(state) {
    try {
      window.localStorage.setItem(STATE_KEY, JSON.stringify(state));
    } catch (_error) {
      // Best-effort browser-side transparency only.
    }
  }

  function explorerLink(label) {
    return `<a href="${ADDRESS_PAGE}" target="_blank" rel="noopener noreferrer">${label}</a>`;
  }

  async function loadPoolWalletWatch() {
    const statusId = "pool-wallet-watch-status";
    const balanceId = "pool-wallet-watch-balance";
    const receivedId = "pool-wallet-watch-received";
    const deltaId = "pool-wallet-watch-delta";
    const updatedId = "pool-wallet-watch-updated";
    const noteId = "pool-wallet-watch-note";

    if (!document.getElementById(statusId)) return;

    setText(statusId, "Checking explorer");
    setText(balanceId, "-");
    setText(receivedId, "-");
    setText(deltaId, "-");
    setText(updatedId, "-");
    setHtml(noteId, `Read-only rough signal from ${explorerLink("pool reward wallet")}.`);

    try {
      const [addressData, balanceData, heightData] = await Promise.allSettled([
        fetchJsonOrText(ADDRESS_API),
        fetchJsonOrText(BALANCE_API),
        fetchJsonOrText(HEIGHT_API)
      ]);

      if (addressData.status !== "fulfilled") {
        throw addressData.reason || new Error("Explorer address API failed");
      }

      const addressPayload = addressData.value;
      const addressObject = Array.isArray(addressPayload) ? addressPayload[0] : addressPayload;
      const fallbackBalance = balanceData.status === "fulfilled" ? asNumber(balanceData.value) : null;
      const height = heightData.status === "fulfilled" ? asNumber(heightData.value) : null;

      const balance = firstNumber(addressObject, [
        "balance", "Balance", "currentBalance", "current_balance"
      ]) ?? fallbackBalance;
      const totalReceived = firstNumber(addressObject, [
        "received", "totalReceived", "total_received", "totalreceived", "Total Received", "totalReceivedAmount"
      ]);
      const totalSent = firstNumber(addressObject, [
        "sent", "totalSent", "total_sent", "totalsent", "Total Sent", "totalSentAmount"
      ]);

      const nowIso = new Date().toISOString();
      const previous = readStoredState();
      const previousReceived = previous && typeof previous.totalReceived === "number" ? previous.totalReceived : null;
      const deltaReceived = previousReceived !== null && totalReceived !== null ? totalReceived - previousReceived : null;
      const previousBalance = previous && typeof previous.balance === "number" ? previous.balance : null;
      const deltaBalance = previousBalance !== null && balance !== null ? balance - previousBalance : null;

      let lastGrowthAt = previous && previous.lastGrowthAt ? previous.lastGrowthAt : null;
      if (deltaReceived !== null && deltaReceived > 0) {
        lastGrowthAt = nowIso;
      } else if (!lastGrowthAt && totalReceived !== null) {
        lastGrowthAt = nowIso;
      }

      const minutesSinceGrowth = lastGrowthAt
        ? Math.max(0, (Date.now() - new Date(lastGrowthAt).getTime()) / 60000)
        : null;

      let status = "OK";
      let note = "Total received is the main rough signal. Balance can fall when payouts are sent.";
      if (totalReceived === null) {
        status = "Explorer format changed";
        note = "Explorer API responded, but total received was not found.";
      } else if (minutesSinceGrowth !== null && minutesSinceGrowth * 60000 > NO_GROWTH_WARNING_MS) {
        status = "Watch";
        note = "No browser-observed total received growth for over 3 hours. Check blocks/payments if miners are active.";
      }
      if (deltaBalance !== null && deltaBalance < 0 && status === "OK") {
        note = "Balance decreased; this can be normal when payouts are sent. Total received remains the main signal.";
      }

      setText(statusId, status);
      setText(balanceId, `${formatPepew(balance)} PEPEW`);
      setText(receivedId, `${formatPepew(totalReceived)} PEPEW`);
      setText(deltaId, deltaReceived === null ? "First browser sample" : `${formatDelta(deltaReceived)} PEPEW`);
      setText(updatedId, height ? `Height ${formatPepew(height)}` : formatTime(nowIso));
      setHtml(noteId, `${note} ${explorerLink("Open explorer ↗")}`);

      writeStoredState({
        wallet: WALLET,
        balance,
        totalReceived,
        totalSent,
        height,
        lastGrowthAt,
        updatedAt: nowIso
      });
    } catch (error) {
      setText(statusId, "Explorer unavailable");
      setText(balanceId, "-");
      setText(receivedId, "-");
      setText(deltaId, "-");
      setText(updatedId, "-");
      setHtml(noteId, `Could not read explorer API from this browser. ${explorerLink("Open wallet manually ↗")}`);
      console.warn("Pool wallet watch failed:", error);
    }
  }

  document.addEventListener("DOMContentLoaded", loadPoolWalletWatch);
})();
