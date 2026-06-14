(function () {
  const originalToLocaleString = Date.prototype.toLocaleString;

  function pad(value) {
    return String(value).padStart(2, "0");
  }

  function formatDateTime(date) {
    return [
      date.getFullYear(),
      "-",
      pad(date.getMonth() + 1),
      "-",
      pad(date.getDate()),
      " ",
      pad(date.getHours()),
      ":",
      pad(date.getMinutes()),
      ":",
      pad(date.getSeconds())
    ].join("");
  }

  Date.prototype.toLocaleString = function (locales, options) {
    if (arguments.length === 0) {
      return formatDateTime(this);
    }
    return originalToLocaleString.call(this, locales, options);
  };
})();
