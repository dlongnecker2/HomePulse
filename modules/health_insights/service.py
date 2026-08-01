from __future__ import annotations

import json
import math
import sqlite3
import threading
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable
from zoneinfo import ZoneInfo

from modules.health_insights.database import HealthInsightsDatabase
from modules.health_insights.google_health import (
    ALL_SCOPES,
    GoogleHealthClient,
    GoogleHealthError,
    granted_scopes,
    interval_local_date,
    load_local_credentials,
    load_local_tokens,
    missing_scopes,
    detect_homepulse_timezone,
    normalize_exercise_point,
    normalize_nutrition_point,
    normalize_rollup_value,
    normalize_sleep_point,
    parse_datetime,
    rollup_local_date,
    source_identity,
)
from modules.health_insights.models import DailyHealthInsight
from modules.weight_progress.models import WeightMeasurement


MINIMUM_COMPLETE_DAYS = 14
RECENT_REFRESH_DAYS = 7
METERS_PER_MILE = 1609.344
NUTRITION_FIELDS = (
    "nutrition_calories",
    "protein_grams",
    "carbohydrate_grams",
    "fat_grams",
    "fiber_grams",
    "sodium_milligrams",
)
ACTIVITY_ROLLUPS = {
    "steps": "steps",
    "total-calories": "total_calories_burned",
    "active-energy-burned": "active_energy_calories",
    "active-minutes": "active_minutes",
    "active-zone-minutes": "active_zone_minutes",
    "distance": "distance_miles",
}


class HealthInsightsError(RuntimeError):
    pass


def normalize_nutrition_rollups(
    rollups: Iterable[dict],
    raw_points: Iterable[dict],
    timezone_name: str,
) -> dict[str, dict]:
    raw_by_day: dict[str, list[dict]] = defaultdict(list)
    for point in raw_points or []:
        normalized = normalize_nutrition_point(point, timezone_name)
        if normalized.get("local_date"):
            raw_by_day[normalized["local_date"]].append(normalized)

    output: dict[str, dict] = {}
    platforms_by_day: dict[str, set[str]] = defaultdict(set)
    rollup_counts: dict[str, int] = defaultdict(int)
    for point in rollups or []:
        local_date = rollup_local_date(point)
        if not local_date:
            continue
        normalized = normalize_rollup_value("nutrition-log", point)
        if not isinstance(normalized, dict):
            normalized = {}
        rollup_counts[local_date] += 1
        platform = source_identity(point).get("platform")
        if platform and platform != "PLATFORM_UNSPECIFIED":
            platforms_by_day[local_date].add(platform)
        existing = output.setdefault(local_date, {})
        for source_name, destination in (
            ("calories_kcal", "nutrition_calories"),
            ("protein_g", "protein_grams"),
            ("carbohydrates_g", "carbohydrate_grams"),
            ("fat_g", "fat_grams"),
            ("fiber_g", "fiber_grams"),
            ("sodium_mg", "sodium_milligrams"),
        ):
            value = normalized.get(source_name)
            if value is not None:
                existing[destination] = value

    all_days = set(output) | set(raw_by_day)
    for local_date in all_days:
        rows = raw_by_day.get(local_date, [])
        platforms = sorted(
            platforms_by_day.get(local_date, set())
            | {
                str((row.get("source") or {}).get("platform") or "")
                for row in rows
                if str((row.get("source") or {}).get("platform") or "")
            }
        )
        platform = ", ".join(platforms) or None
        values = output.setdefault(local_date, {})
        values["nutrition_platform"] = platform
        values["nutrition_source"] = nutrition_source_label(platforms)
        values["nutrition_record_count"] = (
            len(rows) if rows else rollup_counts.get(local_date, 0)
        )
        values["nutrition_complete"] = all(
            values.get(field_name) is not None for field_name in NUTRITION_FIELDS
        )
    return output


def nutrition_source_label(platforms: Iterable[str]) -> str:
    normalized = {str(value or "").upper() for value in platforms}
    if "FITBIT_WEB_API" in normalized:
        return "Unidentified app via Fitbit Web API"
    if normalized & {"FITBIT", "FITBIT_WEB_API"}:
        return "Fitbit via Google Health"
    return "Google Health"


