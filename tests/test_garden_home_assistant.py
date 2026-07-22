import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask, render_template

from modules.garden.providers.home_assistant import HomeAssistantGardenProvider


ROOT = Path(__file__).resolve().parents[1]


def garden_config():
    return {
        "router_recovery": {
            "home_assistant_url": "http://homeassistant.local",
            "home_assistant_token": "secret-token",
        },
        "providers": {
            "home_assistant": {
                "enabled": True,
            }
        },
    }


def irrigation_states(active=False):
    return [
        {
            "entity_id": "sensor.smart_outdoor_timer_next_watering",
            "state": "2026-07-22T03:11:00+00:00",
            "attributes": {"friendly_name": "Smart Outdoor Timer Next watering", "device_class": "timestamp", "icon": "mdi:sprinkler-variant"},
        },
        {
            "entity_id": "switch.smart_outdoor_timer_rain_delay",
            "state": "off",
            "attributes": {"friendly_name": "Smart Outdoor Timer Rain delay", "icon": "mdi:weather-pouring"},
        },
        {
            "entity_id": "valve.smart_outdoor_timer_front_zone",
            "state": "open" if active else "closed",
            "attributes": {
                "friendly_name": "Smart Outdoor Timer Front zone",
                "device_class": "water",
                "supported_features": 3,
                "device_id": "device.smart_outdoor_timer",
            },
        },
        {
            "entity_id": "switch.smart_outdoor_timer_front_smart_watering",
            "state": "on",
            "attributes": {"friendly_name": "Smart Outdoor Timer Front smart watering"},
        },
        {
            "entity_id": "update.orbit_bhyve_update",
            "state": "off",
            "attributes": {"friendly_name": "Orbit BHyve Update", "supported_features": 23},
        },
    ]


class HomeAssistantGardenProviderTests(unittest.TestCase):
    def setUp(self):
        self.provider = HomeAssistantGardenProvider()
        self.app = Flask(__name__, template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static"))
        for endpoint in (
            "home",
            "home_center",
            "environment_center",
            "internet",
            "solar",
            "vehicle_center",
            "weather",
            "lighting",
            "garden",
            "weight_progress",
            "speed_test_center",
            "email_center",
            "settings",
            "lab",
            "logs",
            "about",
        ):
            self.app.add_url_rule(f"/{endpoint}", endpoint, lambda: "")

    def run_provider(self, states):
        with patch.object(HomeAssistantGardenProvider, "request_json", return_value=states):
            return self.provider.fetch_status(garden_config(), timeout_seconds=1)

    def test_irrigation_entities_are_recognized_without_direct_bhyve_credentials(self):
        status = self.run_provider(irrigation_states(active=False))

        self.assertEqual(status["provider"], "home_assistant")
        self.assertTrue(status["configured"])
        self.assertEqual(status["controller_count"], 1)
        self.assertEqual(status["zone_count"], 1)
        self.assertEqual(status["active_watering_zone"], None)
        self.assertEqual(status["next_watering_schedule"], "2026-07-22T03:11:00+00:00")
        self.assertEqual(status["rain_delay_active"], False)
        self.assertEqual(status["integration"], "Orbit B-hyve")
        self.assertEqual(status["status"], "No active watering")
        self.assertNotIn("username", status)
        self.assertNotIn("password", status)
        self.assertNotIn("access_token", status)

    def test_controller_and_zone_states_are_normalized_safely(self):
        status = self.run_provider(irrigation_states(active=True))

        controller = status["controllers"][0]
        zone = status["zones"][0]

        self.assertEqual(status["status"], "Front zone running")
        self.assertEqual(status["active_watering_zone"], "Front zone")
        self.assertEqual(controller["active_watering_zone"], "Front zone")
        self.assertEqual(zone["status"], "running")
        self.assertEqual(zone["availability"], "available")
        self.assertEqual(zone["smart_watering_state"], "on")
        self.assertTrue(status["read_only"])
        self.assertTrue(controller["manual_start_stop"]["read_only"])
        self.assertTrue(zone["manual_start_stop"]["read_only"])

    def test_missing_optional_schedule_and_rain_delay_data_does_not_break_garden(self):
        states = [
            {
                "entity_id": "valve.smart_outdoor_timer_front_zone",
                "state": "closed",
                "attributes": {
                    "friendly_name": "Smart Outdoor Timer Front zone",
                    "device_class": "water",
                    "supported_features": 3,
                    "device_id": "device.smart_outdoor_timer",
                },
            }
        ]
        status = self.run_provider(states)

        self.assertEqual(status["status"], "No active watering")
        self.assertIsNone(status["next_watering_schedule"])
        self.assertIsNone(status["rain_delay_active"])
        self.assertEqual(status["zone_count"], 1)
        self.assertEqual(status["controllers"][0]["zone_count"], 1)

    def test_no_matching_entities_produces_friendly_empty_state(self):
        states = [
            {
                "entity_id": "sensor.living_room_temperature",
                "state": "72.0",
                "attributes": {"friendly_name": "Living Room Temperature"},
            }
        ]
        status = self.run_provider(states)

        self.assertEqual(status["status"], "No irrigation entities found")
        self.assertFalse(status["controllers"])
        self.assertFalse(status["zones"])
        self.assertIn("No irrigation entities were found in Home Assistant.", status["message"])
        self.assertNotIn("Loading", status["message"])

    def test_irrigation_path_remains_read_only(self):
        status = self.run_provider(irrigation_states(active=False))

        self.assertTrue(status["read_only"])
        self.assertTrue(status["controllers"][0]["manual_start_stop"]["read_only"])
        self.assertTrue(status["zones"][0]["manual_start_stop"]["read_only"])
        self.assertFalse(status["controllers"][0]["manual_start_stop"]["start"])
        self.assertFalse(status["controllers"][0]["manual_start_stop"]["stop"])

    def test_garden_page_does_not_request_bhyve_credentials(self):
        status = self.run_provider(irrigation_states(active=False))
        greenhouse = {
            "enabled": True,
            "configured": True,
            "source_status": "live",
            "status": "Connected",
            "temperature_display": "75.0°F",
            "humidity_display": "44%",
            "temperature_band": "Normal",
            "today_high": "80.0°F",
            "today_low": "72.0°F",
            "last_updated": "2026-07-21T14:00:00+00:00",
            "observed_at": "2026-07-21T14:00:00+00:00",
            "source_timestamp": "2026-07-21T13:55:00+00:00",
            "history_count": 2,
            "history_points": [],
            "source": "live",
            "message": "Live greenhouse readings are available.",
        }
        with self.app.test_request_context("/garden"):
            html = render_template("garden.html", now=datetime.now(), garden=status, greenhouse=greenhouse)

        self.assertIn("Home Assistant", html)
        self.assertNotIn("Add B-hyve credentials", html)
        self.assertNotIn("bhyve_username", html)
        self.assertNotIn("bhyve_password", html)
        self.assertNotIn("bhyve_access_token", html)

    def test_no_credentials_appear_in_api_responses(self):
        status = self.run_provider(irrigation_states(active=False))

        for key in ("username", "password", "access_token", "home_assistant_token"):
            self.assertNotIn(key, status)
        self.assertTrue(status["controller_entity_ids"])


if __name__ == "__main__":
    unittest.main()
