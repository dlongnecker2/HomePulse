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
                    body {{
                        font-family: Arial, sans-serif;
                        margin: 40px;
                        background: #f3f5f7;
                        color: #222;
                    }}
                    .card {{
                        background: white;
                        border-radius: 16px;
                        padding: 28px;
                        max-width: 920px;
                        box-shadow: 0 3px 12px rgba(0,0,0,0.14);
                    }}
                    h1 {{
                        margin-top: 0;
                        margin-bottom: 4px;
                        font-size: 36px;
                    }}
                    .subtitle {{
                        color: #666;
                        margin-bottom: 24px;
                        font-size: 16px;
                    }}
                    .status {{
                        font-size: 28px;
                        color: {color};
                        font-weight: bold;
                        margin-bottom: 18px;
                    }}
                    .section-title {{
                        margin-top: 28px;
                        font-size: 20px;
                        font-weight: bold;
                    }}
                    table {{
                        border-collapse: collapse;
                        width: 100%;
                        margin-top: 10px;
                    }}
                    td {{
                        padding: 9px;
                        border-bottom: 1px solid #ddd;
                    }}
                    td:first-child {{
                        font-weight: bold;
                        width: 42%;
                    }}
                    .small {{
                        color: #666;
                        font-size: 13px;
                        margin-top: 22px;
                    }}
                </style>
            </head>
            <body>
                <div class="card">
                    <h1>HomePulse</h1>
                    <div class="subtitle">Home Reliability Dashboard</div>

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
                        <tr><td>Download</td><td>{speedtest["download"]}</td></tr>
                        <tr><td>Upload</td><td>{speedtest["upload"]}</td></tr>
                        <tr><td>Ping</td><td>{speedtest["ping"]}</td></tr>
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

                    <p class="small">
                        This is the first HomePulse-branded release. Internet is the first module.
                        Solar, EV, greenhouse, and other home systems can be added later.
                    </p>
                </div>
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
