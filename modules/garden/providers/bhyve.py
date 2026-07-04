from datetime import datetime

from modules.garden.providers.base import GardenProvider


class BhyveProvider(GardenProvider):
    provider_key = "bhyve"
    source_name = "Orbit B-hyve"

    def fetch_status(self, garden, timeout_seconds):
        providers = garden.get("providers", {}) if isinstance(garden, dict) else {}
        bhyve_cfg = providers.get("bhyve", {}) if isinstance(providers, dict) else {}

        username = str(bhyve_cfg.get("username") or "").strip()
        password = str(bhyve_cfg.get("password") or "").strip()
        token = str(bhyve_cfg.get("access_token") or "").strip()

        if not username and not token:
            raise ValueError("B-hyve credentials are required.")
        if username and not password and not token:
            raise ValueError("B-hyve password or access token is required.")

        return {
            "enabled": True,
            "configured": True,
            "status": "Provider pending",
            "provider": self.provider_key,
            "source": self.source_name,
            "live_data": False,
            "controller_count": 0,
            "controllers": [],
            "active_watering_zone": None,
            "next_watering_schedule": None,
            "rain_delay_active": None,
            "rain_delay_until": None,
            "last_updated": str(datetime.now()),
            "error": None,
            "message": "B-hyve provider credentials saved. Live read-only API integration is pending in a follow-up sprint.",
        }
