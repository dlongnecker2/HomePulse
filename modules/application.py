import threading
from datetime import datetime

from modules.logger import get_logger
from modules.config import Config
from modules.database import Database
from modules.scheduler import Scheduler
from modules.dashboard import Dashboard


class Application:
    def __init__(self):
        self.log = get_logger()
        self.config = Config()
        self.db = Database(self.config.get("database"))
        self.scheduler = Scheduler(self.log)

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
        self.log.info("Health check placeholder ran")
        self.db.add_event(
            timestamp=str(datetime.now()),
            event_type="health_check",
            message="Health check placeholder ran"
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
