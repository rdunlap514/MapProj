# Regression tests

Run the backend checks after installing the app requirements:

```sh
python -m unittest discover -s tests -v
python tests/smoke.py
```

These tests create temporary app copies; they do not modify your saved buildings or accounts.

Security checks cover CSRF rejection, random default passwords, explicit demo setup, admin-only calibration, maintenance/technology status updates, viewer restrictions, and preservation of room geometry. The test client simulates the page token for ordinary requests; negative tests explicitly omit or replace it.

The browser checks use Node.js and Playwright as optional development tools:

```sh
npm install --no-save --package-lock=false playwright
npx playwright install chromium
node tests/ui-regressions.cjs
node tests/legend-regressions.cjs
```

Alternatively, set `MAPPROJ_BROWSER_CHANNEL=chrome` to use an installed Chrome browser. In PowerShell, use `$env:MAPPROJ_BROWSER_CHANNEL = 'chrome'`.

Browser tests run the relevant JavaScript in a headless browser with simulated server responses. They cover literal note rendering, resolve-button binding, viewer restrictions, save failures, and successful saves. They do not replace a complete manual upload/draw/save walkthrough.

They also check the status request payload and that the shared CSRF wrapper adds tokens only to same-origin writes.
