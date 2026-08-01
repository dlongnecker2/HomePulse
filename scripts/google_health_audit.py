"""Configure, authorize, and audit Google Health without database writes."""

from __future__ import annotations

import argparse
import getpass
import json
import sqlite3
import sys
import threading
import webbrowser
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.health_insights.google_health import (  # noqa: E402
    ACTIVITY_SCOPE,
    ALL_SCOPES,
    API_BASE,
    CALLBACK_URI,
    DEFAULT_JOURNEY_START,
    NUTRITION_SCOPE,
    SLEEP_SCOPE,
    GoogleHealthClient,
    GoogleHealthError,
    GoogleOAuthClient,
    aggregate_daily_nutrition,
    atomic_write_json,
    classify_exercise,
    configure_credentials,
    granted_scopes,
    load_local_credentials,
    load_local_tokens,
    local_credentials_path,
    local_tokens_path,
    missing_scopes,
    normalize_exercise_point,
    normalize_nutrition_point,
    normalize_rollup_value,
    normalize_sleep_point,
    parse_datetime,
    rollup_local_date,
    sanitized_shape,
    save_tokens,
    scope_name,
    source_identity,
    stable_record_key,
    validate_callback,
    generate_pkce_pair,
)
from modules.weight_progress.models import WeightMeasurement  # noqa: E402


