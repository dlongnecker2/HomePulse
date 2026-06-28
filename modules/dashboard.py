from datetime import datetime
from pathlib import Path

from flask import Flask, redirect, render_template, url_for


class Dashboard:
    def __init__(self, application):
        self.application = application
        self.app = Flask(
            __name__,
            template_folder="../templates",
            static_folder="../static"
        )
        self.register_routes()

    def register_routes(self):
        @self.app.route("/")
        def home():
            status = self.application.status.get()
            return render_template(
                "dashboard.html",
                config=self.application.config,
                status=status,
                internet=status["internet"],
                speedtest=status["speedtest"],
                system=status["system"],
                now=datetime.now()
            )

        @self.app.route("/dev")
        def dev():
            status = self.application.status.get()
            return render_template(
                "dev.html",
                status=status,
                internet=status["internet"],
                speedtest=status["speedtest"],
                now=datetime.now()
            )

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
                lines = log_file.read_text(
                    encoding="utf-8",
                    errors="ignore"
                ).splitlines()
                recent = lines[-150:]
            else:
                recent = ["No log file found."]

            return render_template(
                "logs.html",
                lines=recent,
                now=datetime.now()
            )

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
