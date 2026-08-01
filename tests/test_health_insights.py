import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from modules.dashboard import Dashboard
from modules.health_insights.database import HealthInsightsDatabase
from modules.health_insights.google_health import GoogleHealthError
from modules.health_insights.models import DailyHealthInsight
from modules.health_insights.service import (
    HealthInsightsError,
    HealthInsightsService,
    normalize_activity_rollups,
)


TIMEZONE = "America/Los_Angeles"
TEST_DAY = date(2026, 5, 4)


class FakeLog:
    def info(self, message):
        pass

    def exception(self, message):
        pass


def civil_day(day=TEST_DAY):
    return {
        "civilStartTime": {
            "date": {"year": day.year, "month": day.month, "day": day.day},
            "time": {"hours": 0},
        },
        "dataSource": {"platform": "FITBIT"},
    }


def nutrition_rollup():
    return {
        **civil_day(),
        "nutritionLog": {
            "energy": {"kcalSum": 1800},
            "totalCarbohydrate": {"gramsSum": 190},
            "totalFat": {"gramsSum": 60},
            "nutrients": [
                {"nutrient": "PROTEIN", "quantity": {"gramsSum": 130}},
                {"nutrient": "DIETARY_FIBER", "quantity": {"gramsSum": 28}},
                {"nutrient": "SODIUM", "quantity": {"gramsSum": 2.1}},
            ],
        },
    }


def nutrition_point():
    return {
        "name": "users/redacted/dataTypes/nutrition-log/dataPoints/synthetic",
        "dataSource": {"platform": "FITBIT_WEB_API"},
        "nutritionLog": {
            "interval": {
                "startTime": "2026-05-04T19:00:00Z",
                "endTime": "2026-05-04T19:00:01Z",
                "civilStartTime": civil_day()["civilStartTime"],
            },
            "energy": {"kcal": 1800},
        },
    }


class FakeGoogleHealthClient:
    def __init__(self, fail_type=None):
        self.fail_type = fail_type

    def daily_rollups(self, data_type, start_date, end_date):
        if self.fail_type == data_type:
            raise GoogleHealthError("synthetic unavailable")
        point = civil_day()
        payloads = {
            "nutrition-log": [nutrition_rollup()],
            "steps": [{**point, "steps": {"countSum": "7654"}}],
            "total-calories": [{**point, "totalCalories": {"kcalSum": 2450}}],
            "active-energy-burned": [
                {**point, "activeEnergyBurned": {"kcalSum": 450}}
            ],
            "active-minutes": [
                {
                    **point,
                    "activeMinutes": {
                        "activeMinutesRollupByActivityLevel": [
                            {"activityLevel": "LIGHT", "activeMinutesSum": "25"},
                            {"activityLevel": "VIGOROUS", "activeMinutesSum": "15"},
                        ]
                    },
                }
            ],
            "active-zone-minutes": [
                {**point, "activeZoneMinutes": {"sumInFatBurnHeartZone": "20"}}
            ],
            "distance": [{**point, "distance": {"millimetersSum": 8046720}}],
        }
        return payloads.get(data_type, []), {"requests": 1}

    def list_data_points(self, data_type, *, start_date, end_date):
        if self.fail_type == data_type:
            raise GoogleHealthError("synthetic unavailable")
        return ([nutrition_point()] if data_type == "nutrition-log" else []), {
            "requests": 1
        }


class FakeWeightReader:
    def read(self, start_date, end_date, timezone_name):
        return {
            TEST_DAY.isoformat(): {
                "weight_pounds": 250.0,
                "seven_day_average_weight_pounds": 251.0,
                "body_fat_percentage": 30.0,
                "muscle_percentage": 40.0,
                "visceral_fat_index": 12.0,
                "weight_available": True,
                "weight_source": "Withings via Weight Progress",
            }
        }


