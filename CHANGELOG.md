# Changelog

## Unreleased

- Added configurable scheduled speed tests, defaulting to every 30 minutes.
- Added configurable speed, latency, maintenance-window, and reboot-cooldown settings.
- Added a 4:00 AM maintenance check that can recommend a router reboot only when speed or sustained health thresholds fail.
- Kept daytime speed tests separate from reboot decisions.
- Preserved existing Flask routes and SQLite schemas.

## v2.6.2

- Refined the dashboard into a denser premium monitoring view designed to fit better on 1920x1080 screens.
- Added a more prominent hero status, healthy pulse indicator, and operational status subtitle.
- Replaced dashboard metadata cards with a compact information strip including application uptime.
- Added inline SVG icons to status cards and the recent activity timeline without adding dependencies.
- Improved empty speed-test states so unavailable values read clearly instead of showing placeholder Mbps values.
- Improved the latency chart with a stronger gradient, emphasized current point, average latency reference line, and cleaner tooltip styling.
- Reworked Recent Events into a compact activity timeline using existing live status data.
- Preserved existing Flask routes, monitoring behavior, and SQLite compatibility.

## v2.6.1

- Modernized the dashboard with a polished operations-console layout.
- Added a responsive top status bar and refined dashboard metadata cards.
- Improved typography, spacing, rounded cards, subtle shadows, and mobile layout.
- Restyled the latency chart with cleaner axes, softer gridlines, and smoother updates.
- Added a Recent Events panel using existing live dashboard status data.
- Preserved existing Flask routes, monitoring behavior, and SQLite compatibility.

## v2.6.0

- Added redesigned dashboard with status cards.
- Added `/api/status` JSON endpoint for live dashboard updates.
- Added `static/js/live_dashboard.js` for 10-second polling.
- Updated latency chart script so the chart refreshes instead of stacking duplicate charts.
- Added startup loading of the latest SQLite health check.
- Updated version references to 2.6.0.

## v2.5.2

- SQLite health history working.
- First latency chart live.
- Flask templates in use.
