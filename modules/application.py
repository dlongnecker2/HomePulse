import threading
from datetime import datetime, timedelta

from modules.config import Config
from modules.dashboard import Dashboard
from modules.database import Database
from modules.logger import get_logger
from modules.network import NetworkMonitor
from modules.port_check import check_dashboard_port
from modules.scheduler import Scheduler
from modules.speedtest_engine import SpeedTestEngine
from modules.status import StatusManager


class Application:
    def __init__(self):
        self.log = get_logger()
        self.config = Config()
        self.db = Database(self.config.get("database"))
        self.scheduler = Scheduler(self.log)
        self.network = NetworkMonitor(self.config, self.log)
        self.speedtest = SpeedTestEngine(self.log)
        self.status = StatusManager()

    def startup_message(self):
        self.log.info("=" * 60)
        self.log.info("HomePulse starting...")
        self.log.info("Home Reliability Dashboard")
        self.log.info(f"Version: {self.config.get('version', default='2.6.4')}")
        self.log.info("Dashboard: http://localhost:8080")
        self.log.info("Developer Console: http://localhost:8080/dev")
        self.log.info("Logs: http://localhost:8080/logs")
        self.log.info("=" * 60)

    def initialize(self):
        self.startup_message()
        self.db.initialize()
        self.log.info("Database initialized successfully")
        self.load_latest_speedtest()
        self.load_latest_health_check()
        self.register_jobs()

    def load_latest_speedtest(self):
        latest = self.db.latest_speed_test()
        if latest:
            self.status.update_speedtest(
                download=latest["download"],
                upload=latest["upload"],
                ping=latest["ping"],
                server=latest["server"],
                last_run=latest["timestamp"],
            )

    def load_latest_health_check(self):
        latest = self.db.latest_health_check()
        if latest:
            status = "Healthy" if latest["score"] >= 90 else "Degraded" if latest["score"] >= 60 else "Unhealthy"
            self.status.update_internet(
                status=status,
                score=latest["score"],
                latency=latest["latency"],
                packet_loss=latest["packet_loss"],
                dns_ok=latest["dns_ok"],
                details="Loaded from latest SQLite health check",
                last_check=latest["timestamp"],
            )

    def register_jobs(self):
        self.scheduler.every_minutes(
            name="Internet Health Check",
            minutes=self.config.get("monitor_interval_minutes"),
            function=self.health_check,
        )
        self.register_speedtest_jobs()
        self.register_maintenance_job()

    def register_speedtest_jobs(self):
        if not self.config.get("speedtest_schedule_enabled", default=True):
            self.log.info("Scheduled speed tests are disabled")
            return
        speedtest_times = self.configured_speedtest_times()
        for time_value in speedtest_times:
            hour, minute = self.parse_clock_time(time_value)
            self.scheduler.daily(
                name=f"Scheduled Speed Test {time_value}",
                hour=hour,
                minute=minute,
                function=self.daily_speed_test,
            )
        self.log.info(f"Scheduled speed tests: {', '.join(speedtest_times)}")

    def register_maintenance_job(self):
        time_value = self.config.get("reboot_window_time", default="04:00")
        hour, minute = self.parse_clock_time(time_value)
        self.scheduler.daily(
            name=f"Maintenance Check {time_value}",
            hour=hour,
            minute=minute,
            function=self.maintenance_check,
        )
        self.log.info(f"Maintenance check scheduled for {time_value}")

    def configured_speedtest_times(self):
        default_times = self.default_speedtest_times()
        configured = self.config.get("speedtest_times", default=default_times)
        if not isinstance(configured, list) or not configured:
            self.log.warning("Invalid speedtest_times config; using 30-minute defaults")
            configured = default_times

        valid_times = []
        seen = set()
        for time_value in configured:
            try:
                normalized = self.normalize_clock_time(time_value)
            except ValueError as exc:
                self.log.warning(f"Ignoring invalid speed test time {time_value!r}: {exc}")
                continue
            if normalized not in seen:
                valid_times.append(normalized)
                seen.add(normalized)

        if valid_times:
            return valid_times

        self.log.warning("No valid speedtest_times configured; using 30-minute defaults")
        return default_times

    @staticmethod
    def default_speedtest_times():
        return [f"{hour:02d}:{minute:02d}" for hour in range(24) for minute in (0, 30)]

    @staticmethod
    def speedtest_times_for_interval(hours):
        return [f"{hour:02d}:00" for hour in range(0, 24, hours)]

    def speedtest_schedule_mode(self):
        if not self.config.get("speedtest_schedule_enabled", default=True):
            return "disabled"
        mode = self.config.get("speedtest_schedule_mode", default=None)
        if mode:
            return mode

        times = self.configured_speedtest_times()
        presets = {
            "every_30_minutes": self.default_speedtest_times(),
            "every_1_hour": self.speedtest_times_for_interval(1),
            "every_3_hours": self.speedtest_times_for_interval(3),
            "every_6_hours": self.speedtest_times_for_interval(6),
        }
        for preset, preset_times in presets.items():
            if times == preset_times:
                return preset
        return "custom"

    def speedtest_schedule_label(self):
        labels = {
            "disabled": "Disabled",
            "every_30_minutes": "Every 30 minutes",
            "every_1_hour": "Every 1 hour",
            "every_3_hours": "Every 3 hours",
            "every_6_hours": "Every 6 hours",
            "custom": "Custom scheduled times",
        }
        return labels.get(self.speedtest_schedule_mode(), "Custom scheduled times")

    def update_speedtest_schedule(self, mode, custom_times=None):
        mode_times = {
            "every_30_minutes": self.default_speedtest_times,
            "every_1_hour": lambda: self.speedtest_times_for_interval(1),
            "every_3_hours": lambda: self.speedtest_times_for_interval(3),
            "every_6_hours": lambda: self.speedtest_times_for_interval(6),
        }

        if mode == "disabled":
            self.config.data["speedtest_schedule_enabled"] = False
            self.config.data["speedtest_schedule_mode"] = "disabled"
        elif mode == "custom":
            times = self.normalize_custom_speedtest_times(custom_times or "")
            self.config.data["speedtest_schedule_enabled"] = True
            self.config.data["speedtest_schedule_mode"] = "custom"
            self.config.data["speedtest_times"] = times
        elif mode in mode_times:
            self.config.data["speedtest_schedule_enabled"] = True
            self.config.data["speedtest_schedule_mode"] = mode
            self.config.data["speedtest_times"] = mode_times[mode]()
        else:
            raise ValueError("Unknown speed test schedule mode")

        self.config.save()
        self.scheduler.remove_jobs_by_prefix("Scheduled Speed Test")
        self.register_speedtest_jobs()

    def normalize_custom_speedtest_times(self, raw_times):
        pieces = raw_times.replace(",", "\n").splitlines()
        normalized = []
        seen = set()
        for piece in pieces:
            value = piece.strip()
            if not value:
                continue
            time_value = self.normalize_clock_time(value)
            if time_value not in seen:
                normalized.append(time_value)
                seen.add(time_value)
        if not normalized:
            raise ValueError("Enter at least one custom time")
        return normalized

    def next_scheduled_speedtest(self, now=None):
        if not self.config.get("speedtest_schedule_enabled", default=True):
            return None

        now = now or datetime.now()
        candidates = []
        for time_value in self.configured_speedtest_times():
            hour, minute = self.parse_clock_time(time_value)
            candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate <= now:
                candidate += timedelta(days=1)
            candidates.append(candidate)

        if not candidates:
            return None
        return min(candidates)

    @classmethod
    def normalize_clock_time(cls, value):
        hour, minute = cls.parse_clock_time(value)
        return f"{hour:02d}:{minute:02d}"

    @staticmethod
    def parse_clock_time(value):
        if not isinstance(value, str) or ":" not in value:
            raise ValueError("expected HH:MM")
        hour_text, minute_text = value.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValueError("time must be between 00:00 and 23:59")
        return hour, minute

    def health_check(self):
        result = self.network.check()
        now = str(datetime.now())
        self.status.update_internet(
            status=result.status,
            score=result.score,
            latency=result.latency,
            packet_loss=result.packet_loss,
            dns_ok=result.dns_ok,
            details=result.details,
            last_check=now,
        )
        self.db.add_health_check(
            timestamp=now,
            latency=result.latency,
            packet_loss=result.packet_loss,
            dns_ok=result.dns_ok,
            score=result.score,
            rebooted=0,
        )
        self.log.info(
            f"Internet Health: {result.status} | Score={result.score} | "
            f"Latency={result.latency}ms | PacketLoss={result.packet_loss}% | "
            f"DNS={result.dns_ok} | {result.details}"
        )

    def daily_speed_test(self):
        result = self.speedtest.run()
        self.status.update_speedtest(
            download=result.download,
            upload=result.upload,
            ping=result.ping,
            server=result.server,
            last_run=result.timestamp,
        )
        self.db.add_speed_test(
            timestamp=result.timestamp,
            download=result.download,
            upload=result.upload,
            ping=result.ping,
            server=result.server,
        )
        self.db.add_event(
            timestamp=result.timestamp,
            event_type="speed_test",
            message=f"Speed test complete: {result.download} down / {result.upload} up",
        )

    def maintenance_check(self):
        now = datetime.now()
        window_time = self.config.get("reboot_window_time", default="04:00")
        if not self.is_maintenance_window(now, window_time):
            self.log.info(f"Maintenance check skipped outside reboot window {window_time}")
            return

        reasons = self.reboot_recommendation_reasons()
        if not reasons:
            self.log.info("Maintenance check complete: reboot not recommended")
            self.db.add_event(
                timestamp=str(now),
                event_type="maintenance_check",
                message="No reboot recommended during maintenance window",
            )
            return

        recent_reboot = self.recent_router_reboot(now)
        if recent_reboot:
            message = (
                "Reboot recommendation skipped because router reboot cooldown is active. "
                f"Reasons: {'; '.join(reasons)}"
            )
            self.log.info(message)
            self.db.add_event(timestamp=str(now), event_type="router_reboot_skipped", message=message)
            return

        self.recommend_router_reboot(now, reasons)

    def reboot_recommendation_reasons(self):
        reasons = []
        latest_speed = self.db.latest_speed_test()
        if latest_speed and self.speed_below_thresholds(latest_speed):
            reasons.append(
                "latest speed test below thresholds "
                f"({latest_speed['download']} down / {latest_speed['upload']} up)"
            )

        sustained_reason = self.sustained_health_problem()
        if sustained_reason:
            reasons.append(sustained_reason)

        return reasons

    def speed_below_thresholds(self, speed_result):
        minimum_download = self.config.get("minimum_download_mbps", default=100)
        minimum_upload = self.config.get("minimum_upload_mbps", default=10)
        download = speed_result.get("download")
        upload = speed_result.get("upload")
        return (
            download is not None
            and upload is not None
            and (download < minimum_download or upload < minimum_upload)
        )

    def sustained_health_problem(self):
        recent_checks = self.db.health_history(limit=6)
        if len(recent_checks) < 3:
            return None

        maximum_latency = self.config.get("maximum_latency_ms", default=100)
        maximum_packet_loss = self.config.get("thresholds", "packet_loss", default=5)
        poor_checks = [
            row for row in recent_checks
            if (
                row["latency"] is not None
                and row["latency"] > maximum_latency
            )
            or (
                row["packet_loss"] is not None
                and row["packet_loss"] > maximum_packet_loss
            )
        ]

        if len(poor_checks) >= 4:
            return (
                "latency or packet loss poor for sustained period "
                f"({len(poor_checks)} of {len(recent_checks)} recent checks)"
            )
        return None

    def recent_router_reboot(self, now):
        latest_reboot = self.latest_reboot_activity()
        if not latest_reboot:
            return None

        rebooted_at = self.parse_timestamp(latest_reboot["timestamp"])
        if not rebooted_at:
            return None

        cooldown_hours = self.config.get("reboot_cooldown_hours", default=24)
        if now - rebooted_at < timedelta(hours=cooldown_hours):
            return latest_reboot
        return None

    def latest_reboot_activity(self):
        events = [
            event for event in (
                self.db.latest_event("router_reboot"),
                self.db.latest_event("router_reboot_recommended"),
            )
            if event and self.parse_timestamp(event["timestamp"])
        ]
        if not events:
            return None
        return max(events, key=lambda event: self.parse_timestamp(event["timestamp"]))

    def recommend_router_reboot(self, now, reasons):
        message = (
            "Router reboot recommended during maintenance window. "
            "No reboot command was executed. "
            f"Reasons: {'; '.join(reasons)}"
        )
        self.log.warning(message)
        self.db.add_event(timestamp=str(now), event_type="router_reboot_recommended", message=message)

    @classmethod
    def is_maintenance_window(cls, now, window_time):
        hour, minute = cls.parse_clock_time(window_time)
        return now.hour == hour and now.minute >= minute

    @staticmethod
    def parse_timestamp(value):
        if not value:
            return None
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        return None

    def start_dashboard(self):
        check_dashboard_port(self.config, self.log)
        dashboard = Dashboard(self)
        dashboard_thread = threading.Thread(target=dashboard.run, daemon=True)
        dashboard_thread.start()
        self.log.info("Dashboard started on http://localhost:8080")

    def start(self):
        self.initialize()
        if self.config.get("dashboard", "enabled"):
            self.start_dashboard()
        self.scheduler.run_forever(sleep_seconds=10)
