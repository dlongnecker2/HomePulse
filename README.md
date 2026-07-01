# HomePulse

HomePulse is a home reliability dashboard.

Current module:

- Internet health monitoring
- SQLite health history
- Daily speed tests
- Flask dashboard with live status cards
- Latency chart with automatic refresh

## Folder

For now, the Windows folder remains:

```text
C:\RouterMonitorV2
```

## Run

```bat
cd C:\RouterMonitorV2
pip install -r requirements.txt
python router_monitor.py
```

Open:

```text
http://localhost:8080
```

Developer console:

```text
http://localhost:8080/dev
```

Logs:

```text
http://localhost:8080/logs
```

## v2.6.0 highlights

- Redesigned dashboard layout
- Live status cards refreshed by `/api/status`
- Latency chart auto-refresh without page reload
- Improved card styling and responsive layout
- Latest SQLite health check loaded on startup
