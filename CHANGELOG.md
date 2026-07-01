# Changelog

## Upcoming v2.10.0 - Energy Center polish

- Added ChargePoint live data polish for the HomePulse Energy Center dashboard card.
- Improved Energy Center value formatting, loading states, missing-value handling, and active charging presentation.
- Added Lab/About runtime visibility for HomePulse application identity, enabled modules, database status, and scheduler status.
- Improved speed test failure handling with provider fallback and clearer provider-unavailable states.
- Use HTTPS secure mode for Speedtest.net checks to avoid HTTP 403 failures.

## v2.9.0

- Added multi-recipient email notification support with comma, semicolon, and newline-separated recipient parsing.
- Added the HomePulse Lab diagnostics page for developer-only runtime visibility.
- Added Lab navigation alongside the existing Dashboard, Internet, History, Reports, Settings, Developer Console, and Logs pages.
- Added read-only runtime overview details including version, start time, uptime, Python version, SQLite status, database size, memory usage, scheduler status, thread count, and configuration load state.
- Added scheduler diagnostics for next ping, next speed test, next maintenance, last speed test, last maintenance, and scheduled job count.
- Added recent color-coded log entries, SQLite record counts, read-only runtime configuration values, and manual action buttons.
- Added guarded router reboot automation phase 1 with dry-run-only execution, SQLite reboot event logging, and optional SMTP email notifications.
- Added inert structure for HTTP, SSH, and smart-plug reboot methods; real power control remains disabled pending explicit approval.
- Added Settings controls for reboot method structure and email notification configuration without displaying saved SMTP passwords.
- Added dry-run reboot event visibility on the Dashboard, History, and Lab pages.
- Refactored router recovery around adapter-based device types, including a disabled TP-Link Tapo P125M Matter placeholder and recovery timing settings.
- Added a unified Settings diagnostics framework with structured JSON test endpoints, SMTP/ping/speed/Tapo/database/scheduler/log tests, and SQLite event logging.
- Preserved existing routes, SQLite schema compatibility, and dependency set.

## v2.8.1

- Redesigned the History page into a chart-first analytics view.
- Added top summary cards for quality, latency, download, upload, outages, and router reboots.
- Added Speed History, Internet Quality History, and Latency History charts using existing Chart.js.
- Added display-only time-range controls for 6H, 24H, 7D, and 30D.
- Kept recent speed tests, recent events, and outage/reboot history below the charts.
- Preserved existing routes and SQLite schema compatibility.

## v2.8.0

- Added dedicated Internet, History, and Reports navigation pages.
- Kept the Dashboard focused on a clean live overview and moved detailed intelligence/reliability views to dedicated pages.
- Added a History page with 24-hour latency overview, quality trend, recent speed tests, and recent outage/reboot activity.
- Added a Reports foundation page with monthly reliability summary metrics; PDF generation is not included yet.
- Preserved existing routes, SQLite schema compatibility, and local-only calculations.

## v2.7.0

- Added Internet Intelligence using existing local HomePulse data only.
- Replaced the dashboard Health Score display with a calculated Internet Quality Score.
- Added 30-day reliability metrics for uptime, outage count, longest outage, and router reboot events.
- Added ISP Grade, Reliability Trend, and local recommendations based on collected health and speed-test data.
- Preserved existing Flask routes, SQLite schema compatibility, and local-only operation.

## v2.6.4

- Added a compact Automation Rules dashboard section for scheduled speed-test and reboot-safety settings.
- Added Settings controls for disabling speed tests, preset intervals, and custom scheduled times.
- Saved speed-test schedule selections to `config.json` and refreshed in-memory scheduled speed-test jobs.
- Displayed speed-test scheduling status, next scheduled test, reboot window, reboot cooldown, and configured quality thresholds.
- Clarified that daytime speed tests do not trigger router reboots and automatic reboot is limited to the maintenance window.
- Preserved existing monitoring behavior, Flask routes, and SQLite schemas.

## v2.6.3

- Added configurable scheduled speed tests, defaulting to every 30 minutes.
- Added configurable speed, latency, maintenance-window, and reboot-cooldown settings.
- Added a 4:00 AM maintenance check that can recommend a router reboot only when speed or sustained health thresholds fail.
- Kept daytime speed tests separate from reboot decisions.
- Added the next scheduled speed test to the existing dashboard speed-test panel and live status payload.
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
