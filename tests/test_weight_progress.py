import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from flask import Flask, render_template

from modules.power_adapters.base import PowerAdapterResult
from modules.weight_progress import WeightMeasurement, WeightProgressService


ROOT = Path(__file__).resolve().parents[1]


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


def build_config(weight_progress=None, router_reboot=None):
    return DummyConfig(
        {
            "router_reboot": router_reboot
            or {
                "home_assistant_url": "http://homeassistant.local:8123",
                "home_assistant_token": "super-secret-token",
            },
            "weight_progress": weight_progress
            or {
                "enabled": True,
                "database": "data/weight_progress.db",
                "display_unit": "lb",
                "starting_weight": None,
                "goal_weight": 220,
                "entities": {
                    "weight": "sensor.withings_weight",
                    "body_fat": "sensor.withings_fat_ratio",
                    "withings_goal": "sensor.withings_weight_goal",
                    "fat_mass": "sensor.withings_fat_mass",
                    "fat_free_mass": "sensor.withings_fat_free_mass",
                    "muscle_mass": "sensor.withings_muscle_mass",
                    "bone_mass": "sensor.withings_bone_mass",
                    "heart_rate": "sensor.withings_heart_pulse",
                    "battery": "sensor.withings_battery",
                },
            },
        }
    )


class WeightProgressServiceTests(unittest.TestCase):
    def _service(self, config=None):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        cfg = config or build_config()
        cfg.data["weight_progress"]["database"] = str(Path(temp_dir.name) / "weight_progress.db")
        service = WeightProgressService(cfg, MagicMock())
        service.initialize()
        return service

    def _measurement(self, timestamp, weight_kg, body_fat=None):
        return WeightMeasurement.create(
            captured_at=timestamp,
            source_timestamp=timestamp,
            source_entity="sensor.withings_weight",
            weight_kg=weight_kg,
            body_fat_percent=body_fat,
            fat_mass_kg=None,
            fat_free_mass_kg=None,
            muscle_mass_kg=None,
            bone_mass_kg=None,
            heart_rate_bpm=None,
            scale_battery=None,
            reading_hash=f"hash-{timestamp}",
            metadata={"timestamp": timestamp},
        )

    def test_entities_are_read_through_existing_home_assistant_adapter(self):
        service = self._service()
        results = {
            "sensor.withings_weight": PowerAdapterResult(
                status="PASS",
                message="ok",
                metadata={
                    "state": "100.0",
                    "last_updated": "2026-07-18T08:00:00",
                    "attributes": {"unit_of_measurement": "kg"},
                },
            ),
            "sensor.withings_fat_ratio": PowerAdapterResult(
                status="PASS",
                message="ok",
                metadata={
                    "state": "17.5",
                    "last_updated": "2026-07-18T08:00:00",
                    "attributes": {"unit_of_measurement": "%"},
                },
            ),
            "sensor.withings_weight_goal": PowerAdapterResult(
                status="PASS",
                message="ok",
                metadata={
                    "state": "95.0",
                    "last_updated": "2026-07-18T08:00:00",
                    "attributes": {"unit_of_measurement": "kg"},
                },
            ),
            "sensor.withings_fat_mass": PowerAdapterResult(
                status="PASS",
                message="ok",
                metadata={
                    "state": "18.0",
                    "last_updated": "2026-07-18T08:00:00",
                    "attributes": {"unit_of_measurement": "kg"},
                },
            ),
            "sensor.withings_fat_free_mass": PowerAdapterResult(
                status="PASS",
                message="ok",
                metadata={
                    "state": "82.0",
                    "last_updated": "2026-07-18T08:00:00",
                    "attributes": {"unit_of_measurement": "kg"},
                },
            ),
            "sensor.withings_muscle_mass": PowerAdapterResult(
                status="PASS",
                message="ok",
                metadata={
                    "state": "60.0",
                    "last_updated": "2026-07-18T08:00:00",
                    "attributes": {"unit_of_measurement": "kg"},
                },
            ),
            "sensor.withings_bone_mass": PowerAdapterResult(
                status="PASS",
                message="ok",
                metadata={
                    "state": "3.2",
                    "last_updated": "2026-07-18T08:00:00",
                    "attributes": {"unit_of_measurement": "kg"},
                },
            ),
            "sensor.withings_heart_pulse": PowerAdapterResult(
                status="PASS",
                message="ok",
                metadata={
                    "state": "58",
                    "last_updated": "2026-07-18T08:00:00",
                    "attributes": {"unit_of_measurement": "bpm"},
                },
            ),
            "sensor.withings_battery": PowerAdapterResult(
                status="PASS",
                message="ok",
                metadata={
                    "state": "low",
                    "last_updated": "2026-07-18T08:00:00",
                    "attributes": {},
                },
            ),
        }

        def fake_get_entity_state(entity_id, timeout_seconds=10):
            return results[entity_id]

        with patch("modules.weight_progress.service.HomeAssistantAdapter.get_entity_state", side_effect=fake_get_entity_state) as get_state:
            measurement = service.capture_current_measurement()

        self.assertEqual(get_state.call_count, 9)
        self.assertEqual(measurement.weight_kg, 100.0)
        self.assertEqual(measurement.body_fat_percent, 17.5)
        self.assertEqual(measurement.withings_goal_kg, 95.0)
        self.assertEqual(measurement.fat_mass_kg, 18.0)
        self.assertEqual(measurement.scale_battery, "low")

    def test_kilograms_convert_to_pounds(self):
        service = self._service()
        service.database.insert_measurement(self._measurement("2026-07-01 08:00:00", 100.0, 17.5))

        payload = service.view_model(include_live=False)

        self.assertEqual(payload["summary_cards"][0]["value"], "220.5 lb")
        self.assertEqual(payload["summary_cards"][5]["value"], "17.5%")

    def test_unknown_and_unavailable_states_fail_safely(self):
        service = self._service()
        with patch(
            "modules.weight_progress.service.HomeAssistantAdapter.get_entity_state",
            return_value=PowerAdapterResult(status="FAIL", message="Home Assistant unreachable.", metadata={}),
        ):
            measurement = service.capture_current_measurement()
            payload = service.view_model(include_live=False)

        self.assertIsNone(measurement)
        self.assertEqual(payload["summary_cards"][0]["value"], "--")
        self.assertIn("No weight history", payload["chart_message"])

    def test_duplicate_measurements_are_not_inserted(self):
        service = self._service()
        measurement = self._measurement("2026-07-01 08:00:00", 100.0, 17.5)
        inserted_first = service.database.insert_measurement(measurement)
        inserted_second = service.database.insert_measurement(measurement)

        self.assertTrue(inserted_first)
        self.assertFalse(inserted_second)
        self.assertEqual(service.database.count_measurements(), 1)

    def test_newer_measurement_is_inserted(self):
        service = self._service()
        first = self._measurement("2026-07-01 08:00:00", 100.0, 17.5)
        second = self._measurement("2026-07-02 08:00:00", 99.0, 17.2)
        second.reading_hash = "hash-2"
        service.database.insert_measurement(first)
        service.database.insert_measurement(second)

        self.assertEqual(service.database.count_measurements(), 2)

    def test_starting_weight_is_read_from_configuration_when_configured(self):
        config = build_config(
            weight_progress={
                "enabled": True,
                "database": "data/weight_progress.db",
                "display_unit": "kg",
                "starting_weight": 212.0,
                "goal_weight": 220.0,
                "entities": build_config().data["weight_progress"]["entities"],
            }
        )
        service = self._service(config)
        service.database.insert_measurement(self._measurement("2026-07-01 08:00:00", 205.0, 16.2))

        payload = service.view_model(include_live=False)

        self.assertEqual(payload["summary_cards"][2]["value"], "212.0 kg")
        self.assertEqual(payload["summary_cards"][2]["note"], "Configured starting point")

    def test_earliest_stored_measurement_is_used_when_starting_weight_is_absent(self):
        service = self._service()
        service.database.insert_measurement(self._measurement("2026-07-01 08:00:00", 100.0, 18.0))
        service.database.insert_measurement(self._measurement("2026-07-08 08:00:00", 98.0, 17.0))

        payload = service.view_model(include_live=False)

        self.assertEqual(payload["summary_cards"][2]["value"], "220.5 lb")
        self.assertEqual(payload["summary_cards"][2]["note"], "Since HomePulse tracking began")

    def test_latest_weigh_in_timestamp_is_formatted_for_display(self):
        service = self._service()
        measurement = self._measurement("2026-07-19 07:35:33.270181", 100.0, 17.5)
        service.database.insert_measurement(measurement)

        payload = service.view_model(include_live=False)

        self.assertEqual(payload["latest_weigh_in_label"], "Jul 19, 2026 at 7:35 AM")
        self.assertEqual(payload["latest_measurement"]["source_timestamp"], "2026-07-19 07:35:33.270181")

    def test_waiting_for_first_reading_note_is_used_without_history(self):
        service = self._service()

        payload = service.view_model(include_live=False)

        self.assertEqual(payload["summary_cards"][2]["note"], "Waiting for the first reading")

    def test_goal_weight_is_read_from_configuration(self):
        config = build_config(
            weight_progress={
                "enabled": True,
                "database": "data/weight_progress.db",
                "display_unit": "kg",
                "starting_weight": None,
                "goal_weight": 200.0,
                "entities": build_config().data["weight_progress"]["entities"],
            }
        )
        service = self._service(config)
        service.database.insert_measurement(self._measurement("2026-07-01 08:00:00", 210.0, 18.5))

        payload = service.view_model(include_live=False)

        self.assertEqual(payload["summary_cards"][3]["value"], "200.0 kg")

    def test_withings_goal_is_saved_and_displayed_separately(self):
        service = self._service()
        with patch("modules.weight_progress.service.HomeAssistantAdapter.get_entity_state") as get_state:
            get_state.side_effect = [
                PowerAdapterResult(
                    status="PASS",
                    message="ok",
                    metadata={
                        "state": "100.0",
                        "last_updated": "2026-07-18T08:00:00",
                        "attributes": {"unit_of_measurement": "kg"},
                    },
                ),
                PowerAdapterResult(
                    status="PASS",
                    message="ok",
                    metadata={
                        "state": "17.5",
                        "last_updated": "2026-07-18T08:00:00",
                        "attributes": {"unit_of_measurement": "%"},
                    },
                ),
                PowerAdapterResult(
                    status="PASS",
                    message="ok",
                    metadata={
                        "state": "95.0",
                        "last_updated": "2026-07-18T08:00:00",
                        "attributes": {"unit_of_measurement": "kg"},
                    },
                ),
                PowerAdapterResult(
                    status="PASS",
                    message="ok",
                    metadata={
                        "state": "18.0",
                        "last_updated": "2026-07-18T08:00:00",
                        "attributes": {"unit_of_measurement": "kg"},
                    },
                ),
                PowerAdapterResult(
                    status="PASS",
                    message="ok",
                    metadata={
                        "state": "82.0",
                        "last_updated": "2026-07-18T08:00:00",
                        "attributes": {"unit_of_measurement": "kg"},
                    },
                ),
                PowerAdapterResult(
                    status="PASS",
                    message="ok",
                    metadata={
                        "state": "60.0",
                        "last_updated": "2026-07-18T08:00:00",
                        "attributes": {"unit_of_measurement": "kg"},
                    },
                ),
                PowerAdapterResult(
                    status="PASS",
                    message="ok",
                    metadata={
                        "state": "3.2",
                        "last_updated": "2026-07-18T08:00:00",
                        "attributes": {"unit_of_measurement": "kg"},
                    },
                ),
                PowerAdapterResult(
                    status="PASS",
                    message="ok",
                    metadata={
                        "state": "58",
                        "last_updated": "2026-07-18T08:00:00",
                        "attributes": {"unit_of_measurement": "bpm"},
                    },
                ),
                PowerAdapterResult(
                    status="PASS",
                    message="ok",
                    metadata={
                        "state": "low",
                        "last_updated": "2026-07-18T08:00:00",
                        "attributes": {},
                    },
                ),
            ]

            measurement = service.capture_current_measurement()
            service.database.insert_measurement(measurement)
            payload = service.view_model(include_live=False)

        self.assertEqual(payload["summary_cards"][3]["value"], "220.0 lb")
        self.assertEqual(payload["withings_goal"], "209.4 lb")
        self.assertEqual(payload["latest_measurement"]["withings_goal_kg"], 95.0)
        self.assertEqual(payload["summary_cards"][4]["value"], "0.5 lb")

    def test_missing_withings_goal_does_not_crash(self):
        service = self._service()
        results = {
            "sensor.withings_weight": PowerAdapterResult(
                status="PASS",
                message="ok",
                metadata={
                    "state": "100.0",
                    "last_updated": "2026-07-18T08:00:00",
                    "attributes": {"unit_of_measurement": "kg"},
                },
            ),
            "sensor.withings_fat_ratio": PowerAdapterResult(
                status="PASS",
                message="ok",
                metadata={
                    "state": "17.5",
                    "last_updated": "2026-07-18T08:00:00",
                    "attributes": {"unit_of_measurement": "%"},
                },
            ),
            "sensor.withings_weight_goal": PowerAdapterResult(
                status="WARN",
                message="unavailable",
                metadata={"state": "unavailable"},
            ),
            "sensor.withings_fat_mass": PowerAdapterResult(
                status="PASS",
                message="ok",
                metadata={
                    "state": "18.0",
                    "last_updated": "2026-07-18T08:00:00",
                    "attributes": {"unit_of_measurement": "kg"},
                },
            ),
            "sensor.withings_fat_free_mass": PowerAdapterResult(
                status="PASS",
                message="ok",
                metadata={
                    "state": "82.0",
                    "last_updated": "2026-07-18T08:00:00",
                    "attributes": {"unit_of_measurement": "kg"},
                },
            ),
            "sensor.withings_muscle_mass": PowerAdapterResult(
                status="PASS",
                message="ok",
                metadata={
                    "state": "60.0",
                    "last_updated": "2026-07-18T08:00:00",
                    "attributes": {"unit_of_measurement": "kg"},
                },
            ),
            "sensor.withings_bone_mass": PowerAdapterResult(
                status="PASS",
                message="ok",
                metadata={
                    "state": "3.2",
                    "last_updated": "2026-07-18T08:00:00",
                    "attributes": {"unit_of_measurement": "kg"},
                },
            ),
            "sensor.withings_heart_pulse": PowerAdapterResult(
                status="PASS",
                message="ok",
                metadata={
                    "state": "58",
                    "last_updated": "2026-07-18T08:00:00",
                    "attributes": {"unit_of_measurement": "bpm"},
                },
            ),
            "sensor.withings_battery": PowerAdapterResult(
                status="PASS",
                message="ok",
                metadata={
                    "state": "low",
                    "last_updated": "2026-07-18T08:00:00",
                    "attributes": {},
                },
            ),
        }

        with patch("modules.weight_progress.service.HomeAssistantAdapter.get_entity_state", side_effect=lambda entity_id, timeout_seconds=10: results[entity_id]):
            measurement = service.capture_current_measurement()
            payload = service.view_model(include_live=False)

        self.assertIsNotNone(measurement)
        self.assertEqual(payload["withings_goal"], "--")

    def test_homepulse_goal_remains_authoritative_when_withings_goal_differs(self):
        config = build_config(
            weight_progress={
                "enabled": True,
                "database": "data/weight_progress.db",
                "display_unit": "lb",
                "starting_weight": None,
                "goal_weight": 220.0,
                "entities": build_config().data["weight_progress"]["entities"],
            }
        )
        service = self._service(config)
        service.database.insert_measurement(
            WeightMeasurement.create(
                captured_at="2026-07-01 08:00:00",
                source_timestamp="2026-07-01 08:00:00",
                source_entity="sensor.withings_weight",
                weight_kg=100.0,
                body_fat_percent=17.5,
                fat_mass_kg=18.0,
                fat_free_mass_kg=82.0,
                muscle_mass_kg=60.0,
                bone_mass_kg=3.2,
                heart_rate_bpm=58,
                scale_battery="low",
                withings_goal_kg=95.0,
                reading_hash="hash-goal",
                metadata={"timestamp": "2026-07-01 08:00:00"},
            )
        )

        payload = service.view_model(include_live=False)

        self.assertEqual(payload["summary_cards"][3]["value"], "220.0 lb")
        self.assertEqual(payload["withings_goal"], "209.4 lb")

    def test_total_lost_and_remaining_to_goal_are_calculated_correctly(self):
        config = build_config(
            weight_progress={
                "enabled": True,
                "database": "data/weight_progress.db",
                "display_unit": "kg",
                "starting_weight": 210.0,
                "goal_weight": 180.0,
                "entities": build_config().data["weight_progress"]["entities"],
            }
        )
        service = self._service(config)
        service.database.insert_measurement(self._measurement("2026-07-01 08:00:00", 200.0, 18.5))

        payload = service.view_model(include_live=False)

        self.assertEqual(payload["summary_cards"][1]["value"], "10.0 kg")
        self.assertEqual(payload["summary_cards"][4]["value"], "20.0 kg")

    def test_seven_day_average_is_calculated_correctly(self):
        config = build_config(
            weight_progress={
                "enabled": True,
                "database": "data/weight_progress.db",
                "display_unit": "kg",
                "starting_weight": None,
                "goal_weight": 220,
                "entities": build_config().data["weight_progress"]["entities"],
            }
        )
        service = self._service(config)
        service.database.insert_measurement(self._measurement("2026-07-01 08:00:00", 200.0, 18.5))
        service.database.insert_measurement(self._measurement("2026-07-04 08:00:00", 198.0, 18.2))
        service.database.insert_measurement(self._measurement("2026-07-09 08:00:00", 196.0, 18.0))

        payload = service.view_model(include_live=False, range_key="1m")

        self.assertEqual(payload["chart"]["points"][-1]["rolling_average"], 197.0)


