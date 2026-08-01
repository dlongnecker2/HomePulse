from contextlib import redirect_stdout
from datetime import timedelta
from hashlib import sha256
import hmac
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from modules.weight_progress.withings_api import (
    HistoricalAuditResult,
    OAuthTokens,
    VISCERAL_FAT_INDEX_TYPE,
    WithingsAuditError,
    WithingsMeasureClient,
    WithingsOAuthClient,
    build_history_measurements,
    compare_readings,
    parse_visceral_fat_groups,
    withings_signature,
)
from scripts.withings_audit import (
    backup_weight_progress_database,
    config_file_path,
    configure,
    load_homepulse_visceral_readings,
    oauth_client,
    verify_credentials,
)
from modules.weight_progress.database import WeightProgressDatabase
from modules.weight_progress.models import WeightMeasurement


def response(groups, *, more=0, offset=None, status=0):
    body = {"measuregrps": groups, "more": more}
    if offset is not None:
        body["offset"] = offset
    return {"status": status, "body": body}


def group(group_id="123", timestamp=1_700_000_000, value=84, unit=-1, measure_type=170):
    return {
        "grpid": group_id,
        "date": timestamp,
        "measures": [{"type": measure_type, "value": value, "unit": unit}],
    }


class WithingsOAuthTests(unittest.TestCase):
    def test_authorization_url_has_minimal_scope_and_state(self):
        client = WithingsOAuthClient(
            "client-id",
            "private-secret",
            "http://127.0.0.1:8765/callback",
            request_json=lambda *args: {},
        )
        url, state = client.authorization_url("csrf-state")
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.netloc, "account.withings.com")
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["client_id"], ["client-id"])
        self.assertEqual(query["scope"], ["user.metrics"])
        self.assertEqual(
            query["redirect_uri"], ["http://127.0.0.1:8765/callback"]
        )
        self.assertEqual(query["state"], ["csrf-state"])
        self.assertEqual(state, "csrf-state")
        self.assertNotIn("private-secret", url)

    def test_code_exchange_and_refresh_rotate_tokens_without_repr_leak(self):
        calls = []

        def request(endpoint, fields, token, timeout):
            calls.append(fields.copy())
            suffix = str(len(calls))
            return {
                "status": 0,
                "body": {
                    "access_token": f"access-secret-{suffix}",
                    "refresh_token": f"refresh-secret-{suffix}",
                    "userid": "private-user-id",
                    "expires_in": 10800,
                    "scope": "user.metrics",
                },
            }

        client = WithingsOAuthClient(
            "client-id",
            "client-secret",
            "http://127.0.0.1:8765/callback",
            request_json=request,
        )
        first = client.exchange_code("authorization-secret")
        second = client.refresh(first.refresh_token)
        self.assertEqual(calls[0]["grant_type"], "authorization_code")
        self.assertEqual(
            calls[0]["redirect_uri"], "http://127.0.0.1:8765/callback"
        )
        self.assertEqual(
            set(calls[0]),
            {
                "action",
                "grant_type",
                "client_id",
                "client_secret",
                "code",
                "redirect_uri",
            },
        )
        self.assertEqual(calls[1]["grant_type"], "refresh_token")
        self.assertEqual(second.refresh_token, "refresh-secret-2")
        self.assertEqual(repr(second), "OAuthTokens(<redacted>)")
        for secret in ("access-secret-2", "refresh-secret-2", "private-user-id"):
            self.assertNotIn(secret, repr(second))

    def test_failed_exchange_reports_only_sanitized_contract_details(self):
        secrets = {
            "client_id": "private-client-id",
            "client_secret": "private-client-secret",
            "code": "private-authorization-code",
        }

        def request(endpoint, fields, token, timeout):
            return {
                "_http_status": 200,
                "status": 503,
                "body": {
                    "error": (
                        "invalid_client: client_secret=private-client-secret "
                        "code=private-authorization-code userid=998877"
                    )
                },
            }

        client = WithingsOAuthClient(
            secrets["client_id"],
            secrets["client_secret"],
            "http://127.0.0.1:8765/callback",
            request_json=request,
        )
        with self.assertRaises(WithingsAuditError) as caught:
            client.exchange_code(secrets["code"])
        diagnostic = str(caught.exception)
        for expected in (
            "authentication_mode=direct",
            "http_status=200",
            "withings_status=503",
            "endpoint=https://wbsapi.withings.net/v2/oauth2",
            "action_present=true",
            "grant_type_present=true",
            "client_id_present=true",
            "client_secret_present=true",
            "authorization_code_present=true",
            "nonce_present=false",
            "signature_present=false",
            "callback_matched=true",
        ):
            self.assertIn(expected, diagnostic)
        for forbidden in (*secrets.values(), "998877"):
            self.assertNotIn(forbidden, diagnostic)

    def test_configure_preserves_complete_hidden_input(self):
        class FakeConfig:
            def __init__(self):
                self.data = {"weight_progress": {}}

            def save(self):
                return None

        fake = FakeConfig()
        with (
            patch("scripts.withings_audit.Config", return_value=fake),
            patch(
                "builtins.input",
                side_effect=["client-id", "http://127.0.0.1:8765/callback"],
            ),
            patch(
                "scripts.withings_audit.getpass.getpass",
                return_value="complete-secret-value-without-truncation",
            ),
        ):
            configure()
        stored = fake.data["weight_progress"]["withings_oauth"]
        self.assertEqual(
            stored["client_secret"], "complete-secret-value-without-truncation"
        )

    def test_configure_rejects_masked_quotes_and_boundary_whitespace(self):
        class FakeConfig:
            def __init__(self):
                self.data = {"weight_progress": {}}

            def save(self):
                self.fail("configure must not save an invalid secret")

        for secret, message in (
            ("masked****", "asterisks"),
            ('"quoted-secret"', "quotation marks"),
            (" secret-with-space", "whitespace corruption"),
        ):
            fake = FakeConfig()
            with (
                self.subTest(secret_kind=message),
                patch("scripts.withings_audit.Config", return_value=fake),
                patch(
                    "builtins.input",
                    side_effect=["client-id", "http://127.0.0.1:8765/callback"],
                ),
                patch(
                    "scripts.withings_audit.getpass.getpass",
                    return_value=secret,
                ),
            ):
                with self.assertRaisesRegex(WithingsAuditError, message):
                    configure()

    def test_clipboard_configure_preserves_identity_and_never_uses_getpass(self):
        class FakeConfig:
            def __init__(self):
                self.data = {
                    "weight_progress": {
                        "withings_oauth": {
                            "client_id": "existing-client-id",
                            "client_secret": "old-secret",
                            "redirect_uri": "http://127.0.0.1:8765/callback",
                            "access_token": "old-access",
                            "refresh_token": "old-refresh",
                        }
                    }
                }
                self.saved = False

            def save(self):
                self.saved = True

        fake = FakeConfig()
        output = io.StringIO()
        with (
            patch("scripts.withings_audit.Config", return_value=fake),
            patch(
                "scripts.withings_audit.read_windows_clipboard",
                return_value="complete-clipboard-secret\r\n",
            ),
            patch(
                "scripts.withings_audit.getpass.getpass",
                side_effect=AssertionError("getpass must not be called"),
            ),
            patch(
                "builtins.input",
                side_effect=AssertionError("typing prompts must not be called"),
            ),
            redirect_stdout(output),
        ):
            configure(secret_from_clipboard=True)
        stored = fake.data["weight_progress"]["withings_oauth"]
        self.assertTrue(fake.saved)
        self.assertEqual(stored["client_id"], "existing-client-id")
        self.assertEqual(
            stored["redirect_uri"], "http://127.0.0.1:8765/callback"
        )
        self.assertEqual(stored["client_secret"], "complete-clipboard-secret")
        self.assertEqual(stored["access_token"], "")
        self.assertEqual(stored["refresh_token"], "")
        self.assertIn("saved_secret_length=25", output.getvalue())
        self.assertIn("saved_secret_appears_valid=true", output.getvalue())
        self.assertNotIn("complete-clipboard-secret", output.getvalue())

    def test_clipboard_configure_rejects_corrupt_values_without_saving(self):
        class FakeConfig:
            def __init__(self):
                self.data = {
                    "weight_progress": {
                        "withings_oauth": {
                            "client_id": "existing-client-id",
                            "client_secret": "old-secret",
                            "redirect_uri": "http://127.0.0.1:8765/callback",
                        }
                    }
                }
                self.saved = False

            def save(self):
                self.saved = True

        for secret in (
            "",
            "\r\n",
            "x\r\n",
            "masked****\r\n",
            '"quoted"\r\n',
            " leading-space\r\n",
            "trailing-space \r\n",
            "internal whitespace\r\n",
            "embedded\tcontrol\r\n",
        ):
            fake = FakeConfig()
            with (
                self.subTest(secret_length=len(secret)),
                patch("scripts.withings_audit.Config", return_value=fake),
                patch(
                    "scripts.withings_audit.read_windows_clipboard",
                    return_value=secret,
                ),
            ):
                with self.assertRaises(WithingsAuditError):
                    configure(secret_from_clipboard=True)
                self.assertFalse(fake.saved)
                self.assertEqual(
                    fake.data["weight_progress"]["withings_oauth"][
                        "client_secret"
                    ],
                    "old-secret",
                )

    def test_verify_credentials_compares_exactly_without_exposure_or_save(self):
        stored_secret = "abcdef0123456789"

        class FakeConfig:
            data = {
                "weight_progress": {
                    "withings_oauth": {
                        "client_id": "client-id",
                        "client_secret": stored_secret,
                    }
                }
            }

            def save(self):
                raise AssertionError("verification must be read-only")

        output = io.StringIO()
        with (
            patch("scripts.withings_audit.Config", return_value=FakeConfig()),
            patch(
                "scripts.withings_audit.getpass.getpass",
                return_value=stored_secret,
            ),
            redirect_stdout(output),
        ):
            verify_credentials()
        text = output.getvalue()
        self.assertIn("dashboard_secret_matches_stored=true", text)
        self.assertIn("stored_secret_length=16", text)
        self.assertNotIn(stored_secret, text)

    def test_configure_authorize_and_verifier_share_project_config(self):
        self.assertEqual(config_file_path(), Path("config.json").resolve())
        with patch.dict(
            "os.environ", {"WITHINGS_CLIENT_SECRET": "environment-secret"}
        ):
            client = oauth_client(
                {
                    "client_id": "configured-id",
                    "client_secret": "configured-secret",
                    "redirect_uri": "http://127.0.0.1:8765/callback",
                }
            )
        self.assertEqual(client._client_secret, "configured-secret")

    def test_nonce_and_request_signatures_follow_documented_order(self):
        expected_nonce = hmac.new(
            b"client-secret",
            b"getnonce,client-id,1700000000",
            sha256,
        ).hexdigest()
        expected_request = hmac.new(
            b"client-secret",
            b"requesttoken,client-id,fresh-nonce",
            sha256,
        ).hexdigest()
        self.assertEqual(
            withings_signature(
                {
                    "timestamp": "1700000000",
                    "client_id": "client-id",
                    "action": "getnonce",
                },
                "client-secret",
            ),
            expected_nonce,
        )
        self.assertEqual(
            withings_signature(
                {
                    "nonce": "fresh-nonce",
                    "client_id": "client-id",
                    "action": "requesttoken",
                    "code": "not-signed",
                },
                "client-secret",
            ),
            expected_request,
        )

    def test_signed_mode_uses_fresh_nonce_and_omits_raw_secret(self):
        calls = []

        def request(endpoint, fields, token, timeout):
            calls.append((endpoint, fields.copy()))
            if endpoint.endswith("/v2/signature"):
                return {
                    "_http_status": 200,
                    "status": 0,
                    "body": {"nonce": "private-fresh-nonce"},
                }
            return {
                "_http_status": 200,
                "status": 0,
                "body": {
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "userid": "user-id",
                    "expires_in": 10800,
                },
            }

        client = WithingsOAuthClient(
            "client-id",
            "client-secret",
            "http://127.0.0.1:8765/callback",
            request_json=request,
        )
        with patch("modules.weight_progress.withings_api.time.time", return_value=1_700_000_000):
            client.exchange_code("new-code", mode="signed")
        self.assertEqual(len(calls), 2)
        nonce_fields = calls[0][1]
        token_fields = calls[1][1]
        self.assertEqual(
            set(nonce_fields),
            {"action", "client_id", "timestamp", "signature"},
        )
        self.assertEqual(
            set(token_fields),
            {
                "action",
                "client_id",
                "redirect_uri",
                "code",
                "grant_type",
                "nonce",
                "signature",
            },
        )
        self.assertNotIn("client_secret", token_fields)
        self.assertIn("authentication_mode=signed", client.last_diagnostics)

    def test_signed_diagnostics_redact_nonce_signature_code_and_tokens(self):
        def request(endpoint, fields, token, timeout):
            if endpoint.endswith("/v2/signature"):
                return {
                    "_http_status": 200,
                    "status": 0,
                    "body": {"nonce": "nonce-private-value"},
                }
            return {
                "_http_status": 200,
                "status": 503,
                "body": {
                    "message": (
                        f"nonce={fields['nonce']} signature={fields['signature']} "
                        f"code={fields['code']} access_token=token-private"
                    )
                },
            }

        client = WithingsOAuthClient(
            "client-id",
            "client-secret",
            "http://127.0.0.1:8765/callback",
            request_json=request,
        )
        with self.assertRaises(WithingsAuditError) as caught:
            client.exchange_code("code-private-value", mode="signed")
        diagnostic = str(caught.exception)
        for forbidden in (
            "nonce-private-value",
            "code-private-value",
            "token-private",
        ):
            self.assertNotIn(forbidden, diagnostic)
        self.assertIn("authentication_mode=signed", diagnostic)
        self.assertIn("client_secret_present=false", diagnostic)


