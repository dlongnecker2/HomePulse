import json
from io import BytesIO
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

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

    def test_body_composition_rows_prioritize_percentage_metrics(self):
        service = self._service()
        service.database.insert_measurement(
            WeightMeasurement.create(
                captured_at="2026-07-10 08:00:00",
                source_timestamp="2026-07-10 08:00:00",
                source_entity="sensor.withings_weight",
                weight_kg=100.0,
                body_fat_percent=20.0,
                fat_mass_kg=20.0,
                fat_free_mass_kg=80.0,
                muscle_mass_kg=60.0,
                hydration_kg=70.0,
                bone_mass_kg=3.2,
                visceral_fat_index=8.4,
                reading_hash="hash-composition-rows",
                metadata={"timestamp": "2026-07-10 08:00:00"},
            )
        )

        payload = service.view_model(include_live=False)
        labels = [row["label"] for row in payload["body_composition_rows"]]

        self.assertEqual(
            labels[:9],
            [
                "Body Fat %",
                "Muscle %",
                "Hydration %",
                "Visceral Fat Index",
                "Fat Mass",
                "Fat-Free Mass",
                "Muscle Mass",
                "Hydration Mass",
                "Bone Mass",
            ],
        )

    def test_muscle_percentage_is_derived_and_validated(self):
        service = self._service()

        valid_measurement = WeightMeasurement.create(
            captured_at="2026-07-10 08:00:00",
            source_timestamp="2026-07-10 08:00:00",
            source_entity="sensor.withings_weight",
            weight_kg=127.6,
            muscle_mass_kg=77.5,
            reading_hash="hash-muscle-valid",
            metadata={"timestamp": "2026-07-10 08:00:00"},
        )
        self.assertEqual(service._derived_muscle_percentage(valid_measurement), 60.7)

        for weight_kg, muscle_mass_kg in [
            (None, 60.0),
            (100.0, None),
            (0, 50.0),
            (-1.0, 50.0),
            (100.0, 0),
            (100.0, -1.0),
            (100.0, 120.0),
            ("abc", 60.0),
            (100.0, "bad"),
        ]:
            with self.subTest(weight_kg=weight_kg, muscle_mass_kg=muscle_mass_kg):
                measurement = WeightMeasurement.create(
                    captured_at="2026-07-10 08:00:00",
                    source_timestamp="2026-07-10 08:00:00",
                    source_entity="sensor.withings_weight",
                    weight_kg=weight_kg,
                    muscle_mass_kg=muscle_mass_kg,
                    reading_hash=f"hash-{weight_kg}-{muscle_mass_kg}",
                    metadata={"timestamp": "2026-07-10 08:00:00"},
                )
                self.assertIsNone(service._derived_muscle_percentage(measurement))

    def test_muscle_percentage_summary_uses_percentage_points_and_tooltip_fields(self):
        config = build_config(
            weight_progress={
                "enabled": True,
                "database": "data/weight_progress.db",
                "display_unit": "lb",
                "starting_weight": None,
                "journey_start_date": "2026-07-01",
                "goal_weight": 220,
                "entities": build_config().data["weight_progress"]["entities"],
            }
        )
        service = self._service(config)
        service.database.insert_measurement(
            WeightMeasurement.create(
                captured_at="2026-07-01 08:00:00",
                source_timestamp="2026-07-01 08:00:00",
                source_entity="sensor.withings_weight",
                weight_kg=120.0,
                muscle_mass_kg=72.0,
                reading_hash="hash-muscle-start",
                metadata={"timestamp": "2026-07-01 08:00:00"},
            )
        )
        service.database.insert_measurement(
            WeightMeasurement.create(
                captured_at="2026-07-09 08:00:00",
                source_timestamp="2026-07-09 08:00:00",
                source_entity="sensor.withings_weight",
                weight_kg=130.0,
                muscle_mass_kg=79.3,
                reading_hash="hash-muscle-latest",
                metadata={"timestamp": "2026-07-09 08:00:00"},
            )
        )

        payload = service.view_model(include_live=False)
        trends = payload["composition_trends"]
        muscle_options = [option["value"] for option in trends["metric_options"]]
        more_options = [option["value"] for option in trends["more_metric_options"]]

        summary = service._composition_summary(
            trends["points"],
            trends["all_points"],
            "muscle_percentage",
            service._journey_start_date(service.weight_progress_config()),
            service.weight_progress_config().get("display_unit", "lb"),
        )

        self.assertEqual(trends["default_metric"], "muscle_percentage")
        self.assertEqual(trends["selected_metric"], "muscle_percentage")
        self.assertEqual(muscle_options, ["body_fat", "muscle_percentage", "hydration_percentage", "visceral_fat"])
        self.assertEqual(more_options, ["fat_mass", "fat_free_mass", "muscle_mass", "hydration", "bone_mass"])
        self.assertEqual(trends["all_points"][0]["muscle_percentage"], 60.0)
        self.assertEqual(trends["all_points"][1]["muscle_percentage"], 61.0)
        self.assertEqual(trends["all_points"][1]["muscle_mass_lb"], 174.8)
        self.assertEqual(trends["all_points"][1]["weight_lb"], 286.6)
        self.assertEqual(trends["all_points"][1]["hydration_percentage"], None)
        self.assertEqual(summary["summary_cards"][0]["value"], "61.0%")
        self.assertEqual(summary["summary_cards"][1]["value"], "60.0%")
        self.assertEqual(summary["summary_cards"][2]["value"], "Up 1.0 percentage points")
        self.assertEqual(summary["summary_cards"][3]["value"], "Jul 1, 2026")
        self.assertEqual(summary["summary_cards"][4]["value"], "Jul 9, 2026")
        self.assertIn("muscle mass as a share of total body weight", summary["summary_message"])

    def test_hydration_percentage_is_derived_and_validated(self):
        service = self._service()

        valid_measurement = WeightMeasurement.create(
            captured_at="2026-07-10 08:00:00",
            source_timestamp="2026-07-10 08:00:00",
            source_entity="sensor.withings_weight",
            weight_kg=100.0,
            hydration_kg=70.0,
            reading_hash="hash-hydration-valid",
            metadata={"timestamp": "2026-07-10 08:00:00"},
        )
        self.assertEqual(service._derived_hydration_percentage(valid_measurement), 70.0)

        for weight_kg, hydration_kg in [
            (None, 70.0),
            (100.0, None),
            (0, 50.0),
            (-1.0, 50.0),
            (100.0, 0),
            (100.0, -1.0),
            (100.0, 120.0),
            ("abc", 70.0),
            (100.0, "bad"),
        ]:
            with self.subTest(weight_kg=weight_kg, hydration_kg=hydration_kg):
                measurement = WeightMeasurement.create(
                    captured_at="2026-07-10 08:00:00",
                    source_timestamp="2026-07-10 08:00:00",
                    source_entity="sensor.withings_weight",
                    weight_kg=weight_kg,
                    hydration_kg=hydration_kg,
                    reading_hash=f"hash-{weight_kg}-{hydration_kg}",
                    metadata={"timestamp": "2026-07-10 08:00:00"},
                )
                self.assertIsNone(service._derived_hydration_percentage(measurement))

    def test_hydration_percentage_summary_uses_percentage_points_and_tooltip_fields(self):
        config = build_config(
            weight_progress={
                "enabled": True,
                "database": "data/weight_progress.db",
                "display_unit": "lb",
                "starting_weight": None,
                "journey_start_date": "2026-07-01",
                "goal_weight": 220,
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
                hydration_kg=70.0,
                reading_hash="hash-hydration-start",
                metadata={"timestamp": "2026-07-01 08:00:00"},
            )
        )
        service.database.insert_measurement(
            WeightMeasurement.create(
                captured_at="2026-07-09 08:00:00",
                source_timestamp="2026-07-09 08:00:00",
                source_entity="sensor.withings_weight",
                weight_kg=120.0,
                hydration_kg=78.0,
                reading_hash="hash-hydration-latest",
                metadata={"timestamp": "2026-07-09 08:00:00"},
            )
        )

        payload = service.view_model(include_live=False)
        trends = payload["composition_trends"]
        summary = service._composition_summary(
            trends["points"],
            trends["all_points"],
            "hydration_percentage",
            service._journey_start_date(service.weight_progress_config()),
            service.weight_progress_config().get("display_unit", "lb"),
        )

        self.assertEqual(trends["all_points"][0]["hydration_percentage"], 70.0)
        self.assertEqual(trends["all_points"][1]["hydration_percentage"], 65.0)
        self.assertEqual(trends["all_points"][1]["hydration_mass_lb"], 172.0)
        self.assertEqual(trends["all_points"][1]["weight_lb"], 264.6)
        self.assertEqual(trends["metric_labels"]["visceral_fat"], "Visceral Fat Index")
        self.assertEqual(summary["summary_cards"][0]["value"], "65.0%")
        self.assertEqual(summary["summary_cards"][1]["value"], "70.0%")
        self.assertEqual(summary["summary_cards"][2]["value"], "Down 5.0 percentage points")

    def test_visceral_fat_history_uses_stored_index_values(self):
        config = build_config(
            weight_progress={
                "enabled": True,
                "database": "data/weight_progress.db",
                "display_unit": "lb",
                "starting_weight": None,
                "journey_start_date": "2026-07-01",
                "goal_weight": 220,
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
                visceral_fat_index=9.2,
                reading_hash="hash-visceral-start",
                metadata={"timestamp": "2026-07-01 08:00:00"},
            )
        )
        service.database.insert_measurement(
            WeightMeasurement.create(
                captured_at="2026-07-09 08:00:00",
                source_timestamp="2026-07-09 08:00:00",
                source_entity="sensor.withings_weight",
                weight_kg=98.0,
                visceral_fat_index=8.4,
                reading_hash="hash-visceral-latest",
                metadata={"timestamp": "2026-07-09 08:00:00"},
            )
        )

        payload = service.view_model(include_live=False)
        trends = payload["composition_trends"]
        summary = service._composition_summary(
            service._composition_points(service.database.query_measurements(), "lb"),
            service._composition_points(service.database.query_measurements(), "lb"),
            "visceral_fat",
            service._journey_start_date(service.weight_progress_config()),
            service.weight_progress_config().get("display_unit", "lb"),
        )

        self.assertEqual(trends["metric_options"][-1]["value"], "visceral_fat")
        self.assertEqual(summary["trend_points"], 2)
        self.assertEqual(summary["current_value"], 8.4)
        self.assertEqual(summary["journey_value"], 9.2)
        self.assertEqual(summary["summary_cards"][2]["value"], "Down 0.8 Index")

    def test_visceral_chart_reconciles_home_assistant_snapshots_and_keeps_imports(self):
        service = self._service()
        imported = WeightMeasurement.create(
            captured_at="2023-12-13 04:18:52+00:00",
            source_timestamp="2023-12-13 04:18:52+00:00",
            source_entity="withings_public_api_history",
            visceral_fat_index=9.5,
            import_source="withings_public_api_history",
            reading_hash="imported-visceral-history",
            metadata={"withings_measure_type": 170},
        )
        service.database.insert_measurement(imported)
        for index, (source_timestamp, sensor_timestamp, value, body_fat) in enumerate(
            (
                (
                    "2026-07-20 08:00:00",
                    "2026-07-20T13:00:00+00:00",
                    8.4,
                    20.0,
                ),
                (
                    "2026-07-20 09:00:00",
                    "2026-07-20T18:00:00+00:00",
                    8.4,
                    21.0,
                ),
                (
                    "2026-07-20 10:00:00",
                    "2026-07-20T19:00:00+00:00",
                    8.3,
                    22.0,
                ),
            )
        ):
            service.database.insert_measurement(
                WeightMeasurement.create(
                    captured_at=source_timestamp,
                    source_timestamp=source_timestamp,
                    source_entity="sensor.withings_weight",
                    weight_kg=100.0 - index,
                    body_fat_percent=body_fat,
                    visceral_fat_index=value,
                    import_source="home_assistant",
                    reading_hash=f"home-assistant-visceral-{index}",
                    metadata={
                        "entities": {
                            "visceral_fat_index": {
                                "metadata": {
                                    "last_updated": sensor_timestamp,
                                    "last_changed": sensor_timestamp,
                                }
                            }
                        }
                    },
                )
            )

        payload = service.view_model(include_live=False, range_key="all")
        points = payload["composition_trends"]["all_points"]
        visceral_points = [
            point for point in points if point["visceral_fat"] is not None
        ]

        self.assertEqual(len(visceral_points), 3)
        self.assertEqual(
            [point["visceral_fat"] for point in visceral_points],
            [9.5, 8.4, 8.3],
        )
        self.assertEqual(
            visceral_points[1]["visceral_fat_timestamp"],
            service._normalize_timestamp("2026-07-20T18:00:00+00:00"),
        )
        self.assertEqual(
            [point["body_fat"] for point in points if point["body_fat"] is not None],
            [20.0, 21.0, 22.0],
        )
        trends = payload["composition_trends"]
        self.assertEqual(len(trends["visceral_fat_points"]), 3)
        self.assertEqual(
            [point["visceral_fat"] for point in trends["visceral_fat_points"]],
            [9.5, 8.4, 8.3],
        )
        self.assertEqual(
            [point["timestamp"] for point in trends["visceral_fat_points"]],
            sorted(point["timestamp"] for point in trends["visceral_fat_points"]),
        )
        self.assertEqual(trends["metric_labels"]["visceral_fat"], "Visceral Fat Index")
        self.assertEqual(trends["metric_units"]["visceral_fat"], "Index")
        self.assertEqual(trends["metric_kinds"]["visceral_fat"], "index")

        script = Path("static/js/weight_progress.js").read_text(encoding="utf-8")
        self.assertIn('metricConfig.key === "visceral_fat"', script)
        self.assertIn("`${metricLabel} - 7-day trend`", script)

    def _weekly_service(self, journey_start_date=None):
        config = build_config()
        config.data["timezone"] = "America/Los_Angeles"
        if journey_start_date:
            config.data["weight_progress"]["journey_start_date"] = journey_start_date
        return self._service(config)

    @staticmethod
    def _weekly_measurement(
        timestamp,
        weight_lb,
        *,
        import_source="withings_xlsx",
        original_weight_timestamp=None,
        reading_hash=None,
        visceral_fat_index=None,
    ):
        metadata = {"timestamp": timestamp}
        if original_weight_timestamp:
            metadata = {
                "entities": {
                    "weight": {
                        "metadata": {
                            "last_updated": original_weight_timestamp,
                            "last_changed": original_weight_timestamp,
                        }
                    }
                }
            }
        if weight_lb is None or isinstance(weight_lb, str):
            weight_kg = weight_lb
        else:
            weight_kg = weight_lb / 2.2046226218
        return WeightMeasurement.create(
            captured_at=str(timestamp),
            source_timestamp=str(timestamp),
            source_entity="sensor.withings_weight",
            weight_kg=weight_kg,
            visceral_fat_index=visceral_fat_index,
            import_source=import_source,
            reading_hash=reading_hash or f"weekly-{timestamp}-{weight_lb}",
            metadata=metadata,
        )

    def test_tuesday_periods_select_completed_last_week_and_current_week(self):
        service = self._weekly_service()
        now = datetime(2026, 7, 31, 12, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
        history = [
            self._weekly_measurement("2026-07-21 00:00:00", 286.2),
            self._weekly_measurement("2026-07-27 23:59:59.999999", 283.8),
            self._weekly_measurement("2026-07-28 00:00:00", 283.8),
            self._weekly_measurement("2026-07-31 09:00:00", 282.9),
        ]

        last_week, this_week = service._weekly_weight_cards(history, now=now)

        self.assertEqual(service.local_timezone_name(), "America/Los_Angeles")
        self.assertEqual(last_week["period_start"], "2026-07-21")
        self.assertEqual(last_week["period_end"], "2026-07-27")
        self.assertEqual(last_week["period_day_count"], 7)
        self.assertEqual(
            last_week["date_range_display"],
            "Jul 21\N{EN DASH}Jul 27 (7 days)",
        )
        self.assertEqual(last_week["measurement_count"], 2)
        self.assertEqual(last_week["first_weight"], 286.2)
        self.assertEqual(last_week["last_weight"], 283.8)
        self.assertEqual(last_week["change_pounds"], 2.4)
        self.assertEqual(last_week["direction"], "lost")
        self.assertEqual(last_week["display_text"], "2.4 lb lost")
        self.assertEqual(this_week["period_start"], "2026-07-28")
        self.assertEqual(this_week["period_end"], "2026-07-31")
        self.assertEqual(this_week["period_day_count"], 4)
        self.assertEqual(
            this_week["date_range_display"],
            "Jul 28\N{EN DASH}Jul 31 (4 days)",
        )
        self.assertEqual(this_week["measurement_count"], 2)
        self.assertEqual(this_week["display_text"], "0.9 lb lost")
        self.assertTrue(last_week["first_timestamp"].startswith("2026-07-21 00:00:00"))
        self.assertTrue(last_week["last_timestamp"].startswith("2026-07-27 23:59:59"))

    def test_weekly_change_wording_handles_gain_no_change_and_insufficient_data(self):
        service = self._weekly_service()
        now = datetime(2026, 7, 31, 12, 0, tzinfo=ZoneInfo("America/Los_Angeles"))

        gained = service._weekly_weight_cards(
            [
                self._weekly_measurement("2026-07-28 08:00:00", 280.0),
                self._weekly_measurement("2026-07-31 08:00:00", 280.8),
            ],
            now=now,
        )[1]
        unchanged = service._weekly_weight_cards(
            [
                self._weekly_measurement("2026-07-28 08:00:00", 280.0),
                self._weekly_measurement("2026-07-31 08:00:00", 280.0),
            ],
            now=now,
        )[1]
        one_reading = service._weekly_weight_cards(
            [self._weekly_measurement("2026-07-29 08:00:00", 280.0)],
            now=now,
        )[1]
        no_readings = service._weekly_weight_cards([], now=now)[1]

        self.assertEqual(gained["change_pounds"], -0.8)
        self.assertEqual(gained["direction"], "gained")
        self.assertEqual(gained["display_text"], "0.8 lb gained")
        self.assertNotIn("-", gained["display_text"])
        self.assertEqual(unchanged["status"], "no_change")
        self.assertEqual(unchanged["direction"], "none")
        self.assertEqual(unchanged["display_text"], "No change")
        for card, count in ((one_reading, 1), (no_readings, 0)):
            self.assertEqual(card["status"], "insufficient_data")
            self.assertEqual(card["direction"], "unknown")
            self.assertEqual(card["display_text"], "Not enough data")
            self.assertEqual(card["measurement_count"], count)
            self.assertIn("Not enough weigh-ins", card["note_lines"])

    def test_weekly_cards_reconcile_duplicates_and_ignore_non_weight_rows(self):
        service = self._weekly_service()
        now = datetime(2026, 7, 31, 12, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
        history = [
            self._weekly_measurement(
                "2026-07-29 08:05:00",
                283.0,
                import_source="home_assistant",
                original_weight_timestamp="2026-07-29T15:00:00+00:00",
                reading_hash="snapshot-a",
            ),
            self._weekly_measurement(
                "2026-07-29 11:00:00",
                283.0,
                import_source="home_assistant",
                original_weight_timestamp="2026-07-29T15:00:00+00:00",
                reading_hash="snapshot-b",
            ),
            self._weekly_measurement(
                "2026-07-30 08:00:00",
                282.0,
                import_source="home_assistant",
                reading_hash="live-canonical",
            ),
            self._weekly_measurement(
                "2026-07-30 08:03:00",
                282.1,
                import_source="withings_xlsx",
                reading_hash="import-overlap",
            ),
            self._weekly_measurement(
                "2026-07-30 09:00:00",
                None,
                visceral_fat_index=8.2,
                reading_hash="visceral-only",
            ),
            self._weekly_measurement("2026-07-30 10:00:00", "bad"),
            self._weekly_measurement("2026-07-30 11:00:00", "nan"),
            self._weekly_measurement("2026-07-30 11:30:00", 0.0),
            self._weekly_measurement("2026-08-01 08:00:00", 275.0),
        ]

        this_week = service._weekly_weight_cards(history, now=now)[1]

        self.assertEqual(this_week["measurement_count"], 2)
        self.assertEqual(this_week["first_weight"], 283.0)
        self.assertEqual(this_week["last_weight"], 282.0)
        self.assertEqual(this_week["display_text"], "1.0 lb lost")
        self.assertTrue(this_week["first_timestamp"].startswith("2026-07-29 08:00:00"))

    def test_weekly_cards_use_chronological_readings_and_keep_same_day_weigh_ins(self):
        service = self._weekly_service(journey_start_date="2026-07-30")
        now = datetime(2026, 7, 31, 20, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
        history = [
            self._weekly_measurement("2026-07-29 18:00:00", 279.0),
            self._weekly_measurement("2026-07-29 08:00:00", 280.0),
            self._weekly_measurement("2026-07-29 12:00:00", 282.0),
        ]

        this_week = service._weekly_weight_cards(history, now=now)[1]

        self.assertEqual(this_week["measurement_count"], 3)
        self.assertEqual(this_week["first_weight"], 280.0)
        self.assertEqual(this_week["last_weight"], 279.0)
        self.assertEqual(this_week["display_text"], "1.0 lb lost")

    def test_utc_timestamps_convert_to_local_tuesday_and_monday_boundaries(self):
        service = self._weekly_service()
        now = datetime(2026, 7, 28, 10, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
        history = [
            self._weekly_measurement("2026-07-21T07:00:00+00:00", 286.0),
            self._weekly_measurement("2026-07-28T06:59:59+00:00", 284.0),
            self._weekly_measurement("2026-07-28T07:00:00+00:00", 283.8),
            self._weekly_measurement("2026-07-28T16:00:00+00:00", 283.0),
        ]

        last_week, this_week = service._weekly_weight_cards(history, now=now)

        self.assertEqual(last_week["measurement_count"], 2)
        self.assertTrue(last_week["last_timestamp"].startswith("2026-07-27 23:59:59"))
        self.assertEqual(this_week["measurement_count"], 2)
        self.assertTrue(this_week["first_timestamp"].startswith("2026-07-28 00:00:00"))
        self.assertEqual(this_week["period_end"], "2026-07-28")

    def test_current_period_start_is_correct_on_monday_and_tuesday(self):
        service = self._weekly_service()
        zone = ZoneInfo("America/Los_Angeles")

        monday = service._weekly_weight_cards(
            [], now=datetime(2026, 8, 3, 23, 0, tzinfo=zone)
        )
        tuesday = service._weekly_weight_cards(
            [], now=datetime(2026, 8, 4, 0, 0, tzinfo=zone)
        )

        self.assertEqual(monday[1]["period_start"], "2026-07-28")
        self.assertEqual(monday[1]["period_end"], "2026-08-03")
        self.assertEqual(
            monday[1]["date_range_display"],
            "Jul 28\N{EN DASH}Aug 3 (7 days)",
        )
        self.assertEqual(tuesday[0]["period_start"], "2026-07-28")
        self.assertEqual(tuesday[0]["period_end"], "2026-08-03")
        self.assertEqual(tuesday[1]["period_start"], "2026-08-04")
        self.assertEqual(tuesday[1]["period_end"], "2026-08-04")
        self.assertEqual(tuesday[1]["period_day_count"], 1)
        self.assertEqual(
            tuesday[1]["date_range_display"],
            "Aug 4\N{EN DASH}Aug 4 (1 day)",
        )

    def test_week_boundaries_remain_local_across_daylight_saving_transition(self):
        service = self._weekly_service()
        now = datetime(2026, 3, 10, 12, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
        history = [
            self._weekly_measurement("2026-03-03T08:00:00+00:00", 290.0),
            self._weekly_measurement("2026-03-10T06:59:59+00:00", 288.0),
            self._weekly_measurement("2026-03-10T07:00:00+00:00", 287.8),
            self._weekly_measurement("2026-03-10T18:00:00+00:00", 287.0),
        ]

        last_week, this_week = service._weekly_weight_cards(history, now=now)

        self.assertEqual(last_week["period_start"], "2026-03-03")
        self.assertEqual(last_week["period_end"], "2026-03-09")
        self.assertTrue(last_week["first_timestamp"].endswith("-08:00"))
        self.assertTrue(last_week["last_timestamp"].endswith("-07:00"))
        self.assertEqual(this_week["period_start"], "2026-03-10")
        self.assertEqual(this_week["measurement_count"], 2)

    def test_average_weekly_loss_value_and_composition_outputs_are_unchanged(self):
        service = self._weekly_service()
        first = self._measurement("2026-07-01 08:00:00", 100.0, 20.0)
        last = self._measurement("2026-07-08 08:00:00", 99.0, 19.0)
        last.reading_hash = "weekly-average-last"
        service.database.insert_measurement(first)
        service.database.insert_measurement(last)
        expected_average = service._format_delta(
            service._average_weekly_change([first, last], "lb"),
            "lb",
            per_week=True,
        )

        payload = service.view_model(include_live=False)
        average_card = next(
            card for card in payload["summary_cards"]
            if card["label"] == "Average Weekly Loss"
        )

        self.assertEqual(average_card["value"], expected_average)
        self.assertEqual(
            [card["label"] for card in payload["summary_cards"][-3:]],
            ["Average Weekly Loss", "Last Week", "This Week So Far"],
        )
        self.assertEqual(payload["composition_trends"]["default_metric"], "muscle_percentage")
        self.assertIn("visceral_fat_points", payload["composition_trends"])


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
        self.assertNotIn("weight-progress-import-file", html)
        self.assertNotIn("weight-progress-import-preview-grid", html)
        self.assertLess(html.index("Current Weight"), html.index("Weight Trend"))
        self.assertLess(html.index("Weight Trend"), html.index("Body Composition Trends"))
        self.assertLess(html.index("Body Composition Trends"), html.index("Manage Weight History"))

    def test_page_renders_weekly_cards_after_average_with_supporting_text(self):
        payload = self._service_payload()
        payload["summary_cards"][-2:] = [
            {
                "label": "Last Week",
                "value": "2.4 lb lost",
                "date_range_display": "Jul 21\N{EN DASH}Jul 27 (7 days)",
                "note_lines": [
                    "Jul 21\N{EN DASH}Jul 27 (7 days)",
                    "286.2 lb \N{RIGHTWARDS ARROW} 283.8 lb",
                    "7 weigh-ins",
                ],
            },
            {
                "label": "This Week So Far",
                "value": "Not enough data",
                "date_range_display": "Jul 28\N{EN DASH}Jul 31 (4 days)",
                "note_lines": [
                    "Jul 28\N{EN DASH}Jul 31 (4 days)",
                    "Not enough weigh-ins",
                ],
            },
        ]

        html = self._render(payload)

        self.assertLess(html.index("Average Weekly Loss"), html.index("Last Week"))
        self.assertLess(html.index("Last Week"), html.index("This Week So Far"))
        self.assertIn("2.4 lb lost", html)
        self.assertIn("Jul 21\N{EN DASH}Jul 27 (7 days)", html)
        self.assertIn("Jul 28\N{EN DASH}Jul 31 (4 days)", html)
        self.assertIn("286.2 lb \N{RIGHTWARDS ARROW} 283.8 lb", html)
        self.assertIn("7 weigh-ins", html)
        self.assertIn("Not enough data", html)
        self.assertIn("Not enough weigh-ins", html)

    def test_page_renders_percentage_primary_selector_and_secondary_metrics(self):
        measurement = WeightMeasurement.create(
            captured_at="2026-07-19 07:35:33.270181",
            source_timestamp="2026-07-19 07:35:33.270181",
            source_entity="sensor.withings_weight",
            weight_kg=100.0,
            body_fat_percent=17.5,
            fat_mass_kg=18.0,
            fat_free_mass_kg=82.0,
            muscle_mass_kg=60.0,
            hydration_kg=70.0,
            bone_mass_kg=3.2,
            heart_rate_bpm=58,
            scale_battery="low",
            withings_goal_kg=95.0,
            reading_hash="hash-2",
            metadata={"timestamp": "2026-07-19 07:35:33.270181"},
        )
        payload = self._service_payload(measurement)
        html = self._render(payload)
        primary_start = html.index('<div class="range-controls" aria-label="Body composition metrics">')
        primary_end = html.index("</div>", primary_start)
        primary_block = html[primary_start:primary_end]

        self.assertIn('data-default-metric="muscle_percentage"', html)
        self.assertIn("Body Fat %", primary_block)
        self.assertIn("Muscle %", primary_block)
        self.assertIn("Hydration %", primary_block)
        self.assertIn("Visceral Fat Index", primary_block)
        self.assertNotIn("Fat Mass", primary_block)
        self.assertNotIn("Fat-Free Mass", primary_block)
        self.assertNotIn("Muscle Mass", primary_block)
        self.assertIn("Fat Mass", html)
        self.assertIn("Fat-Free Mass", html)
        self.assertIn("Muscle Mass", html)
        self.assertIn("Hydration Mass", html)
        self.assertIn("Bone Mass", html)

    def test_page_renders_empty_state_without_history(self):
        payload = self._service_payload()
        html = self._render(payload)

        self.assertIn("No weight history has been collected yet.", html)
        self.assertIn("No weight history stored yet. The first successful weigh-in will appear here.", html)
        self.assertIn("No body composition history has been collected yet.", html)
        self.assertNotIn("Import Weight History", html)
        self.assertIn("Manage Weight History", html)
        self.assertNotIn("weight-progress-import-file", html)
        self.assertNotIn("weight-progress-import-preview-grid", html)

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

        with app.test_request_context("/settings#weight-history-maintenance"):
            return render_template("settings.html", **context)

    def test_settings_contains_collapsed_history_import_section(self):
        html = self._render()

        self.assertIn("History Import &amp; Maintenance", html)
        self.assertIn('id="weight-history-maintenance" class="advanced-settings"', html)
        self.assertNotIn('id="weight-history-maintenance" class="advanced-settings" open', html)
        self.assertIn("Preview Import", html)
        self.assertIn('id="weight-progress-import-file"', html)
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
