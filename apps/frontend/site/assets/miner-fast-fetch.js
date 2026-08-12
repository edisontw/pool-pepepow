(function () {
  const PRICE_WAIT_MS = 350;

  if (document.body.dataset.page !== "miner" || typeof window.fetch !== "function") return;
  if (window.__pepepowMinerFastFetchInstalled) return;

  const originalFetch = window.fetch.bind(window);

  function pathnameOf(input) {
    try {
      const raw = typeof input === "string"
        ? input
        : (input && typeof input.url === "string" ? input.url : "");
      return new URL(raw, window.location.origin).pathname;
    } catch (_error) {
      return "";
    }
  }

  function jsonResponse(payload) {
    return new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "Content-Type": "application/json" }
    });
  }

  window.fetch = function (input, init) {
    const pathname = pathnameOf(input);

    // /api/miner/<wallet> already returns recentPayments for that wallet.
    // The legacy Miner renderer also requests the complete payment snapshot
    // only to filter it again in the browser. Avoid that multi-thousand-row
    // transfer and let the renderer fall back to recentPayments.
    if (pathname === "/api/payments") {
      return Promise.resolve(jsonResponse({ items: [], boundedForMinerLookup: true }));
    }

    // Price is secondary information. Keep the real request running, but do
    // not let an external price refresh delay wallet activity by several
    // seconds. If it is not ready quickly, render miner data without fiat
    // estimates; a later page load can use the refreshed server cache.
    if (pathname === "/api/price/pepew-usdt") {
      const actual = originalFetch(input, init);
      const deadline = new Promise(function (resolve) {
        window.setTimeout(function () {
          resolve(jsonResponse({
            symbol: "PEPEW_USDT",
            price: null,
            source: "deferred",
            updatedAt: null,
            cacheSeconds: 0
          }));
        }, PRICE_WAIT_MS);
      });
      return Promise.race([actual, deadline]);
    }

    return originalFetch(input, init);
  };

  window.__pepepowMinerFastFetchInstalled = true;
})();
