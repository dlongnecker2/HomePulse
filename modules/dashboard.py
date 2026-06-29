from datetime import datetime
from pathlib import Path
from flask import Flask, redirect, render_template, request, url_for, jsonify


class Dashboard:
    def __init__(self, application):
        self.application = application
        self.app = Flask(
            __name__,
            template_folder="../templates",
            static_folder="../static",
        )
        self.register_routes()

    def _dashboard_payload(self):
        status = self.application.status.get()
        last_reboot = self.application.db.latest_event("router_reboot")
        if last_reboot:
            status["router"]["last_reboot"] = last_reboot["timestamp"]
        next_speedtest = self.application.next_scheduled_speedtest()
        status["speedtest"]["next_run"] = str(next_speedtest) if next_speedtest else None
        status["speedtest"]["schedule_label"] = self.application.speedtest_schedule_label()
        return status

    def register_routes(self):
        @self.app.route("/")
        def home():
            status = self._dashboard_payload()
            return render_template(
                "dashboard.html",
                config=self.application.config,
                status=status,
                internet=status["internet"],
                speedtest=status["speedtest"],
                router=status["router"],
                system=status["system"],
                now=datetime.now(),
            )

        @self.app.route("/settings", methods=["GET", "POST"])
        def settings():
            error = None
            if request.method == "POST":
                mode = request.form.get("speedtest_schedule_mode", "every_30_minutes")
                custom_times = request.form.get("custom_speedtest_times", "")
                try:
                    self.application.update_speedtest_schedule(mode, custom_times)
                    return redirect(url_for("settings", saved="1"))
                except ValueError as exc:
                    error = str(exc)

            return render_template(
                "settings.html",
                config=self.application.config,
                schedule_mode=self.application.speedtest_schedule_mode(),
                schedule_label=self.application.speedtest_schedule_label(),
                speedtest_times=self.application.configured_speedtest_times(),
                error=error,
                saved=request.args.get("saved") == "1",
                now=datetime.now(),
            )

        @self.app.route("/dev")
        def dev():
            status = self._dashboard_payload()
            return render_template(
                "dev.html",
                status=status,
                internet=status["internet"],
                speedtest=status["speedtest"],
                now=datetime.now(),
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
                lines = log_file.read_text(encoding="utf-8", errors="ignore").splitlines()
                recent = lines[-150:]
            else:
                recent = ["No log file found."]
            return render_template("logs.html", lines=recent, now=datetime.now())

        @self.app.route("/api/status")
        def api_status():
            status = self._dashboard_payload()
            internet = status["internet"]
            speedtest = status["speedtest"]
            router = status["router"]
            system = status["system"]
            return jsonify({
                "version": status["version"],
                "internet_status": internet["status"],
                "health_score": internet["score"],
                "latest_latency_ms": internet["latency"],
                "packet_loss": internet["packet_loss"],
                "dns_ok": internet["dns_ok"],
                "internet_details": internet["details"],
                "last_check": internet["last_check"],
                "download": speedtest["download"],
                "upload": speedtest["upload"],
                "speedtest_ping": speedtest["ping"],
                "speedtest_server": speedtest["server"],
                "last_speedtest": speedtest["last_run"],
                "next_speedtest": speedtest.get("next_run"),
                "speedtest_schedule_label": speedtest.get("schedule_label"),
                "router_status": router.get("status", "Monitoring"),
                "last_reboot": router.get("last_reboot"),
                "started_at": system["started_at"],
                "last_update": system["last_update"],
                "timestamp": str(datetime.now()),
            })

        @self.app.route("/api/charts/latency")
        def api_latency_chart():
            rows = self.application.db.health_history(limit=96)
            labels = []
            values = []
            scores = []
            for row in rows:
                labels.append(row["timestamp"][11:16] if row["timestamp"] else "")
                values.append(row["latency"])
                scores.append(row["score"])
            return jsonify({"labels": labels, "values": values, "scores": scores})

        @self.app.route("/health")
        def health():
            return jsonify({"status": self._dashboard_payload(), "timestamp": str(datetime.now())})

    def run(self):
        self.app.run(
            host=self.application.config.get("dashboard", "host"),
            port=self.application.config.get("dashboard", "port"),
            debug=False,
            use_reloader=False,
        )
