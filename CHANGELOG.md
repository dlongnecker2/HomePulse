# Changelog

## v3.4.0

- Added Home Center with `/home` for a unified, at-a-glance operational view of Internet, Solar, Energy, Vehicle, Weather, Lighting, and Home Status.
- Added `/api/home/status` to combine existing center status payloads into one defensive Home Center API response.
- Added a compact Dashboard "Home Center / House at a Glance" card linked to the new Home Center page.
- Added registry-ready Exterior Lights and Home Status placeholders without faking live device data.
- Registered Home Center and Lighting in the platform compatibility registry and exposed them through existing Lab registry visibility.
- Added dark HomePulse tile styling for the Home Center summary grid.
- Added reusable 1D / 1W / 1M / 6M / 1Y time-range selectors for history-backed charts with range-aware History API aggregation.

## v3.2.0

- Added the v3.3 Platform Architecture foundation with plugin, device, and widget registries.
- Added compatibility plugins for Internet, Energy, Solar, Vehicle, and Weather without moving existing modules or changing URLs/APIs.
- Added startup logging for loaded plugins, registered dashboard widgets, and registered device types.
- Prepared Dashboard to receive widget metadata from the WidgetRegistry while preserving existing dashboard cards.
- Added Lab visibility for platform plugin/widget/device registry state.
- Stabilized the v3.2 UI after Analytics and Solar Center updates.
- Fixed the Solar overview API crash caused by a missing timestamp formatting helper.
- Added functional left-navigation pages for Energy Center, Vehicle Center, Speed Test, Email Center, and About.
- Standardized main pages to the darker HomePulse theme.
- Fixed Settings input readability and kept Solar/Vehicle dashboard cards on the dark card treatment in active states.
- Added a Weather Center foundation with placeholder/manual configuration and `/api/weather/status`.
- Added optional Open-Meteo live weather support using configured latitude/longitude with no API key required.
- Added Dashboard and Solar Center Solar vs EV Charging comparison charts using Solar and Energy history snapshots.
- Added Solar Center overlap summary metrics for solar/EV overlap, peak solar, peak charging, and estimated solar-supported charging.
- Added weather metrics to History Service snapshots when Weather Center is enabled.
- Connected Solar Center's Weather & Solar Correlation panel to the Weather Center status API with placeholder source labeling.
- Improved UI readability by hardening dark-theme Settings form controls, placeholders, disabled fields, select options, and autofill states.
- Added a compact Dashboard Weather card backed by `/api/weather/status`.
- Changed Solar and Internet history visuals to labeled dark line charts with x-axis time labels and y-axis values.
- Refocused Solar Center on solar production, weather, forecast, and Enphase health by removing EV charging panels from the Solar page.
- Added Internet Center history chart panels for latency, health score, packet loss, download, and upload history.
- Added module-specific Energy, Vehicle, and Speed Test chart placeholders backed by the History Service when data exists.
- Added the Analytics Foundation with a central History Service for Solar, Vehicle, Energy, and Internet metrics.
- Added local SQLite metric snapshots in `data/homepulse_history.db` with timestamp, module, metric, value, unit, source, and optional metadata.
- Added scheduled history snapshots with configurable enablement, interval, and retention settings.
- Added `/api/history/latest`, `/api/history/metrics`, and `/api/history/summary` endpoints.
- Added reusable frontend history chart helpers and connected the Solar Center production chart to real history data when available.
- Added Lab visibility for History / Analytics status, database path, last snapshot, and recorded metric count.
- Preserved placeholder panels for weather correlation, energy flow, and future analytics reports.

## v3.1.0

- Added the modular Solar Center using local Home Assistant Enphase Envoy entities.
- Added `/api/solar/status` for live solar production, lifetime production, and estimated value data.
- Added the dedicated Solar Center page with persistent left navigation and reusable secondary top tabs.
- Implemented the Solar Center Overview tab with live solar summary data and placeholder-ready analytics panels.
- Added Solar Center dashboard card, Settings configuration, and Lab module visibility.
- Added electricity-rate sharing with Energy Center plus a Solar Center override.
- Added defensive handling for unavailable, unknown, missing, or unparsable solar entity values.
- Added throttled Solar Center refresh-failure logging.

## v3.0.0

- Added the new modular Vehicle Center for HomePulse.
- Added Home Assistant vehicle integration using OnStar2MQTT-exposed entities.
- Added a Vehicle Center dashboard card with battery, range, plug, charging, odometer, lifetime energy, efficiency, cost, and cost-per-mile values.
- Added Vehicle Center settings for enablement, vehicle name, Home Assistant entity IDs, and electricity-rate override support.
- Added the `/api/vehicle/status` endpoint for live vehicle telemetry.
- Added lifetime efficiency calculations using odometer miles and lifetime energy.
- Added lifetime electricity cost calculations using the shared Energy Center electricity rate or a Vehicle Center override.
- Added cost per mile calculations for long-term EV operating visibility.
- Improved the modular architecture with a dedicated `modules.vehicle` package and defensive manager/model boundaries.
- Added ChargePoint live data polish for the HomePulse Energy Center dashboard card.
- Improved Energy Center value formatting, loading states, missing-value handling, and active charging presentation.
- Added Lab/About runtime visibility for HomePulse application identity, enabled modules, database status, and scheduler status.
- Improved speed test failure handling with provider fallback and clearer provider-unavailable states.
- Use HTTPS secure mode for Speedtest.net checks to avoid HTTP 403 failures.
- Improved Vehicle Center formatting, last-updated display, partial-data states, and throttled refresh-failure logging.
- Centralized HomePulse application name and version constants in `version.py`.
- Added configurable scheduled Speed Test frequency in Settings with runtime rescheduling.

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
