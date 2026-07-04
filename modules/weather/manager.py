import json
import socket
import ssl
from datetime import datetime
from urllib.parse import urlencode
from urllib.error import URLError, HTTPError
from urllib.request import urlopen


WEATHER_DEFAULTS = {
    "enabled": True,
    "location_name": "Home",
    "latitude": "",
    "longitude": "",
    "provider": "placeholder",
}

OPEN_METEO_TIMEOUT_SECONDS = 10
OPEN_METEO_CACHE_SECONDS = 600
OPEN_METEO_FAILURE_COOLDOWN_SECONDS = 180


class WeatherManager:
    def __init__(self, config, log):
        self.config = config
        self.log = log
        self._last_status = None
        self._last_error_status = None
        self._last_warning_at = None
        self._last_fetch_at = None
        self._last_failure_at = None

    def weather_config(self):
        configured = dict(self.config.get("weather", default={}))
        merged = dict(WEATHER_DEFAULTS)
        merged.update(configured)
        return merged

    def get_status(self):
        weather = self.weather_config()
        if not weather.get("enabled", True):
            return self.status_payload(
                weather,
                enabled=False,
                condition="Disabled",
                source="Disabled",
                error=None,
            )

        provider = str(weather.get("provider") or "placeholder").strip().lower()
        if provider not in ("placeholder", "manual", "open_meteo"):
            provider = "placeholder"
        if provider == "open_meteo":
            return self.open_meteo_status(weather)

        # Placeholder/manual provider intentionally returns no measured weather values.
        return self.status_payload(
            weather,
            enabled=True,
            condition="Weather provider not connected",
            source="Placeholder",
            error=None,
        )

    def open_meteo_status(self, weather):
        now = datetime.now()
        if self._last_status and self._last_fetch_at and (now - self._last_fetch_at).total_seconds() < OPEN_METEO_CACHE_SECONDS:
            return dict(self._last_status)

        if self._last_failure_at and (now - self._last_failure_at).total_seconds() < OPEN_METEO_FAILURE_COOLDOWN_SECONDS:
            if self._last_status:
                return self.stale_cached_status(self._last_status, self._last_error_status)
            if self._last_error_status:
                return dict(self._last_error_status)

        latitude = self.parse_float(weather.get("latitude"))
        longitude = self.parse_float(weather.get("longitude"))
        if latitude is None or longitude is None:
            return self.status_payload(
                weather,
                enabled=True,
                condition="Latitude and longitude required",
                source="Open-Meteo",
                live_data=False,
                error="Open-Meteo requires latitude and longitude.",
            )

        params = urlencode({
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,relative_humidity_2m,cloud_cover,wind_speed_10m,uv_index",
            "hourly": "temperature_2m,relative_humidity_2m,cloud_cover,wind_speed_10m,uv_index",
            "daily": "sunrise,sunset,uv_index_max,temperature_2m_max,temperature_2m_min",
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "timezone": "auto",
            "forecast_days": 3,
        })
        url = f"https://api.open-meteo.com/v1/forecast?{params}"
        try:
            with urlopen(url, timeout=OPEN_METEO_TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
            self.validate_open_meteo_payload(payload)
            status = self.open_meteo_payload(weather, payload)
            self._last_status = status
            self._last_fetch_at = now
            self._last_failure_at = None
            self._last_error_status = None
            return status
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, ValueError, ssl.SSLError, socket.timeout) as exc:
            error_text = self.describe_provider_error(exc)
            self.log_weather_warning(f"Open-Meteo weather fetch failed: {error_text}")
            self._last_failure_at = now
            self._last_error_status = self.status_payload(
                weather,
                enabled=True,
                condition="Weather provider error",
                source="Open-Meteo",
                live_data=False,
                error=error_text,
            )
            self._last_error_status["message"] = "Open-Meteo provider error; retrying after cooldown."
            if self._last_status:
                return self.stale_cached_status(self._last_status, self._last_error_status)
            return dict(self._last_error_status)

    def open_meteo_payload(self, weather, payload):
        current = payload.get("current") or {}
        daily = payload.get("daily") or {}
        hourly = payload.get("hourly") or {}
        cloud_cover = self.parse_float(current.get("cloud_cover"))
        temperature = self.parse_float(current.get("temperature_2m"))
        humidity = self.parse_float(current.get("relative_humidity_2m"))
        wind = self.parse_float(current.get("wind_speed_10m"))
        uv = self.parse_float(current.get("uv_index"))
        sunshine = round(max(0, min(100, 100 - cloud_cover)), 1) if cloud_cover is not None else None
        return {
            "enabled": True,
            "configured": True,
            "location_name": weather.get("location_name") or "Home",
            "latitude": weather.get("latitude") or None,
            "longitude": weather.get("longitude") or None,
            "provider": "open_meteo",
            "live_data": True,
            "temperature_f": temperature,
            "condition": self.condition_from_clouds(cloud_cover),
            "cloud_cover_percent": cloud_cover,
            "sunshine_percent": sunshine,
            "humidity_percent": humidity,
            "wind_mph": wind,
            "uv_index": uv,
            "sunrise": self.first_value(daily.get("sunrise")),
            "sunset": self.first_value(daily.get("sunset")),
            "forecast_days": self.forecast_days(daily),
            "hourly": self.hourly_rows(hourly),
            "last_updated": str(datetime.now()),
            "source": "Open-Meteo",
            "error": None,
            "message": "Weather Center is receiving live Open-Meteo data.",
        }

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
            "condition": condition,
            "cloud_cover_percent": None,
            "sunshine_percent": None,
            "humidity_percent": None,
            "wind_mph": None,
            "uv_index": None,
            "sunrise": None,
            "sunset": None,
            "forecast_days": [],
            "hourly": [],
            "last_updated": str(datetime.now()),
            "source": source,
            "error": error,
            "message": "Weather Center is ready for a live provider." if enabled else "Weather Center is disabled.",
        }

    def stale_cached_status(self, cached_status, error_status):
        stale = dict(cached_status)
        stale["live_data"] = False
        stale["stale"] = True
        stale["source"] = "Open-Meteo (stale cache)"
        stale["condition"] = f"{stale.get('condition') or 'Weather available'} (stale)"
        stale["error"] = error_status.get("error") if error_status else "Using stale weather data due to provider error."
        stale["message"] = "Showing last known weather due to Open-Meteo provider issue."
        return stale

    @staticmethod
    def validate_open_meteo_payload(payload):
        if not isinstance(payload, dict):
            raise ValueError("Malformed response: payload is not an object")
        current = payload.get("current")
        if not isinstance(current, dict):
            raise ValueError("Malformed response: missing current section")
        if "temperature_2m" not in current:
            raise ValueError("Malformed response: current.temperature_2m missing")
        daily = payload.get("daily")
        if not isinstance(daily, dict):
            raise ValueError("Malformed response: missing daily section")

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

    @staticmethod
    def parse_float(value):
        try:
            if value in (None, ""):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def condition_from_clouds(cloud_cover):
        if cloud_cover is None:
            return "Weather data received"
        if cloud_cover <= 20:
            return "Sunny"
        if cloud_cover <= 60:
            return "Partly cloudy"
        return "Cloudy"

    @staticmethod
    def first_value(values):
        if isinstance(values, list) and values:
            return values[0]
        return None

    def forecast_days(self, daily):
        times = daily.get("time") or []
        rows = []
        for index, day in enumerate(times[:3]):
            rows.append({
                "date": day,
                "sunrise": self.item_at(daily.get("sunrise"), index),
                "sunset": self.item_at(daily.get("sunset"), index),
                "temperature_max_f": self.item_at(daily.get("temperature_2m_max"), index),
                "temperature_min_f": self.item_at(daily.get("temperature_2m_min"), index),
                "uv_index_max": self.item_at(daily.get("uv_index_max"), index),
            })
        return rows

    def hourly_rows(self, hourly):
        times = hourly.get("time") or []
        rows = []
        for index, timestamp in enumerate(times[:48]):
            rows.append({
                "timestamp": timestamp,
                "temperature_f": self.item_at(hourly.get("temperature_2m"), index),
                "cloud_cover_percent": self.item_at(hourly.get("cloud_cover"), index),
                "humidity_percent": self.item_at(hourly.get("relative_humidity_2m"), index),
                "wind_mph": self.item_at(hourly.get("wind_speed_10m"), index),
                "uv_index": self.item_at(hourly.get("uv_index"), index),
            })
        return rows

    @staticmethod
    def item_at(values, index):
        if isinstance(values, list) and index < len(values):
            return values[index]
        return None

    def log_weather_warning(self, message, seconds=900):
        now = datetime.now()
        if not self._last_warning_at or (now - self._last_warning_at).total_seconds() >= seconds:
            self._last_warning_at = now
            self.log.warning(message)
        else:
            self.log.debug(message)
