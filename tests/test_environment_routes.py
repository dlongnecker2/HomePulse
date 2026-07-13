import unittest
from types import SimpleNamespace

from modules.dashboard import Dashboard


class DummyRegistry:
    def all(self):
        return []


class DummyPluginManager:
    def __init__(self):
        self.widget_registry = DummyRegistry()
        self.device_registry = DummyRegistry()


class DummyEnvironment:
    def __init__(self):
        self.status_payload_calls = 0
        self.entity_history_calls = 0
        self.snapshot = {
            "enabled": True,
            "configured": True,
            "status": "Connected",
            "availability": "live",
            "message": "Loaded from cached environmental snapshot.",
            "error": None,
            "timestamp": "2026-07-12T10:00:00",
            "last_successful_refresh": "2026-07-12T10:00:00",
            "snapshot_age_seconds": 15,
            "snapshot_age_label": "15s ago",
            "stale": False,
            "last_refresh_error": None,
            "summary": {
                "areas": 1,
                "devices": 1,
                "supported_entities": 1,
                "entities_with_readings": 1,
                "readings_recorded": 1,
                "stale_after_minutes": 10,
            },
            "areas": [],
            "entities": [],
            "refresh": {},
        }

    def status_payload(self):
        self.status_payload_calls += 1
        return dict(self.snapshot)

    def entity_history(self, entity_id, limit=200):
        self.entity_history_calls += 1
        if entity_id == "sensor.living_room_temperature":
            return [
                {
                    "timestamp": "2026-07-12T09:55:00",
                    "entity_id": entity_id,
                    "domain": "sensor",
                    "raw_state": "21.4",
                    "raw_value": "21.4",
                    "unit_of_measurement": "C",
                    "parsed_number": 21.4,
                    "parsed_boolean": None,
                    "availability": "available",
                    "area_id": "area.living_room",
                    "area_name": "Living Room",
                    "device_id": "device.thermostat",
                    "device_name": "Thermostat",
                    "entity_name": "Living Room Temperature",
                    "label_source": "registry",
                    "confidence": 1.0,
                    "metadata": {},
                }
            ]
        return []

    def refresh_snapshot(self):
        raise AssertionError("Routes must remain cache-only and must not trigger refreshes")


class DummyLog:
    def debug(self, *args, **kwargs):
        pass

    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def exception(self, *args, **kwargs):
        pass


class EnvironmentRouteTests(unittest.TestCase):
    def setUp(self):
        self.application = SimpleNamespace(
            environment=DummyEnvironment(),
            config=SimpleNamespace(get=lambda *args, **kwargs: {}),
            log=DummyLog(),
            plugin_manager=DummyPluginManager(),
            db=SimpleNamespace(),
            status=SimpleNamespace(get=lambda: {}),
            timeline=SimpleNamespace(get_summary=lambda **kwargs: {}, get_events=lambda **kwargs: []),
            notification_manager=SimpleNamespace(get_notifications=lambda **kwargs: [], get_unread_count=lambda: 0),
            health_score=SimpleNamespace(compute=lambda statuses: {"score": 100, "status_text": "Excellent", "trend": "Stable", "breakdown": {}}),
            alert_manager=SimpleNamespace(detect_alerts=lambda statuses: [], severity_priority=lambda severity: 0),
        )
        self.dashboard = Dashboard(self.application)
        self.client = self.dashboard.app.test_client()

    def test_environment_page_renders(self):
        response = self.client.get("/environment")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Environment Center", body)
        self.assertIn("Area-first, device-second grouping", body)
        self.assertEqual(self.application.environment.status_payload_calls, 1)

    def test_environment_api_returns_cached_snapshot_and_history(self):
        status_response = self.client.get("/api/environment/status")
        self.assertEqual(status_response.status_code, 200)
        status = status_response.get_json()
        self.assertEqual(status["status"], "Connected")
        self.assertEqual(status["summary"]["supported_entities"], 1)
        self.assertEqual(self.application.environment.status_payload_calls, 1)

        history_response = self.client.get("/api/environment/history/sensor.living_room_temperature?limit=1")
        self.assertEqual(history_response.status_code, 200)
        history = history_response.get_json()
        self.assertEqual(history["entity_id"], "sensor.living_room_temperature")
        self.assertEqual(history["count"], 1)
        self.assertEqual(len(history["history"]), 1)
        self.assertEqual(self.application.environment.entity_history_calls, 1)


if __name__ == "__main__":
    unittest.main()
