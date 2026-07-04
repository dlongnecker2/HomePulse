from datetime import datetime
from urllib.parse import urlencode

from modules.weather.providers.base import WeatherProvider


class OpenMeteoProvider(WeatherProvider):
    provider_key = "open_meteo"
    source_name = "Open-Meteo"

    def fetch_status(self, weather, timeout_seconds):
        latitude = self.parse_float(weather.get("latitude"))
        longitude = self.parse_float(weather.get("longitude"))
        if latitude is None or longitude is None:
            raise ValueError("Latitude and longitude are required for Open-Meteo.")

        params = urlencode({
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,cloud_cover,wind_speed_10m,uv_index",
            "hourly": "temperature_2m,apparent_temperature,relative_humidity_2m,cloud_cover,wind_speed_10m,uv_index",
            "daily": "sunrise,sunset,uv_index_max,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "timezone": "auto",
            "forecast_days": 7,
        })
        url = f"https://api.open-meteo.com/v1/forecast?{params}"
        payload = self.request_json(url, timeout_seconds)
        self.validate_payload(payload)
        return self.payload_to_status(weather, payload)

    def payload_to_status(self, weather, payload):
        current = payload.get("current") or {}
        daily = payload.get("daily") or {}
        hourly = payload.get("hourly") or {}

        cloud_cover = self.parse_float(current.get("cloud_cover"))
        temperature = self.parse_float(current.get("temperature_2m"))
        apparent_temperature = self.parse_float(current.get("apparent_temperature"))
        humidity = self.parse_float(current.get("relative_humidity_2m"))
        wind = self.parse_float(current.get("wind_speed_10m"))
        uv = self.parse_float(current.get("uv_index"))
        if uv is None:
            uv = self.parse_float(self.item_at(daily.get("uv_index_max"), 0))
        sunshine = round(max(0, min(100, 100 - cloud_cover)), 1) if cloud_cover is not None else None

        return {
            "enabled": True,
            "configured": True,
            "location_name": weather.get("location_name") or "Home",
            "latitude": weather.get("latitude") or None,
            "longitude": weather.get("longitude") or None,
            "provider": self.provider_key,
            "live_data": True,
            "temperature_f": temperature,
            "feels_like_f": apparent_temperature,
            "apparent_temperature_f": apparent_temperature,
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
            "source": self.source_name,
            "error": None,
            "message": "Weather Center is receiving live Open-Meteo data.",
        }

    @staticmethod
    def validate_payload(payload):
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
    def condition_from_clouds(cloud_cover):
        if cloud_cover is None:
            return "Weather data received"
        if cloud_cover <= 20:
            return "Sunny"
        if cloud_cover <= 60:
            return "Partly cloudy"
        return "Cloudy"

    def forecast_days(self, daily):
        times = daily.get("time") or []
        rows = []
        for index, day in enumerate(times[:7]):
            rows.append({
                "date": day,
                "sunrise": self.item_at(daily.get("sunrise"), index),
                "sunset": self.item_at(daily.get("sunset"), index),
                "temperature_max_f": self.item_at(daily.get("temperature_2m_max"), index),
                "temperature_min_f": self.item_at(daily.get("temperature_2m_min"), index),
                "precipitation_probability_percent": self.item_at(daily.get("precipitation_probability_max"), index),
                "precipitation_chance_percent": self.item_at(daily.get("precipitation_probability_max"), index),
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
                "apparent_temperature_f": self.item_at(hourly.get("apparent_temperature"), index),
                "cloud_cover_percent": self.item_at(hourly.get("cloud_cover"), index),
                "humidity_percent": self.item_at(hourly.get("relative_humidity_2m"), index),
                "wind_mph": self.item_at(hourly.get("wind_speed_10m"), index),
                "uv_index": self.item_at(hourly.get("uv_index"), index),
            })
        return rows