RAW_DATA_TYPES = (
    ("nutrition-log", NUTRITION_SCOPE, True),
    ("steps", ACTIVITY_SCOPE, False),
    ("exercise", ACTIVITY_SCOPE, True),
    ("active-energy-burned", ACTIVITY_SCOPE, False),
    ("active-minutes", ACTIVITY_SCOPE, False),
    ("active-zone-minutes", ACTIVITY_SCOPE, False),
    ("distance", ACTIVITY_SCOPE, False),
    ("sleep", SLEEP_SCOPE, True),
)
ROLLUP_DATA_TYPES = (
    ("nutrition-log", NUTRITION_SCOPE),
    ("steps", ACTIVITY_SCOPE),
    ("active-energy-burned", ACTIVITY_SCOPE),
    ("total-calories", ACTIVITY_SCOPE),
    ("active-minutes", ACTIVITY_SCOPE),
    ("active-zone-minutes", ACTIVITY_SCOPE),
    ("distance", ACTIVITY_SCOPE),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="HomePulse read-only Google Health OAuth and data audit."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    configure = subparsers.add_parser(
        "configure", help="Import a downloaded Google OAuth credentials JSON file."
    )
    configure.add_argument("--credentials-file", required=True)
    configure.add_argument(
        "--timezone",
        help="IANA timezone override only when HomePulse cannot detect the Windows timezone.",
    )

    authorize = subparsers.add_parser(
        "authorize", help="Authorize with a short-lived local browser callback."
    )
    authorize.add_argument(
        "--callback-timeout",
        type=int,
        default=180,
        help="Seconds to wait for the one local callback (default: 180).",
    )
    authorize.add_argument(
        "--no-browser",
        action="store_true",
        help="Print the authorization URL instead of opening the default browser.",
    )

    subparsers.add_parser("status", help="Show sanitized local authorization status.")

    audit = subparsers.add_parser(
        "audit", help="Run a real read-only API and Withings overlap audit."
    )
    audit.add_argument("--from-date", default=DEFAULT_JOURNEY_START.isoformat())
    audit.add_argument("--through-date", default=None)
    audit.add_argument(
        "--output",
        help="Optional JSON output path under data/health_insights (never a database).",
    )
    return parser


def command_configure(args: argparse.Namespace) -> int:
    result = configure_credentials(
        args.credentials_file,
        PROJECT_ROOT,
        timezone_name=args.timezone,
    )
    for key in (
        "credential_file_recognized",
        "client_id_present",
        "client_secret_present",
        "configured_callback_uri",
        "destination_configuration_path",
    ):
        print(f"{key}: {safe_scalar(result[key])}")
    return 0


def command_status(_: argparse.Namespace) -> int:
    configured = local_credentials_path(PROJECT_ROOT).exists()
    credentials = {}
    if configured:
        try:
            credentials = load_local_credentials(PROJECT_ROOT)
        except GoogleHealthError:
            configured = False
    tokens = load_local_tokens(PROJECT_ROOT, required=False)
    granted = granted_scopes(tokens)
    expires_at = parse_datetime(tokens.get("expires_at"))
    refresh_expires_at = parse_datetime(tokens.get("refresh_token_expires_at"))
    now = datetime.now(timezone.utc)
    refresh_present = bool(tokens.get("refresh_token"))
    access_present = bool(tokens.get("access_token"))
    missing = missing_scopes(tokens)
    authorized = access_present and not missing
    reauthorization_needed = (
        not authorized
        or not refresh_present
        or (refresh_expires_at is not None and refresh_expires_at <= now)
    )
    testing_implication = (
        "time-limited refresh token detected"
        if refresh_expires_at is not None
        else "not detectable; Testing mode refresh tokens expire after 7 days"
    )
    status = {
        "configured": configured,
        "authorized": authorized,
        "granted_scopes": sorted(scope_name(value) for value in granted),
        "refresh_token_present": refresh_present,
        "access_token_expiration_time": expires_at.isoformat() if expires_at else None,
        "reauthorization_needed": reauthorization_needed,
        "testing_mode_implication": testing_implication,
        "configuration_file_used": str(local_credentials_path(PROJECT_ROOT)),
        "windows_account": getpass.getuser(),
        "callback_uri": credentials.get("callback_uri") if configured else CALLBACK_URI,
    }
    print_json(status)
    return 0


def command_authorize(args: argparse.Namespace) -> int:
    credentials = load_local_credentials(PROJECT_ROOT)
    state = _random_state()
    verifier, challenge = generate_pkce_pair()
    oauth = GoogleOAuthClient(credentials)
    authorization_url = oauth.authorization_url(state, code_challenge=challenge)
    result: dict[str, object] = {}
    server = _callback_server(state, result)
    server.timeout = max(10, min(int(args.callback_timeout), 600))

    if args.no_browser:
        print("Open this Google authorization URL in your browser:")
        print(authorization_url)
    else:
        print("Opening Google authorization in your default browser.")
        try:
            opened = webbrowser.open(authorization_url, new=1, autoraise=True)
        except OSError:
            opened = False
        if not opened:
            print("The browser did not open. Open this URL manually:")
            print(authorization_url)
    print(f"Waiting for the local callback at {CALLBACK_URI}")
    server.handle_request()
    server.server_close()

    callback_error = result.get("error")
    if isinstance(callback_error, GoogleHealthError):
        raise callback_error
    code = result.get("code")
    if not isinstance(code, str) or not code:
        raise GoogleHealthError(
            "No OAuth callback was received before the listener closed.",
            callback_match=False,
            credentials_present=True,
            requested_scopes=ALL_SCOPES,
        )
    token_response = oauth.exchange_code(code, code_verifier=verifier)
    stored = save_tokens(PROJECT_ROOT, token_response)
    missing = missing_scopes(stored)
    if missing:
        raise GoogleHealthError(
            "Google authorization returned only partial consent; reauthorization is required.",
            error_name="partial_consent",
            description="Missing requested read-only scopes: "
            + ", ".join(sorted(scope_name(value) for value in missing)),
            callback_match=True,
            credentials_present=True,
            requested_scopes=ALL_SCOPES,
        )
    print("Google Health authorization completed and tokens were stored locally.")
    return 0


def _callback_server(expected_state: str, result: dict[str, object]) -> HTTPServer:
    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            try:
                validated = validate_callback(self.path, expected_state=expected_state)
                result["code"] = validated["code"]
                status = 200
                body = (
                    "<!doctype html><title>HomePulse</title>"
                    "<p>Google Health authorization was received. "
                    "You can close this window and return to PowerShell.</p>"
                )
            except GoogleHealthError as exc:
                result["error"] = exc
                status = 400
                body = (
                    "<!doctype html><title>HomePulse</title>"
                    "<p>Authorization was not completed. "
                    "Close this window and review the sanitized PowerShell error.</p>"
                )
            raw = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, format, *args):  # noqa: A002
            return

    parsed = urlsplit(CALLBACK_URI)
    try:
        return HTTPServer(
            (parsed.hostname or "127.0.0.1", parsed.port or 8765),
            CallbackHandler,
        )
    except OSError as exc:
        raise GoogleHealthError(
            "The local OAuth callback listener could not start.",
            description=type(exc).__name__,
            callback_match=False,
            credentials_present=True,
            requested_scopes=ALL_SCOPES,
        ) from None


