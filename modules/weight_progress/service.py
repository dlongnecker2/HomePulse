import json
import secrets
import tempfile
import threading
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path

from modules.power_adapters.home_assistant import HomeAssistantAdapter
from modules.weight_progress.importer import UPLOAD_MAX_BYTES, WithingsWorkbookImporter
from modules.weight_progress.database import WeightProgressDatabase
from modules.weight_progress.defaults import DEFAULT_WEIGHT_PROGRESS_CONFIG
from modules.weight_progress.models import WeightMeasurement


UNAVAILABLE_STATES = {"", "unknown", "unavailable", "none", "null", "--", "nan"}


class WeightProgressService:
    RANGE_SETTINGS = {
        "current_journey": None,
        "30d": timedelta(days=30),
        "90d": timedelta(days=90),
        "1y": timedelta(days=365),
        "all": None,
    }

    def __init__(self, config, log):
        self.config = config
        self.log = log
        self.database = WeightProgressDatabase(self.database_path())
        self.importer = WithingsWorkbookImporter(self.log)
        self._pending_imports = {}
        self._pending_imports_lock = threading.Lock()

    def database_path(self):
        weight_progress = self.config.get("weight_progress", default={})
        return Path(weight_progress.get("database", DEFAULT_WEIGHT_PROGRESS_CONFIG["database"]))

    def refresh_config(self, config):
        self.config = config
        self.database = WeightProgressDatabase(self.database_path())

    def initialize(self):
        self.database.initialize()
        self.log.info(f"Weight Progress database initialized: {self.database.path}")

    def enabled(self):
        return bool(self.weight_progress_config().get("enabled", True))

    def display_unit(self, value=None):
        unit = str(value or self.weight_progress_config().get("display_unit") or "lb").strip().lower()
        return "kg" if unit == "kg" else "lb"

    def weight_progress_config(self):
        current = dict(self.config.get("weight_progress", default={}))
        merged = dict(DEFAULT_WEIGHT_PROGRESS_CONFIG)
        entities = dict(DEFAULT_WEIGHT_PROGRESS_CONFIG["entities"])
        entities.update(current.get("entities", {}))
        merged.update(current)
        merged["entities"] = entities
        merged["display_unit"] = self.display_unit(merged.get("display_unit"))
        return merged

    def _store_uploaded_workbook(self, file_storage):
        if file_storage is None or not getattr(file_storage, "filename", ""):
            raise ValueError("Choose an .xlsx workbook to import.")
        filename = Path(str(file_storage.filename)).name
        if not filename.lower().endswith(".xlsx"):
            raise ValueError("Only .xlsx workbooks are accepted.")
        raw = file_storage.read()
        if not raw:
            raise ValueError("The uploaded workbook is empty.")
        if len(raw) > UPLOAD_MAX_BYTES:
            raise ValueError("Upload exceeds the allowed size limit.")

        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx", prefix="weight-progress-")
        try:
            temp_file.write(raw)
            temp_file.flush()
            temp_path = temp_file.name
        finally:
            temp_file.close()
        return temp_path, filename

    def _register_pending_import(self, path, filename):
        self._prune_pending_imports()
        token = secrets.token_urlsafe(16)
        with self._pending_imports_lock:
            self._pending_imports[token] = {
                "path": path,
                "filename": filename,
                "created_at": self._now(),
            }
        return token

    def _pop_pending_import(self, token):
        self._prune_pending_imports()
        if not token:
            return None
        with self._pending_imports_lock:
            return self._pending_imports.pop(token, None)

    def _prune_pending_imports(self, max_age=timedelta(hours=2)):
        cutoff = self._now() - max_age
        with self._pending_imports_lock:
            expired_tokens = [
                token for token, data in self._pending_imports.items()
                if data.get("created_at") and data["created_at"] < cutoff
            ]
            for token in expired_tokens:
                pending = self._pending_imports.pop(token, None)
                if pending:
                    self._cleanup_pending_path(pending.get("path"))

    @staticmethod
    def _cleanup_pending_path(path):
        if not path:
            return
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass

    def snapshot(self, timeout_seconds=10):
        measurement = self.capture_current_measurement(timeout_seconds=timeout_seconds)
        if measurement is None:
            return None
        self.database.insert_measurement(measurement)
        return measurement

    def preview_weight_history_import(self, file_storage):
        cfg = self.weight_progress_config()
        temp_path, filename = self._store_uploaded_workbook(file_storage)
        try:
            existing = self.database.query_measurements()
            preview = self.importer.preview(
                path=temp_path,
                existing_measurements=existing,
                journey_start_date=cfg.get("journey_start_date"),
                source_label="withings_xlsx",
                filename=filename,
            )
            token = self._register_pending_import(temp_path, filename)
            payload = preview.to_preview_dict()
            payload["preview_token"] = token
            return payload
        except Exception:
            self._cleanup_pending_path(temp_path)
            raise

    def confirm_weight_history_import(self, token):
        pending = self._pop_pending_import(token)
        if not pending:
            raise ValueError("Import preview expired or was not found.")
        try:
            cfg = self.weight_progress_config()
            existing = self.database.query_measurements()
            result, measurements = self.importer.build_measurements(
                path=pending["path"],
                existing_measurements=existing,
                journey_start_date=cfg.get("journey_start_date"),
                source_label="withings_xlsx",
                filename=pending["filename"],
            )
            inserted = 0
            for measurement in measurements:
                if self.database.insert_measurement(measurement):
                    inserted += 1
            return {
                "ok": True,
                "inserted": inserted,
                "exact_duplicates": result.exact_duplicates,
                "likely_overlaps": result.likely_overlaps,
                "invalid_rows": result.invalid_rows,
                "preview": result.to_preview_dict(),
                "weight_progress": self.view_model(include_live=False, range_key="current_journey"),
            }
        finally:
            self._cleanup_pending_path(pending["path"])

    def cancel_weight_history_import(self, token):
        pending = self._pop_pending_import(token)
        if pending:
            self._cleanup_pending_path(pending["path"])
        return {"ok": True}

    def capture_current_measurement(self, timeout_seconds=10):
        cfg = self.weight_progress_config()
        if not cfg.get("enabled", True):
            return None

        entities = cfg.get("entities", {})
        adapter = HomeAssistantAdapter(self.config, self.log)
        values = {}
        metadata = {}
        for key, entity_id in entities.items():
            entity_id = str(entity_id or "").strip()
            if not entity_id:
                continue
            result = adapter.get_entity_state(entity_id, timeout_seconds=timeout_seconds)
            values[key] = self._normalize_entity_value(key, result)
            metadata[key] = {
                "entity_id": entity_id,
                "status": result.status,
                "message": result.message,
                "metadata": result.metadata,
            }

        weight = values.get("weight")
        if not weight or weight["weight_kg"] is None:
            return None

        timestamps = [
            self._normalize_timestamp(values[key].get("source_timestamp"))
            for key in values
            if values[key].get("source_timestamp")
        ]
        source_timestamp = self._latest_timestamp(timestamps) or self._now_text()
        fingerprint = self._measurement_fingerprint(
            source_entity=entities.get("weight", ""),
            source_timestamp=source_timestamp,
            values=values,
        )

        measurement = WeightMeasurement.create(
            captured_at=self._now_text(),
            source_timestamp=source_timestamp,
            source_entity=str(entities.get("weight") or "").strip(),
            weight_kg=weight["weight_kg"],
            body_fat_percent=values.get("body_fat", {}).get("body_fat_percent"),
            withings_goal_kg=values.get("withings_goal", {}).get("weight_kg"),
            fat_mass_kg=values.get("fat_mass", {}).get("weight_kg"),
            fat_free_mass_kg=values.get("fat_free_mass", {}).get("weight_kg"),
            muscle_mass_kg=values.get("muscle_mass", {}).get("weight_kg"),
            bone_mass_kg=values.get("bone_mass", {}).get("weight_kg"),
            hydration_kg=None,
            heart_rate_bpm=values.get("heart_rate", {}).get("heart_rate_bpm"),
            scale_battery=values.get("battery", {}).get("scale_battery"),
            comments=None,
            import_source="home_assistant",
            source_label="home_assistant",
            imported_at=self._now_text(),
            reading_hash=fingerprint,
            metadata={
                "entities": metadata,
                "display_unit": cfg.get("display_unit", "lb"),
            },
        )
        return measurement

    def view_model(self, include_live=True, range_key="current_journey"):
        cfg = self.weight_progress_config()
        if include_live:
            self.snapshot()

        latest = self.database.latest_measurement()
        all_history = self.database.query_measurements(end_time=self._now_text())
        journey_start_date = self._journey_start_date(cfg)
        journey_history = self._journey_history(all_history, journey_start_date)
        history = self._range_history(all_history, range_key, journey_start_date)
        earliest = all_history[0] if all_history else None
        if latest is None and all_history:
            latest = all_history[-1]
        display_unit = cfg.get("display_unit", "lb")
        current_weight = self._to_display_weight(latest.weight_kg if latest else None, display_unit)
        starting_weight, starting_note = self._starting_weight(cfg, journey_history, earliest, display_unit)
        goal_weight = self._to_display_scalar(cfg.get("goal_weight"), display_unit)
        withings_goal = self._to_display_weight(latest.withings_goal_kg if latest else None, display_unit)
        total_lost = self._delta_value(starting_weight, current_weight)
        remaining_to_goal = self._delta_value(current_weight, goal_weight)
        body_fat = self._to_display_percent(latest.body_fat_percent if latest else None)
        weekly_change = self._average_weekly_change(journey_history, display_unit)
        progress_percent = self._journey_progress_percent(starting_weight, current_weight, goal_weight)
        chart_points = self._chart_points(history, goal_weight, display_unit)
        all_chart_points = self._chart_points(all_history, goal_weight, display_unit)
        composition_rows = self._body_composition_rows(latest, display_unit)
        latest_label = self._format_display_timestamp(latest.source_timestamp if latest else None)
        measurement_count = len(all_history)
        journey_measurement_count = len(journey_history)

        return {
            "enabled": cfg.get("enabled", True),
            "status_label": "Tracking" if cfg.get("enabled", True) else "Disabled",
            "display_unit": display_unit,
            "default_range": "current_journey",
            "measurement_count": measurement_count,
            "journey_measurement_count": journey_measurement_count,
            "journey_start_date": journey_start_date.isoformat() if journey_start_date else None,
            "journey_start_label": self._journey_start_label(cfg, journey_start_date, journey_history),
            "journey_start_source": self._journey_start_source(cfg, journey_start_date, journey_history),
            "chart_message": self._chart_message(measurement_count, latest),
            "summary_cards": [
                {"label": "Current Weight", "value": self._format_weight(current_weight, display_unit)},
                {"label": "Total Lost", "value": self._format_delta(total_lost, display_unit)},
                {"label": "Starting Weight", "value": self._format_weight(starting_weight, display_unit), "note": starting_note},
                {"label": "Goal Weight", "value": self._format_weight(goal_weight, display_unit)},
                {"label": "Remaining to Goal", "value": self._format_delta(remaining_to_goal, display_unit)},
                {"label": "Journey Progress", "value": self._format_percent(progress_percent)},
                {"label": "Current Body Fat", "value": self._format_percent(body_fat)},
                {"label": "Latest Weigh-In", "value": latest_label},
                {"label": "Journey Average Weekly Change", "value": self._format_delta(weekly_change, display_unit, per_week=True)},
            ],
            "body_composition_rows": composition_rows,
            "withings_goal": self._format_weight(withings_goal, display_unit),
            "withings_goal_note": "Supplemental",
            "latest_weigh_in_label": latest_label,
            "chart": {
                "default_range": "current_journey",
                "points": chart_points,
                "all_points": all_chart_points,
                "goal_weight": goal_weight,
                "display_unit": display_unit,
                "measurement_count": measurement_count,
                "journey_measurement_count": journey_measurement_count,
                "journey_start_date": journey_start_date.isoformat() if journey_start_date else None,
                "range_options": [
                    {"value": "current_journey", "label": "Current Journey"},
                    {"value": "30d", "label": "30 Days"},
                    {"value": "90d", "label": "90 Days"},
                    {"value": "1y", "label": "1 Year"},
                    {"value": "all", "label": "All History"},
                ],
            },
            "latest_measurement": latest.to_dict() if latest else None,
            "all_history_count": measurement_count,
            "tracking_details": [
                {"label": "Display Unit", "value": display_unit},
                {"label": "Stored Readings", "value": measurement_count},
                {"label": "Journey Readings", "value": journey_measurement_count},
                {"label": "Current Journey", "value": f"{journey_start_date:%b} {journey_start_date.day}, {journey_start_date:%Y}" if journey_start_date else "Since HomePulse tracking began"},
                {"label": "Current Journey Source", "value": self._journey_start_source(cfg, journey_start_date, journey_history)},
                {"label": "Latest Weigh-In", "value": latest_label},
                {"label": "Goal Weight", "value": self._format_weight(goal_weight, display_unit)},
                {"label": "Withings Goal", "value": self._format_weight(withings_goal, display_unit)},
            ],
            "configuration": cfg,
        }

    def _body_composition_rows(self, measurement, display_unit):
        if not measurement:
            return [
                {"label": "Fat Mass", "value": "--"},
                {"label": "Fat-Free Mass", "value": "--"},
                {"label": "Muscle Mass", "value": "--"},
                {"label": "Bone Mass", "value": "--"},
                {"label": "Hydration", "value": "--"},
                {"label": "Heart Rate", "value": "--"},
                {"label": "Scale Battery", "value": "--"},
            ]
        return [
            {"label": "Fat Mass", "value": self._format_weight(self._to_display_weight(measurement.fat_mass_kg, display_unit), display_unit)},
            {"label": "Fat-Free Mass", "value": self._format_weight(self._to_display_weight(measurement.fat_free_mass_kg, display_unit), display_unit)},
            {"label": "Muscle Mass", "value": self._format_weight(self._to_display_weight(measurement.muscle_mass_kg, display_unit), display_unit)},
            {"label": "Bone Mass", "value": self._format_weight(self._to_display_weight(measurement.bone_mass_kg, display_unit), display_unit)},
            {"label": "Hydration", "value": self._format_weight(self._to_display_weight(measurement.hydration_kg, display_unit), display_unit)},
            {"label": "Heart Rate", "value": f"{int(round(measurement.heart_rate_bpm))} bpm" if measurement.heart_rate_bpm is not None else "--"},
            {"label": "Scale Battery", "value": str(measurement.scale_battery).strip() if measurement.scale_battery else "--"},
        ]

    def _chart_points(self, history, goal_weight, display_unit):
        points = []
        parsed_history = [
            {
                "timestamp": self._normalize_timestamp(item.source_timestamp),
                "weight": self._to_display_weight(item.weight_kg, display_unit),
            }
            for item in history
            if item.weight_kg is not None
        ]
        for index, item in enumerate(parsed_history):
            rolling = self._rolling_average(parsed_history, index)
            points.append({
                "timestamp": item["timestamp"],
                "weight": item["weight"],
                "rolling_average": rolling,
                "goal_weight": goal_weight,
            })
        return points

    def _rolling_average(self, points, index):
        if index < 1:
            return None
        end_point = self._parse_timestamp(points[index]["timestamp"])
        if end_point is None:
            return None
        window_start = end_point - timedelta(days=7)
        values = [
            point["weight"]
            for point in points[: index + 1]
            if (parsed := self._parse_timestamp(point["timestamp"])) is not None and parsed >= window_start
            and point["weight"] is not None
        ]
        if len(values) < 2:
            return None
        return round(sum(values) / len(values), 2)

    def _average_weekly_change(self, history, display_unit):
        readings = [item for item in history if item.weight_kg is not None]
        if len(readings) < 2:
            return None
        first = readings[0]
        last = readings[-1]
        first_ts = self._parse_timestamp(first.source_timestamp)
        last_ts = self._parse_timestamp(last.source_timestamp)
        if not first_ts or not last_ts or last_ts <= first_ts:
            return None
        first_weight = self._to_display_weight(first.weight_kg, display_unit)
        last_weight = self._to_display_weight(last.weight_kg, display_unit)
        days = max((last_ts - first_ts).total_seconds() / 86400, 1 / 24)
        return round(((last_weight - first_weight) / days) * 7, 2)

    def _starting_weight(self, cfg, journey_history, earliest, display_unit):
        starting = self._to_display_scalar(cfg.get("starting_weight"), display_unit)
        if starting is not None:
            return starting, "Manual"
        journey_date = self._journey_start_date(cfg)
        if journey_history:
            if journey_date:
                return self._to_display_weight(journey_history[0].weight_kg, display_unit), f"{journey_date:%b} {journey_date.day}, {journey_date:%Y}"
            return self._to_display_weight(journey_history[0].weight_kg, display_unit), "Since HomePulse tracking began"
        if earliest and earliest.weight_kg is not None:
            return self._to_display_weight(earliest.weight_kg, display_unit), "Since HomePulse tracking began"
        return None, "Waiting for the first reading"

    def _chart_message(self, measurement_count, latest):
        if latest is None:
            return "No weight history has been collected yet."
        if measurement_count < 2:
            return "Only one reading is available so far. Additional history will appear as measurements are collected."
        return "Daily weight and body-composition readings can vary. The trend is generally more useful than a single reading."

    def _journey_start_date(self, cfg):
        value = cfg.get("journey_start_date")
        if not value:
            return None
        if isinstance(value, datetime):
            return value.date()
        if hasattr(value, "isoformat") and not isinstance(value, str):
            try:
                return value if value.__class__.__name__ == "date" else value.date()
            except Exception:
                pass
        try:
            return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
        except ValueError:
            return None

    def _journey_history(self, history, journey_start_date):
        if not journey_start_date:
            return list(history)
        return [item for item in history if self._parse_timestamp(item.source_timestamp) and self._parse_timestamp(item.source_timestamp).date() >= journey_start_date]

    def _range_history(self, history, range_key, journey_start_date):
        normalized = self.normalize_range(range_key)
        if normalized == "all":
            return list(history)
        if normalized == "current_journey":
            return self._journey_history(history, journey_start_date)
        start = self._range_start(normalized)
        return [item for item in history if self._parse_timestamp(item.source_timestamp) and self._parse_timestamp(item.source_timestamp) >= start]

    def _journey_start_label(self, cfg, journey_start_date, journey_history):
        if cfg.get("starting_weight") not in (None, ""):
            return "Manual"
        if journey_start_date:
            return f"{journey_start_date:%b} {journey_start_date.day}, {journey_start_date:%Y}"
        if journey_history:
            return "Since HomePulse tracking began"
        return "Waiting for the first reading"

    def _journey_start_source(self, cfg, journey_start_date, journey_history):
        if cfg.get("starting_weight") not in (None, ""):
            return "Manual"
        if journey_start_date:
            return f"Starting Weight — {journey_start_date:%b} {journey_start_date.day}, {journey_start_date:%Y}"
        if journey_history:
            return "Starting Weight — Since HomePulse tracking began"
        return "Since HomePulse tracking began"

    def _journey_progress_percent(self, starting_weight, current_weight, goal_weight):
        if starting_weight is None or current_weight is None or goal_weight is None:
            return None
        if starting_weight <= goal_weight:
            return None
        span = starting_weight - goal_weight
        if span <= 0:
            return None
        progress = ((starting_weight - current_weight) / span) * 100
        return round(max(0, min(progress, 100)), 1)

    def _normalize_entity_value(self, key, result):
        if not result or result.status != "PASS":
            return {}
        metadata = result.metadata or {}
        state = metadata.get("state")
        if self._is_unavailable(state):
            return {}
        timestamps = {
            "source_timestamp": self._normalize_timestamp(metadata.get("last_updated") or metadata.get("last_changed")),
        }
        if key == "weight":
            value = self._parse_float(state)
            if value is None:
                return {}
            return {"weight_kg": self._normalize_weight_unit(value, metadata), **timestamps}
        if key == "body_fat":
            value = self._parse_float(state)
            return {"body_fat_percent": value, **timestamps} if value is not None else {}
        if key in {"withings_goal", "fat_mass", "fat_free_mass", "muscle_mass", "bone_mass"}:
            value = self._parse_float(state)
            if value is None:
                return {}
            return {"weight_kg": self._normalize_weight_unit(value, metadata), **timestamps}
        if key == "heart_rate":
            value = self._parse_float(state)
            return {"heart_rate_bpm": value, **timestamps} if value is not None else {}
        if key == "battery":
            return {"scale_battery": str(state).strip(), **timestamps}
        return {}

    def _normalize_weight_unit(self, value, metadata):
        unit = str((metadata or {}).get("attributes", {}).get("unit_of_measurement") or "").strip().lower()
        if unit in {"lb", "lbs", "pound", "pounds"}:
            return round(value / 2.2046226218, 6)
        return round(value, 6)

    def _measurement_fingerprint(self, source_entity, source_timestamp, values):
        payload = {
            "source_entity": source_entity,
            "source_timestamp": source_timestamp,
            "values": values,
        }
        return sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()

    def _latest_timestamp(self, timestamps):
        parsed = [self._parse_timestamp(value) for value in timestamps if value]
        parsed = [value for value in parsed if value is not None]
        if not parsed:
            return None
        return max(parsed).isoformat(sep=" ", timespec="microseconds")

    def _range_start(self, range_key):
        normalized = self.normalize_range(range_key)
        if normalized == "current_journey":
            journey_date = self._journey_start_date(self.weight_progress_config())
            return datetime.combine(journey_date, datetime.min.time()) if journey_date else None
        duration = self.RANGE_SETTINGS.get(normalized)
        return self._now() - duration if duration else None

    def normalize_range(self, range_key):
        normalized = str(range_key or "current_journey").strip().lower()
        aliases = {
            "1w": "30d",
            "1m": "30d",
            "6m": "90d",
            "current": "current_journey",
            "journey": "current_journey",
        }
        normalized = aliases.get(normalized, normalized)
        return normalized if normalized in self.RANGE_SETTINGS else "current_journey"

    def _to_display_weight(self, value_kg, display_unit):
        if value_kg is None:
            return None
        if display_unit == "kg":
            return round(value_kg, 1)
        return round(value_kg * 2.2046226218, 1)

    def _to_display_scalar(self, value, display_unit):
        if value in (None, ""):
            return None
        number = self._parse_float(value)
        if number is None:
            return None
        return round(number, 1)

    def _to_display_percent(self, value):
        if value is None:
            return None
        return round(value, 1)

    def _format_weight(self, value, display_unit):
        if value is None:
            return "--"
        return f"{value:.1f} {display_unit}"

    def _format_percent(self, value):
        if value is None:
            return "--"
        return f"{value:.1f}%"

    def _format_delta(self, value, display_unit, per_week=False):
        if value is None:
            return "--"
        suffix = f"{display_unit}/week" if per_week else display_unit
        return f"{value:+.1f} {suffix}" if value < 0 else f"{value:.1f} {suffix}"

    def _delta_value(self, start, current):
        if start is None or current is None:
            return None
        return round(start - current, 1) if current <= start else round(start - current, 1)

    def _is_unavailable(self, value):
        return str(value or "").strip().lower() in UNAVAILABLE_STATES

    @staticmethod
    def _parse_float(value):
        if value in (None, ""):
            return None
        try:
            text = str(value).strip().replace(",", "")
            text = text.replace("%", "").replace("bpm", "").strip()
            return float(text)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_timestamp(value):
        if not value:
            return None
        text = str(value).strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
            return parsed.astimezone().replace(tzinfo=None) if parsed.tzinfo else parsed
        except ValueError:
            return None

    @staticmethod
    def _normalize_timestamp(value):
        parsed = WeightProgressService._parse_timestamp(value)
        if parsed is None:
            return None
        return parsed.isoformat(sep=" ", timespec="microseconds")

    @staticmethod
    def _format_display_timestamp(value):
        parsed = WeightProgressService._parse_timestamp(value)
        if parsed is None:
            return "--"
        time_text = parsed.strftime("%I:%M %p").lstrip("0")
        return f"{parsed.strftime('%b')} {parsed.day}, {parsed.year} at {time_text}"

    @staticmethod
    def _now():
        return datetime.now()

    @classmethod
    def _now_text(cls):
        return cls._now().isoformat(sep=" ", timespec="microseconds")
