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

## Windows startup

HomePulse can be started automatically when you sign in to Windows using Task Scheduler.

Install the startup task:

```powershell
cd C:\RouterMonitorV2
powershell -ExecutionPolicy Bypass -File .\scripts\install_startup_task.ps1
```

Remove the startup task:

```powershell
cd C:\RouterMonitorV2
powershell -ExecutionPolicy Bypass -File .\scripts\remove_startup_task.ps1
```

The task is named `HomePulse`, runs at the current user's logon, starts in `C:\RouterMonitorV2`, and runs:

```text
C:\RouterMonitorV2\scripts\start_homepulse.bat
```

The launcher uses `.venv\Scripts\python.exe` or `venv\Scripts\python.exe` when present, otherwise it uses `python` from PATH. Startup output is appended to:

```text
C:\RouterMonitorV2\logs\startup.log
```

Lab includes local Admin Actions for restarting or stopping HomePulse. HomePulse does not include a login system, so keep Lab available only on trusted local networks.

## v2.6.0 highlights

- Redesigned dashboard layout
- Live status cards refreshed by `/api/status`
- Latency chart auto-refresh without page reload
- Improved card styling and responsive layout
- Latest SQLite health check loaded on startup