def command_audit(args: argparse.Namespace) -> int:
    start_date = parse_date_argument(args.from_date, "--from-date")
    credentials = load_local_credentials(PROJECT_ROOT)
    timezone_name = str(credentials["timezone"])
    today = datetime.now().astimezone().date()
    end_date = parse_date_argument(args.through_date, "--through-date") if args.through_date else today
    if end_date < start_date:
        raise GoogleHealthError("Audit through date cannot precede the from date.")
    tokens = load_local_tokens(PROJECT_ROOT)
    missing = missing_scopes(tokens)
    if missing:
        raise GoogleHealthError(
            "Google Health authorization is missing required read-only scopes.",
            error_name="partial_consent",
            description=", ".join(sorted(scope_name(value) for value in missing)),
            credentials_present=True,
            requested_scopes=ALL_SCOPES,
        )

    client = GoogleHealthClient(PROJECT_ROOT)
    report: dict[str, object] = {
        "audit_mode": "read-only; no HomePulse database writes",
        "api_base": API_BASE,
        "timezone": timezone_name,
        "period": {"from": start_date.isoformat(), "through": end_date.isoformat()},
        "granted_scopes": sorted(scope_name(value) for value in granted_scopes(tokens)),
        "data_types": {},
        "linked_foods": {},
    }
    raw_by_type: dict[str, list[dict[str, object]]] = {}

    for data_type, scope, full_history_practical in RAW_DATA_TYPES:
        request_start = client.request_count
        try:
            if full_history_practical:
                all_points, stats = client.list_data_points(data_type)
                journey_points = [
                    point
                    for point in all_points
                    if _point_in_range(point, data_type, timezone_name, start_date, end_date)
                ]
                earliest_available = _point_date(
                    min(
                        all_points,
                        key=lambda item: _point_sort_value(item, data_type),
                        default=None,
                    ),
                    data_type,
                    timezone_name,
                )
            else:
                journey_points, stats = client.list_data_points(
                    data_type,
                    start_date=start_date,
                    end_date=end_date,
                )
                earliest_available = None
            raw_by_type[data_type] = journey_points
            stats["requests"] = client.request_count - request_start
            report["data_types"][data_type] = summarize_raw_type(
                data_type,
                scope,
                journey_points,
                stats,
                start_date,
                end_date,
                timezone_name,
                earliest_available=earliest_available,
                full_history_probed=full_history_practical,
            )
        except GoogleHealthError as exc:
            raw_by_type[data_type] = []
            report["data_types"][data_type] = failed_data_type_summary(
                data_type,
                scope,
                client.request_count - request_start,
                exc,
                operation="list",
            )

    rollups: dict[str, list[dict[str, object]]] = {}
    for data_type, scope in ROLLUP_DATA_TYPES:
        request_start = client.request_count
        try:
            points, stats = client.daily_rollups(data_type, start_date, end_date)
            rollups[data_type] = points
            report["data_types"][f"{data_type}:dailyRollUp"] = summarize_rollup_type(
                data_type,
                scope,
                points,
                stats,
                start_date,
                end_date,
            )
        except GoogleHealthError as exc:
            rollups[data_type] = []
            report["data_types"][
                f"{data_type}:dailyRollUp"
            ] = failed_data_type_summary(
                data_type,
                scope,
                client.request_count - request_start,
                exc,
                operation="dailyRollUp",
            )

    food_references = sorted(
        {
            str((point.get("nutritionLog") or {}).get("food"))
            for point in raw_by_type["nutrition-log"]
            if (point.get("nutritionLog") or {}).get("food")
        }
    )
    food_shapes = []
    food_errors = []
    food_request_start = client.request_count
    for reference in food_references:
        try:
            food_shapes.append(sanitized_shape(client.get_data_point(reference)))
        except GoogleHealthError as exc:
            food_errors.append(exc.diagnostics())
    report["linked_foods"] = {
        "endpoint": f"{API_BASE}/users/me/dataTypes/food/dataPoints/{{record}}",
        "linked_references": len(food_references),
        "requests": client.request_count - food_request_start,
        "records_returned": len(food_shapes),
        "errors": food_errors,
        "sanitized_sample_shape": food_shapes[0] if food_shapes else None,
    }

    daily_nutrition = aggregate_daily_nutrition(
        raw_by_type["nutrition-log"], timezone_name, start_date, end_date
    )
    nutrition_classification = classify_nutrition_history(
        raw_by_type["nutrition-log"], daily_nutrition
    )
    exercises = [
        normalize_exercise_point(point, timezone_name)
        for point in raw_by_type["exercise"]
    ]
    sleep = [
        normalize_sleep_point(point, timezone_name)
        for point in raw_by_type["sleep"]
    ]
    report["nutrition_quality"] = {
        "classification": nutrition_classification,
        "mynetdiary_identification": identify_mynetdiary(raw_by_type["nutrition-log"]),
        "daily_availability": [
            {
                "date": day.local_date,
                "calories": day.calories_kcal is not None,
                "protein": day.protein_g is not None,
                "carbohydrates": day.carbohydrates_g is not None,
                "fat": day.fat_g is not None,
                "fiber": day.fiber_g is not None,
                "sodium": day.sodium_mg is not None,
                "completeness": day.completeness,
            }
            for day in daily_nutrition
        ],
    }
    report["activity_quality"] = {
        "fitbit_identification": identify_fitbit(
            point
            for data_type in (
                "steps",
                "exercise",
                "active-energy-burned",
                "active-minutes",
                "active-zone-minutes",
                "distance",
            )
            for point in raw_by_type[data_type]
        ),
        "exercise_categories": dict(Counter(item.category for item in exercises)),
        "calorie_source_of_truth": (
            "Daily total-calories is overall estimated expenditure. "
            "Active energy and exercise calories are reported as overlapping components "
            "and are never added to total calories."
        ),
    }
    report["sleep_quality"] = {
        "sessions": len(sleep),
        "days_with_sleep": len({item.local_date for item in sleep if item.local_date}),
        "summary_stage_totals_available": any(
            item.deep_minutes is not None
            or item.light_minutes is not None
            or item.rem_minutes is not None
            for item in sleep
        ),
        "granular_stages_retained": False,
    }
    report["withings_weight_overlap"] = read_weight_trend(
        start_date, end_date, timezone_name
    )
    report["feasibility"] = correlation_feasibility(
        daily_nutrition,
        rollups.get("steps", []),
        report["withings_weight_overlap"],
    )
    report["request_count_total"] = client.request_count
    report["production_health_database_written"] = False

    if args.output:
        destination = Path(args.output)
        if not destination.is_absolute():
            destination = PROJECT_ROOT / destination
        allowed = (PROJECT_ROOT / "data" / "health_insights").resolve()
        try:
            destination.resolve().relative_to(allowed)
        except ValueError as exc:
            raise GoogleHealthError(
                "Audit output must stay under data/health_insights."
            ) from exc
        atomic_write_json(destination, report)
        print(f"Sanitized audit report stored at: {destination}")
    print_json(report)
    return 0