class WithingsHistoryAuditTests(unittest.TestCase):
    def test_type_170_is_recognized_and_84_scaled_to_8_point_4(self):
        reading = parse_visceral_fat_groups([group()])[0]
        self.assertEqual(VISCERAL_FAT_INDEX_TYPE, 170)
        self.assertEqual(reading.value, 8.4)
        self.assertEqual(parse_visceral_fat_groups([group(measure_type=6)]), [])

    def test_historical_request_shape_uses_runtime_enddate(self):
        calls = []

        def request(endpoint, fields, token, timeout):
            calls.append(fields.copy())
            return response([])

        WithingsMeasureClient(
            "secret-token", request_json=request, clock=lambda: 1_800_000_123.9
        ).fetch_visceral_fat_history()
        self.assertEqual(
            calls[0],
            {
                "action": "getmeas",
                "category": "1",
                "meastypes": "170",
                "startdate": "0",
                "enddate": "1800000123",
            },
        )

    def test_actual_more_offset_contract_is_followed_and_shape_recorded(self):
        calls = []
        replies = [
            response([group("a")], more=1, offset=42),
            response([group("b", timestamp=1_700_000_100)], more=0),
        ]

        def request(endpoint, fields, token, timeout):
            calls.append(fields.copy())
            return replies.pop(0)

        result = WithingsMeasureClient("token", request_json=request).fetch_visceral_fat_history()
        self.assertEqual(result.pages_retrieved, 2)
        self.assertEqual(calls[1]["offset"], "42")
        self.assertEqual(
            result.page_shapes,
            [
                {
                    "more_type": "int",
                    "more": True,
                    "offset_present": True,
                    "measuregrps_type": "list",
                },
                {
                    "more_type": "int",
                    "more": False,
                    "offset_present": False,
                    "measuregrps_type": "list",
                },
            ],
        )

    def test_repeated_offset_and_duplicate_source_are_protected(self):
        replies = [
            response([group("same")], more=1, offset=2),
            response([group("same")]),
        ]

        def duplicates(endpoint, fields, token, timeout):
            return replies.pop(0)

        result = WithingsMeasureClient("token", request_json=duplicates).fetch_visceral_fat_history()
        self.assertEqual(len(result.readings), 1)
        self.assertEqual(result.duplicate_count, 1)

        with self.assertRaisesRegex(WithingsAuditError, "repeated pagination offset"):
            WithingsMeasureClient(
                "token",
                request_json=lambda *args: response([], more=1, offset=2),
            ).fetch_visceral_fat_history()

    def test_expired_access_token_uses_refresh_once(self):
        calls = []

        def request(endpoint, fields, token, timeout):
            calls.append(token)
            return (
                {"status": 401, "body": {}}
                if len(calls) == 1
                else response([])
            )

        result = WithingsMeasureClient(
            "expired",
            request_json=request,
            refresh_access_token=lambda: "replacement",
        ).fetch_visceral_fat_history()
        self.assertIsInstance(result, HistoricalAuditResult)
        self.assertEqual(calls, ["expired", "replacement"])

    def test_errors_and_objects_do_not_expose_credentials(self):
        secret = "highly-private-access-token"
        with self.assertRaises(WithingsAuditError) as caught:
            WithingsMeasureClient(
                secret,
                request_json=lambda *args: {"status": 500, "body": {}},
            ).fetch_visceral_fat_history()
        self.assertNotIn(secret, str(caught.exception))
        self.assertNotIn(secret, repr(caught.exception))
        tokens = OAuthTokens(secret, "refresh-secret", "user-id", 100, "user.metrics")
        self.assertEqual(repr(tokens), "OAuthTokens(<redacted>)")

    def test_comparison_detects_present_and_new_readings(self):
        readings = parse_visceral_fat_groups(
            [group("a"), group("b", timestamp=1_700_000_100)]
        )
        present, new = compare_readings(
            readings, [(readings[0].timestamp_utc, readings[0].value)]
        )
        self.assertEqual(present, [readings[0]])
        self.assertEqual(new, [readings[1]])

    def test_comparison_reconciles_delayed_home_assistant_updates_once(self):
        readings = parse_visceral_fat_groups(
            [
                group("a", timestamp=1_700_000_000, value=84),
                group("b", timestamp=1_700_000_100, value=84),
            ]
        )
        delayed_update = readings[0].timestamp_utc.replace(
            microsecond=0
        ) + timedelta(hours=5)
        present, new = compare_readings(readings, [(delayed_update, 8.4)])
        self.assertEqual(len(present), 1)
        self.assertEqual(len(new), 1)

    def test_history_measurements_are_metric_only_and_idempotent(self):
        readings = parse_visceral_fat_groups(
            [
                group("existing", timestamp=1_700_000_000, value=84),
                group("new", timestamp=1_700_000_100, value=83),
            ]
        )
        existing = WeightMeasurement.create(
            captured_at=readings[0].timestamp_utc.isoformat(
                sep=" ", timespec="seconds"
            ),
            source_timestamp=readings[0].timestamp_utc.isoformat(
                sep=" ", timespec="seconds"
            ),
            source_entity="sensor.withings_weight",
            visceral_fat_index=8.4,
            reading_hash="home-assistant-reading",
            metadata={},
        )
        proposed = build_history_measurements(readings, [existing])
        self.assertEqual(len(proposed), 1)
        measurement = proposed[0]
        self.assertEqual(measurement.visceral_fat_index, 8.3)
        self.assertEqual(
            measurement.source_entity, "withings_public_api_history"
        )
        self.assertEqual(
            measurement.import_source, "withings_public_api_history"
        )
        self.assertEqual(
            measurement.source_timestamp,
            readings[1].timestamp_utc.isoformat(sep=" ", timespec="seconds"),
        )
        for field in (
            "weight_kg",
            "body_fat_percent",
            "fat_mass_kg",
            "fat_free_mass_kg",
            "muscle_mass_kg",
            "bone_mass_kg",
            "hydration_kg",
            "heart_rate_bpm",
            "withings_goal_kg",
        ):
            self.assertIsNone(getattr(measurement, field))
        self.assertEqual(
            build_history_measurements(readings, [existing, measurement]), []
        )

    def test_history_import_rerun_uses_database_api_without_duplicates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = WeightProgressDatabase(Path(temp_dir) / "weight.db")
            database.initialize()
            reading = parse_visceral_fat_groups([group("stable")])
            first = build_history_measurements(
                reading, database.query_measurements()
            )
            self.assertEqual(len(first), 1)
            self.assertTrue(database.insert_measurement(first[0]))
            second = build_history_measurements(
                reading, database.query_measurements()
            )
            self.assertEqual(second, [])
            self.assertEqual(database.count_measurements(), 1)

    def test_database_backup_is_consistent_and_separate(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            data_dir.mkdir()
            source_path = data_dir / "weight.db"
            connection = sqlite3.connect(source_path)
            connection.execute("CREATE TABLE marker (value TEXT)")
            connection.execute("INSERT INTO marker VALUES ('preserved')")
            connection.commit()
            connection.close()
            with patch("scripts.withings_audit.PROJECT_ROOT", root):
                backup_path = backup_weight_progress_database(source_path)
            self.assertNotEqual(backup_path, source_path)
            backup = sqlite3.connect(backup_path)
            try:
                self.assertEqual(
                    backup.execute("SELECT value FROM marker").fetchone()[0],
                    "preserved",
                )
            finally:
                backup.close()

    def test_homepulse_audit_database_access_is_read_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "weight.db"
            connection = sqlite3.connect(path)
            connection.execute(
                """
                CREATE TABLE weight_measurements (
                    visceral_fat_index REAL,
                    source_timestamp TEXT,
                    metadata_json TEXT
                )
                """
            )
            connection.execute(
                "INSERT INTO weight_measurements VALUES (?, ?, ?)",
                (8.4, "2026-07-20 01:35:21+00:00", "{}"),
            )
            connection.commit()
            connection.close()
            before = path.read_bytes()

            class FakeConfig:
                def get(self, *keys, default=None):
                    return str(path)

            with patch("scripts.withings_audit.PROJECT_ROOT", Path(temp_dir)):
                readings = load_homepulse_visceral_readings(FakeConfig())
            self.assertEqual(len(readings), 1)
            self.assertEqual(path.read_bytes(), before)

    def test_synthetic_response_shape_fixture(self):
        fixture = Path("tests/fixtures/withings_type170_synthetic_shape.json")
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        self.assertIs(payload["captured_from_real_response"], False)
        self.assertIs(payload["synthetic_fixture"], True)
        self.assertEqual(payload["reading_count"], 2)
        self.assertEqual(payload["duplicate_count"], 1)
        self.assertIsInstance(payload["pages"], list)
        serialized = json.dumps(payload).lower()
        for forbidden in ("access_token", "refresh_token", "userid", "client_secret"):
            self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()
