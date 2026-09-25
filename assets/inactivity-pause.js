// Stop the once-a-second run poller after 5 minutes without user activity, so an
// idle or forgotten tab sends no requests and Cloud Run can scale the service to zero.
// A warning appears 60 seconds beforehand so users can stay active (WCAG 2.2.1).
(function () {
  var INACTIVITY_LIMIT_MS = 5 * 60 * 1000;
  var WARNING_BEFORE_MS = 60 * 1000;
  var CHECK_EVERY_MS = 5 * 1000;
  var lastActivity = Date.now();
  var paused = false;
  var banner = null;
  var bannerKind = null;

  function setPollerDisabled(disabled) {
    if (window.dash_clientside && window.dash_clientside.set_props) {
      window.dash_clientside.set_props("run-poller", { disabled: disabled });
    }
  }

  function hideBanner() {
    if (banner) {
      banner.remove();
      banner = null;
      bannerKind = null;
    }
  }

  function showBanner(kind, role, text) {
    hideBanner();
    banner = document.createElement("div");
    banner.className = "app-paused-banner";
    banner.setAttribute("role", role);
    banner.textContent = text;
    bannerKind = kind;
    document.body.appendChild(banner);
  }

  function pause() {
    paused = true;
    setPollerDisabled(true);
    showBanner(
      "paused",
      "status",
      "HapApp paused after 5 minutes of inactivity. Click anywhere or press a key to continue. " +
        "Results that were not downloaded may no longer be available."
    );
  }

  function resume() {
    paused = false;
    setPollerDisabled(false);
  }

  function recordActivity() {
    lastActivity = Date.now();
    if (bannerKind === "warning") {
      hideBanner();
    }
  }

  function resumeIfPaused() {
    if (paused) {
      resume();
      hideBanner();
    }
  }

  ["mousemove", "wheel", "scroll"].forEach(function (name) {
    window.addEventListener(name, recordActivity, { capture: true, passive: true });
  });
  ["mousedown", "keydown", "touchstart"].forEach(function (name) {
    window.addEventListener(
      name,
      function () {
        recordActivity();
        resumeIfPaused();
      },
      { capture: true, passive: true }
    );
  });

  window.setInterval(function () {
    if (paused) {
      return;
    }
    var idle = Date.now() - lastActivity;
    if (idle >= INACTIVITY_LIMIT_MS) {
      pause();
    } else if (idle >= INACTIVITY_LIMIT_MS - WARNING_BEFORE_MS && bannerKind !== "warning") {
      showBanner(
        "warning",
        "alert",
        "HapApp will pause in about 60 seconds because of inactivity. " +
          "Move the mouse or press any key to stay active."
      );
    }
  }, CHECK_EVERY_MS);
})();
