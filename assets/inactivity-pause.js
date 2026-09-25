// Stop the once-a-second run poller after 5 minutes without user activity, so an
// idle or forgotten tab sends no requests and Cloud Run can scale the service to zero.
(function () {
  var INACTIVITY_LIMIT_MS = 5 * 60 * 1000;
  var CHECK_EVERY_MS = 15 * 1000;
  var lastActivity = Date.now();
  var paused = false;
  var banner = null;

  function setPollerDisabled(disabled) {
    if (window.dash_clientside && window.dash_clientside.set_props) {
      window.dash_clientside.set_props("run-poller", { disabled: disabled });
    }
  }

  function showBanner() {
    banner = document.createElement("div");
    banner.className = "app-paused-banner";
    banner.setAttribute("role", "status");
    banner.textContent =
      "HapApp paused after 5 minutes of inactivity. Click anywhere or press a key to continue. " +
      "Results that were not downloaded may no longer be available.";
    document.body.appendChild(banner);
  }

  function pause() {
    paused = true;
    setPollerDisabled(true);
    showBanner();
  }

  function resume() {
    paused = false;
    lastActivity = Date.now();
    setPollerDisabled(false);
    if (banner) {
      banner.remove();
      banner = null;
    }
  }

  function recordActivity() {
    lastActivity = Date.now();
  }

  function resumeIfPaused() {
    if (paused) {
      resume();
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
    if (!paused && Date.now() - lastActivity >= INACTIVITY_LIMIT_MS) {
      pause();
    }
  }, CHECK_EVERY_MS);
})();
