import json
import socket
import ssl
from datetime import datetime
from urllib.error import HTTPError, URLError

from modules.weather.providers import NationalWeatherServiceProvider, OpenMeteoProvider


WEATHER_DEFAULTS = {
    "enabled": True,
    "location_name": "Home",
    "latitude": "",
    "longitude": "",
    "provider": "placeholder",
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
            "open_meteo": OpenMeteoProvider(),
            "national_weather_service": NationalWeatherServiceProvider(),
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

        provider_key = self.normalize_provider_key(weather.get("provider"))
        if provider_key not in self.providers:
            return self.status_payload(
                weather,
                enabled=True,
                condition="Weather provider not connected",
                source="Placeholder",
                error=None,
            )

        return self.fetch_provider_status(weather, provider_key)

    def fetch_provider_status(self, weather, provider_key):
        provider = self.providers[provider_key]
        state = self._provider_state[provider_key]
        now = datetime.now()

        if state["last_status"] and state["last_fetch_at"] and (now - state["last_fetch_at"]).total_seconds() < PROVIDER_CACHE_SECONDS:
            return dict(state["last_status"])

        if state["last_failure_at"] and (now - state["last_failure_at"]).total_seconds() < PROVIDER_FAILURE_COOLDOWN_SECONDS:
            if state["last_status"]:
                return self.stale_cached_status(state["last_status"], state["last_error_status"], provider.source_name)
            if state["last_error_status"]:
                return dict(state["last_error_status"])

        try:
            status = provider.fetch_status(weather, PROVIDER_TIMEOUT_SECONDS)
            state["last_status"] = status
            state["last_fetch_at"] = now
            state["last_failure_at"] = None
            state["last_error_status"] = None
            return dict(status)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, ValueError, ssl.SSLError, socket.timeout) as exc:
            error_text = self.describe_provider_error(exc)
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
            state["last_error_status"]["message"] = f"{provider.source_name} provider error; retrying after cooldown."

            if state["last_status"]:
                return self.stale_cached_status(state["last_status"], state["last_error_status"], provider.source_name)

            return dict(state["last_error_status"])

    @staticmethod
    def normalize_provider_key(value):
        provider = str(value or "placeholder").strip().lower()
        aliases = {
            "nws": "national_weather_service",
            "weather_gov": "national_weather_service",
        }
        provider = aliases.get(provider, provider)
        if provider in ("placeholder", "manual"):
            return "placeholder"
        return provider

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

    def stale_cached_status(self, cached_status, error_status, provider_source_name):
        stale = dict(cached_status)
        stale["live_data"] = False
        stale["stale"] = True
        stale["source"] = f"{provider_source_name} (stale cache)"
        stale["condition"] = f"{stale.get('condition') or 'Weather available'} (stale)"
        stale["error"] = error_status.get("error") if error_status else "Using stale weather data due to provider error."
        stale["message"] = f"Showing last known weather due to {provider_source_name} provider issue."
        return stale

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