class WeightProgressTemplateTests(unittest.TestCase):
    def _service_payload(self, measurement=None):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        cfg = build_config()
        cfg.data["weight_progress"]["database"] = str(Path(temp_dir.name) / "weight_progress.db")
        service = WeightProgressService(cfg, MagicMock())
        service.initialize()
        if measurement is not None:
            service.database.insert_measurement(measurement)
        return service.view_model(include_live=False)

    def _render(self, payload):
        app = Flask(__name__, template_folder=str(ROOT / "templates"))
        app.jinja_env.globals["app_name"] = "HomePulse"
        for endpoint in (
            "home",
            "home_center",
            "environment_center",
            "internet",
            "solar",
            "vehicle_center",
            "weight_progress",
            "weather",
            "lighting",
            "garden",
            "speed_test_center",
            "email_center",
            "settings",
            "lab",
            "logs",
            "about",
        ):
            app.add_url_rule(f"/{endpoint}", endpoint, lambda: "")

        with app.test_request_context("/weight-progress"):
            return render_template("weight_progress.html", weight_progress=payload)

    def test_page_renders_with_current_reading(self):
        measurement = WeightMeasurement.create(
            captured_at="2026-07-19 07:35:33.270181",
            source_timestamp="2026-07-19 07:35:33.270181",
            source_entity="sensor.withings_weight",
            weight_kg=100.0,
            body_fat_percent=17.5,
            fat_mass_kg=18.0,
            fat_free_mass_kg=82.0,
            muscle_mass_kg=60.0,
            bone_mass_kg=3.2,
            heart_rate_bpm=58,
            scale_battery="low",
            withings_goal_kg=95.0,
            reading_hash="hash-1",
            metadata={"timestamp": "2026-07-01 08:00:00"},
        )
        payload = self._service_payload(measurement)
        html = self._render(payload)

        self.assertIn("Weight Progress", html)
        self.assertIn("220.5 lb", html)
        self.assertIn("Withings Goal", html)
        self.assertIn("Current Weight", html)
        self.assertIn("Jul 19, 2026 at 7:35 AM", html)
        self.assertIn("Latest Weigh-In", html)

    def test_page_renders_empty_state_without_history(self):
        payload = self._service_payload()
        html = self._render(payload)

        self.assertIn("No weight history has been collected yet.", html)
        self.assertIn("No weight history stored yet. The first successful weigh-in will appear here.", html)

    def test_no_tokens_appear_in_rendered_output(self):
        payload = self._service_payload()
        html = self._render(payload)

        self.assertNotIn("super-secret-token", html)
        self.assertNotIn("home_assistant_token", html)


if __name__ == "__main__":
    unittest.main()
