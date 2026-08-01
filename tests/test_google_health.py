import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs

from modules.health_insights.google_health import (
    ACTIVITY_SCOPE,
    ALL_SCOPES,
    AUTHORIZATION_ENDPOINT,
    CALLBACK_URI,
    LEGACY_AUTHORIZATION_ENDPOINT,
    LEGACY_TOKEN_ENDPOINT,
    NUTRITION_SCOPE,
    SLEEP_SCOPE,
    TOKEN_ENDPOINT,
    GoogleHealthClient,
    GoogleHealthError,
    GoogleOAuthClient,
    aggregate_daily_nutrition,
    atomic_write_json,
    classify_exercise,
    configure_credentials,
    granted_scopes,
    interval_local_date,
    load_local_credentials,
    load_local_tokens,
    missing_scopes,
    normalize_exercise_point,
    normalize_nutrition_point,
    normalize_rollup_value,
    normalize_sleep_point,
    rollup_local_date,
    sanitized_shape,
    sanitize_text,
    save_tokens,
    source_identity,
    stable_record_key,
    validate_callback,
)
from modules.health_insights.models import DailyActivity
from scripts import google_health_audit


SECRET = "client-secret-that-must-never-print"
ACCESS_TOKEN = "ya29.access-token-that-must-never-print"
REFRESH_TOKEN = "1//refresh-token-that-must-never-print"
CLIENT_ID = "123456789-example.apps.googleusercontent.com"
PROJECT_ID = "homepulse-health-test"


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def credential_document(kind="web", **overrides):
    client = {
        "client_id": CLIENT_ID,
        "client_secret": SECRET,
        "project_id": PROJECT_ID,
        "auth_uri": AUTHORIZATION_ENDPOINT,
        "token_uri": TOKEN_ENDPOINT,
        "redirect_uris": [CALLBACK_URI],
    }
    client.update(overrides)
    return {kind: client}


def nutrition_point(
    *,
    name="users/redacted/dataTypes/nutrition-log/dataPoints/record-one",
    day="2026-05-04",
    platform="GOOGLE_PARTNER_INTEGRATION",
):
    year, month, day_number = (int(value) for value in day.split("-"))
    return {
        "name": name,
        "dataSource": {
            "platform": platform,
            "recordingMethod": "MANUAL",
            "application": {"packageName": "com.mynetdiary.mobile"},
        },
        "nutritionLog": {
            "interval": {
                "startTime": f"{day}T19:00:00Z",
                "endTime": f"{day}T19:00:01Z",
                "civilStartTime": {
                    "date": {"year": year, "month": month, "day": day_number},
                    "time": {"hours": 12},
                },
            },
            "energy": {"kcal": 500},
            "totalCarbohydrate": {"grams": 50},
            "totalFat": {"grams": 20},
            "nutrients": [
                {"nutrient": "PROTEIN", "quantity": {"grams": 30}},
                {"nutrient": "DIETARY_FIBER", "quantity": {"grams": 8}},
                {"nutrient": "SODIUM", "quantity": {"grams": 0.8}},
            ],
            "food": "users/redacted/dataTypes/food/dataPoints/food-one",
            "foodDisplayName": "Private food name",
        },
    }


class GoogleCredentialsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "HomePulse"
        self.root.mkdir()
        self.source = self.base / "client.json"

    def tearDown(self):
        self.temp.cleanup()

    def write_credentials(self, payload=None):
        self.source.write_text(
            json.dumps(payload or credential_document()),
            encoding="utf-8",
        )

    def test_credentials_json_import_web(self):
        self.write_credentials()
        result = configure_credentials(
            self.source, self.root, timezone_name="America/Los_Angeles"
        )
        stored = load_local_credentials(self.root)
        self.assertTrue(result["credential_file_recognized"])
        self.assertEqual(stored["client_type"], "web")
        self.assertEqual(stored["callback_uri"], CALLBACK_URI)
        self.assertEqual(stored["auth_uri"], AUTHORIZATION_ENDPOINT)
        self.assertEqual(stored["token_uri"], TOKEN_ENDPOINT)

    def test_desktop_credentials_json_rejected(self):
        self.write_credentials(credential_document("installed"))
        with self.assertRaisesRegex(GoogleHealthError, 'top-level "web"'):
            configure_credentials(
                self.source, self.root, timezone_name="America/Los_Angeles"
            )

    def test_old_and_current_official_endpoint_variants_are_normalized(self):
        endpoint_pairs = (
            (LEGACY_AUTHORIZATION_ENDPOINT, LEGACY_TOKEN_ENDPOINT),
            (LEGACY_AUTHORIZATION_ENDPOINT, TOKEN_ENDPOINT),
            (AUTHORIZATION_ENDPOINT, LEGACY_TOKEN_ENDPOINT),
            (AUTHORIZATION_ENDPOINT, TOKEN_ENDPOINT),
        )
        for auth_uri, token_uri in endpoint_pairs:
            with self.subTest(auth_uri=auth_uri, token_uri=token_uri):
                self.write_credentials(
                    credential_document(auth_uri=auth_uri, token_uri=token_uri)
                )
                configure_credentials(
                    self.source, self.root, timezone_name="America/Los_Angeles"
                )
                stored = load_local_credentials(self.root)
                self.assertEqual(stored["auth_uri"], AUTHORIZATION_ENDPOINT)
                self.assertEqual(stored["token_uri"], TOKEN_ENDPOINT)

    def test_lookalike_and_malicious_endpoint_hosts_are_rejected(self):
        hostile_endpoints = (
            {
                "auth_uri": "https://accounts.google.com.evil.example/o/oauth2/v2/auth",
            },
            {
                "auth_uri": "https://accounts-google.com/o/oauth2/v2/auth",
            },
            {
                "auth_uri": "https://evil.example/?next=https://accounts.google.com/o/oauth2/v2/auth",
            },
            {
                "token_uri": "https://oauth2.googleapis.com.evil.example/token",
            },
            {
                "token_uri": "https://accounts.google.com.evil.example/o/oauth2/token",
            },
            {
                "token_uri": "http://oauth2.googleapis.com/token",
            },
        )
        for overrides in hostile_endpoints:
            with self.subTest(overrides=overrides):
                self.write_credentials(credential_document(**overrides))
                with self.assertRaisesRegex(GoogleHealthError, "incompatible .* endpoint"):
                    configure_credentials(
                        self.source, self.root, timezone_name="America/Los_Angeles"
                    )

    def test_invalid_credentials_json_rejected(self):
        self.write_credentials({"web": {"client_id": CLIENT_ID}})
        with self.assertRaises(GoogleHealthError):
            configure_credentials(
                self.source, self.root, timezone_name="America/Los_Angeles"
            )

    def test_client_id_and_secret_must_be_nonempty(self):
        for key in ("client_id", "client_secret"):
            with self.subTest(key=key):
                self.write_credentials(credential_document(**{key: "  "}))
                with self.assertRaisesRegex(GoogleHealthError, "required OAuth"):
                    configure_credentials(
                        self.source, self.root, timezone_name="America/Los_Angeles"
                    )

    def test_incompatible_client_type_rejected(self):
        self.write_credentials({"service_account": {"client_id": CLIENT_ID}})
        with self.assertRaises(GoogleHealthError):
            configure_credentials(
                self.source, self.root, timezone_name="America/Los_Angeles"
            )

    def test_web_callback_must_match_exactly(self):
        self.write_credentials(
            credential_document(redirect_uris=["http://127.0.0.1:9999/wrong"])
        )
        with self.assertRaisesRegex(GoogleHealthError, "exact callback"):
            configure_credentials(
                self.source, self.root, timezone_name="America/Los_Angeles"
            )

    def test_credentials_from_project_tree_rejected(self):
        source = self.root / "download.json"
        source.write_text(json.dumps(credential_document()), encoding="utf-8")
        with self.assertRaisesRegex(GoogleHealthError, "outside"):
            configure_credentials(
                source, self.root, timezone_name="America/Los_Angeles"
            )

    def test_different_configured_project_rejected(self):
        self.write_credentials()
        configure_credentials(
            self.source, self.root, timezone_name="America/Los_Angeles"
        )
        other = self.base / "other.json"
        other.write_text(
            json.dumps(
                credential_document(
                    project_id="different-project",
                    client_id="999-other.apps.googleusercontent.com",
                )
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(GoogleHealthError, "different Google Cloud project"):
            configure_credentials(
                other, self.root, timezone_name="America/Los_Angeles"
            )

    def test_credentials_are_never_printed(self):
        self.write_credentials()
        args = type(
            "Args",
            (),
            {
                "credentials_file": str(self.source),
                "timezone": "America/Los_Angeles",
            },
        )()
        output = io.StringIO()
        with patch.object(google_health_audit, "PROJECT_ROOT", self.root):
            with redirect_stdout(output):
                google_health_audit.command_configure(args)
        self.assertNotIn(SECRET, output.getvalue())
        self.assertNotIn(CLIENT_ID, output.getvalue())


class GoogleOAuthTests(unittest.TestCase):
    def credentials(self):
        return {
            "client_id": CLIENT_ID,
            "client_secret": SECRET,
            "auth_uri": AUTHORIZATION_ENDPOINT,
            "token_uri": TOKEN_ENDPOINT,
            "callback_uri": CALLBACK_URI,
        }

    def test_authorization_url_is_read_only_offline_and_explicit(self):
        url = GoogleOAuthClient(self.credentials()).authorization_url(
            "safe-state", code_challenge="challenge"
        )
        query = parse_qs(url.split("?", 1)[1])
        self.assertEqual(query["access_type"], ["offline"])
        self.assertEqual(query["prompt"], ["consent"])
        self.assertEqual(set(query["scope"][0].split()), set(ALL_SCOPES))
        self.assertTrue(all(scope.endswith(".readonly") for scope in ALL_SCOPES))
        self.assertEqual(query["redirect_uri"], [CALLBACK_URI])
        self.assertEqual(query["code_challenge_method"], ["S256"])

    def test_runtime_endpoints_are_normalized_from_official_legacy_aliases(self):
        credentials = self.credentials()
        credentials["auth_uri"] = LEGACY_AUTHORIZATION_ENDPOINT
        credentials["token_uri"] = LEGACY_TOKEN_ENDPOINT
        seen = {}

        def opener(request, timeout):
            seen["token_url"] = request.full_url
            return FakeResponse({"access_token": ACCESS_TOKEN, "expires_in": 3600})

        client = GoogleOAuthClient(credentials, opener=opener)
        authorization_url = client.authorization_url("safe-state")
        client.refresh(REFRESH_TOKEN)
        self.assertTrue(authorization_url.startswith(f"{AUTHORIZATION_ENDPOINT}?"))
        self.assertEqual(seen["token_url"], TOKEN_ENDPOINT)

    def test_runtime_rejects_non_google_endpoint_hosts(self):
        credentials = self.credentials()
        credentials["auth_uri"] = (
            "https://accounts.google.com.evil.example/o/oauth2/v2/auth"
        )
        with self.assertRaisesRegex(GoogleHealthError, "authorization endpoint"):
            GoogleOAuthClient(credentials)

    def test_state_mismatch_rejected(self):
        with self.assertRaisesRegex(GoogleHealthError, "state validation"):
            validate_callback(
                "/oauth2/callback?state=wrong&code=private",
                expected_state="expected",
            )

    def test_exact_callback_path_validation(self):
        with self.assertRaisesRegex(GoogleHealthError, "path did not match"):
            validate_callback(
                "/wrong?state=expected&code=private",
                expected_state="expected",
            )

    def test_successful_callback_does_not_include_code_in_repr(self):
        result = validate_callback(
            "/oauth2/callback?state=expected&code=private-code",
            expected_state="expected",
        )
        self.assertEqual(result["code"], "private-code")

    def test_oauth_refresh_request(self):
        seen = {}

        def opener(request, timeout):
            seen["body"] = parse_qs(request.data.decode("ascii"))
            return FakeResponse({"access_token": ACCESS_TOKEN, "expires_in": 3600})

        response = GoogleOAuthClient(
            self.credentials(), opener=opener
        ).refresh(REFRESH_TOKEN)
        self.assertEqual(response["access_token"], ACCESS_TOKEN)
        self.assertEqual(seen["body"]["grant_type"], ["refresh_token"])
        self.assertEqual(seen["body"]["refresh_token"], [REFRESH_TOKEN])

    def test_oauth_error_is_sanitized(self):
        raw = json.dumps(
            {
                "error": "invalid_grant",
                "error_description": (
                    "bad token ya29.abcdefghijklmnopqrstuvwxyz0123456789"
                    " and user@example.com"
                ),
            }
        ).encode()

        def opener(request, timeout):
            raise HTTPError(
                request.full_url,
                400,
                "Bad Request",
                {},
                io.BytesIO(raw),
            )

        with self.assertRaises(GoogleHealthError) as caught:
            GoogleOAuthClient(self.credentials(), opener=opener).refresh(REFRESH_TOKEN)
        diagnostics = caught.exception.diagnostics()
        rendered = json.dumps(diagnostics)
        self.assertNotIn("ya29.", rendered)
        self.assertNotIn("user@example.com", rendered)
        self.assertEqual(diagnostics["http_status"], 400)

    def test_rotated_refresh_token_replaces_old_one(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            save_tokens(
                root,
                {
                    "access_token": "old-access",
                    "refresh_token": "old-refresh",
                    "scope": " ".join(ALL_SCOPES),
                },
            )
            save_tokens(
                root,
                {
                    "access_token": "new-access",
                    "refresh_token": "new-refresh",
                    "expires_in": 3600,
                },
            )
            self.assertEqual(load_local_tokens(root)["refresh_token"], "new-refresh")

    def test_refresh_token_preserved_when_response_omits_it(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            save_tokens(
                root,
                {"access_token": "old", "refresh_token": "keep-me"},
            )
            save_tokens(root, {"access_token": "new", "expires_in": 3600})
            self.assertEqual(load_local_tokens(root)["refresh_token"], "keep-me")

    def test_partial_consent_is_detected(self):
        tokens = {"scope": f"{NUTRITION_SCOPE} {ACTIVITY_SCOPE}"}
        self.assertEqual(missing_scopes(tokens), {SLEEP_SCOPE})

    def test_tokens_are_never_printed_by_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            credentials_path = (
                root / "data" / "health_insights" / "google_credentials.json"
            )
            atomic_write_json(
                credentials_path,
                {
                    "client_type": "web",
                    "client_id": CLIENT_ID,
                    "client_secret": SECRET,
                    "project_id": PROJECT_ID,
                    "auth_uri": AUTHORIZATION_ENDPOINT,
                    "token_uri": TOKEN_ENDPOINT,
                    "callback_uri": CALLBACK_URI,
                    "timezone": "America/Los_Angeles",
                },
            )
            save_tokens(
                root,
                {
                    "access_token": ACCESS_TOKEN,
                    "refresh_token": REFRESH_TOKEN,
                    "scope": " ".join(ALL_SCOPES),
                    "expires_in": 3600,
                },
            )
            output = io.StringIO()
            with patch.object(google_health_audit, "PROJECT_ROOT", root):
                with redirect_stdout(output):
                    google_health_audit.command_status(type("Args", (), {})())
            rendered = output.getvalue()
            self.assertNotIn(ACCESS_TOKEN, rendered)
            self.assertNotIn(REFRESH_TOKEN, rendered)
            self.assertNotIn(SECRET, rendered)


class GoogleHealthTransportTests(unittest.TestCase):
    def make_client(self, root, opener, *, max_retries=3, sleeper=lambda seconds: None):
        atomic_write_json(
            root / "data" / "health_insights" / "google_credentials.json",
            {
                "client_type": "web",
                "client_id": CLIENT_ID,
                "client_secret": SECRET,
                "project_id": PROJECT_ID,
                "auth_uri": AUTHORIZATION_ENDPOINT,
                "token_uri": TOKEN_ENDPOINT,
                "callback_uri": CALLBACK_URI,
                "timezone": "America/Los_Angeles",
            },
        )
        save_tokens(
            root,
            {
                "access_token": ACCESS_TOKEN,
                "refresh_token": REFRESH_TOKEN,
                "scope": " ".join(ALL_SCOPES),
                "expires_at": (
                    datetime.now(timezone.utc) + timedelta(hours=1)
                ).isoformat(),
            },
        )
        return GoogleHealthClient(
            root,
            opener=opener,
            max_retries=max_retries,
            sleeper=sleeper,
        )

    def test_pagination(self):
        responses = iter(
            [
                FakeResponse({"dataPoints": [{"name": "one"}], "nextPageToken": "next"}),
                FakeResponse({"dataPoints": [{"name": "two"}]}),
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            client = self.make_client(Path(temp_dir), lambda request, timeout: next(responses))
            points, stats = client.list_data_points(
                "steps", start_date=date(2026, 5, 4), end_date=date(2026, 5, 5)
            )
        self.assertEqual([item["name"] for item in points], ["one", "two"])
        self.assertEqual(stats["pages"], 2)

    def test_repeated_page_token_protection(self):
        responses = iter(
            [
                FakeResponse({"dataPoints": [], "nextPageToken": "same"}),
                FakeResponse({"dataPoints": [], "nextPageToken": "same"}),
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            client = self.make_client(Path(temp_dir), lambda request, timeout: next(responses))
            with self.assertRaisesRegex(GoogleHealthError, "repeated"):
                client.list_data_points("steps")

    def test_rate_limit_retries(self):
        calls = {"count": 0}
        sleeps = []

        def opener(request, timeout):
            calls["count"] += 1
            if calls["count"] == 1:
                raise HTTPError(
                    request.full_url,
                    429,
                    "Too Many Requests",
                    {"Retry-After": "0"},
                    io.BytesIO(b'{"error":{"status":"RESOURCE_EXHAUSTED"}}'),
                )
            return FakeResponse({"ok": True})

        with tempfile.TemporaryDirectory() as temp_dir:
            client = self.make_client(
                Path(temp_dir), opener, max_retries=1, sleeper=sleeps.append
            )
            self.assertTrue(client.request_json("GET", "users/me")["ok"])
        self.assertEqual(calls["count"], 2)
        self.assertEqual(sleeps, [0.0])

    def test_request_timeout_is_sanitized(self):
        def opener(request, timeout):
            raise TimeoutError("private endpoint details")

        with tempfile.TemporaryDirectory() as temp_dir:
            client = self.make_client(Path(temp_dir), opener, max_retries=0)
            with self.assertRaises(GoogleHealthError) as caught:
                client.request_json("GET", "users/me")
        self.assertEqual(caught.exception.description, "TimeoutError")

    def test_network_error_is_retryable(self):
        def opener(request, timeout):
            raise URLError("private host")

        with tempfile.TemporaryDirectory() as temp_dir:
            client = self.make_client(Path(temp_dir), opener, max_retries=0)
            with self.assertRaises(GoogleHealthError) as caught:
                client.request_json("GET", "users/me")
        self.assertTrue(caught.exception.retryable)

    def test_per_endpoint_date_chunking_14_days(self):
        bodies = []

        def opener(request, timeout):
            bodies.append(json.loads(request.data.decode("utf-8")))
            return FakeResponse({"rollupDataPoints": []})

        with tempfile.TemporaryDirectory() as temp_dir:
            client = self.make_client(Path(temp_dir), opener)
            _, stats = client.daily_rollups(
                "total-calories", date(2026, 5, 1), date(2026, 5, 30)
            )
        self.assertEqual(stats["chunks"], 3)
        self.assertEqual(stats["maximum_range_days"], 14)
        self.assertEqual(len(bodies), 3)
        self.assertNotIn("pageSize", bodies[0])
        self.assertEqual(
            bodies[0]["range"]["start"],
            {
                "date": {"year": 2026, "month": 5, "day": 1},
                "time": {"hours": 0, "minutes": 0, "seconds": 0, "nanos": 0},
            },
        )
        self.assertEqual(
            bodies[0]["range"]["end"],
            {
                "date": {"year": 2026, "month": 5, "day": 14},
                "time": {"hours": 23, "minutes": 59, "seconds": 59, "nanos": 0},
            },
        )

    def test_per_endpoint_date_chunking_90_days(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            client = self.make_client(
                Path(temp_dir),
                lambda request, timeout: FakeResponse({"rollupDataPoints": []}),
            )
            _, stats = client.daily_rollups(
                "steps", date(2026, 1, 1), date(2026, 7, 30)
            )
        self.assertEqual(stats["chunks"], 3)
        self.assertEqual(stats["maximum_range_days"], 90)


class GoogleHealthNormalizationTests(unittest.TestCase):
    def test_daily_rollup_civil_start_date_parsing(self):
        self.assertEqual(
            rollup_local_date(
                {
                    "civilStartTime": {
                        "date": {"year": 2026, "month": 5, "day": 4},
                        "time": {"hours": 0},
                    },
                    "steps": {"countSum": "1234"},
                }
            ),
            "2026-05-04",
        )

    def test_empty_nutrition_rollup_remains_missing(self):
        self.assertIsNone(
            normalize_rollup_value(
                "nutrition-log",
                {
                    "civilStartTime": {
                        "date": {"year": 2026, "month": 5, "day": 4}
                    }
                },
            )
        )

    def test_nutrition_log_parsing(self):
        result = normalize_nutrition_point(
            nutrition_point(), "America/Los_Angeles"
        )
        self.assertEqual(result["calories_kcal"], 500)
        self.assertEqual(result["protein_g"], 30)
        self.assertEqual(result["fiber_g"], 8)
        self.assertEqual(result["sodium_mg"], 800)
        self.assertTrue(result["food_name_present"])

    def test_food_and_nutrient_shape_redacts_name_and_identifier(self):
        shape = sanitized_shape(nutrition_point())
        rendered = json.dumps(shape)
        self.assertNotIn("Private food name", rendered)
        self.assertNotIn("record-one", rendered)
        self.assertIn("<redacted>", rendered)

    def test_steps_rollup_parsing(self):
        self.assertEqual(
            normalize_rollup_value("steps", {"steps": {"countSum": "4321"}}),
            4321,
        )

    def test_exercise_session_parsing_and_strength_classification(self):
        point = {
            "name": "users/redacted/dataTypes/exercise/dataPoints/workout",
            "dataSource": {"platform": "FITBIT"},
            "exercise": {
                "interval": {
                    "startTime": "2026-05-04T17:00:00Z",
                    "endTime": "2026-05-04T17:45:00Z",
                },
                "exerciseType": "WEIGHTLIFTING",
                "activeDuration": "2400s",
                "metricsSummary": {
                    "caloriesKcal": 200,
                    "distanceMillimeters": 0,
                    "steps": "0",
                    "activeZoneMinutes": "10",
                },
                "updateTime": "2026-05-04T18:00:00Z",
            },
        }
        result = normalize_exercise_point(point, "America/Los_Angeles")
        self.assertEqual(result.category, "strength")
        self.assertEqual(result.active_minutes, 40)
        self.assertEqual(result.steps, 0)

    def test_exercise_classification_does_not_infer_from_heart_rate(self):
        self.assertEqual(classify_exercise("WORKOUT"), "unknown")
        self.assertEqual(classify_exercise("WALKING"), "walking")
        self.assertEqual(classify_exercise("RUNNING"), "cardio")

    def test_active_energy_rollup_parsing(self):
        self.assertEqual(
            normalize_rollup_value(
                "active-energy-burned",
                {"activeEnergyBurned": {"kcalSum": 456.5}},
            ),
            456.5,
        )

    def test_total_calories_rollup_parsing(self):
        self.assertEqual(
            normalize_rollup_value(
                "total-calories", {"totalCalories": {"kcalSum": 2345.5}}
            ),
            2345.5,
        )

    def test_active_minutes_rollup_parsing(self):
        point = {
            "activeMinutes": {
                "activeMinutesRollupByActivityLevel": [
                    {"activityLevel": "LIGHT", "activeMinutesSum": "12"},
                    {"activityLevel": "VIGOROUS", "activeMinutesSum": "8"},
                ]
            }
        }
        self.assertEqual(normalize_rollup_value("active-minutes", point), 20)

    def test_active_zone_minutes_rollup_parsing(self):
        point = {
            "activeZoneMinutes": {
                "sumInFatBurnHeartZone": "10",
                "sumInCardioHeartZone": "12",
                "sumInPeakHeartZone": "4",
            }
        }
        self.assertEqual(
            normalize_rollup_value("active-zone-minutes", point), 26
        )

    def test_sleep_summary_parsing_without_granular_stages(self):
        point = {
            "name": "users/redacted/dataTypes/sleep/dataPoints/night",
            "dataSource": {"platform": "FITBIT"},
            "sleep": {
                "interval": {
                    "startTime": "2026-05-05T06:00:00Z",
                    "endTime": "2026-05-05T14:00:00Z",
                },
                "stages": [{"type": "PRIVATE_MINUTE_LEVEL_DATA"}],
                "summary": {
                    "minutesAsleep": "430",
                    "stagesSummary": [
                        {"type": "DEEP", "minutes": "80", "count": "3"},
                        {"type": "REM", "minutes": "90", "count": "4"},
                    ],
                },
            },
        }
        result = normalize_sleep_point(point, "America/Los_Angeles")
        self.assertEqual(result.sleep_minutes, 430)
        self.assertEqual(result.deep_minutes, 80)
        self.assertFalse(hasattr(result, "stages"))

    def test_stable_source_id_deduplication(self):
        first = nutrition_point()
        second = json.loads(json.dumps(first))
        self.assertEqual(stable_record_key(first), stable_record_key(second))
        self.assertEqual(len(stable_record_key(first)), 64)

    def test_missing_values_remain_missing(self):
        point = nutrition_point()
        point["nutritionLog"].pop("totalFat")
        point["nutritionLog"]["nutrients"] = []
        result = normalize_nutrition_point(point, "America/Los_Angeles")
        self.assertIsNone(result["fat_g"])
        self.assertIsNone(result["protein_g"])
        daily = aggregate_daily_nutrition(
            [point],
            "America/Los_Angeles",
            date(2026, 5, 4),
            date(2026, 5, 5),
        )
        self.assertEqual(daily[0].completeness, "partial")
        self.assertEqual(daily[1].completeness, "no data")
        self.assertIsNone(daily[1].calories_kcal)

    def test_valid_zero_activity_remains_zero(self):
        self.assertEqual(
            normalize_rollup_value("steps", {"steps": {"countSum": "0"}}), 0
        )

    def test_no_calorie_double_counting(self):
        activity = DailyActivity(
            local_date="2026-05-04",
            total_calories_kcal=2400,
            active_energy_kcal=500,
            exercise_minutes=45,
        )
        self.assertEqual(activity.expenditure_source_of_truth, 2400)
        self.assertEqual(activity.estimated_calorie_balance(1800), -600)

    def test_local_date_conversion_across_spring_dst(self):
        interval = {"startTime": "2026-03-08T09:30:00Z"}
        self.assertEqual(
            interval_local_date(
                interval, "America/Los_Angeles", prefer_end=False
            ),
            "2026-03-08",
        )
        interval = {"startTime": "2026-03-08T07:30:00Z"}
        self.assertEqual(
            interval_local_date(
                interval, "America/Los_Angeles", prefer_end=False
            ),
            "2026-03-07",
        )

    def test_local_date_conversion_across_fall_dst(self):
        first = {"startTime": "2026-11-01T08:30:00Z"}
        second = {"startTime": "2026-11-01T09:30:00Z"}
        self.assertEqual(
            interval_local_date(first, "America/Los_Angeles", prefer_end=False),
            "2026-11-01",
        )
        self.assertEqual(
            interval_local_date(second, "America/Los_Angeles", prefer_end=False),
            "2026-11-01",
        )

    def test_fitbit_source_is_recognizable(self):
        identity = source_identity(
            {"dataSource": {"platform": "FITBIT", "recordingMethod": "DERIVED"}}
        )
        self.assertEqual(identity["platform"], "FITBIT")

    def test_sanitizer_removes_common_secret_shapes(self):
        text = sanitize_text(
            "token ya29.abcdefghijklmnopqrstuvwxyz0123456789 user@example.com "
            "code=abcdefghijklmnopqrstuvwxyz012345678901234567890 "
            "users/123456789/dataTypes/sleep/dataPoints/private-record"
        )
        self.assertNotIn("ya29.", text)
        self.assertNotIn("user@example.com", text)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz012345678901234567890", text)
        self.assertNotIn("123456789", text)
        self.assertNotIn("private-record", text)


class GoogleHealthReadOnlyIntegrationTests(unittest.TestCase):
    def test_weight_progress_database_remains_byte_identical(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            data_dir.mkdir()
            database_path = data_dir / "weight_progress.db"
            connection = sqlite3.connect(database_path)
            connection.execute(
                """
                CREATE TABLE weight_measurements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    captured_at TEXT NOT NULL,
                    source_timestamp TEXT NOT NULL,
                    source_entity TEXT NOT NULL,
                    weight_kg REAL,
                    body_fat_percent REAL,
                    fat_mass_kg REAL,
                    fat_free_mass_kg REAL,
                    muscle_mass_kg REAL,
                    bone_mass_kg REAL,
                    hydration_kg REAL,
                    visceral_fat_index REAL,
                    heart_rate_bpm REAL,
                    scale_battery TEXT,
                    comments TEXT,
                    import_source TEXT,
                    source_label TEXT,
                    imported_at TEXT,
                    withings_goal_kg REAL,
                    reading_hash TEXT NOT NULL UNIQUE,
                    metadata_json TEXT
                )
                """
            )
            connection.execute(
                """
                INSERT INTO weight_measurements
                (captured_at, source_timestamp, source_entity, weight_kg,
                 reading_hash)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "2026-05-04T12:00:00Z",
                    "2026-05-04T12:00:00Z",
                    "sensor.withings_weight",
                    100.0,
                    "hash-one",
                ),
            )
            connection.commit()
            connection.close()
            (root / "config.json").write_text(
                json.dumps(
                    {"weight_progress": {"database": "data/weight_progress.db"}}
                ),
                encoding="utf-8",
            )
            before = hashlib.sha256(database_path.read_bytes()).hexdigest()
            with patch.object(google_health_audit, "PROJECT_ROOT", root):
                result = google_health_audit.read_weight_trend(
                    date(2026, 5, 4), date(2026, 5, 5)
                )
            after = hashlib.sha256(database_path.read_bytes()).hexdigest()
            self.assertTrue(result["available"])
            self.assertFalse(result["database_written"])
            self.assertEqual(before, after)

    def test_audit_without_authorization_writes_no_database(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            args = type(
                "Args",
                (),
                {
                    "from_date": "2026-05-04",
                    "through_date": "2026-05-05",
                    "output": None,
                },
            )()
            with patch.object(google_health_audit, "PROJECT_ROOT", root):
                with self.assertRaises(GoogleHealthError):
                    google_health_audit.command_audit(args)
            self.assertEqual(list(root.rglob("*.db")), [])

    def test_synthetic_fixtures_contain_no_private_identifiers(self):
        rendered = json.dumps(nutrition_point())
        self.assertNotIn(ACCESS_TOKEN, rendered)
        self.assertNotIn(REFRESH_TOKEN, rendered)
        self.assertNotIn(SECRET, rendered)
        self.assertNotIn("google-user-id", rendered)
        self.assertNotIn("fitbit-user-id", rendered)


if __name__ == "__main__":
    unittest.main()
