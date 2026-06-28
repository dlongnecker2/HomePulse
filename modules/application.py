import threading
from datetime import datetime

from modules.logger import get_logger
from modules.config import Config
from modules.database import Database
from modules.scheduler import Scheduler
from modules.dashboard import Dashboard
from modules.network import NetworkMonitor


class Application:
    def __init__(self):
        self.log = get_logger()
        self.config = Config()
        self.db = Database(self.config.get("database"))
        self.scheduler = Scheduler(self.log)
        self.network = NetworkMonitor(self.config, self.log)

        self.status = {
            "internet_status": "Starting",
            "health_score": None,
            "latency": None,
            "packet_loss": None,
            "dns_ok": None,
            "details": "Application starting",
            "last_health_check": None
        }

    def startup_message(self):
        self.log.info("=" * 60)
        self.log.info("RouterMonitorV2 starting...")
        self.log.info(f"Project: {self.config.get('project_name')}")
        self.log.info(f"Version: {self.config.get('version')}")
        self.log.info("=" * 60)

    def initialize(self):
        self.startup_message()
        self.db.initialize()
        self.log.info("Database initialized successfully")
        self.register_jobs()

    def register_jobs(self):
        self.scheduler.every_minutes(
            name="Health Check",
            minutes=self.config.get("monitor_interval_minutes"),
            function=self.health_check
        )

        self.scheduler.daily(
            name="Daily Speed Test",
            hour=self.config.get("speedtest_hour"),
            minute=0,
            function=self.daily_speed_test
        )

    def health_check(self):
        result = self.network.check()
        now = str(datetime.now())

        self.status.update({
            "internet_status": result.status,
            "health_score": result.score,
            "latency": result.latency,
            "packet_loss": result.packet_loss,
            "dns_ok": result.dns_ok,
            "details": result.details,
            "last_health_check": now
        })

        self.db.add_health_check(
            timestamp=now,
            latency=result.latency,
            packet_loss=result.packet_loss,
            dns_ok=result.dns_ok,
            score=result.score,
            rebooted=0
        )

        self.log.info(
            f"Health: {result.status} | Score={result.score} | "
            f"Latency={result.latency}ms | PacketLoss={result.packet_loss}% | "
            f"DNS={result.dns_ok} | {result.details}"
        )

    def daily_speed_test(self):
        self.log.info("Daily speed test placeholder ran")
        self.db.add_event(
            timestamp=str(datetime.now()),
            event_type="speed_test",
            message="Daily speed test placeholder ran"
        )

    def start_dashboard(self):
        dashboard = Dashboard(self)
        dashboard_thread = threading.Thread(
            target=dashboard.run,
            daemon=True
        )
        dashboard_thread.start()
        self.log.info("Dashboard started on http://localhost:8080")

    def start(self):
        self.initialize()

        if self.config.get("dashboard", "enabled"):
            self.start_dashboard()

        self.scheduler.run_forever(sleep_seconds=10)