def normalize_activity_rollups(
    rollups_by_type: dict[str, Iterable[dict]],
) -> dict[str, dict]:
    output: dict[str, dict] = {}
    platforms_by_day: dict[str, set[str]] = defaultdict(set)
    for data_type, destination in ACTIVITY_ROLLUPS.items():
        for point in rollups_by_type.get(data_type, []) or []:
            local_date = rollup_local_date(point)
            if not local_date:
                continue
            value = normalize_rollup_value(data_type, point)
            if value is None:
                continue
            if data_type == "distance":
                value = float(value) / METERS_PER_MILE
            output.setdefault(local_date, {})[destination] = value
            platform = source_identity(point).get("platform")
            if platform and platform != "PLATFORM_UNSPECIFIED":
                platforms_by_day[local_date].add(platform)
    for local_date, values in output.items():
        platforms = platforms_by_day.get(local_date, set())
        values["activity_source"] = activity_source_label(platforms)
        values["activity_complete"] = (
            values.get("steps") is not None
            and values.get("total_calories_burned") is not None
        )
    return output


def activity_source_label(platforms: Iterable[str]) -> str:
    normalized = {str(value or "").upper() for value in platforms}
    if normalized & {"FITBIT", "FITBIT_WEB_API"}:
        return "Fitbit via Google Health"
    return "Google Health"


def aggregate_exercise_sessions(
    points: Iterable[dict],
    timezone_name: str,
) -> dict[str, dict]:
    sessions = [normalize_exercise_point(point, timezone_name) for point in points or []]
    canonical = []
    seen_keys = set()
    seen_intervals = set()
    for session in sorted(
        sessions,
        key=lambda item: (item.local_date or "", item.start_time or "", item.end_time or ""),
    ):
        interval_key = (
            session.local_date,
            session.start_time,
            session.end_time,
            session.exercise_type,
        )
        if session.record_key in seen_keys or interval_key in seen_intervals:
            continue
        seen_keys.add(session.record_key)
        seen_intervals.add(interval_key)
        canonical.append(session)

    grouped: dict[str, list] = defaultdict(list)
    for session in canonical:
        if session.local_date:
            grouped[session.local_date].append(session)
    output = {}
    for local_date, rows in grouped.items():
        minutes = [item.active_minutes for item in rows if item.active_minutes is not None]
        calories = [item.calories_kcal for item in rows if item.calories_kcal is not None]
        platforms = {item.source_platform for item in rows if item.source_platform}
        output[local_date] = {
            "exercise_session_count": len(rows),
            "exercise_minutes": sum(minutes) if minutes else None,
            "exercise_calories": sum(calories) if calories else None,
            "activity_source": activity_source_label(platforms),
        }
    return output


def aggregate_sleep_sessions(
    points: Iterable[dict],
    timezone_name: str,
) -> dict[str, dict]:
    canonical = []
    seen = set()
    for point in points or []:
        sleep = normalize_sleep_point(point, timezone_name)
        identity = (sleep.local_date, sleep.start_time, sleep.end_time)
        if not sleep.local_date or identity in seen:
            continue
        seen.add(identity)
        canonical.append(sleep)
    grouped: dict[str, list] = defaultdict(list)
    for sleep in canonical:
        grouped[sleep.local_date].append(sleep)
    output = {}
    for local_date, rows in grouped.items():
        sleep_values = [item.sleep_minutes for item in rows if item.sleep_minutes is not None]
        awake_values = [item.awake_minutes for item in rows if item.awake_minutes is not None]
        sleep_minutes = sum(sleep_values) if sleep_values else None
        platforms = {
            platform
            for item in rows
            for platform in item.source_platforms
            if platform
        }
        output[local_date] = {
            "sleep_minutes": sleep_minutes,
            "sleep_hours": sleep_minutes / 60.0 if sleep_minutes is not None else None,
            "awake_minutes": sum(awake_values) if awake_values else None,
            "sleep_session_count": len(rows),
            "sleep_complete": sleep_minutes is not None,
            "sleep_source": activity_source_label(platforms),
        }
    return output