class HealthInsightsDatabaseTests(unittest.TestCase):
    def test_round_trip_and_idempotent_upsert(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = HealthInsightsDatabase(Path(temp_dir) / "health.db")
            database.initialize()
            record = DailyHealthInsight(
                local_date="2026-05-04",
                timezone=TIMEZONE,
                steps=0,
                activity_complete=True,
                data_status="incomplete",
                first_imported_at="2026-05-05T08:00:00-07:00",
                last_refreshed_at="2026-05-05T08:00:00-07:00",
            )
            self.assertEqual(database.upsert_days([record])["inserted"], 1)
            self.assertEqual(database.upsert_days([record])["unchanged"], 1)
            stored = database.get_day("2026-05-04")
            self.assertEqual(stored["steps"], 0)
            self.assertTrue(stored["activity_complete"])
            self.assertEqual(database.date_range(), ("2026-05-04", "2026-05-04"))


class HealthInsightsNormalizationTests(unittest.TestCase):
    def test_total_expenditure_is_not_added_to_active_energy(self):
        point = civil_day()
        result = normalize_activity_rollups(
            {
                "steps": [{**point, "steps": {"countSum": "1000"}}],
                "total-calories": [
                    {**point, "totalCalories": {"kcalSum": 2400}}
                ],
                "active-energy-burned": [
                    {**point, "activeEnergyBurned": {"kcalSum": 500}}
                ],
                "distance": [{**point, "distance": {"millimetersSum": 1609344}}],
            }
        )[TEST_DAY.isoformat()]
        self.assertEqual(result["total_calories_burned"], 2400)
        self.assertEqual(result["active_energy_calories"], 500)
        self.assertAlmostEqual(result["distance_miles"], 1.0)
        self.assertTrue(result["activity_complete"])


class HealthInsightsServiceTests(unittest.TestCase):
    def make_service(self, root, client=None):
        service = HealthInsightsService(
            root,
            FakeLog(),
            database_path=Path(root) / "health.db",
            client_factory=lambda project_root: client or FakeGoogleHealthClient(),
            weight_reader=FakeWeightReader(),
            now_provider=lambda zone: datetime(2026, 5, 5, 8, 0, tzinfo=zone),
        )
        service.timezone_name = lambda: TIMEZONE
        return service

    def test_preview_combines_sources_without_writing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = self.make_service(Path(temp_dir))
            service.initialize()
            result = service.preview(
                TEST_DAY,
                TEST_DAY,
                now=datetime(2026, 5, 5, 8, 0, tzinfo=ZoneInfo(TIMEZONE)),
            )
            row = result["records"][0]
            self.assertFalse(result["database_written"])
            self.assertEqual(service.database.count_days(), 0)
            self.assertEqual(row["nutrition_calories"], 1800)
            self.assertEqual(
                row["nutrition_source"],
                "Unidentified app via Fitbit Web API",
            )
            self.assertEqual(row["steps"], 7654)
            self.assertEqual(row["total_calories_burned"], 2450)
            self.assertEqual(row["weight_pounds"], 250.0)
            self.assertTrue(row["nutrition_activity_weight_complete"])
            self.assertEqual(row["data_status"], "complete")

    def test_sync_is_idempotent_and_records_success(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = self.make_service(Path(temp_dir))
            service.initialize()
            now = datetime(2026, 5, 5, 8, 0, tzinfo=ZoneInfo(TIMEZONE))
            first = service.sync(TEST_DAY, TEST_DAY, now=now)
            second = service.sync(TEST_DAY, TEST_DAY, now=now)
            self.assertEqual(first["inserted"], 1)
            self.assertTrue(first["backup_created"])
            self.assertEqual(second["unchanged"], 1)
            self.assertFalse(second["backup_created"])
            self.assertEqual(service.status()["complete_days"], 1)
            self.assertEqual(service.database.sync_state()["last_status"], "success")

    def test_future_range_is_rejected_before_network_access(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = self.make_service(Path(temp_dir))
            service.initialize()
            now = datetime(2026, 5, 5, 8, 0, tzinfo=ZoneInfo(TIMEZONE))
            with self.assertRaisesRegex(HealthInsightsError, "Future"):
                service.preview(date(2026, 5, 6), date(2026, 5, 6), now=now)


class HealthInsightsRouteTests(unittest.TestCase):
    def test_page_and_status_api_render_without_stored_days(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = HealthInsightsService(
                Path(temp_dir),
                FakeLog(),
                database_path=Path(temp_dir) / "health.db",
            )
            service.timezone_name = lambda: TIMEZONE
            service.authorization_status = lambda: {
                "configured": True,
                "authorized": True,
            }
            service.initialize()
            application = SimpleNamespace(health_insights=service, log=FakeLog())
            client = Dashboard(application).app.test_client()

            page = client.get("/health-insights")
            self.assertEqual(page.status_code, 200)
            self.assertIn(b"Health Insights", page.data)
            self.assertIn(b"No Health Insights days have been stored", page.data)

            status = client.get("/api/health-insights/status")
            self.assertEqual(status.status_code, 200)
            self.assertTrue(status.get_json()["ok"])

    def test_page_uses_plain_language_calorie_labels_and_preserves_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = HealthInsightsService(
                Path(temp_dir),
                FakeLog(),
                database_path=Path(temp_dir) / "health.db",
            )
            service.timezone_name = lambda: TIMEZONE
            service.authorization_status = lambda: {
                "configured": True,
                "authorized": True,
            }
            service.initialize()
            service.database.upsert_days(
                [
                    DailyHealthInsight(
                        local_date="2026-05-04",
                        timezone=TIMEZONE,
                        nutrition_calories=1800,
                        total_calories_burned=2450,
                        exercise_minutes=40,
                        exercise_calories=450,
                        data_status="complete",
                        first_imported_at="2026-05-05T08:00:00-07:00",
                        last_refreshed_at="2026-05-05T08:00:00-07:00",
                    )
                ]
            )
            application = SimpleNamespace(health_insights=service, log=FakeLog())
            client = Dashboard(application).app.test_client()

            page = client.get("/health-insights")
            body = page.get_data(as_text=True)
            view_model = service.dashboard_view_model()
            row = view_model["daily_rows"][0]

            self.assertEqual(page.status_code, 200)
            self.assertNotIn("kcal", body.lower())
            self.assertIn("Calories Eaten", body)
            self.assertIn("Calories Burned", body)
            self.assertEqual(view_model["summary_cards"][2]["value"], "1800 Calories")
            self.assertEqual(row["calories"], "1800")
            self.assertEqual(row["calories_burned"], "2450")
            self.assertEqual(row["exercise"], "40 min / 450 Calories")


if __name__ == "__main__":
    unittest.main()
