(() => {
  const measurementId = "G-X2B6WBJHHS";

  const sanitizedUrl = (value) => {
    try {
      const url = new URL(value, window.location.origin);
      return `${url.origin}${url.pathname}`;
    } catch (_) {
      return "";
    }
  };

  window.dataLayer = window.dataLayer || [];
  window.gtag = window.gtag || function gtag() {
    window.dataLayer.push(arguments);
  };

  const tag = document.createElement("script");
  tag.async = true;
  tag.src = `https://www.googletagmanager.com/gtag/js?id=${measurementId}`;
  document.head.appendChild(tag);

  window.gtag("js", new Date());
  window.gtag("config", measurementId, {
    allow_ad_personalization_signals: false,
    allow_google_signals: false,
    page_location: sanitizedUrl(window.location.href),
    page_referrer: sanitizedUrl(document.referrer),
  });
})();
