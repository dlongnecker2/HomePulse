import threading
from datetime import datetime

from modules.logger import get_logger
from modules.config import Config
from modules.database import Database
from modules.scheduler import Scheduler
from modules.dashboard import Dashboard
from modules.network import NetworkMonitor
from modules.status import StatusManager
from modules.speedtest_engine import SpeedTestEngine


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
        self.log.info(f"Version: {self.config.get('version', default='2.2')}")
        self.log.info("Dashboard: http://localhost:8080")
        self.log.info("Developer Console: http://localhost:8080/dev")
        self.log.info("Logs: http://localhost:8080/logs")
        self.log.info("=" * 60)

    def initialize(self):
        self.startup_message()
        self.db.initialize()
        self.log.info("Database initialized successfully")
        self.load_latest_speedtest()
        self.register_jobs()

    def load_latest_speedtest(self):
        latest = self.db.latest_speed_test()
        if latest:
            self.status.update_speedtest(
                download=latest["download"],
                upload=latest["upload"],
                ping=latest["ping"],
                server=latest["server"],
                last_run=latest["timestamp"]
            )

    def register_jobs(self):
        self.scheduler.every_minutes(
            name="Internet Health Check",
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

        self.status.update_internet(
            status=result.status,
            score=result.score,
            latency=result.latency,
            packet_loss=result.packet_loss,
            dns_ok=result.dns_ok,
            details=result.details,
            last_check=now
        )

        self.db.add_health_check(
            timestamp=now,
            latency=result.latency,
            packet_loss=result.packet_loss,
            dns_ok=result.dns_ok,
            score=result.score,
            rebooted=0
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
            last_run=result.timestamp
        )

        self.db.add_speed_test(
            timestamp=result.timestamp,
            download=result.download,
            upload=result.upload,
            ping=result.ping,
            server=result.server
        )

        self.db.add_event(
            timestamp=result.timestamp,
            event_type="speed_test",
            message=f"Speed test complete: {result.download} down / {result.upload} up"
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
