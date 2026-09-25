// Stop the once-a-second run poller after 5 minutes without user activity, so an
// idle or forgotten tab sends no requests and Cloud Run can scale the service to zero.
// With no requests, Cloud Run may shut the instance down within about 15 minutes, which
// deletes results that were not downloaded, so users with unsaved results are warned
// when the pause starts (WCAG 2.2.1). Any activity resumes polling right away.
(function () {
  var INACTIVITY_LIMIT_MS = 5 * 60 * 1000;
  var CHECK_EVERY_MS = 5 * 1000;
  var lastActivity = Date.now();
  var paused = false;
  var warning = null;
  var focusBeforeWarning = null;

  function setPollerDisabled(disabled) {
    if (window.dash_clientside && window.dash_clientside.set_props) {
      window.dash_clientside.set_props("run-poller", { disabled: disabled });
    }
  }

  function hasUnsavedResults() {
    var flag = document.getElementById("madc-unsaved-results");
    return Boolean(flag && flag.textContent.trim() === "true");
  }

  function makeButton(label, className, onClick) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = className;
    button.textContent = label;
    button.addEventListener("click", onClick);
    return button;
  }

  function hideWarning(restoreFocus) {
    if (!warning) {
      return;
    }
    warning.remove();
    warning = null;
    if (restoreFocus && focusBeforeWarning && document.contains(focusBeforeWarning)) {
      focusBeforeWarning.focus();
    }
    focusBeforeWarning = null;
  }

  function showWarning() {
    if (warning) {
      // Still showing from an earlier pause; keep the one warning rather than stacking another.
      return;
    }
    focusBeforeWarning = document.activeElement;
    warning = document.createElement("div");
    warning.className = "inactivity-warning";
    warning.setAttribute("role", "alertdialog");
    warning.setAttribute("aria-modal", "false");
    warning.setAttribute("aria-labelledby", "inactivity-warning-title");
    warning.setAttribute("aria-describedby", "inactivity-warning-body");

    var title = document.createElement("h2");
    title.id = "inactivity-warning-title";
    title.textContent = "Download your results before they’re lost";

    var body = document.createElement("p");
    body.id = "inactivity-warning-body";
    body.textContent =
      "HapApp has paused because this page has been inactive. Your results haven’t been " +
      "downloaded yet, and they will be deleted if the page stays inactive — this can happen " +
      "within the next 15 minutes. Download them now, or move the mouse or press any key to keep working.";

    var stay = makeButton("Stay active", "btn btn-primary", function () {
      hideWarning(true);
    });

    var actions = document.createElement("div");
    actions.className = "inactivity-warning-actions";
    actions.appendChild(stay);

    warning.appendChild(title);
    warning.appendChild(body);
    warning.appendChild(actions);
    document.body.appendChild(warning);
    stay.focus();
  }

  function pause() {
    paused = true;
    setPollerDisabled(true);
    if (hasUnsavedResults()) {
      showWarning();
    }
  }

  function recordActivity() {
    lastActivity = Date.now();
    if (paused) {
      // Resume polling silently as soon as the user is back.
      paused = false;
      setPollerDisabled(false);
    }
  }

  // Moving the mouse or scrolling resumes polling but leaves the warning up to be read;
  // a click, tap, or key press also dismisses it.
  ["mousemove", "wheel", "scroll"].forEach(function (name) {
    window.addEventListener(name, recordActivity, { capture: true, passive: true });
  });
  ["mousedown", "keydown", "touchstart"].forEach(function (name) {
    window.addEventListener(
      name,
      function () {
        recordActivity();
        if (warning) {
          window.setTimeout(function () {
            hideWarning(true);
          }, 0);
        }
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
