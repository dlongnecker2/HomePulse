import json
import socket
import ssl
from copy import deepcopy
from datetime import datetime
from urllib.error import HTTPError, URLError

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
                status,
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
                status,
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
                status = dict(state["last_status"])
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
                status = provider.fetch_status(weather, PROVIDER_TIMEOUT_SECONDS)
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
                    stale_candidates.append((key, self.stale_cached_status(state["last_status"], state["last_error_status"], provider.source_name)))

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
            status,
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
