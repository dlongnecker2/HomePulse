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

            return f"""
            <!doctype html>
            <html>
            <head>
                <title>RouterMonitor V2</title>
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
                        max-width: 720px;
                        box-shadow: 0 2px 8px rgba(0,0,0,0.12);
                    }}
                    h1 {{ margin-top: 0; }}
                    .status {{
                        font-size: 22px;
                        color: green;
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
                </style>
            </head>
            <body>
                <div class="card">
                    <h1>RouterMonitor V2</h1>
                    <div class="status">Running</div>
                    <table>
                        <tr><td>Project</td><td>{config.get("project_name")}</td></tr>
                        <tr><td>Version</td><td>{config.get("version")}</td></tr>
                        <tr><td>Current Time</td><td>{datetime.now()}</td></tr>
                        <tr><td>Monitor Interval</td><td>{config.get("monitor_interval_minutes")} minutes</td></tr>
                        <tr><td>Daily Speed Test</td><td>{config.get("speedtest_hour")}:00</td></tr>
                        <tr><td>Dry Run Mode</td><td>{config.get("dry_run")}</td></tr>
                        <tr><td>Database</td><td>{config.get("database")}</td></tr>
                    </table>
                    <p>
                        This dashboard is the first live web interface.
                        Network health, speed tests, reboot history, and charts will appear here as we add them.
                    </p>
                </div>
            </body>
            </html>
            """

        @self.app.route("/health")
        def health():
            return {
                "status": "running",
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
