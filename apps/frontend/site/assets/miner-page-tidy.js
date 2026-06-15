(function () {
  function walletFromUrl() {
    try {
      const params = new URLSearchParams(window.location.search || "");
      return params.get("wallet") || "";
    } catch (_error) {
      return "";
    }
  }

  function setWalletFromUrl() {
    const wallet = walletFromUrl().trim();
    if (!wallet) return;
    const input = document.getElementById("wallet-input");
    if (input && !input.value.trim()) input.value = wallet;
  }

  function cleanRecordedPaymentsTable() {
    const root = document.getElementById("miner-recorded-payments");
    if (!root) return;
    const table = root.querySelector("table");
    if (!table || table.dataset.minerTidied === "1") return;
    table.dataset.minerTidied = "1";

    const headerCells = Array.from(table.querySelectorAll("thead th"));
    const walletIndex = headerCells.findIndex(function (cell) {
      return cell.textContent.trim().toLowerCase() === "wallet";
    });

    if (walletIndex >= 0) {
      table.querySelectorAll("tr").forEach(function (row) {
        const cells = row.children;
        if (cells[walletIndex]) cells[walletIndex].remove();
      });
    }

    Array.from(table.querySelectorAll('td[data-label="TxID"] [data-copy-value]')).forEach(function (button) {
      button.remove();
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    setWalletFromUrl();
    const target = document.getElementById("miner-result");
    if (!target) return;
    const observer = new MutationObserver(function () {
      window.setTimeout(cleanRecordedPaymentsTable, 0);
    });
    observer.observe(target, { childList: true, subtree: true });
    cleanRecordedPaymentsTable();
  });
})();