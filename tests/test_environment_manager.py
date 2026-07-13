import sqlite3
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

from modules.environment.database import EnvironmentStore
from modules.environment.manager import EnvironmentManager


class DummyConfig:
    def __init__(self, data):
        self.data = data

    def get(self, *keys, default=None):
        value = self.data
        try:
            for key in keys:
                value = value[key]
            return value
        except Exception:
            return default


class DummyLog:
    def debug(self, *args, **kwargs):
        pass

    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def exception(self, *args, **kwargs):
        pass


class EnvironmentManagerTests(unittest.TestCase):
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

    def tearDown(self):
        self.conn.close()

    def sample_payloads(self):
        states = [
            {
                "entity_id": "sensor.living_room_temperature",
                "state": "21.5",
                "attributes": {
                    "device_class": "temperature",
                    "state_class": "measurement",
                    "unit_of_measurement": "C",
                    "friendly_name": "Living Room Temperature",
                },
                "last_updated": "2026-07-12T10:00:00",
                "last_changed": "2026-07-12T10:00:00",
            },
            {
                "entity_id": "binary_sensor.basement_leak",
                "state": "off",
                "attributes": {
                    "device_class": "moisture",
                },
                "last_updated": "2026-07-12T10:00:00",
                "last_changed": "2026-07-12T10:00:00",
            },
            {
                "entity_id": "sensor.random_counter",
                "state": "17",
                "attributes": {
                    "friendly_name": "Random Counter",
                },
            },
        ]
        entity_registry = [
            {
                "entity_id": "sensor.living_room_temperature",
                "name": "Living Room Temperature",
                "original_name": "Living Room Temp",
                "device_id": "device.thermostat",
                "area_id": "area.living_room",
                "platform": "homeassistant",
            },
            {
                "entity_id": "binary_sensor.basement_leak",
                "name": "",
            },
        ]
        device_registry = [
            {
                "id": "device.thermostat",
                "name": "Thermostat",
                "area_id": "area.living_room",
            },
        ]
        area_registry = [
            {
                "area_id": "area.living_room",
                "name": "Living Room",
            }
        ]
        return states, entity_registry, device_registry, area_registry

    def sample_payload_bundle(self, enrichment_error=None):
        states, entity_registry, device_registry, area_registry = self.sample_payloads()
        return states, entity_registry, device_registry, area_registry, enrichment_error

    def states_only_payloads(self):
        return self.sample_payloads()[0]

    def fake_request_json(self, url, token, timeout_seconds):
        if url.endswith("/api/states"):
            return self.states_only_payloads()
        raise AssertionError(f"Unexpected Home Assistant request: {url}")

    def test_refresh_discovers_supported_entities_and_preserves_fallback_groups(self):
        manager = EnvironmentManager(self.config, self.log, self.store)

        with patch.object(manager, "_fetch_home_assistant_payloads", return_value=self.sample_payload_bundle()):
            snapshot = manager.refresh_snapshot()

        self.assertEqual(snapshot["status"], "Connected")
        self.assertEqual(snapshot["summary"]["supported_entities"], 2)
        self.assertEqual(snapshot["summary"]["areas"], 2)
        self.assertEqual(snapshot["summary"]["devices"], 2)
        self.assertEqual(self.store.count_readings(), 2)
        self.assertEqual(len(self.store.history("sensor.living_room_temperature")), 1)
        self.assertEqual(len(self.store.history("binary_sensor.basement_leak")), 1)
        self.assertNotIn("sensor.random_counter", {entity["entity_id"] for entity in snapshot["entities"]})

        living_room = next(area for area in snapshot["areas"] if area["area_id"] == "area.living_room")
        fallback_area = next(area for area in snapshot["areas"] if area["fallback_group"])
        self.assertEqual(living_room["display_name"], "Living Room")
        self.assertTrue(fallback_area["fallback_group"])

        temp_entity = next(entity for entity in snapshot["entities"] if entity["entity_id"] == "sensor.living_room_temperature")
        leak_entity = next(entity for entity in snapshot["entities"] if entity["entity_id"] == "binary_sensor.basement_leak")
        self.assertEqual(temp_entity["label_source"], "registry")
        self.assertEqual(leak_entity["label_source"], "fallback")

        with patch.object(manager, "_fetch_home_assistant_payloads", return_value=self.sample_payload_bundle()):
            second_snapshot = manager.refresh_snapshot()
        self.assertEqual(self.store.count_readings(), 2)
        self.assertEqual(second_snapshot["summary"]["supported_entities"], 2)

    def test_refresh_failure_preserves_last_good_snapshot(self):
        manager = EnvironmentManager(self.config, self.log, self.store)

        with patch.object(manager, "_fetch_home_assistant_payloads", return_value=self.sample_payload_bundle()):
            success_snapshot = manager.refresh_snapshot()

        with patch.object(manager, "_fetch_home_assistant_payloads", side_effect=RuntimeError("home assistant offline")):
            failed_snapshot = manager.refresh_snapshot()

        self.assertEqual(failed_snapshot["summary"]["supported_entities"], success_snapshot["summary"]["supported_entities"])
        self.assertTrue(failed_snapshot["stale"])
        self.assertIn("home assistant offline", failed_snapshot["last_refresh_error"])
        self.assertEqual(failed_snapshot["areas"][0]["display_name"], "Living Room")
        self.assertGreaterEqual(self.store.count_readings(), 2)

    def test_home_assistant_payloads_use_websocket_registry_enrichment(self):
        manager = EnvironmentManager(self.config, self.log, self.store)

        with patch.object(manager, "_request_json", side_effect=self.fake_request_json), patch.object(
            manager, "_fetch_registry_enrichment_via_websocket", return_value=self.sample_payload_bundle()[1:]
        ) as websocket_fetch:
            states, entity_registry, device_registry, area_registry, enrichment_error = manager._fetch_home_assistant_payloads()

        self.assertEqual(len(states), 3)
        self.assertEqual(len(entity_registry), 2)
        self.assertEqual(len(device_registry), 1)
        self.assertEqual(len(area_registry), 1)
        self.assertIsNone(enrichment_error)
        websocket_fetch.assert_called_once()

    def test_registry_enrichment_404_does_not_fail_refresh(self):
        manager = EnvironmentManager(self.config, self.log, self.store)

        def raise_404(*args, **kwargs):
            raise HTTPError("http://homeassistant.local/api/websocket", 404, "Not Found", hdrs=None, fp=None)

        with patch.object(manager, "_request_json", side_effect=self.fake_request_json), patch.object(
            manager, "_fetch_registry_enrichment_via_websocket", side_effect=raise_404
        ):
            snapshot = manager.refresh_snapshot()

        self.assertEqual(snapshot["status"], "Connected")
        self.assertEqual(snapshot["summary"]["supported_entities"], 2)
        self.assertEqual(snapshot["summary"]["areas"], 1)
        self.assertEqual(snapshot["summary"]["devices"], 1)
        self.assertEqual(snapshot["entities"][0]["area_name"], "Unassigned Area")
        self.assertEqual(snapshot["entities"][0]["device_name"], "Unknown Device")
        self.assertIn("enrichment_error", snapshot)
        self.assertGreaterEqual(self.store.count_readings(), 2)

    def test_registry_enrichment_websocket_unavailable_does_not_fail_refresh(self):
        manager = EnvironmentManager(self.config, self.log, self.store)

        with patch.object(manager, "_request_json", side_effect=self.fake_request_json), patch.object(
            manager, "_fetch_registry_enrichment_via_websocket", side_effect=OSError("websocket unavailable")
        ):
            snapshot = manager.refresh_snapshot()

        self.assertEqual(snapshot["status"], "Connected")
        self.assertEqual(snapshot["summary"]["supported_entities"], 2)
        self.assertEqual(snapshot["summary"]["areas"], 1)
        self.assertEqual(snapshot["summary"]["devices"], 1)
        self.assertTrue(any(area["fallback_group"] for area in snapshot["areas"]))
        self.assertTrue(any(device["fallback_group"] for area in snapshot["areas"] for device in area["devices"]))
        self.assertTrue(any(entity["entity_id"] == "sensor.living_room_temperature" for entity in snapshot["entities"]))
        self.assertIn("enrichment_error", snapshot)

    def test_states_failure_still_fails_refresh(self):
        manager = EnvironmentManager(self.config, self.log, self.store)

        def raise_states_404(url, token, timeout_seconds):
            raise HTTPError(url, 404, "Not Found", hdrs=None, fp=None)

        with patch.object(manager, "_request_json", side_effect=raise_states_404):
            snapshot = manager.refresh_snapshot()

        self.assertEqual(snapshot["status"], "No data")
        self.assertTrue(snapshot["stale"])
        self.assertIn("404", snapshot["last_refresh_error"])
        self.assertEqual(snapshot["summary"]["supported_entities"], 0)


if __name__ == "__main__":
    unittest.main()
