import json
from io import BytesIO
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from flask import Flask, render_template
from openpyxl import Workbook
from openpyxl.utils.datetime import to_excel
from werkzeug.datastructures import FileStorage

from modules.power_adapters.base import PowerAdapterResult
from modules.weight_progress import WeightMeasurement, WeightProgressService


ROOT = Path(__file__).resolve().parents[1]
WEIGHT_HISTORY_HEADERS = [
    "Date",
    "Weight (lb)",
    "Fat mass (lb)",
    "Bone mass (lb)",
    "Muscle mass (lb)",
    "Hydration (lb)",
    "Comments",
]


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
                    "hydration": "sensor.withings_hydration",
                    "visceral_fat_index": "sensor.withings_visceral_fat_index",
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
            "sensor.withings_hydration": PowerAdapterResult(
                status="PASS",
                message="ok",
                metadata={
                    "state": "76.5",
                    "last_updated": "2026-07-18T08:00:00",
                    "attributes": {"unit_of_measurement": "kg"},
                },
            ),
            "sensor.withings_visceral_fat_index": PowerAdapterResult(
                status="PASS",
                message="ok",
                metadata={
                    "state": "8.4",
                    "last_updated": "2026-07-18T08:00:00",
                    "attributes": {"unit_of_measurement": "Index"},
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

        self.assertEqual(get_state.call_count, 11)
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
        self.assertEqual(payload["summary_cards"][6]["value"], "17.5%")

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
        self.assertEqual(payload["summary_cards"][2]["note"], "Manual")

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
                        "state": "76.5",
                        "last_updated": "2026-07-18T08:00:00",
                        "attributes": {"unit_of_measurement": "kg"},
                    },
                ),
                PowerAdapterResult(
                    status="PASS",
                    message="ok",
                    metadata={
                        "state": "8.4",
                        "last_updated": "2026-07-18T08:00:00",
                        "attributes": {"unit_of_measurement": "Index"},
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
            "sensor.withings_hydration": PowerAdapterResult(
                status="PASS",
                message="ok",
                metadata={
                    "state": "76.5",
                    "last_updated": "2026-07-18T08:00:00",
                    "attributes": {"unit_of_measurement": "kg"},
                },
            ),
            "sensor.withings_visceral_fat_index": PowerAdapterResult(
                status="PASS",
                message="ok",
                metadata={
                    "state": "8.4",
                    "last_updated": "2026-07-18T08:00:00",
                    "attributes": {"unit_of_measurement": "Index"},
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

    def test_body_composition_trends_include_all_points_and_current_journey_filter(self):
        config = build_config(
            weight_progress={
                "enabled": True,
                "database": "data/weight_progress.db",
                "display_unit": "kg",
                "starting_weight": None,
                "journey_start_date": "2026-05-04",
                "goal_weight": 220.0,
                "entities": build_config().data["weight_progress"]["entities"],
            }
        )
        service = self._service(config)
        service.database.insert_measurement(
            WeightMeasurement.create(
                captured_at="2026-05-01 08:00:00",
                source_timestamp="2026-05-01 08:00:00",
                source_entity="sensor.withings_weight",
                weight_kg=100.0,
                body_fat_percent=20.0,
                fat_mass_kg=20.0,
                fat_free_mass_kg=80.0,
                muscle_mass_kg=60.0,
                bone_mass_kg=3.2,
                hydration_kg=70.0,
                visceral_fat_index=9.2,
                heart_rate_bpm=58,
                scale_battery="low",
                reading_hash="hash-old",
                metadata={"timestamp": "2026-05-01 08:00:00"},
            )
        )
        service.database.insert_measurement(
            WeightMeasurement.create(
                captured_at="2026-05-05 08:00:00",
                source_timestamp="2026-05-05 08:00:00",
                source_entity="sensor.withings_weight",
                weight_kg=99.0,
                body_fat_percent=18.0,
                fat_mass_kg=18.0,
                fat_free_mass_kg=81.0,
                muscle_mass_kg=60.5,
                bone_mass_kg=3.1,
                hydration_kg=68.0,
                visceral_fat_index=8.4,
                heart_rate_bpm=57,
                scale_battery="full",
                reading_hash="hash-new",
                metadata={"timestamp": "2026-05-05 08:00:00"},
            )
        )

        payload = service.view_model(include_live=False)
        trends = payload["composition_trends"]

        self.assertEqual(trends["selected_metric_summary"]["trend_points"], 1)
        self.assertEqual(trends["selected_metric_summary"]["summary_cards"][3]["value"], "May 5, 2026")
        self.assertEqual(trends["all_points"][0]["hydration"], 70.0)
        self.assertEqual(trends["all_points"][1]["visceral_fat"], 8.4)
        self.assertEqual(trends["points"][0]["visceral_fat"], 8.4)

    def test_body_fat_percent_is_derived_from_weight_and_fat_mass_when_missing(self):
        service = self._service()
        service.database.insert_measurement(
            WeightMeasurement.create(
                captured_at="2026-07-10 08:00:00",
                source_timestamp="2026-07-10 08:00:00",
                source_entity="sensor.withings_weight",
                weight_kg=100.0,
                body_fat_percent=None,
                fat_mass_kg=20.0,
                fat_free_mass_kg=80.0,
                muscle_mass_kg=60.0,
                bone_mass_kg=3.2,
                hydration_kg=70.0,
                reading_hash="hash-derived-body-fat",
                metadata={"timestamp": "2026-07-10 08:00:00"},
            )
        )

        payload = service.view_model(include_live=False)

        self.assertEqual(payload["summary_cards"][6]["value"], "20.0%")
        self.assertEqual(payload["composition_trends"]["points"][0]["body_fat"], 20.0)


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
        self.assertIn("Current Journey baseline", html)
        self.assertIn("Body Composition Trends", html)
        self.assertIn("Manage Weight History", html)
        self.assertNotIn("Import Weight History", html)
        self.assertLess(html.index("Current Weight"), html.index("Weight Trend"))
        self.assertLess(html.index("Weight Trend"), html.index("Body Composition Trends"))
        self.assertLess(html.index("Body Composition Trends"), html.index("Manage Weight History"))

    def test_page_renders_empty_state_without_history(self):
        payload = self._service_payload()
        html = self._render(payload)

        self.assertIn("No weight history has been collected yet.", html)
        self.assertIn("No weight history stored yet. The first successful weigh-in will appear here.", html)
        self.assertIn("No body composition history has been collected yet.", html)
        self.assertNotIn("Import Weight History", html)
        self.assertIn("Manage Weight History", html)

    def test_no_tokens_appear_in_rendered_output(self):
        payload = self._service_payload()
        html = self._render(payload)

        self.assertNotIn("super-secret-token", html)
        self.assertNotIn("home_assistant_token", html)


class WeightProgressSettingsTests(unittest.TestCase):
    def _render(self):
        app = Flask(__name__, template_folder=str(ROOT / "templates"))
        app.jinja_env.globals["app_name"] = "HomePulse"
        app.jinja_env.globals["render_test_button"] = lambda name, endpoint: f"<button>{name}</button>"

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
            "test_home_assistant",
            "test_home_assistant_power_cycle",
            "test_smtp",
            "test_ping",
            "test_speed",
            "test_full_diagnostics",
        ):
            app.add_url_rule(f"/{endpoint}", endpoint, lambda: "")

        context = dict(
            config=build_config(),
            schedule_mode="every_1_hour",
            schedule_label="Every hour",
            speedtest_times=[],
            router_reboot={
                "home_assistant_url": "http://homeassistant.local:8123",
                "recovery_entity_id": "switch.office_router_plug",
                "matter_entity_id": "switch.office_router_plug",
                "router_recovery_live_enabled": False,
            },
            router_recovery_config={
                "home_assistant_url": "http://homeassistant.local:8123",
                "recovery_entity_id": "switch.office_router_plug",
                "matter_entity_id": "switch.office_router_plug",
            },
            email={"notifications": {}},
            energy={"home_assistant_entities": {}, "alerts": {}},
            vehicle={"entities": {}},
            solar={"entities": {}},
            weather={},
            lighting={},
            garden={},
            diagnostic_result=None,
            router_recovery_status={
                "mode_label": "DRY RUN",
                "recovery_method": "home_assistant",
                "home_assistant_url": "http://homeassistant.local:8123",
                "recovery_entity": "switch.office_router_plug",
                "current_state": "ON",
                "cooldown_status": "READY",
                "last_attempt": "None",
                "last_result": "None",
            },
            error=None,
            saved=False,
            now=None,
            weight_progress=build_config().data["weight_progress"],
        )

        with app.test_request_context("/settings#weight-progress-history-maintenance"):
            return render_template("settings.html", **context)

    def test_settings_contains_collapsed_history_import_section(self):
        html = self._render()

        self.assertIn("History Import &amp; Maintenance", html)
        self.assertIn('id="weight-progress-history-maintenance" class="advanced-settings"', html)
        self.assertNotIn('id="weight-progress-history-maintenance" class="advanced-settings" open', html)
        self.assertIn("Preview Import", html)
        self.assertIn("weight_progress.js", html)


def _build_workbook_bytes(rows, headers=None, sheet_name="weight"):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = sheet_name
    sheet.append(headers or WEIGHT_HISTORY_HEADERS)
    normalized_headers = [str(header).strip().lower() for header in (headers or WEIGHT_HISTORY_HEADERS)]
    for row in rows:
        if isinstance(row, dict):
            sheet.append([row.get(header) if header in row else row.get(header.strip().lower()) for header in normalized_headers])
        else:
            sheet.append(list(row))
    payload = BytesIO()
    workbook.save(payload)
    payload.seek(0)
    return payload.getvalue()


def _upload_file(content, filename="Weight History.xlsx"):
    return FileStorage(
        stream=BytesIO(content),
        filename=filename,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _sample_import_rows():
    return [
        {
            "date": datetime(2026, 7, 19, 7, 34, 0),
            "weight (lb)": 283.1,
            "fat mass (lb)": 102.3,
            "bone mass (lb)": 8.9,
            "muscle mass (lb)": 171.9,
            "hydration (lb)": 185.2,
            "comments": "latest reading",
        },
        {
            "date": datetime(2026, 6, 1, 7, 15, 0),
            "weight (lb)": 296.4,
            "fat mass (lb)": 110.0,
            "bone mass (lb)": 9.0,
            "muscle mass (lb)": 176.0,
            "hydration (lb)": 189.0,
            "comments": "",
        },
        {
            "date": datetime(2026, 5, 4, 18, 20, 0),
            "weight (lb)": 308.9,
            "fat mass (lb)": 119.0,
            "bone mass (lb)": 9.1,
            "muscle mass (lb)": 179.5,
            "hydration (lb)": 191.2,
            "comments": "same day second reading",
        },
        {
            "date": datetime(2026, 5, 4, 9, 5, 16),
            "weight (lb)": 309.7,
            "fat mass (lb)": 119.9,
            "bone mass (lb)": 9.1,
            "muscle mass (lb)": 180.0,
            "hydration (lb)": 192.0,
            "comments": "journey baseline",
        },
        {
            "date": datetime(2023, 12, 12, 12, 0, 0),
            "weight (lb)": 360.0,
            "fat mass (lb)": 144.0,
            "bone mass (lb)": 10.0,
            "muscle mass (lb)": 185.0,
            "hydration (lb)": 198.0,
            "comments": "earliest reading",
        },
    ]


def _sample_import_workbook(headers=None):
    return _build_workbook_bytes(_sample_import_rows(), headers=headers)


class WeightProgressImportTests(unittest.TestCase):
    def _service(self, config=None):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        cfg = config or build_config(
            weight_progress={
                "enabled": True,
                "database": "data/weight_progress.db",
                "display_unit": "lb",
                "starting_weight": None,
                "journey_start_date": "2026-05-04",
                "goal_weight": 220,
                "entities": build_config().data["weight_progress"]["entities"],
            }
        )
        cfg.data["weight_progress"]["database"] = str(Path(temp_dir.name) / "weight_progress.db")
        service = WeightProgressService(cfg, MagicMock())
        service.initialize()
        return service

    def test_preview_identifies_journey_baseline_and_counts(self):
        service = self._service()
        preview = service.preview_weight_history_import(_upload_file(_sample_import_workbook()))

        self.assertEqual(preview["filename"], "Weight History.xlsx")
        self.assertEqual(preview["worksheet"], "weight")
        self.assertEqual(preview["rows_found"], 5)
        self.assertEqual(preview["valid_measurements"], 5)
        self.assertEqual(preview["invalid_rows"], 0)
        self.assertEqual(preview["measurements_before_journey_start"], 1)
        self.assertEqual(preview["measurements_on_or_after_journey_start"], 4)
        self.assertEqual(preview["proposed_journey_date"], "May 4, 2026")
        self.assertEqual(preview["proposed_journey_baseline"], "May 4, 2026 at 9:05 AM")
        self.assertEqual(preview["proposed_starting_weight"], "309.7 lb")

    def test_preview_does_not_write_database_and_temp_file_is_removed_on_cancel(self):
        service = self._service()
        preview = service.preview_weight_history_import(_upload_file(_sample_import_workbook()))
        token = preview["preview_token"]
        temp_path = Path(service._pending_imports[token]["path"])

        self.assertEqual(service.database.count_measurements(), 0)
        self.assertTrue(temp_path.exists())

        service.cancel_weight_history_import(token)

        self.assertFalse(temp_path.exists())
        self.assertEqual(service.database.count_measurements(), 0)

    def test_required_header_validation_rejects_missing_weight_column(self):
        service = self._service()
        workbook = _build_workbook_bytes(_sample_import_rows(), headers=[
            "Date",
            "Fat mass (lb)",
            "Bone mass (lb)",
            "Muscle mass (lb)",
            "Hydration (lb)",
            "Comments",
        ])

        with self.assertRaises(ValueError):
            service.preview_weight_history_import(_upload_file(workbook))

    def test_case_insensitive_headers_and_excel_date_serials_are_supported(self):
        service = self._service()
        headers = [" date ", " weight (lb) ", " fat mass (lb) ", " bone mass (lb) ", " muscle mass (lb) ", " hydration (lb) ", " comments "]
        rows = [
            {
                "date": to_excel(datetime(2026, 5, 4, 9, 5, 16)),
                "weight (lb)": 309.7,
                "fat mass (lb)": 119.9,
                "bone mass (lb)": 9.1,
                "muscle mass (lb)": 180.0,
                "hydration (lb)": 192.0,
                "comments": "serial date",
            }
        ]
        preview = service.preview_weight_history_import(_upload_file(_build_workbook_bytes(rows, headers=headers)))
        self.assertEqual(preview["valid_measurements"], 1)
        self.assertEqual(preview["proposed_journey_baseline"], "May 4, 2026 at 9:05 AM")

    def test_pounds_and_body_fat_values_are_preserved(self):
        service = self._service()
        preview = service.preview_weight_history_import(_upload_file(_sample_import_workbook()))
        result = service.confirm_weight_history_import(preview["preview_token"])

        self.assertTrue(result["ok"])
        self.assertEqual(result["inserted"], 5)
        latest = service.database.latest_measurement()
        payload = service.view_model(include_live=False)
        self.assertAlmostEqual(latest.weight_kg * 2.2046226218, 283.1, places=1)
        self.assertAlmostEqual(latest.hydration_kg * 2.2046226218, 185.2, places=1)
        self.assertAlmostEqual(latest.body_fat_percent, 36.1, places=1)
        self.assertEqual(latest.comments, "latest reading")
        self.assertEqual(payload["summary_cards"][6]["value"], "36.1%")

    def test_invalid_weight_rows_are_rejected_safely(self):
        service = self._service()
        rows = _sample_import_rows()
        rows[0] = {
            "date": datetime(2026, 7, 19, 7, 34, 0),
            "weight (lb)": "not-a-number",
            "fat mass (lb)": 102.3,
            "bone mass (lb)": 8.9,
            "muscle mass (lb)": 171.9,
            "hydration (lb)": 185.2,
            "comments": "invalid",
        }
        preview = service.preview_weight_history_import(_upload_file(_build_workbook_bytes(rows)))

        self.assertEqual(preview["invalid_rows"], 1)
        self.assertEqual(preview["valid_measurements"], 4)

    def test_direct_body_fat_value_is_preserved_when_present(self):
        service = self._service()
        headers = ["Date", "Weight (lb)", "Body Fat (%)", "Fat mass (lb)", "Bone mass (lb)", "Muscle mass (lb)", "Hydration (lb)", "Comments"]
        rows = [
            {
                "date": datetime(2026, 5, 4, 9, 5, 16),
                "weight (lb)": 309.7,
                "body fat (%)": 12.3,
                "fat mass (lb)": 119.9,
                "bone mass (lb)": 9.1,
                "muscle mass (lb)": 180.0,
                "hydration (lb)": 192.0,
                "comments": "direct body fat",
            }
        ]
        preview = service.preview_weight_history_import(_upload_file(_build_workbook_bytes(rows, headers=headers)))
        service.confirm_weight_history_import(preview["preview_token"])

        latest = service.database.latest_measurement()
        self.assertEqual(round(latest.body_fat_percent, 1), 12.3)

    def test_current_journey_and_all_history_ranges_are_filtered_correctly(self):
        service = self._service()
        preview = service.preview_weight_history_import(_upload_file(_sample_import_workbook()))
        service.confirm_weight_history_import(preview["preview_token"])

        current_journey = service.view_model(include_live=False, range_key="current_journey")
        all_history = service.view_model(include_live=False, range_key="all")

        self.assertEqual(current_journey["summary_cards"][2]["note"], "May 4, 2026")
        self.assertEqual(current_journey["summary_cards"][5]["value"], "29.7%")
        self.assertFalse(current_journey["chart"]["points"][0]["timestamp"].startswith("2023-12-12"))
        self.assertTrue(all_history["chart"]["points"][0]["timestamp"].startswith("2023-12-12"))

    def test_exact_reimport_creates_no_duplicates(self):
        service = self._service()
        preview = service.preview_weight_history_import(_upload_file(_sample_import_workbook()))
        service.confirm_weight_history_import(preview["preview_token"])
        first_count = service.database.count_measurements()

        second_preview = service.preview_weight_history_import(_upload_file(_sample_import_workbook()))
        second_result = service.confirm_weight_history_import(second_preview["preview_token"])

        self.assertEqual(first_count, 5)
        self.assertEqual(second_result["inserted"], 0)
        self.assertEqual(second_result["exact_duplicates"], 5)
        self.assertEqual(service.database.count_measurements(), 5)

    def test_likely_overlap_with_existing_live_reading_is_skipped(self):
        service = self._service()
        existing = WeightMeasurement.create(
            captured_at="2026-07-19 07:34:30.000000",
            source_timestamp="2026-07-19 07:34:30.000000",
            source_entity="sensor.withings_weight",
            weight_kg=128.416,
            body_fat_percent=36.1,
            fat_mass_kg=46.4,
            fat_free_mass_kg=82.0,
            muscle_mass_kg=77.4,
            bone_mass_kg=4.0,
            hydration_kg=84.0,
            heart_rate_bpm=None,
            scale_battery=None,
            reading_hash="live-overlap",
            metadata={"source": "live"},
        )
        service.database.insert_measurement(existing)
        workbook_rows = [
            {
                "date": datetime(2026, 7, 19, 7, 35, 0),
                "weight (lb)": 283.1,
                "fat mass (lb)": 102.3,
                "bone mass (lb)": 8.9,
                "muscle mass (lb)": 171.9,
                "hydration (lb)": 185.2,
                "comments": "overlap",
            }
        ] + _sample_import_rows()[1:]
        preview = service.preview_weight_history_import(_upload_file(_build_workbook_bytes(workbook_rows)))

        self.assertEqual(preview["likely_overlaps"], 1)
        result = service.confirm_weight_history_import(preview["preview_token"])

        self.assertEqual(result["likely_overlaps"], 1)
        self.assertEqual(service.database.count_measurements(), len(workbook_rows))

    def test_multiple_same_day_measurements_are_preserved(self):
        service = self._service()
        rows = [
            {
                "date": datetime(2026, 5, 4, 9, 5, 16),
                "weight (lb)": 309.7,
                "fat mass (lb)": 119.9,
                "bone mass (lb)": 9.1,
                "muscle mass (lb)": 180.0,
                "hydration (lb)": 192.0,
                "comments": "morning",
            },
            {
                "date": datetime(2026, 5, 4, 18, 20, 0),
                "weight (lb)": 308.9,
                "fat mass (lb)": 119.0,
                "bone mass (lb)": 9.1,
                "muscle mass (lb)": 179.5,
                "hydration (lb)": 191.2,
                "comments": "evening",
            },
        ]
        preview = service.preview_weight_history_import(_upload_file(_build_workbook_bytes(rows)))
        service.confirm_weight_history_import(preview["preview_token"])

        self.assertEqual(service.database.count_measurements(), 2)
        stored = service.database.query_measurements()
        self.assertEqual(len([row for row in stored if row.source_timestamp.startswith("2026-05-04")]), 2)

    def test_preview_then_confirm_cleans_up_temp_files(self):
        service = self._service()
        preview = service.preview_weight_history_import(_upload_file(_sample_import_workbook()))
        token = preview["preview_token"]
        temp_path = Path(service._pending_imports[token]["path"])

        self.assertTrue(temp_path.exists())
        service.confirm_weight_history_import(token)

        self.assertFalse(temp_path.exists())
        self.assertNotIn(token, service._pending_imports)

    def test_malformed_or_non_xlsx_uploads_fail_safely(self):
        service = self._service()

        with self.assertRaises(ValueError):
            service.preview_weight_history_import(_upload_file(b"not a workbook", filename="Weight History.txt"))

        with self.assertRaises(Exception):
            service.preview_weight_history_import(_upload_file(b"not a real xlsx workbook", filename="Weight History.xlsx"))


if __name__ == "__main__":
    unittest.main()
