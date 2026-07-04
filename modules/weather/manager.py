import json
import math
import socket
import ssl
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from urllib.error import HTTPError, URLError

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9 compatibility guard
    ZoneInfo = None

from modules.weather.providers import NationalWeatherServiceProvider, OpenMeteoProvider


WEATHER_DEFAULTS = {
    "enabled": True,
    "location_name": "Home",
    "latitude": "",
    "longitude": "",
    "provider": "open_meteo",
    "provider_strategy": "automatic_failover",
    "provider_priority": ["national_weather_service", "open_meteo"],
    "providers": {
        "national_weather_service": {"enabled": True},
        "open_meteo": {"enabled": True},
    },
}

PROVIDER_TIMEOUT_SECONDS = 6
PROVIDER_CACHE_SECONDS = 600
PROVIDER_FAILURE_COOLDOWN_SECONDS = 180


class WeatherManager:
    def __init__(self, config, log):
        self.config = config
        self.log = log
        self._last_warning_at = None
        self.providers = {
            "national_weather_service": NationalWeatherServiceProvider(),
            "open_meteo": OpenMeteoProvider(),
        }
        self._provider_state = {
            key: {
                "last_status": None,
                "last_error_status": None,
                "last_fetch_at": None,
                "last_failure_at": None,
            }
            for key in self.providers
        }

    def weather_config(self):
        configured = dict(self.config.get("weather", default={}))
        merged = deepcopy(WEATHER_DEFAULTS)
        for key, value in configured.items():
            if key == "providers" and isinstance(value, dict):
                merged.setdefault("providers", {})
                for provider_key, provider_data in value.items():
                    if isinstance(provider_data, dict):
                        merged["providers"].setdefault(provider_key, {})
                        merged["providers"][provider_key].update(provider_data)
            elif key in ("provider_priority",) and isinstance(value, list):
                merged[key] = list(value)
            else:
                merged[key] = value
        return self.normalize_weather_framework(merged)

    def normalize_weather_framework(self, weather):
        legacy_provider = str(weather.get("provider", "open_meteo") or "open_meteo").strip().lower()
        providers = weather.get("providers")
        if not isinstance(providers, dict):
            providers = {}

        for key in ("national_weather_service", "open_meteo"):
            providers.setdefault(key, {"enabled": True})
            if not isinstance(providers.get(key), dict):
                providers[key] = {"enabled": True}
            providers[key]["enabled"] = bool(providers[key].get("enabled", True))

        # Backward compatibility: old single-provider configs now run in failover mode
        # unless legacy manual/placeholder mode was intentionally selected.
        if legacy_provider in ("manual", "placeholder") and "providers" not in self.config.get("weather", default={}):
            providers["national_weather_service"]["enabled"] = False
            providers["open_meteo"]["enabled"] = False
        elif "providers" not in self.config.get("weather", default={}):
            providers["national_weather_service"]["enabled"] = True
            providers["open_meteo"]["enabled"] = True

        priority = weather.get("provider_priority")
        default_priority = ["national_weather_service", "open_meteo"]
        if not isinstance(priority, list):
            priority = list(default_priority)
        else:
            normalized = []
            seen = set()
            for key in priority:
                text = str(key or "").strip().lower()
                if text in default_priority and text not in seen:
                    normalized.append(text)
                    seen.add(text)
            for key in default_priority:
                if key not in seen:
                    normalized.append(key)
            priority = normalized

        weather["providers"] = providers
        weather["provider_priority"] = priority
        weather["provider_strategy"] = "automatic_failover"
        return weather

    def enabled_providers_in_priority(self, weather):
        providers = weather.get("providers", {})
        priority = weather.get("provider_priority", [])
        enabled = []
        for key in priority:
            provider_cfg = providers.get(key, {})
            if isinstance(provider_cfg, dict) and provider_cfg.get("enabled", False):
                enabled.append(key)
        return enabled

    def get_status(self):
        weather = self.weather_config()
        if not weather.get("enabled", True):
            status = self.status_payload(
                weather,
                enabled=False,
                condition="Disabled",
                source="Disabled",
                error=None,
            )
            return self.attach_framework_fields(
                self.normalize_status(weather, status),
                weather,
                attempted_providers=[],
                provider_errors={},
                selected_provider=None,
                fallback_used=False,
            )

        enabled_providers = self.enabled_providers_in_priority(weather)
        if not enabled_providers:
            status = self.status_payload(
                weather,
                enabled=True,
                condition="Weather unavailable",
                source="Provider framework",
                live_data=False,
                error="No weather providers are enabled.",
            )
            status["message"] = "Enable at least one weather provider in Settings."
            return self.attach_framework_fields(
                self.normalize_status(weather, status),
                weather,
                attempted_providers=[],
                provider_errors={},
                selected_provider=None,
                fallback_used=False,
            )

        return self.fetch_with_failover(weather, enabled_providers)

    def fetch_with_failover(self, weather, enabled_providers):
        attempted = []
        provider_errors = {}
        stale_candidates = []

        for key in enabled_providers:
            provider = self.providers.get(key)
            if provider is None:
                attempted.append(key)
                provider_errors[key] = "Provider not registered"
                continue

            state = self._provider_state.setdefault(
                key,
                {
                    "last_status": None,
                    "last_error_status": None,
                    "last_fetch_at": None,
                    "last_failure_at": None,
                },
            )
            now = datetime.now()
            attempted.append(key)

            if state["last_status"] and state["last_fetch_at"] and (now - state["last_fetch_at"]).total_seconds() < PROVIDER_CACHE_SECONDS:
                status = self.normalize_status(weather, dict(state["last_status"]))
                return self.attach_framework_fields(
                    status,
                    weather,
                    attempted_providers=attempted,
                    provider_errors=provider_errors,
                    selected_provider=key,
                    fallback_used=False,
                )

            if state["last_failure_at"] and (now - state["last_failure_at"]).total_seconds() < PROVIDER_FAILURE_COOLDOWN_SECONDS:
                provider_errors[key] = "Provider in failure cooldown"
                if state["last_status"]:
                    stale_candidates.append((key, self.stale_cached_status(state["last_status"], state["last_error_status"], provider.source_name)))
                continue

            try:
                status = self.normalize_status(weather, provider.fetch_status(weather, PROVIDER_TIMEOUT_SECONDS))
                state["last_status"] = dict(status)
                state["last_fetch_at"] = now
                state["last_failure_at"] = None
                state["last_error_status"] = None
                return self.attach_framework_fields(
                    status,
                    weather,
                    attempted_providers=attempted,
                    provider_errors=provider_errors,
                    selected_provider=key,
                    fallback_used=False,
                )
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, ValueError, ssl.SSLError, socket.timeout) as exc:
                error_text = self.describe_provider_error(exc)
                provider_errors[key] = error_text
                self.log_weather_warning(f"{provider.source_name} weather fetch failed: {error_text}")

                state["last_failure_at"] = now
                state["last_error_status"] = self.status_payload(
                    weather,
                    enabled=True,
                    condition="Weather provider error",
                    source=provider.source_name,
                    live_data=False,
                    error=error_text,
                )
                state["last_error_status"]["message"] = f"{provider.source_name} provider error; failover will continue."

                if state["last_status"]:
                    stale_candidates.append((key, self.stale_cached_status(state["last_status"], state["last_error_status"], provider.source_name, weather)))

        if stale_candidates:
            selected_key, stale_status = stale_candidates[0]
            stale_status["message"] = "All live providers failed; using stale cached weather."
            return self.attach_framework_fields(
                stale_status,
                weather,
                attempted_providers=attempted,
                provider_errors=provider_errors,
                selected_provider=selected_key,
                fallback_used=True,
            )

        summary = "; ".join([f"{key}: {text}" for key, text in provider_errors.items()]) or "All providers failed."
        status = self.status_payload(
            weather,
            enabled=True,
            condition="Weather unavailable",
            source="Provider framework",
            live_data=False,
            error=summary,
        )
        status["message"] = "All weather providers failed and no cached weather is available."
        return self.attach_framework_fields(
            self.normalize_status(weather, status),
            weather,
            attempted_providers=attempted,
            provider_errors=provider_errors,
            selected_provider=None,
            fallback_used=True,
        )

    def status_payload(self, weather, enabled, condition, source, error, live_data=False):
        return {
            "enabled": enabled,
            "configured": bool(enabled),
            "location_name": weather.get("location_name") or "Home",
            "latitude": weather.get("latitude") or None,
            "longitude": weather.get("longitude") or None,
            "provider": weather.get("provider") or "placeholder",
            "live_data": live_data,
            "temperature_f": None,
            "feels_like_f": None,
            "apparent_temperature_f": None,
            "condition": condition,
            "cloud_cover_percent": None,
            "cloud_cover_estimated": False,
            "cloud_cover_estimation_method": None,
            "sunshine_percent": None,
            "precipitation_probability_percent": None,
            "humidity_percent": None,
            "wind_mph": None,
            "uv_index": None,
            "uv_index_estimated": False,
            "uv_index_source": None,
            "sunrise": None,
            "sunset": None,
            "forecast_days": [],
            "hourly": [],
            "last_updated": str(datetime.now()),
            "source": source,
            "error": error,
            "message": "Weather Center is ready for a live provider." if enabled else "Weather Center is disabled.",
        }

    def attach_framework_fields(
        self,
        status,
        weather,
        attempted_providers,
        provider_errors,
        selected_provider,
        fallback_used,
    ):
        result = dict(status)
        result["provider_strategy"] = "automatic_failover"
        result["enabled_providers"] = self.enabled_providers_in_priority(weather)
        result["attempted_providers"] = list(attempted_providers)
        result["provider_errors"] = dict(provider_errors)
        result["fallback_used"] = bool(fallback_used)
        result["selected_provider"] = selected_provider
        if selected_provider:
            result["provider"] = selected_provider
        return result

    def stale_cached_status(self, cached_status, error_status, provider_source_name, weather):
        stale = dict(cached_status)
        stale["live_data"] = False
        stale["stale"] = True
        stale["source"] = f"{provider_source_name} (stale cache)"
        stale["condition"] = f"{stale.get('condition') or 'Weather available'} (stale)"
        stale["error"] = error_status.get("error") if error_status else "Using stale weather data due to provider error."
        stale["message"] = f"Showing last known weather due to {provider_source_name} provider issue."
        return self.normalize_status(weather, stale)

    def normalize_status(self, weather, status):
        normalized = dict(status or {})

        if normalized.get("feels_like_f") is None and normalized.get("apparent_temperature_f") is not None:
            normalized["feels_like_f"] = self.parse_numeric(normalized.get("apparent_temperature_f"))

        cloud_cover = self.parse_numeric(normalized.get("cloud_cover_percent"))
        if cloud_cover is not None:
            normalized["cloud_cover_percent"] = round(max(0.0, min(100.0, cloud_cover)), 1)

        if normalized.get("sunshine_percent") is None and normalized.get("cloud_cover_percent") is not None:
            cloud_cover_value = self.parse_numeric(normalized.get("cloud_cover_percent"))
            if cloud_cover_value is not None:
                normalized["sunshine_percent"] = round(max(0.0, min(100.0, 100.0 - cloud_cover_value)), 1)

        precipitation = self.pick_first_numeric(
            normalized.get("precipitation_probability_percent"),
            normalized.get("precipitation_chance_percent"),
            normalized.get("precipitation_probability"),
        )
        normalized["precipitation_probability_percent"] = precipitation

        forecast_days = normalized.get("forecast_days")
        if isinstance(forecast_days, list):
            adjusted_days = []
            for day in forecast_days:
                if not isinstance(day, dict):
                    adjusted_days.append(day)
                    continue
                day_copy = dict(day)
                day_precip = self.pick_first_numeric(
                    day_copy.get("precipitation_probability_percent"),
                    day_copy.get("precipitation_chance_percent"),
                    day_copy.get("precipitation_probability"),
                    day_copy.get("precipitation_percent"),
                )
                day_copy["precipitation_probability_percent"] = day_precip
                day_copy["precipitation_chance_percent"] = day_precip
                day_copy.setdefault("uv_index_estimated", False)
                day_copy.setdefault("uv_index_source", None)
                adjusted_days.append(day_copy)
            normalized["forecast_days"] = adjusted_days

        if normalized.get("uv_index") is None and isinstance(normalized.get("forecast_days"), list):
            for day in normalized.get("forecast_days"):
                if not isinstance(day, dict):
                    continue
                uv_fallback = self.parse_numeric(day.get("uv_index_max"))
                if uv_fallback is not None:
                    normalized["uv_index"] = round(max(0.0, min(100.0, uv_fallback)), 1)
                    normalized["uv_index_estimated"] = bool(day.get("uv_index_estimated", False))
                    normalized["uv_index_source"] = day.get("uv_index_source") or "forecast_uv_index_max"
                    break

        normalized.setdefault("uv_index_estimated", False)
        normalized.setdefault("uv_index_source", None)

        if normalized.get("sunrise") is None or normalized.get("sunset") is None:
            calculated_sunrise, calculated_sunset = self.calculate_sunrise_sunset(weather)
            if normalized.get("sunrise") is None:
                normalized["sunrise"] = calculated_sunrise
            if normalized.get("sunset") is None:
                normalized["sunset"] = calculated_sunset

        normalized.setdefault("cloud_cover_estimated", False)
        normalized.setdefault("cloud_cover_estimation_method", None)
        return normalized

    def calculate_sunrise_sunset(self, weather):
        latitude = self.parse_numeric(weather.get("latitude"))
        longitude = self.parse_numeric(weather.get("longitude"))
        if latitude is None or longitude is None:
            return None, None

        tzinfo = self.resolve_timezone(weather)
        if tzinfo is None:
            return None, None

        target_date = datetime.now(tzinfo).date()
        sunrise_dt = self.compute_solar_event_utc(target_date, latitude, longitude, tzinfo, is_sunrise=True)
        sunset_dt = self.compute_solar_event_utc(target_date, latitude, longitude, tzinfo, is_sunrise=False)
        return self.iso_local(sunrise_dt), self.iso_local(sunset_dt)

    def resolve_timezone(self, weather):
        configured_tz = str(weather.get("timezone", "") or "").strip()
        if configured_tz and ZoneInfo is not None:
            try:
                return ZoneInfo(configured_tz)
            except Exception:
                self.log.debug(f"Invalid configured weather timezone '{configured_tz}', falling back to local timezone")

        return datetime.now().astimezone().tzinfo

    @staticmethod
    def compute_solar_event_utc(target_date, latitude, longitude, tzinfo, is_sunrise):
        day_of_year = target_date.timetuple().tm_yday
        longitude_hour = longitude / 15.0

        base_hour = 6.0 if is_sunrise else 18.0
        t = day_of_year + ((base_hour - longitude_hour) / 24.0)

        mean_anomaly = (0.9856 * t) - 3.289
        true_longitude = mean_anomaly + (1.916 * math.sin(math.radians(mean_anomaly))) + (0.020 * math.sin(math.radians(2 * mean_anomaly))) + 282.634
        true_longitude = true_longitude % 360.0

        right_ascension = math.degrees(math.atan(0.91764 * math.tan(math.radians(true_longitude))))
        right_ascension = right_ascension % 360.0

        true_longitude_quadrant = math.floor(true_longitude / 90.0) * 90.0
        right_ascension_quadrant = math.floor(right_ascension / 90.0) * 90.0
        right_ascension = right_ascension + (true_longitude_quadrant - right_ascension_quadrant)
        right_ascension_hours = right_ascension / 15.0

        sin_declination = 0.39782 * math.sin(math.radians(true_longitude))
        cos_declination = math.cos(math.asin(sin_declination))
        cos_hour_angle = (
            math.cos(math.radians(90.833))
            - (sin_declination * math.sin(math.radians(latitude)))
        ) / (cos_declination * math.cos(math.radians(latitude)))

        if cos_hour_angle > 1 or cos_hour_angle < -1:
            return None

        hour_angle = 360.0 - math.degrees(math.acos(cos_hour_angle)) if is_sunrise else math.degrees(math.acos(cos_hour_angle))
        hour_angle_hours = hour_angle / 15.0

        local_mean_time = hour_angle_hours + right_ascension_hours - (0.06571 * t) - 6.622
        universal_time_hours = (local_mean_time - longitude_hour) % 24.0

        utc_midnight = datetime.combine(target_date, time(0, 0), tzinfo=timezone.utc)
        event_utc = utc_midnight + timedelta(hours=universal_time_hours)
        return event_utc.astimezone(tzinfo)

    @staticmethod
    def iso_local(value):
        if not isinstance(value, datetime):
            return None
        return value.isoformat(timespec="seconds")

    @staticmethod
    def parse_numeric(value):
        try:
            if value in (None, ""):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def pick_first_numeric(cls, *values):
        for value in values:
            number = cls.parse_numeric(value)
            if number is not None:
                return round(max(0.0, min(100.0, number)), 1)
        return None

    @staticmethod
    def describe_provider_error(exc):
        if isinstance(exc, HTTPError):
            return f"HTTP failure ({exc.code}): {exc.reason}"
        if isinstance(exc, json.JSONDecodeError):
            return "Malformed response: invalid JSON"

        reason = exc.reason if isinstance(exc, URLError) and hasattr(exc, "reason") else exc
        reason_text = str(reason or exc)
        lowered = reason_text.lower()

        if isinstance(reason, socket.gaierror) or "name or service not known" in lowered or "nodename nor servname" in lowered:
            return f"DNS failure: {reason_text}"
        if "handshake" in lowered and "timed out" in lowered:
            return f"SSL handshake timeout: {reason_text}"
        if isinstance(reason, ssl.SSLError) and "timed out" in lowered:
            return f"SSL handshake timeout: {reason_text}"
        if isinstance(exc, (TimeoutError, socket.timeout)) or "timed out" in lowered:
            return f"Provider timeout: {reason_text}"
        if isinstance(exc, URLError):
            return f"Provider connection failure: {reason_text}"
        if isinstance(exc, ValueError):
            return f"Malformed response: {reason_text}"
        return f"Provider error: {reason_text}"

    def log_weather_warning(self, message, seconds=900):
        now = datetime.now()
        if not self._last_warning_at or (now - self._last_warning_at).total_seconds() >= seconds:
            self._last_warning_at = now
            self.log.warning(message)
        else:
            self.log.debug(message)
