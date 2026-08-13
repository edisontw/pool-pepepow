(function () {
  const PRICE_WAIT_MS = 350;
  const originalToLocaleString = Date.prototype.toLocaleString;

  if (document.body.dataset.page !== "miner" || typeof window.fetch !== "function") return;
  if (window.__pepepowMinerFastFetchInstalled) return;

  function pad(value) {
    return String(value).padStart(2, "0");
  }

  function formatDateTime(date) {
    return [
      date.getFullYear(), "-", pad(date.getMonth() + 1), "-", pad(date.getDate()), " ",
      pad(date.getHours()), ":", pad(date.getMinutes()), ":", pad(date.getSeconds())
    ].join("");
  }

  Date.prototype.toLocaleString = function (locales, options) {
    if (arguments.length === 0) return formatDateTime(this);
    return originalToLocaleString.call(this, locales, options);
  };

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelector('[aria-label="Pure SOLO testing notice"]')?.remove();
  }, { once: true });

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

  function enrichSoloMinerPayload(payload) {
    if (!payload || typeof payload !== "object") return payload;
    const blocks = Array.isArray(payload.blocks) ? payload.blocks : [];
    const payments = Array.isArray(payload.payments) ? payload.payments : [];
    const byHash = new Map();
    blocks.forEach(function (block) {
      if (block && block.hash) byHash.set(String(block.hash), block);
    });
    payload.payments = payments.map(function (payment) {
      if (!payment || typeof payment !== "object") return payment;
      const candidateId = String(payment.candidateId || payment.candidate_id || "");
      const candidateHash = candidateId.replace(/^solo:/, "");
      const block = byHash.get(candidateHash);
      if (!block) return payment;
      return {
        ...payment,
        blockHeight: payment.blockHeight ?? block.height,
        blockHash: payment.blockHash ?? block.hash,
        confirmations: block.confirmations ?? payment.confirmations
      };
    });
    return payload;
  }

  window.fetch = function (input, init) {
    const pathname = pathnameOf(input);

    if (pathname === "/api/payments") {
      return Promise.resolve(jsonResponse({ items: [], boundedForMinerLookup: true }));
    }

    if (pathname.startsWith("/api/solo/miner/")) {
      return originalFetch(input, init).then(async function (response) {
        if (!response.ok) return response;
        const payload = await response.clone().json().catch(function () { return null; });
        return payload ? jsonResponse(enrichSoloMinerPayload(payload)) : response;
      });
    }

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
