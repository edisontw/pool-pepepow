(function () {
  const SNAPSHOT_URL = "/pool-wallet-monitor.json";

  function setText(id, value) {
    const node = document.getElementById(id);
    if (node) node.textContent = value;
  }

  function setHtml(id, value) {
    const node = document.getElementById(id);
    if (node) node.innerHTML = value;
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

  async function loadPoolWalletWatch() {
    const root = document.getElementById("pool-wallet-watch-card");
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
      const explorerUrl = data.explorerWalletUrl || "https://explorer.pepepow.net/address/PKTwq3nHNxwcVgDX4QwVxQGX5DYjJB8nho";
      const windowLabel = windowDelta !== null ? formatWindow(windowHours, sampleHours) : "latest sample";

      root.classList.remove("is-ok", "is-guarded", "is-alert");
      const cls = statusClass(status);
      if (cls) root.classList.add(cls);

      setText("pool-wallet-watch-status", statusLabel(status));
      setText("pool-wallet-watch-headline", headline);
      setText("pool-wallet-watch-main", displayDelta !== null ? `${displayDelta >= 0 ? "+" : ""}${formatPepew(displayDelta)} PEPEW` : "No previous sample");
      setText("pool-wallet-watch-sub", `${windowLabel} · Updated ${formatAge(updatedAt)}`);
      setHtml("pool-wallet-watch-note", `${summary} <a href="${explorerUrl}" target="_blank" rel="noopener noreferrer">Open explorer ↗</a>`);
    } catch (error) {
      root.classList.remove("is-ok", "is-guarded");
      root.classList.add("is-alert");
      setText("pool-wallet-watch-status", "Waiting for monitor");
      setText("pool-wallet-watch-headline", "No server snapshot yet");
      setText("pool-wallet-watch-main", "-");
      setText("pool-wallet-watch-sub", "Run live-stratum pool wallet monitor to publish the snapshot.");
      setHtml("pool-wallet-watch-note", "Server-side monitor snapshot is not available yet.");
      console.warn("Pool wallet monitor snapshot unavailable:", error);
    }
  }

  document.addEventListener("DOMContentLoaded", loadPoolWalletWatch);
})();
