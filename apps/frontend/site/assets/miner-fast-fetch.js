(function () {
  const PRICE_WAIT_MS = 350;

  function install() {
    if (document.body.dataset.page !== "miner") return;
    const ui = window.PepepowUI;
    if (!ui || typeof ui.fetchJson !== "function" || ui.__minerFastFetchInstalled) return;

    const originalFetchJson = ui.fetchJson.bind(ui);

    ui.fetchJson = function (url, options) {
      const target = String(url || "");

      // Miner Lookup already receives wallet-specific recentPayments from
      // /api/miner/<wallet>. Do not download the complete public payment
      // history simply to filter it again in the browser.
      if (/\/api\/payments(?:\?|$)/.test(target)) {
        return Promise.resolve({ items: [], boundedForMinerLookup: true });
      }

      // Price is secondary display data. A slow external price refresh must
      // never hold back wallet activity, workers, blocks, or payments.
      if (/\/api\/price\/pepew-usdt(?:\?|$)/.test(target)) {
        const backgroundRequest = originalFetchJson(url, options).catch(function () { return null; });
        const deadline = new Promise(function (resolve) {
          window.setTimeout(function () { resolve(null); }, PRICE_WAIT_MS);
        });
        return Promise.race([backgroundRequest, deadline]);
      }

      return originalFetchJson(url, options);
    };

    ui.__minerFastFetchInstalled = true;
  }

  install();
})();
