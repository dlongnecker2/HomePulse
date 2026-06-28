# Changelog

## v2.4.0
- Added first chart API endpoint: /api/charts/latency
- Added Chart.js to dashboard.
- Added live latency chart using health check history.
- Added database history method for health checks.
- Prepared dashboard structure for additional charts.

## v2.3
- Moved dashboard HTML out of Python strings and into Flask templates.
- Added shared base layout.
- Added dashboard, developer console, and logs templates.
- Added shared HomePulse CSS stylesheet.
- Dashboard routes now use render_template.
- This prepares HomePulse for Chart.js charts.

## v2.2
- Added real Speed Test engine using speedtest-cli Python module.
- Added Run Speed Test Now button to Developer Console.
- Speed test results now update the Status Manager.
- Speed test results now save to SQLite.
- Dashboard Daily Speed Test values now populate after a speed test.
