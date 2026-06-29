import ctypes
import os
import sys
import threading
from datetime import datetime, timedelta
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
        status["intelligence"] = self.application.internet_intelligence()
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
                intelligence=status["intelligence"],
                now=datetime.now(),
            )

        @self.app.route("/internet")
        def internet():
            status = self._dashboard_payload()
            return render_template(
                "internet.html",
                config=self.application.config,
                status=status,
                internet=status["internet"],
                speedtest=status["speedtest"],
                router=status["router"],
                intelligence=status["intelligence"],
                now=datetime.now(),
            )

        @self.app.route("/history")
        def history():
            status = self._dashboard_payload()
            return render_template(
                "history.html",
                status=status,
                history=self.application.history_summary(),
                now=datetime.now(),
            )

        @self.app.route("/reports")
        def reports():
            status = self._dashboard_payload()
            return render_template(
                "reports.html",
                status=status,
                report=self.application.report_summary(),
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

        @self.app.route("/lab")
        def lab():
            return render_template(
                "lab.html",
                lab=self._lab_payload(),
                message=request.args.get("message"),
                now=datetime.now(),
            )

        @self.app.route("/lab/action", methods=["POST"])
        def lab_action():
            action = request.form.get("action")
            actions = {
                "run_ping": ("Ping check completed", self.application.health_check),
                "run_speedtest": ("Speed test completed", self.application.daily_speed_test),
                "run_maintenance": ("Maintenance check completed", self.application.maintenance_check),
                "reload_config": ("Configuration reloaded", self.application.reload_configuration),
            }
            label, function = actions.get(action, ("Unknown Lab action", None))
            if function:
                try:
                    function()
                except Exception as exc:
                    self.application.log.exception(f"Lab action failed: {action} - {exc}")
                    label = f"Lab action failed: {exc}"
            return redirect(url_for("lab", message=label))

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
            intelligence = status["intelligence"]
            return jsonify({
                "version": status["version"],
                "internet_status": internet["status"],
                "health_score": intelligence["quality_score"],
                "internet_quality_score": intelligence["quality_score"],
                "isp_grade": intelligence["isp_grade"],
                "reliability_trend": intelligence["trend"],
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

    def _lab_payload(self):
        status = self._dashboard_payload()
        return {
            "overview": self._lab_overview(status),
            "scheduler": self._lab_scheduler(status),
            "logs": self._recent_log_entries(),
            "database": self._database_counts(),
            "configuration": self._flatten_config(self.application.config.data),
            "actions": [
                ("run_ping", "Run Ping"),
                ("run_speedtest", "Run Speed Test"),
                ("run_maintenance", "Run Maintenance"),
                ("reload_config", "Reload Configuration"),
            ],
        }

    def _lab_overview(self, status):
        started_at = status["system"].get("started_at")
        started = self.application.parse_timestamp(started_at)
        return [
            ("Application Version", status["version"]),
            ("Start Time", started_at or "Unknown"),
            ("Uptime", self._format_uptime(started)),
            ("Python Version", sys.version.split()[0]),
            ("SQLite Status", self._sqlite_status()),
            ("Database Size", self._database_size()),
            ("Memory Usage", self._memory_usage()),
            ("Scheduler Status", self._scheduler_status()),
            ("Background Threads", max(threading.active_count() - 1, 0)),
            ("Configuration Loaded", "Loaded" if self.application.config.data else "Unavailable"),
        ]

    def _lab_scheduler(self, status):
        return [
            ("Next Ping", self._next_interval_run("Internet Health Check")),
            ("Next Speed Test", status["speedtest"].get("next_run") or "Disabled"),
            ("Next Maintenance", self._next_maintenance()),
            ("Last Speed Test", status["speedtest"].get("last_run") or "Never"),
            ("Last Maintenance", self._last_maintenance()),
            ("Queue Status", f"{len(self.application.scheduler.jobs)} scheduled job(s)"),
        ]

    def _scheduler_status(self):
        return "Active" if self.application.scheduler.jobs else "No jobs registered"

    def _next_interval_run(self, job_name):
        now = datetime.now()
        for job in self.application.scheduler.jobs:
            if job["name"] == job_name and job["type"] == "interval":
                last_run = job.get("last_run")
                if not last_run:
                    return "Due now"
                return str(last_run + job["interval"])
        return "Not scheduled"

    def _next_maintenance(self):
        time_value = self.application.config.get("reboot_window_time", default="04:00")
        hour, minute = self.application.parse_clock_time(time_value)
        now = datetime.now()
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return str(candidate)

    def _last_maintenance(self):
        candidates = [
            self.application.db.latest_event("maintenance_check"),
            self.application.db.latest_event("router_reboot_recommended"),
            self.application.db.latest_event("router_reboot_skipped"),
        ]
        candidates = [event for event in candidates if event]
        if not candidates:
            return "Never"
        latest = max(candidates, key=lambda event: event["timestamp"])
        return latest["timestamp"]

    def _database_counts(self):
        health_rows = self.application.db.health_history(limit=10000)
        return [
            ("Latency", self.application.db.count_rows("health_checks")),
            ("Speed Tests", self.application.db.count_rows("speed_tests")),
            ("Outages", len(self.application.outage_runs(health_rows))),
            ("Router Reboots", self.application.db.count_events("router_reboot")),
            ("Events", self.application.db.count_events()),
        ]

    def _recent_log_entries(self):
        log_file = Path("logs/routermonitor.log")
        if not log_file.exists():
            return [{"severity": "info", "line": "No log file found."}]
        lines = log_file.read_text(encoding="utf-8", errors="ignore").splitlines()
        return [
            {"severity": self._line_severity(line), "line": line}
            for line in lines[-80:]
        ]

    @staticmethod
    def _line_severity(line):
        upper = line.upper()
        if "CRITICAL" in upper or "ERROR" in upper or "EXCEPTION" in upper:
            return "error"
        if "WARNING" in upper or "WARN" in upper:
            return "warning"
        if "DEBUG" in upper:
            return "debug"
        return "info"

    def _sqlite_status(self):
        try:
            self.application.db.conn.execute("SELECT 1").fetchone()
            return "Connected"
        except Exception as exc:
            return f"Unavailable: {exc}"

    def _database_size(self):
        path = Path(self.application.db.filename)
        if not path.exists():
            return "Not created"
        return self._format_bytes(path.stat().st_size)

    def _memory_usage(self):
        rss = self._process_memory_bytes()
        return self._format_bytes(rss) if rss else "Unavailable"

    @staticmethod
    def _process_memory_bytes():
        if os.name == "nt":
            try:
                class ProcessMemoryCounters(ctypes.Structure):
                    _fields_ = [
                        ("cb", ctypes.c_ulong),
                        ("PageFaultCount", ctypes.c_ulong),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t),
                    ]

                counters = ProcessMemoryCounters()
                counters.cb = ctypes.sizeof(counters)
                handle = ctypes.windll.kernel32.GetCurrentProcess()
                ok = ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
                return counters.WorkingSetSize if ok else None
            except Exception:
                return None

        try:
            import resource
        except ImportError:
            return None
        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return usage * 1024

    @staticmethod
    def _format_bytes(value):
        size = float(value)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
            size /= 1024
        return f"{size:.1f} GB"

    @staticmethod
    def _format_uptime(started):
        if not started:
            return "Unknown"
        delta = datetime.now() - started
        days = delta.days
        hours, remainder = divmod(delta.seconds, 3600)
        minutes = remainder // 60
        if days:
            return f"{days}d {hours}h {minutes}m"
        if hours:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    @classmethod
    def _flatten_config(cls, data, prefix=""):
        rows = []
        for key in sorted(data):
            value = data[key]
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                rows.extend(cls._flatten_config(value, path))
            elif isinstance(value, list):
                rows.append((path, ", ".join(str(item) for item in value)))
            else:
                rows.append((path, value))
        return rows

    def run(self):
        self.app.run(
            host=self.application.config.get("dashboard", "host"),
            port=self.application.config.get("dashboard", "port"),
            debug=False,
            use_reloader=False,
        )