def summarize_raw_type(
    data_type,
    scope,
    points,
    stats,
    start_date,
    end_date,
    timezone_name,
    *,
    earliest_available,
    full_history_probed,
):
    keys = [stable_record_key(point) for point in points]
    unique = len(set(keys))
    dates = [
        value
        for value in (_point_date(point, data_type, timezone_name) for point in points)
        if value
    ]
    source_counter = Counter(
        (
            source_identity(point)["platform"],
            source_identity(point)["application_kind"],
            source_identity(point)["application_id_hash"],
        )
        for point in points
    )
    days_in_period = (end_date - start_date).days + 1
    days_with_data = len(set(dates))
    endpoint = f"{API_BASE}/users/me/dataTypes/{data_type}/dataPoints"
    return {
        "scope_granted": scope_name(scope),
        "endpoint_called": endpoint,
        "requests": stats["requests"],
        "pagination_pages": stats["pages"],
        "records_returned": len(points),
        "earliest_record_in_period": min(dates) if dates else None,
        "latest_record_in_period": max(dates) if dates else None,
        "earliest_available_record": earliest_available,
        "full_history_probed": full_history_probed,
        "unique_records": unique,
        "duplicate_count": len(keys) - unique,
        "source_platform_distribution": [
            {
                "platform": platform,
                "application_kind": kind,
                "application_id_hash": app_hash or None,
                "records": count,
            }
            for (platform, kind, app_hash), count in sorted(source_counter.items())
        ],
        "days_with_data": days_with_data,
        "missing_days": max(0, days_in_period - days_with_data),
        "history_reaches_journey_start": start_date.isoformat() in set(dates),
        "suitable_for_daily_reports": days_with_data >= 7,
        "sanitized_sample_shape": sanitized_shape(points[0]) if points else None,
        "official_list_range_limit": "none documented",
        "client_chunking_used": "none",
    }


