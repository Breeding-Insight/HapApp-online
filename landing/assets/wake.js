// Wake a scale-to-zero Cloud Run app from its static landing page, so people rarely wait
// on a cold start, while crawlers and link previews never start an instance.
//
// Include once per page and configure with data attributes on the script tag:
//   data-app-url       (required) Cloud Run service origin, e.g. https://my-app-xyz.run.app
//   data-health-path   (optional) quick, unauthenticated path; default "/health".
//                      Avoid paths ending in "z": Cloud Run reserves them.
//   data-app-name      (optional) name shown while starting; default "the app"
//   data-contact-email (optional) shown if the app does not start in time
// Mark each link that opens the app with a data-launch attribute.
//
// The service should serve a robots.txt that disallows crawling, so crawlers that run
// JavaScript do not fetch it either.
(function () {
  var script = document.currentScript;
  var appUrl = ((script && script.dataset.appUrl) || "").replace(/\/+$/, "");
  if (!appUrl) {
    return;
  }
  var healthUrl = appUrl + (script.dataset.healthPath || "/health");
  var appName = script.dataset.appName || "the app";
  var contactEmail = script.dataset.contactEmail || "";

  var START_TIMEOUT_MS = 90 * 1000;
  var RETRY_EVERY_MS = 2 * 1000;
  // Well inside Cloud Run's idle window (instances may stay up to 15 minutes after the last request).
  var AWAKE_FOR_MS = 5 * 60 * 1000;
  var REWAKE_AFTER_MS = 5 * 60 * 1000;
  // Remembered only for this page load, so every visit sends its own wake-up request.
  var lastWakeAt = 0;
  var lastAnswerAt = 0;
  var inFlight = null;

  function looksAutomated() {
    return (
      navigator.webdriver === true ||
      /bot|crawl|spider|slurp|preview|headless|lighthouse/i.test(navigator.userAgent || "")
    );
  }

  function isAwake() {
    return lastAnswerAt > 0 && Date.now() - lastAnswerAt < AWAKE_FOR_MS;
  }

  // An opaque "no-cors" response is enough: it arrives once the service answers, and
  // Cloud Run holds the request open while a cold instance starts.
  function ping() {
    var controller = new AbortController();
    var timer = setTimeout(function () {
      controller.abort();
    }, START_TIMEOUT_MS);
    return fetch(healthUrl + "?t=" + Date.now(), {
      mode: "no-cors",
      cache: "no-store",
      credentials: "omit",
      signal: controller.signal,
    }).then(
      function () {
        clearTimeout(timer);
        return true;
      },
      function () {
        clearTimeout(timer);
        return false;
      }
    );
  }

  function wake() {
    if (!inFlight) {
      lastWakeAt = Date.now();
      inFlight = ping().then(function (ok) {
        inFlight = null;
        if (ok) {
          lastAnswerAt = Date.now();
        }
        return ok;
      });
    }
    return inFlight;
  }

  // Wake on the first sign of a person (not on page load), then again on activity at most
  // every five minutes while the page stays open, so the service stays warm while it is used.
  var intentEvents = ["pointermove", "pointerdown", "keydown", "touchstart", "scroll", "focusin"];
  function onActivity() {
    if (inFlight || looksAutomated()) {
      return;
    }
    if (lastWakeAt === 0 || Date.now() - lastWakeAt >= REWAKE_AFTER_MS) {
      wake();
    }
  }
  intentEvents.forEach(function (name) {
    window.addEventListener(name, onActivity, { capture: true, passive: true });
  });

  function statusFor(link) {
    var container = link.parentElement;
    var status = container.querySelector(".launch-status");
    if (!status) {
      status = document.createElement("p");
      status.className = "launch-status";
      status.setAttribute("role", "status");
      container.appendChild(status);
    }
    return status;
  }

  function showStarting(link) {
    link.dataset.originalHtml = link.innerHTML;
    link.setAttribute("aria-busy", "true");
    link.innerHTML = "";
    var spinner = document.createElement("span");
    spinner.className = "launch-spinner";
    spinner.setAttribute("aria-hidden", "true");
    link.appendChild(spinner);
    link.appendChild(document.createTextNode("Starting " + appName + "…"));
    statusFor(link).textContent = "Starting " + appName + ". This can take up to a minute.";
  }

  function showFailed(link) {
    link.innerHTML = link.dataset.originalHtml;
    link.removeAttribute("aria-busy");
    var status = statusFor(link);
    status.textContent =
      appName + " is taking longer than usual to start. Please try again in a minute." +
      (contactEmail ? " If the problem continues, contact " : "");
    if (contactEmail) {
      var mail = document.createElement("a");
      mail.href = "mailto:" + contactEmail;
      mail.textContent = contactEmail;
      status.appendChild(mail);
      status.appendChild(document.createTextNode("."));
    }
  }

  function launch(link) {
    if (link.getAttribute("aria-busy") === "true") {
      return;
    }
    showStarting(link);
    var deadline = Date.now() + START_TIMEOUT_MS;
    (function attempt() {
      wake().then(function (ok) {
        if (ok) {
          window.location.href = link.href;
        } else if (Date.now() < deadline) {
          setTimeout(attempt, RETRY_EVERY_MS);
        } else {
          showFailed(link);
        }
      });
    })();
  }

  document.querySelectorAll("[data-launch]").forEach(function (link) {
    link.addEventListener("click", function (event) {
      // Let new-tab and other modified clicks through; only handle plain clicks.
      if (isAwake() || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
        return;
      }
      event.preventDefault();
      launch(link);
    });
  });
})();
