import sqlite3
import time
import unittest

from tests.test_greenhouse_conditions import DummyConfig, DummyLog, build_dashboard_app
from modules.dashboard import Dashboard
from modules.environment.database import EnvironmentStore
from modules.environment.manager import EnvironmentManager


class DashboardTimeoutTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.store = EnvironmentStore(self.conn)
        self.store.initialize()
        self.config = DummyConfig(
            {
                "environment": {
                    "enabled": True,
                    "refresh_interval_minutes": 5,
                    "stale_after_minutes": 10,
                },
                "router_reboot": {
                    "home_assistant_url": "http://homeassistant.local",
                    "home_assistant_token": "token",
                },
            }
        )
        self.log = DummyLog()
        self.manager = EnvironmentManager(self.config, self.log, self.store)

    def tearDown(self):
        self.conn.close()

    def test_home_status_remains_responsive_when_timeline_is_slow(self):
        dashboard_app = Dashboard(build_dashboard_app(self.manager))

        class SlowTimeline:
            def get_summary(self, hours_back=24):
                time.sleep(1.5)
                return {}

            def get_events(self, limit=20, hours_back=24, category=None, severity=None):
                time.sleep(1.5)
                return []

        dashboard_app.application.timeline = SlowTimeline()
        client = dashboard_app.app.test_client()

        start = time.perf_counter()
        response = client.get("/api/home/status")
        elapsed = time.perf_counter() - start

        self.assertEqual(response.status_code, 200)
        self.assertLess(elapsed, 5.0)

    def test_recent_endpoints_timeout_when_their_repositories_are_slow(self):
        dashboard_app = Dashboard(build_dashboard_app(self.manager))

        class SlowTimeline:
            def get_events(self, **kwargs):
                time.sleep(1.5)
                return []

        class SlowNotifications:
            def get_notifications(self, **kwargs):
                time.sleep(1.5)
                return []

            def get_unread_count(self):
                time.sleep(1.5)
                return 0

        dashboard_app.application.timeline = SlowTimeline()
        dashboard_app.application.notification_manager = SlowNotifications()
        client = dashboard_app.app.test_client()

        timeline_response = client.get("/api/timeline/recent")
        notifications_response = client.get("/api/notifications/recent")

        self.assertEqual(timeline_response.status_code, 504)
        self.assertEqual(notifications_response.status_code, 504)


if __name__ == "__main__":
    unittest.main()
