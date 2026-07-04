import json
import socket
import ssl
from copy import deepcopy
from datetime import datetime
from urllib.error import HTTPError, URLError

from modules.garden.providers import BhyveProvider


GARDEN_DEFAULTS = {
    "enabled": False,
    "provider_strategy": "automatic_failover",
    "provider_priority": ["bhyve"],
    "providers": {
        "bhyve": {
            "enabled": False,
            "username": "",
            "password": "",
            "access_token": "",
        }
    },
}

PROVIDER_TIMEOUT_SECONDS = 4
PROVIDER_CACHE_SECONDS = 120
PROVIDER_FAILURE_COOLDOWN_SECONDS = 180


class GardenManager:
    def __init__(self, config, log):
        self.config = config
        self.log = log
        self._last_warning_at = None
        self.providers = {
            "bhyve": BhyveProvider(),
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

    def garden_config(self):
        configured = dict(self.config.get("garden", default={}))
        merged = deepcopy(GARDEN_DEFAULTS)
        for key, value in configured.items():
            if key == "providers" and isinstance(value, dict):
                merged.setdefault("providers", {})
                for provider_key, provider_data in value.items():
                    if isinstance(provider_data, dict):
                        merged["providers"].setdefault(provider_key, {})
                        merged["providers"][provider_key].update(provider_data)
            elif key == "provider_priority" and isinstance(value, list):
                merged[key] = list(value)
            else:
                merged[key] = value

        bhyve_cfg = merged.setdefault("providers", {}).setdefault("bhyve", {})
        bhyve_cfg["enabled"] = bool(bhyve_cfg.get("enabled", False))
        bhyve_cfg["username"] = str(bhyve_cfg.get("username") or "")
        bhyve_cfg["password"] = str(bhyve_cfg.get("password") or "")
        bhyve_cfg["access_token"] = str(bhyve_cfg.get("access_token") or "")

        priority = merged.get("provider_priority")
        if not isinstance(priority, list) or not priority:
            priority = ["bhyve"]
        else:
            normalized = []
            for key in priority:
                text = str(key or "").strip().lower()
                if text == "bhyve" and text not in normalized:
                    normalized.append(text)
            if "bhyve" not in normalized:
                normalized.append("bhyve")
            priority = normalized

        merged["provider_priority"] = priority
        merged["provider_strategy"] = "automatic_failover"
        return merged

    def enabled_providers_in_priority(self, garden):
        providers = garden.get("providers", {})
        priority = garden.get("provider_priority", [])
        enabled = []
        for key in priority:
            provider_cfg = providers.get(key, {})
            if isinstance(provider_cfg, dict) and provider_cfg.get("enabled", False):
                enabled.append(key)
        return enabled

    def get_status(self):
        garden = self.garden_config()
        if not garden.get("enabled", False):
            status = self.status_payload(
                enabled=False,
                configured=False,
                status="Disabled",
                source="Garden framework",
                live_data=False,
                error=None,
                message="Garden Center is disabled.",
            )
            return self.attach_framework_fields(status, garden, [], {}, None, False)

        enabled_providers = self.enabled_providers_in_priority(garden)
        if not enabled_providers:
            status = self.status_payload(
                enabled=True,
                configured=False,
                status="Not configured",
                source="Garden framework",
                live_data=False,
                error="No garden providers are enabled.",
                message="Enable the B-hyve provider in Settings.",
            )
            return self.attach_framework_fields(status, garden, [], {}, None, False)

        return self.fetch_with_failover(garden, enabled_providers)

    def fetch_with_failover(self, garden, enabled_providers):
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
                return self.attach_framework_fields(dict(state["last_status"]), garden, attempted, provider_errors, key, False)

            if state["last_failure_at"] and (now - state["last_failure_at"]).total_seconds() < PROVIDER_FAILURE_COOLDOWN_SECONDS:
                provider_errors[key] = "Provider in failure cooldown"
                if state["last_status"]:
                    stale_candidates.append((key, self.stale_cached_status(state["last_status"], state["last_error_status"], provider.source_name)))
                continue

            try:
                status = provider.fetch_status(garden, PROVIDER_TIMEOUT_SECONDS)
                state["last_status"] = dict(status)
                state["last_fetch_at"] = now
                state["last_failure_at"] = None
                state["last_error_status"] = None
                return self.attach_framework_fields(status, garden, attempted, provider_errors, key, False)
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, ValueError, ssl.SSLError, socket.timeout) as exc:
                error_text = self.describe_provider_error(exc)
                provider_errors[key] = error_text
                self.log_garden_warning(f"{provider.source_name} garden fetch failed: {error_text}")

                state["last_failure_at"] = now
                state["last_error_status"] = self.status_payload(
                    enabled=True,
                    configured=False,
                    status="Provider error",
                    source=provider.source_name,
                    live_data=False,
                    error=error_text,
                    message=f"{provider.source_name} provider error; failover will continue.",
                )

                if state["last_status"]:
                    stale_candidates.append((key, self.stale_cached_status(state["last_status"], state["last_error_status"], provider.source_name)))

        if stale_candidates:
            selected_key, stale_status = stale_candidates[0]
            stale_status["message"] = "All live providers failed; using stale cached garden data."
            return self.attach_framework_fields(stale_status, garden, attempted, provider_errors, selected_key, True)

        summary = "; ".join([f"{key}: {text}" for key, text in provider_errors.items()]) or "All providers failed."
        status = self.status_payload(
            enabled=True,
            configured=False,
            status="Unavailable",
            source="Garden framework",
            live_data=False,
            error=summary,
            message="Garden providers unavailable.",
        )
        return self.attach_framework_fields(status, garden, attempted, provider_errors, None, True)

    @staticmethod
    def status_payload(enabled, configured, status, source, live_data, error, message):
        return {
            "enabled": enabled,
            "configured": configured,
            "status": status,
            "provider": "bhyve",
            "source": source,
            "live_data": live_data,
            "controller_count": 0,
            "controllers": [],
            "active_watering_zone": None,
            "next_watering_schedule": None,
            "rain_delay_active": None,
            "rain_delay_until": None,
            "last_updated": str(datetime.now()),
            "error": error,
            "message": message,
        }

    def attach_framework_fields(self, status, garden, attempted_providers, provider_errors, selected_provider, fallback_used):
        result = dict(status)
        result["provider_strategy"] = "automatic_failover"
        result["enabled_providers"] = self.enabled_providers_in_priority(garden)
        result["attempted_providers"] = list(attempted_providers)
        result["provider_errors"] = dict(provider_errors)
        result["fallback_used"] = bool(fallback_used)
        result["selected_provider"] = selected_provider
        if selected_provider:
            result["provider"] = selected_provider
        return result

    @staticmethod
    def stale_cached_status(cached_status, error_status, provider_source_name):
        stale = dict(cached_status)
        stale["live_data"] = False
        stale["stale"] = True
        stale["source"] = f"{provider_source_name} (stale cache)"
        stale["status"] = f"{stale.get('status') or 'Available'} (stale)"
        stale["error"] = error_status.get("error") if error_status else "Using stale garden data due to provider error."
        stale["message"] = f"Showing last known garden status due to {provider_source_name} provider issue."
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
        if "timed out" in lowered:
            return f"Provider timeout: {reason_text}"
        if isinstance(exc, URLError):
            return f"Provider connection failure: {reason_text}"
        if isinstance(exc, ValueError):
            return f"Provider configuration issue: {reason_text}"
        return f"Provider error: {reason_text}"

    def log_garden_warning(self, message, seconds=600):
        now = datetime.now()
        if not self._last_warning_at or (now - self._last_warning_at).total_seconds() >= seconds:
            self._last_warning_at = now
            self.log.warning(message)
        else:
            self.log.debug(message)