def summarize_rollup_type(data_type, scope, points, stats, start_date, end_date):
    dated_values = [
        (rollup_local_date(point), normalize_rollup_value(data_type, point))
        for point in points
    ]
    value_dates = {
        local_date
        for local_date, value in dated_values
        if local_date and value is not None
    }
    all_dates = [local_date for local_date, _ in dated_values if local_date]
    days_with_values = len(value_dates)
    days_in_period = (end_date - start_date).days + 1
    return {
        "scope_granted": scope_name(scope),
        "endpoint_called": (
            f"{API_BASE}/users/me/dataTypes/{data_type}/dataPoints:dailyRollUp"
        ),
        "requests": stats["requests"],
        "pagination_pages": stats["requests"],
        "records_returned": len(points),
        "earliest_record": min(value_dates) if value_dates else None,
        "latest_record": max(value_dates) if value_dates else None,
        "unique_records": len(set(all_dates)),
        "duplicate_count": len(all_dates) - len(set(all_dates)),
        "source_platform_distribution": "not returned by rollup endpoint",
        "days_with_data": days_with_values,
        "missing_days": max(0, days_in_period - days_with_values),
        "history_reaches_journey_start": start_date.isoformat() in value_dates,
        "suitable_for_daily_reports": days_with_values >= 7,
        "sanitized_sample_shape": sanitized_shape(points[0]) if points else None,
        "official_date_range_limit_days": stats["maximum_range_days"],
        "chunks_used": stats["chunks"],
    }


def failed_data_type_summary(data_type, scope, requests, error, *, operation):
    endpoint_suffix = (
        f"users/me/dataTypes/{data_type}/dataPoints:dailyRollUp"
        if operation == "dailyRollUp"
        else f"users/me/dataTypes/{data_type}/dataPoints"
    )
    return {
        "scope_granted": scope_name(scope),
        "endpoint_called": f"{API_BASE}/{endpoint_suffix}",
        "requests": requests,
        "pagination_pages": 0,
        "records_returned": 0,
        "earliest_record": None,
        "latest_record": None,
        "unique_records": 0,
        "duplicate_count": 0,
        "source_platform_distribution": [],
        "days_with_data": 0,
        "missing_days": None,
        "history_reaches_journey_start": False,
        "suitable_for_daily_reports": False,
        "sanitized_sample_shape": None,
        "error": error.diagnostics(),
    }


def identify_mynetdiary(points):
    identities = [source_identity(point) for point in points]
    explicit = [
        identity
        for identity in identities
        if "mynetdiary" in identity["package_name"].lower()
    ]
    if explicit:
        return {
            "identifiable": True,
            "evidence": "Returned application package name contains MyNetDiary.",
            "records": len(explicit),
        }
    if points:
        return {
            "identifiable": False,
            "evidence": (
                "Nutrition records exist, but returned platform/application metadata "
                "does not explicitly identify MyNetDiary."
            ),
            "records": len(points),
        }
    return {
        "identifiable": False,
        "evidence": "No nutrition-log records were returned.",
        "records": 0,
    }


def identify_fitbit(points):
    identities = [source_identity(point) for point in points]
    count = sum(identity["platform"] == "FITBIT" for identity in identities)
    legacy = sum(identity["platform"] == "FITBIT_WEB_API" for identity in identities)
    return {
        "identifiable": count > 0,
        "fitbit_records": count,
        "legacy_fitbit_web_api_records": legacy,
        "evidence": (
            "Google Health dataSource.platform equals FITBIT."
            if count
            else "No returned activity record had dataSource.platform FITBIT."
        ),
    }


