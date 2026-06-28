# Changelog

## v2.5.1
- Added startup protection for dashboard port conflicts.
- HomePulse now checks whether the dashboard port is already in use before starting Flask.
- If port 8080 is already occupied, HomePulse logs a clear error and exits.

## v2.4.0
- Added first chart API endpoint: /api/charts/latency
- Added Chart.js to dashboard.
- Added live latency chart using health check history.
- Added database history method for health checks.
- Prepared dashboard structure for additional charts.
