from datetime import datetime
from flask import Flask


class Dashboard:
    def __init__(self, application):
        self.application = application
        self.app = Flask(__name__)
        self.register_routes()

    def register_routes(self):
        @self.app.route("/")
        def home():
            config = self.application.config
            status = self.application.status
            latest = self.application.db.latest_health_check()

            health_status = status.get("internet_status", "Waiting for first check")
            score = status.get("health_score", "N/A")
            latency = status.get("latency", "N/A")
            packet_loss = status.get("packet_loss", "N/A")
            dns_ok = status.get("dns_ok", "N/A")
            details = status.get("details", "No health check yet")
            last_check = status.get("last_health_check", "Never")

            color = "green"
            if health_status == "Degraded":
                color = "orange"
            elif health_status == "Unhealthy":
                color = "red"

            return f"""
            <!doctype html>
            <html>
            <head>
                <title>RouterMonitor V2</title>
                <meta http-equiv="refresh" content="30">
                <style>
                    body {{
                        font-family: Arial, sans-serif;
                        margin: 40px;
                        background: #f5f5f5;
                    }}
                    .card {{
                        background: white;
                        border-radius: 12px;
                        padding: 24px;
                        max-width: 820px;
                        box-shadow: 0 2px 8px rgba(0,0,0,0.12);
                    }}
                    h1 {{ margin-top: 0; }}
                    .status {{
                        font-size: 26px;
                        color: {color};
                        font-weight: bold;
                    }}
                    table {{
                        border-collapse: collapse;
                        width: 100%;
                        margin-top: 16px;
                    }}
                    td {{
                        padding: 8px;
                        border-bottom: 1px solid #ddd;
                    }}
                    td:first-child {{
                        font-weight: bold;
                        width: 45%;
                    }}
                    .small {{
                        color: #666;
                        font-size: 13px;
                    }}
                </style>
            </head>
            <body>
                <div class="card">
                    <h1>RouterMonitor V2</h1>
                    <div class="status">{health_status}</div>

                    <table>
                        <tr><td>Project</td><td>{config.get("project_name")}</td></tr>
                        <tr><td>Version</td><td>{config.get("version")}</td></tr>
                        <tr><td>Current Time</td><td>{datetime.now()}</td></tr>
                        <tr><td>Last Health Check</td><td>{last_check}</td></tr>
                        <tr><td>Health Score</td><td>{score}</td></tr>
                        <tr><td>Latency</td><td>{latency} ms</td></tr>
                        <tr><td>Packet Loss</td><td>{packet_loss}%</td></tr>
                        <tr><td>DNS</td><td>{dns_ok}</td></tr>
                        <tr><td>Details</td><td>{details}</td></tr>
                        <tr><td>Monitor Interval</td><td>{config.get("monitor_interval_minutes")} minutes</td></tr>
                        <tr><td>Daily Speed Test</td><td>{config.get("speedtest_hour")}:00</td></tr>
                        <tr><td>Dry Run Mode</td><td>{config.get("dry_run")}</td></tr>
                    </table>

                    <p class="small">
                        Page refreshes every 30 seconds. Latest DB row:
                        {latest if latest else "None yet"}
                    </p>
                </div>
            </body>
            </html>
            """

        @self.app.route("/health")
        def health():
            return {
                "status": self.application.status,
                "project": self.application.config.get("project_name"),
                "version": self.application.config.get("version"),
                "timestamp": str(datetime.now())
            }

    def run(self):
        self.app.run(
            host=self.application.config.get("dashboard", "host"),
            port=self.application.config.get("dashboard", "port"),
            debug=False,
            use_reloader=False
        )