def classify_nutrition_history(points, daily):
    if not points:
        return "E. No MyNetDiary nutrition data found"
    identified = identify_mynetdiary(points)["identifiable"]
    complete_days = sum(item.completeness == "complete" for item in daily)
    data_days = sum(item.completeness not in {"no data", "unknown"} for item in daily)
    if not identified:
        return "F. Records exist but the source cannot be confidently identified"
    if data_days and complete_days >= max(1, int(data_days * 0.8)):
        return "A. Complete or nearly complete daily nutrition history"
    if any((point.get("nutritionLog") or {}).get("food") for point in points):
        return "C. Individual foods present but daily totals require aggregation"
    if data_days:
        return "B. Only recent or partial nutrition history"
    return "D. Daily totals present but food detail absent"


def read_weight_trend(
    start_date: date,
    end_date: date,
    timezone_name: str | None = None,
) -> dict[str, object]:
    config_path = PROJECT_ROOT / "config.json"
    if not config_path.exists():
        return {"available": False, "reason": "HomePulse config.json was not found."}
    config = json.loads(config_path.read_text(encoding="utf-8"))
    relative_database = Path(
        (config.get("weight_progress") or {}).get("database")
        or "data/weight_progress.db"
    )
    database_path = (
        relative_database
        if relative_database.is_absolute()
        else PROJECT_ROOT / relative_database
    )
    if not database_path.exists():
        return {"available": False, "reason": "Weight Progress database was not found."}
    measurements = _query_weight_measurements_immutable(database_path)
    by_day = {}
    for item in measurements:
        parsed = _parse_weight_timestamp(item.source_timestamp, timezone_name)
        if parsed is None:
            continue
        local_day = parsed.date()
        if start_date <= local_day <= end_date:
            previous = by_day.get(local_day)
            if previous is None or parsed >= previous[0]:
                by_day[local_day] = (parsed, item)
    trend = []
    for day in sorted(by_day):
        item = by_day[day][1]
        window_start = day - timedelta(days=6)
        weights = [
            measurement.weight_kg
            for measurement_day, (_, measurement) in by_day.items()
            if window_start <= measurement_day <= day
            and measurement.weight_kg is not None
        ]
        body_fat = item.body_fat_percent
        if body_fat is None and item.fat_mass_kg is not None and item.weight_kg:
            body_fat = item.fat_mass_kg / item.weight_kg * 100.0
        muscle_percentage = (
            item.muscle_mass_kg / item.weight_kg * 100.0
            if item.muscle_mass_kg is not None and item.weight_kg
            else None
        )
        trend.append(
            {
                "date": day.isoformat(),
                "weight_lb": round(item.weight_kg * 2.2046226218, 2)
                if item.weight_kg is not None
                else None,
                "seven_day_average_weight_lb": round(
                    sum(weights) / len(weights) * 2.2046226218, 2
                )
                if weights
                else None,
                "body_fat_percentage": round(body_fat, 2)
                if body_fat is not None
                else None,
                "muscle_percentage": round(muscle_percentage, 2)
                if muscle_percentage is not None
                else None,
                "visceral_fat_index": item.visceral_fat_index,
            }
        )
    return {
        "available": bool(trend),
        "repository": "immutable SQLite query (mode=ro)",
        "database_written": False,
        "measurement_days": len(trend),
        "earliest": trend[0]["date"] if trend else None,
        "latest": trend[-1]["date"] if trend else None,
        "history_reaches_journey_start": (
            trend[0]["date"] <= start_date.isoformat() if trend else False
        ),
        "daily_trend": trend,
    }


def _query_weight_measurements_immutable(database_path: Path) -> list[WeightMeasurement]:
    uri = f"{database_path.resolve().as_uri()}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        rows = connection.execute(
            """
            SELECT captured_at, source_timestamp, source_entity, weight_kg,
                   body_fat_percent, fat_mass_kg, fat_free_mass_kg,
                   muscle_mass_kg, bone_mass_kg, hydration_kg,
                   visceral_fat_index, heart_rate_bpm, scale_battery, comments,
                   import_source, source_label, imported_at, withings_goal_kg,
                   reading_hash, metadata_json
            FROM weight_measurements
            ORDER BY source_timestamp ASC, id ASC
            """
        ).fetchall()
    finally:
        connection.close()
    return [WeightMeasurement.from_row(row) for row in rows]


def _parse_weight_timestamp(value, timezone_name):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        if timezone_name:
            return parsed.replace(tzinfo=ZoneInfo(timezone_name))
        return parsed.astimezone()
    if timezone_name:
        return parsed.astimezone(ZoneInfo(timezone_name))
    return parsed.astimezone()


