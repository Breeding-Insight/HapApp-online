# Landing pages for scale-to-zero Cloud Run apps

Breeding Insight apps on Cloud Run scale to zero when idle, so the first visitor after a
quiet period waits for a cold start. To keep costs low without making people wait, each
app follows the same pattern:

- The public landing page is a static site on GitHub Pages. It is free, always on, and
  safe for search engines to crawl.
- The Cloud Run service hosts only the app. It is woken by the landing page when a
  person shows intent, not when a page loads, so crawlers and link previews never start
  an instance.
- The team directory links to landing pages, never directly to Cloud Run.

HapApp is the reference implementation: `landing/` is the landing page, and
`landing/assets/wake.js` is the shared wake-up script.

## Cloud Run service checklist

1. **Minimum instances `0`**, with startup CPU boost enabled.
2. **A quick, unauthenticated health path** that returns immediately without touching a
   database or session. HapApp uses `GET /health` (returns `204`).
   Do not use a path ending in `z` such as `/healthz`: Cloud Run reserves those paths and
   never forwards them to the container.
3. **A `robots.txt` that disallows everything:**

   ```
   User-agent: *
   Disallow: /
   ```

   Search engines that run JavaScript while rendering the landing page check this file
   before fetching the service, so it keeps them from waking it.
4. **Send signed-out visitors to the landing page.** HapApp redirects `/` to
   `HAPAPP_LANDING_URL` (or to sign-in when it is empty).

## Landing page checklist

1. Put the static site in its own folder (HapApp uses `landing/`) with its images,
   and publish that folder with a GitHub Pages workflow (see
   `.github/workflows/pages.yml`). In the repository, set
   **Settings → Pages → Source** to **GitHub Actions**.
2. Point every link that opens the app at the Cloud Run service, and mark it with
   `data-launch`:

   ```html
   <a class="btn btn-primary" href="https://YOUR-SERVICE.run.app/auth/login" data-launch>Sign in</a>
   ```

   Links work without JavaScript; the script only adds the wake-up behaviour.
3. Include the wake-up script once, at the end of the page:

   ```html
   <script src="assets/wake.js" defer
           data-app-url="https://YOUR-SERVICE.run.app"
           data-health-path="/health"
           data-app-name="Your App"
           data-contact-email="bi-science-team@ufl.edu"></script>
   ```

   `data-app-url` must be the same origin used in the `data-launch` links.
4. Add styles for the starting state, if the page's design needs them: the script adds
   `aria-busy="true"` and a `.launch-spinner` to the clicked link, and writes messages to
   a `.launch-status` element beside it. See the styles in `landing/index.html`.

## What wake.js does

> **HapApp:** wake-on-visit (the first two bullets below) is commented out in
> `landing/assets/wake.js`, because HapApp's cold start is short. The service wakes only
> when someone clicks a launch link, which still shows the starting state. Uncomment that
> block for an app whose cold start is slow.

- **Waits for a person.** It sends one wake-up request to the health path on the first
  mouse movement, scroll, touch, key press, or focus on a launch link, not on page load.
  It skips browsers that identify as automated or as bots.
- **Once per page load, then every five minutes of use.** Each page load sends its own
  wake-up on the first interaction. While the page stays open, further activity sends
  at most one more request every five minutes, which keeps the service warm while
  someone is using the page and sends nothing while no one is.
- **Treats the app as awake for five minutes.** A launch click within five minutes of the
  service's last answer goes straight to the app; after that, the link waits for a fresh
  answer, so a page left open for a long time never sends someone into a cold start.
- **No cross-origin setup.** The request uses `no-cors`: the service only has to answer,
  and Cloud Run holds the request open while a cold instance starts.
- **Handles a slow start on click.** If the app has not answered yet when a launch link is
  clicked, the link shows "Starting <app name>…" and a status message, retries every two
  seconds, and opens the app as soon as it answers. After 90 seconds it restores the link
  and shows a message with the contact email.

## Cost

An intent-based wake that is not followed by a sign-in keeps one instance up for at most
about 15 minutes (Cloud Run's idle window). Crawlers, link previews such as Slack's, and
visitors who never interact with the page start nothing.
