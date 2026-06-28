from datetime import datetime
from pathlib import Path

from flask import Flask, redirect, url_for


class Dashboard:
    def __init__(self, application):
        self.application = application
        self.app = Flask(__name__)
        self.register_routes()

    def register_routes(self):
        @self.app.route("/")
        def home():
            config = self.application.config
            status = self.application.status.get()
            internet = status["internet"]
            speedtest = status["speedtest"]
            system = status["system"]

            health_status = internet["status"]
            color = "green"
            if health_status == "Degraded":
                color = "orange"
            elif health_status == "Unhealthy":
                color = "red"

            return f"""
            <!doctype html>
            <html>
            <head>
                <title>HomePulse</title>
                <meta http-equiv="refresh" content="30">
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 40px; background: #f3f5f7; color: #222; }}
                    .card {{ background: white; border-radius: 16px; padding: 28px; max-width: 920px; box-shadow: 0 3px 12px rgba(0,0,0,0.14); }}
                    h1 {{ margin-top: 0; margin-bottom: 4px; font-size: 36px; }}
                    .subtitle {{ color: #666; margin-bottom: 24px; font-size: 16px; }}
                    .status {{ font-size: 28px; color: {color}; font-weight: bold; margin-bottom: 18px; }}
                    .section-title {{ margin-top: 28px; font-size: 20px; font-weight: bold; }}
                    table {{ border-collapse: collapse; width: 100%; margin-top: 10px; }}
                    td {{ padding: 9px; border-bottom: 1px solid #ddd; }}
                    td:first-child {{ font-weight: bold; width: 42%; }}
                    .nav a {{ display: inline-block; margin-right: 12px; }}
                    .small {{ color: #666; font-size: 13px; margin-top: 22px; }}
                </style>
            </head>
            <body>
                <div class="card">
                    <h1>HomePulse</h1>
                    <div class="subtitle">Home Reliability Dashboard</div>
                    <div class="nav">
                        <a href="/">Dashboard</a>
                        <a href="/dev">Developer Console</a>
                        <a href="/logs">Logs</a>
                        <a href="/health">JSON Health</a>
                    </div>

                    <div class="section-title">Internet</div>
                    <div class="status">{health_status}</div>
                    <table>
                        <tr><td>Health Score</td><td>{internet["score"]}</td></tr>
                        <tr><td>Latency</td><td>{internet["latency"]} ms</td></tr>
                        <tr><td>Packet Loss</td><td>{internet["packet_loss"]}%</td></tr>
                        <tr><td>DNS</td><td>{internet["dns_ok"]}</td></tr>
                        <tr><td>Details</td><td>{internet["details"]}</td></tr>
                        <tr><td>Last Internet Check</td><td>{internet["last_check"]}</td></tr>
                    </table>

                    <div class="section-title">Daily Speed Test</div>
                    <table>
                        <tr><td>Download</td><td>{speedtest["download"]} Mbps</td></tr>
                        <tr><td>Upload</td><td>{speedtest["upload"]} Mbps</td></tr>
                        <tr><td>Ping</td><td>{speedtest["ping"]} ms</td></tr>
                        <tr><td>Server</td><td>{speedtest["server"]}</td></tr>
                        <tr><td>Last Run</td><td>{speedtest["last_run"]}</td></tr>
                    </table>

                    <div class="section-title">System</div>
                    <table>
                        <tr><td>Version</td><td>{status["version"]}</td></tr>
                        <tr><td>Folder</td><td>C:\\RouterMonitorV2</td></tr>
                        <tr><td>Current Time</td><td>{datetime.now()}</td></tr>
                        <tr><td>Started At</td><td>{system["started_at"]}</td></tr>
                        <tr><td>Last Update</td><td>{system["last_update"]}</td></tr>
                        <tr><td>Monitor Interval</td><td>{config.get("monitor_interval_minutes")} minutes</td></tr>
                        <tr><td>Dry Run Mode</td><td>{config.get("dry_run")}</td></tr>
                    </table>
                    <p class="small">Page refreshes every 30 seconds.</p>
                </div>
            </body>
            </html>
            """

        @self.app.route("/dev")
        def dev():
            status = self.application.status.get()
            internet = status["internet"]
            speedtest = status["speedtest"]

            return f"""
            <!doctype html>
            <html>
            <head>
                <title>HomePulse Developer Console</title>
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 40px; background: #f3f5f7; }}
                    .card {{ background: white; border-radius: 16px; padding: 28px; max-width: 820px; box-shadow: 0 3px 12px rgba(0,0,0,0.14); }}
                    button {{ font-size: 16px; padding: 10px 16px; margin: 8px 8px 8px 0; cursor: pointer; }}
                    table {{ border-collapse: collapse; width: 100%; margin-top: 16px; }}
                    td {{ padding: 8px; border-bottom: 1px solid #ddd; }}
                    td:first-child {{ font-weight: bold; width: 40%; }}
                </style>
            </head>
            <body>
                <div class="card">
                    <h1>HomePulse Developer Console</h1>
                    <p><a href="/">Dashboard</a> | <a href="/logs">Logs</a> | <a href="/health">JSON Health</a></p>

                    <form action="/dev/run-health-check" method="post">
                        <button type="submit">Run Internet Health Check Now</button>
                    </form>

                    <form action="/dev/run-speedtest" method="post">
                        <button type="submit">Run Speed Test Now</button>
                    </form>

                    <h2>Current Internet Status</h2>
                    <table>
                        <tr><td>Status</td><td>{internet["status"]}</td></tr>
                        <tr><td>Score</td><td>{internet["score"]}</td></tr>
                        <tr><td>Latency</td><td>{internet["latency"]}</td></tr>
                        <tr><td>Packet Loss</td><td>{internet["packet_loss"]}</td></tr>
                        <tr><td>DNS OK</td><td>{internet["dns_ok"]}</td></tr>
                        <tr><td>Details</td><td>{internet["details"]}</td></tr>
                        <tr><td>Last Check</td><td>{internet["last_check"]}</td></tr>
                    </table>

                    <h2>Current Speed Test</h2>
                    <table>
                        <tr><td>Download</td><td>{speedtest["download"]}</td></tr>
                        <tr><td>Upload</td><td>{speedtest["upload"]}</td></tr>
                        <tr><td>Ping</td><td>{speedtest["ping"]}</td></tr>
                        <tr><td>Server</td><td>{speedtest["server"]}</td></tr>
                        <tr><td>Last Run</td><td>{speedtest["last_run"]}</td></tr>
                    </table>
                </div>
            </body>
            </html>
            """

        @self.app.route("/dev/run-health-check", methods=["POST"])
        def run_health_check():
            self.application.health_check()
            return redirect(url_for("dev"))

        @self.app.route("/dev/run-speedtest", methods=["POST"])
        def run_speedtest():
            self.application.daily_speed_test()
            return redirect(url_for("dev"))

        @self.app.route("/logs")
        def logs():
            log_file = Path("logs/routermonitor.log")
            if log_file.exists():
                lines = log_file.read_text(encoding="utf-8", errors="ignore").splitlines()
                recent = lines[-150:]
            else:
                recent = ["No log file found."]

            log_html = "<br>".join(line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") for line in recent)

            return f"""
            <!doctype html>
            <html>
            <head>
                <title>HomePulse Logs</title>
                <meta http-equiv="refresh" content="15">
                <style>
                    body {{ font-family: Consolas, monospace; margin: 30px; background: #111; color: #eee; }}
                    .nav {{ font-family: Arial, sans-serif; margin-bottom: 20px; }}
                    a {{ color: #9bd; }}
                    .log {{ background: #000; border-radius: 8px; padding: 18px; line-height: 1.45; }}
                </style>
            </head>
            <body>
                <div class="nav">
                    <a href="/">Dashboard</a> |
                    <a href="/dev">Developer Console</a> |
                    <a href="/health">JSON Health</a>
                </div>
                <h1>HomePulse Logs</h1>
                <div class="log">{log_html}</div>
            </body>
            </html>
            """

        @self.app.route("/health")
        def health():
            return {
                "status": self.application.status.get(),
                "timestamp": str(datetime.now())
            }

    def run(self):
        self.app.run(
            host=self.application.config.get("dashboard", "host"),
            port=self.application.config.get("dashboard", "port"),
            debug=False,
            use_reloader=False
        )