def correlation_feasibility(daily_nutrition, step_rollups, weight_report):
    complete_nutrition_days = {
        item.local_date for item in daily_nutrition if item.completeness == "complete"
    }
    step_days = {
        rollup_local_date(point)
        for point in step_rollups
        if normalize_rollup_value("steps", point) is not None
    }
    weight_days = {
        item["date"]
        for item in weight_report.get("daily_trend", [])
        if item.get("seven_day_average_weight_lb") is not None
    }
    overlap = complete_nutrition_days & step_days & weight_days
    return {
        "complete_nutrition_activity_weight_overlap_days": len(overlap),
        "meaningful_correlations_feasible": len(overlap) >= 14,
        "minimum_policy": (
            "At least 14 complete overlapping days before showing a correlation; "
            "report sample size and suppress sparse results."
        ),
        "causation_claimed": False,
    }


def _point_in_range(point, data_type, timezone_name, start_date, end_date):
    value = _point_date(point, data_type, timezone_name)
    return bool(value and start_date.isoformat() <= value <= end_date.isoformat())


def _point_date(point, data_type, timezone_name):
    if not point:
        return None
    if data_type == "nutrition-log":
        return normalize_nutrition_point(point, timezone_name)["local_date"]
    if data_type == "exercise":
        return normalize_exercise_point(point, timezone_name).local_date
    if data_type == "sleep":
        return normalize_sleep_point(point, timezone_name).local_date
    if data_type == "daily-resting-heart-rate":
        payload = point.get("dailyRestingHeartRate") or {}
        date_value = payload.get("date") or {}
        try:
            return date(
                int(date_value["year"]),
                int(date_value["month"]),
                int(date_value["day"]),
            ).isoformat()
        except (KeyError, TypeError, ValueError):
            return None
    field_names = {
        "steps": "steps",
        "active-energy-burned": "activeEnergyBurned",
        "active-minutes": "activeMinutes",
        "active-zone-minutes": "activeZoneMinutes",
        "distance": "distance",
    }
    interval = (point.get(field_names[data_type]) or {}).get("interval") or {}
    civil = interval.get("civilStartTime") or {}
    date_value = civil.get("date") or {}
    try:
        return date(
            int(date_value["year"]),
            int(date_value["month"]),
            int(date_value["day"]),
        ).isoformat()
    except (KeyError, TypeError, ValueError):
        parsed = parse_datetime(interval.get("startTime"))
        return parsed.astimezone().date().isoformat() if parsed else None


def _point_sort_value(point, data_type):
    if point is None:
        return ""
    payload_keys = {
        "nutrition-log": "nutritionLog",
        "steps": "steps",
        "exercise": "exercise",
        "active-energy-burned": "activeEnergyBurned",
        "active-minutes": "activeMinutes",
        "active-zone-minutes": "activeZoneMinutes",
        "distance": "distance",
        "sleep": "sleep",
    }
    if data_type == "daily-resting-heart-rate":
        value = (point.get("dailyRestingHeartRate") or {}).get("date") or {}
        return f"{value.get('year', 0):04}-{value.get('month', 0):02}-{value.get('day', 0):02}"
    interval = (point.get(payload_keys[data_type]) or {}).get("interval") or {}
    return str(
        interval.get("startTime")
        or interval.get("endTime")
        or interval.get("civilStartTime")
        or interval.get("civilEndTime")
        or ""
    )


def parse_date_argument(value, label):
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise GoogleHealthError(f"{label} must use YYYY-MM-DD format.") from exc


def safe_scalar(value):
    if value is None:
        return "none"
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def print_json(payload):
    print(json.dumps(payload, indent=2, sort_keys=True))


def _random_state():
    import secrets

    return secrets.token_urlsafe(32)


def print_error(exc: GoogleHealthError) -> None:
    print("Google Health diagnostic failed.", file=sys.stderr)
    print_json_to_stream(exc.diagnostics(), sys.stderr)


def print_json_to_stream(payload, stream):
    print(json.dumps(payload, indent=2, sort_keys=True), file=stream)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    commands = {
        "configure": command_configure,
        "authorize": command_authorize,
        "status": command_status,
        "audit": command_audit,
    }
    try:
        return commands[args.command](args)
    except GoogleHealthError as exc:
        print_error(exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