class WeightProgressDailyReader:
    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root).resolve()

    def read(self, start_date: date, end_date: date, timezone_name: str) -> dict[str, dict]:
        database_path = self._database_path()
        if not database_path.exists():
            return {}
        measurements = self._query_immutable(database_path)
        timezone_info = ZoneInfo(timezone_name)
        readings = []
        for index, measurement in enumerate(measurements):
            weight_kg = _finite_positive(measurement.weight_kg)
            if weight_kg is None:
                continue
            timestamp = self._measurement_timestamp(measurement, timezone_info)
            if timestamp is None:
                continue
            readings.append((timestamp, index, weight_kg, measurement))
        readings.sort(key=lambda item: (item[0], item[1]))
        canonical = []
        for reading in readings:
            if canonical:
                previous = canonical[-1]
                elapsed = abs((reading[0] - previous[0]).total_seconds())
                pounds_delta = abs((reading[2] - previous[2]) * 2.2046226218)
                if (
                    reading[0].date() == previous[0].date()
                    and elapsed <= 300
                    and pounds_delta <= 0.2
                ):
                    canonical[-1] = reading
                    continue
            canonical.append(reading)

        by_day = {}
        for reading in canonical:
            by_day[reading[0].date()] = reading
        output = {}
        for local_day in sorted(by_day):
            if not (start_date <= local_day <= end_date):
                continue
            _, _, weight_kg, measurement = by_day[local_day]
            window_start = local_day - timedelta(days=6)
            window_weights = [
                item[2]
                for day, item in by_day.items()
                if window_start <= day <= local_day
            ]
            body_fat = _finite_number(measurement.body_fat_percent)
            fat_mass = _finite_number(measurement.fat_mass_kg)
            if body_fat is None and fat_mass is not None and weight_kg > 0:
                body_fat = fat_mass / weight_kg * 100.0
            muscle_mass = _finite_number(measurement.muscle_mass_kg)
            muscle_percentage = (
                muscle_mass / weight_kg * 100.0
                if muscle_mass is not None and 0 < muscle_mass <= weight_kg
                else None
            )
            output[local_day.isoformat()] = {
                "weight_pounds": round(weight_kg * 2.2046226218, 2),
                "seven_day_average_weight_pounds": round(
                    sum(window_weights) / len(window_weights) * 2.2046226218,
                    2,
                ),
                "body_fat_percentage": round(body_fat, 2) if body_fat is not None else None,
                "muscle_percentage": round(muscle_percentage, 2)
                if muscle_percentage is not None
                else None,
                "visceral_fat_index": _finite_number(measurement.visceral_fat_index),
                "weight_available": True,
                "weight_source": "Withings via Weight Progress",
            }
        return output

    def _database_path(self) -> Path:
        config_path = self.project_root / "config.json"
        relative_path = Path("data/weight_progress.db")
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
                configured = (config.get("weight_progress") or {}).get("database")
                if configured:
                    relative_path = Path(str(configured))
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                pass
        return (
            relative_path
            if relative_path.is_absolute()
            else self.project_root / relative_path
        )

    @staticmethod
    def _query_immutable(database_path: Path) -> list[WeightMeasurement]:
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
                       visceral_fat_index, heart_rate_bpm, scale_battery,
                       comments, import_source, source_label, imported_at,
                       withings_goal_kg, reading_hash, metadata_json
                FROM weight_measurements
                ORDER BY source_timestamp ASC, id ASC
                """
            ).fetchall()
        finally:
            connection.close()
        return [WeightMeasurement.from_row(row) for row in rows]

    @staticmethod
    def _measurement_timestamp(measurement, timezone_info):
        raw_timestamp = measurement.source_timestamp
        if measurement.metadata_json:
            try:
                metadata = json.loads(measurement.metadata_json)
                weight_entity = ((metadata.get("entities") or {}).get("weight") or {})
                details = weight_entity.get("metadata") or {}
                raw_timestamp = (
                    details.get("last_updated")
                    or details.get("last_changed")
                    or weight_entity.get("source_timestamp")
                    or metadata.get("original_timestamp")
                    or raw_timestamp
                )
            except (AttributeError, TypeError, json.JSONDecodeError):
                pass
        parsed = parse_datetime(raw_timestamp)
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone_info)
        return parsed.astimezone(timezone_info)


def _finite_number(value):
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _finite_positive(value):
    number = _finite_number(value)
    return number if number is not None and number > 0 else None


class HealthInsightsService:
    def __init__(
        self,
        project_root: str | Path,
        log,
        *,
        database_path: str | Path | None = None,
        client_factory: Callable[[Path], GoogleHealthClient] | None = None,
        weight_reader: WeightProgressDailyReader | None = None,
        now_provider: Callable[[ZoneInfo], datetime] | None = None,
    ):
        self.project_root = Path(project_root).resolve()
        path = Path(database_path or "data/health_insights.db")
        if not path.is_absolute():
            path = self.project_root / path
        self.database = HealthInsightsDatabase(path)
        self.log = log
        self.client_factory = client_factory or (lambda root: GoogleHealthClient(root))
        self.weight_reader = weight_reader or WeightProgressDailyReader(self.project_root)
        self.now_provider = now_provider or (lambda zone: datetime.now(zone))
        self._manual_lock = threading.Lock()
        self._manual_state_lock = threading.Lock()
        self._manual_state = {
            "status": "idle",
            "message": "Ready to refresh health data.",
            "started_at": None,
            "finished_at": None,
        }

    def initialize(self):
        self.database.initialize()
        self.log.info(f"Health Insights database initialized: {self.database.path}")

    def timezone_name(self) -> str:
        try:
            credentials = load_local_credentials(self.project_root)
            name = str(credentials.get("timezone") or "").strip()
            if name:
                ZoneInfo(name)
                return name
        except GoogleHealthError:
            pass
        return detect_homepulse_timezone(self.project_root)

    def local_now(self) -> datetime:
        zone = ZoneInfo(self.timezone_name())
        value = self.now_provider(zone)
        if value.tzinfo is None:
            return value.replace(tzinfo=zone)
        return value.astimezone(zone)

    def default_range(self) -> tuple[date, date]:
        today = self.local_now().date()
        return today - timedelta(days=RECENT_REFRESH_DAYS - 1), today

    def authorization_status(self) -> dict:
        try:
            load_local_credentials(self.project_root)
            tokens = load_local_tokens(self.project_root, required=False)
            refresh_expiry = parse_datetime(tokens.get("refresh_token_expires_at"))
            active = bool(
                tokens.get("access_token")
                and not missing_scopes(tokens, ALL_SCOPES)
                and (
                    refresh_expiry is None
                    or refresh_expiry > datetime.now(timezone.utc)
                )
            )
            return {"configured": True, "authorized": active}
        except GoogleHealthError:
            return {"configured": False, "authorized": False}

    def status(self) -> dict:
        database_status = self.database.status()
        complete_days = database_status["complete_days"]
        return {
            **database_status,
            "timezone": self.timezone_name(),
            "authorization": self.authorization_status(),
            "minimum_complete_days": MINIMUM_COMPLETE_DAYS,
            "days_needed": max(MINIMUM_COMPLETE_DAYS - complete_days, 0),
            "correlations_ready": complete_days >= MINIMUM_COMPLETE_DAYS,
        }

    def preview(
        self,
        start_date: date,
        end_date: date,
        *,
        now: datetime | None = None,
    ) -> dict:
        current_time = now or self.local_now()
        timezone_name = self.timezone_name()
        zone = ZoneInfo(timezone_name)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=zone)
        else:
            current_time = current_time.astimezone(zone)
        self._validate_range(start_date, end_date, current_time.date())

        source_errors = {}
        client = self.client_factory(self.project_root)

        nutrition_rollups = self._fetch_rollup(
            client,
            "nutrition-log",
            start_date,
            end_date,
            source_errors,
        )
        raw_nutrition = self._fetch_list(
            client,
            "nutrition-log",
            start_date,
            end_date,
            source_errors,
        )

        activity_rollups = {}
        for data_type in ACTIVITY_ROLLUPS:
            activity_rollups[data_type] = self._fetch_rollup(
                client,
                data_type,
                start_date,
                end_date,
                source_errors,
            )
        exercise_points = self._fetch_list(
            client,
            "exercise",
            start_date,
            end_date,
            source_errors,
        )
        sleep_points = self._fetch_list(
            client,
            "sleep",
            start_date,
            end_date,
            source_errors,
        )

        nutrition = normalize_nutrition_rollups(
            nutrition_rollups,
            raw_nutrition,
            timezone_name,
        )
        activity = normalize_activity_rollups(activity_rollups)
        exercises = aggregate_exercise_sessions(exercise_points, timezone_name)
        sleep = aggregate_sleep_sessions(sleep_points, timezone_name)
        try:
            weight = self.weight_reader.read(start_date, end_date, timezone_name)
        except Exception as exc:
            self.log.exception(f"Health Insights Weight Progress read failed: {exc}")
            weight = {}
            source_errors["weight"] = "Weight Progress data could not be read."

        records = []
        cursor = start_date
        refreshed_at = current_time.isoformat(timespec="seconds")
        while cursor <= end_date:
            key = cursor.isoformat()
            values = {}
            values.update(nutrition.get(key, {}))
            values.update(activity.get(key, {}))
            values.update(exercises.get(key, {}))
            values.update(sleep.get(key, {}))
            values.update(weight.get(key, {}))
            existing = self.database.get_day(key)
            record = DailyHealthInsight(
                local_date=key,
                timezone=timezone_name,
                first_imported_at=(
                    existing.get("first_imported_at")
                    if existing
                    else refreshed_at
                ),
                last_refreshed_at=refreshed_at,
                **{
                    field_name: field_value
                    for field_name, field_value in values.items()
                    if field_name in DailyHealthInsight.__dataclass_fields__
                },
            )
            self._preserve_existing_values(record, existing)
            self._finalize_record(record, cursor == current_time.date())
            records.append(record)
            cursor += timedelta(days=1)

        complete_days = sum(
            record.nutrition_activity_weight_complete
            and not record.is_current_day
            for record in records
        )
        return {
            "mode": "preview",
            "from_date": start_date.isoformat(),
            "through_date": end_date.isoformat(),
            "timezone": timezone_name,
            "records": [record.to_dict() for record in records],
            "complete_days": complete_days,
            "incomplete_days": len(records) - complete_days,
            "failed_days": len(records) if source_errors else 0,
            "source_errors": source_errors,
            "database_written": False,
        }

    def sync(
        self,
        start_date: date,
        end_date: date,
        *,
        now: datetime | None = None,
    ) -> dict:
        backup_path = self.database.backup_before_first_sync()
        self.database.initialize()
        current_time = now or self.local_now()
        attempted_at = current_time.isoformat(timespec="seconds")
        try:
            preview = self.preview(start_date, end_date, now=current_time)
            records = [DailyHealthInsight(**item) for item in preview["records"]]
            counts = self.database.upsert_days(records)
            source_errors = preview["source_errors"]
            status = "partial" if source_errors else "success"
            successful_at = None if source_errors else attempted_at
            self.database.record_sync_state(
                attempted_at=attempted_at,
                successful_at=successful_at,
                from_date=start_date.isoformat(),
                through_date=end_date.isoformat(),
                status=status,
                error=(
                    "; ".join(sorted(source_errors))
                    if source_errors
                    else None
                ),
            )
            return {
                "mode": "sync",
                "from_date": start_date.isoformat(),
                "through_date": end_date.isoformat(),
                **counts,
                "incomplete": preview["incomplete_days"],
                "failed": preview["failed_days"],
                "source_failures": sorted(source_errors),
                "backup_created": bool(backup_path),
                "complete_days_in_range": preview["complete_days"],
                "database_written": True,
            }
        except Exception as exc:
            safe_error = self._safe_error(exc)
            self.database.record_sync_state(
                attempted_at=attempted_at,
                successful_at=None,
                from_date=start_date.isoformat(),
                through_date=end_date.isoformat(),
                status="failed",
                error=safe_error,
            )
            raise HealthInsightsError(safe_error) from None

    def sync_recent(self) -> dict:
        start_date, end_date = self.default_range()
        return self.sync(start_date, end_date)

    def start_manual_refresh(self) -> dict:
        if not self._manual_lock.acquire(blocking=False):
            return {
                "ok": False,
                "busy": True,
                "message": "A health data refresh is already running.",
            }
        started_at = self.local_now().isoformat(timespec="seconds")
        with self._manual_state_lock:
            self._manual_state = {
                "status": "running",
                "message": "Refreshing the most recent seven days.",
                "started_at": started_at,
                "finished_at": None,
            }
        thread = threading.Thread(
            target=self._run_manual_refresh,
            name="health-insights-refresh",
            daemon=True,
        )
        thread.start()
        return {
            "ok": True,
            "busy": False,
            "message": "Health data refresh started.",
        }

    def _run_manual_refresh(self):
        try:
            result = self.sync_recent()
            state = {
                "status": "succeeded",
                "message": (
                    "Health data refreshed: "
                    f"{result['inserted']} inserted, "
                    f"{result['updated']} updated, "
                    f"{result['unchanged']} unchanged."
                ),
            }
        except Exception as exc:
            self.log.exception(f"Health Insights manual refresh failed: {exc}")
            state = {
                "status": "failed",
                "message": "Health data refresh failed. Check the HomePulse log.",
            }
        finally:
            finished_at = self.local_now().isoformat(timespec="seconds")
            with self._manual_state_lock:
                self._manual_state = {
                    **self._manual_state,
                    **state,
                    "finished_at": finished_at,
                }
            self._manual_lock.release()

    def manual_refresh_status(self) -> dict:
        with self._manual_state_lock:
            return dict(self._manual_state)

    def dashboard_view_model(self) -> dict:
        rows = self.database.list_days(limit=14)
        status = self.status()
        complete_days = status["complete_days"]
        days_needed = status["days_needed"]
        latest_nutrition = self._latest_value(rows, "nutrition_calories")
        latest_steps = self._latest_value(rows, "steps")
        latest_sleep = self._latest_value(rows, "sleep_hours")
        latest_weight = self._latest_value(rows, "weight_pounds")
        return {
            "summary_cards": [
                {"label": "Complete Days", "value": f"{complete_days} of {MINIMUM_COMPLETE_DAYS}"},
                {"label": "Days Needed for Insights", "value": str(days_needed)},
                {"label": "Calories Eaten", "value": self._format_number(latest_nutrition, " Calories", 0)},
                {"label": "Latest Steps", "value": self._format_integer(latest_steps)},
                {"label": "Latest Sleep", "value": self._format_number(latest_sleep, " hours", 1)},
                {"label": "Latest Weight", "value": self._format_number(latest_weight, " lb", 1)},
            ],
            "daily_rows": [self._display_row(row) for row in rows],
            "readiness": {
                "ready": status["correlations_ready"],
                "complete_days": complete_days,
                "minimum_days": MINIMUM_COMPLETE_DAYS,
                "days_needed": days_needed,
                "headline": (
                    "Health Insights has enough complete days for the next analysis stage."
                    if status["correlations_ready"]
                    else "Health Insights is collecting data."
                ),
                "detail": (
                    f"{complete_days} of {MINIMUM_COMPLETE_DAYS} complete days are available. "
                    + (
                        "Trend relationships may now be evaluated."
                        if status["correlations_ready"]
                        else f"{days_needed} more complete days are needed before trend relationships are shown."
                    )
                ),
            },
            "freshness": {
                "last_successful_sync": status.get("last_successful_sync") or "Never",
                "timezone": status["timezone"],
                "nutrition_source": self._latest_text(rows, "nutrition_source") or "Google Health",
                "activity_source": self._latest_text(rows, "activity_source") or "Google Health",
                "weight_source": self._latest_text(rows, "weight_source") or "Withings via Weight Progress",
                "google_health_authorized": status["authorization"]["authorized"],
            },
            "manual_refresh": self.manual_refresh_status(),
            "correlations": [],
        }

    @staticmethod
    def _validate_range(start_date: date, end_date: date, today: date):
        if start_date > end_date:
            raise HealthInsightsError("From date must be on or before through date.")
        if start_date > today or end_date > today:
            raise HealthInsightsError("Future Health Insights dates cannot be imported.")

    @staticmethod
    def _fetch_rollup(client, data_type, start_date, end_date, errors):
        try:
            points, _ = client.daily_rollups(data_type, start_date, end_date)
            return points
        except GoogleHealthError:
            errors[f"{data_type}:dailyRollUp"] = "Google Health rollup unavailable."
            return []

    @staticmethod
    def _fetch_list(client, data_type, start_date, end_date, errors):
        try:
            points, _ = client.list_data_points(
                data_type,
                start_date=start_date,
                end_date=end_date,
            )
            return points
        except GoogleHealthError:
            errors[f"{data_type}:list"] = "Google Health list data unavailable."
            return []

    @staticmethod
    def _preserve_existing_values(record, existing):
        if not existing:
            return
        nullable_fields = (
            NUTRITION_FIELDS
            + (
                "nutrition_source",
                "nutrition_platform",
                "steps",
                "total_calories_burned",
                "active_energy_calories",
                "active_minutes",
                "active_zone_minutes",
                "distance_miles",
                "exercise_minutes",
                "exercise_calories",
                "activity_source",
                "sleep_minutes",
                "sleep_hours",
                "awake_minutes",
                "sleep_source",
                "weight_pounds",
                "seven_day_average_weight_pounds",
                "body_fat_percentage",
                "muscle_percentage",
                "visceral_fat_index",
                "weight_source",
            )
        )
        for field_name in nullable_fields:
            if getattr(record, field_name) is None and existing.get(field_name) is not None:
                setattr(record, field_name, existing[field_name])
        for count_field in (
            "nutrition_record_count",
            "exercise_session_count",
            "sleep_session_count",
        ):
            if getattr(record, count_field) == 0 and existing.get(count_field):
                setattr(record, count_field, existing[count_field])

    @staticmethod
    def _finalize_record(record, is_current_day):
        record.nutrition_complete = all(
            getattr(record, field_name) is not None
            for field_name in NUTRITION_FIELDS
        )
        record.activity_complete = (
            record.steps is not None
            and record.total_calories_burned is not None
        )
        record.sleep_complete = (
            record.sleep_minutes is not None
            and record.sleep_session_count > 0
        )
        record.weight_available = record.weight_pounds is not None
        record.is_current_day = bool(is_current_day)
        record.nutrition_activity_weight_complete = (
            record.nutrition_complete
            and record.activity_complete
            and record.weight_available
            and record.seven_day_average_weight_pounds is not None
        )
        if record.is_current_day:
            record.data_status = "in_progress"
        elif record.nutrition_activity_weight_complete:
            record.data_status = "complete"
        else:
            record.data_status = "incomplete"

    @staticmethod
    def _safe_error(exc):
        if isinstance(exc, (GoogleHealthError, HealthInsightsError)):
            return str(exc)
        return "Health Insights synchronization failed."

    @staticmethod
    def _latest_value(rows, field_name):
        return next(
            (row.get(field_name) for row in rows if row.get(field_name) is not None),
            None,
        )

    @staticmethod
    def _latest_text(rows, field_name):
        return next(
            (str(row.get(field_name)) for row in rows if row.get(field_name)),
            None,
        )

    @staticmethod
    def _format_number(value, suffix, decimals):
        return "—" if value is None else f"{float(value):.{decimals}f}{suffix}"

    @staticmethod
    def _format_integer(value):
        return "—" if value is None else f"{int(value):,}"

    def _display_row(self, row):
        parsed_date = date.fromisoformat(row["local_date"])
        has_data = any(
            row.get(field_name) is not None
            for field_name in (
                "nutrition_calories",
                "steps",
                "sleep_minutes",
                "weight_pounds",
            )
        )
        status = (
            "In progress"
            if row["is_current_day"]
            else "Complete"
            if row["nutrition_activity_weight_complete"]
            else "Partial"
            if has_data
            else "Missing"
        )
        exercise = "—"
        if row.get("exercise_minutes") is not None:
            exercise = f"{row['exercise_minutes']:.0f} min"
            if row.get("exercise_calories") is not None:
                exercise += f" / {row['exercise_calories']:.0f} Calories"
        return {
            "date": f"{parsed_date:%b} {parsed_date.day}",
            "calories": self._format_number(row.get("nutrition_calories"), "", 0),
            "protein": self._format_number(row.get("protein_grams"), " g", 1),
            "carbs": self._format_number(row.get("carbohydrate_grams"), " g", 1),
            "fat": self._format_number(row.get("fat_grams"), " g", 1),
            "fiber": self._format_number(row.get("fiber_grams"), " g", 1),
            "steps": self._format_integer(row.get("steps")),
            "calories_burned": self._format_number(row.get("total_calories_burned"), "", 0),
            "exercise": exercise,
            "sleep": self._format_number(row.get("sleep_hours"), " h", 1),
            "weight": self._format_number(row.get("weight_pounds"), " lb", 1),
            "status": status,
            "status_key": row["data_status"],
        }
