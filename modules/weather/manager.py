from datetime import datetime


WEATHER_DEFAULTS = {
    "enabled": True,
    "location_name": "Home",
    "latitude": "",
    "longitude": "",
    "provider": "placeholder",
}


class WeatherManager:
    def __init__(self, config, log):
        self.config = config
        self.log = log

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
        if provider not in ("placeholder", "manual"):
            provider = "placeholder"

        # Placeholder/manual provider intentionally returns no measured weather values.
        return self.status_payload(
            weather,
            enabled=True,
            condition="Weather provider not connected",
            source="Placeholder",
            error=None,
        )

    def status_payload(self, weather, enabled, condition, source, error):
        return {
            "enabled": enabled,
            "configured": bool(enabled),
            "location_name": weather.get("location_name") or "Home",
            "latitude": weather.get("latitude") or None,
            "longitude": weather.get("longitude") or None,
            "provider": weather.get("provider") or "placeholder",
            "temperature_f": None,
            "condition": condition,
            "cloud_cover_percent": None,
            "sunshine_percent": None,
            "humidity_percent": None,
            "wind_mph": None,
            "uv_index": None,
            "sunrise": None,
            "sunset": None,
            "last_updated": str(datetime.now()),
            "source": source,
            "error": error,
            "message": "Weather Center is ready for a live provider." if enabled else "Weather Center is disabled.",
        }
