from datetime import datetime

from modules.weather.providers.base import WeatherProvider


class NationalWeatherServiceProvider(WeatherProvider):
    provider_key = "national_weather_service"
    source_name = "National Weather Service"

    def fetch_status(self, weather, timeout_seconds):
        latitude = self.parse_float(weather.get("latitude"))
        longitude = self.parse_float(weather.get("longitude"))
        if latitude is None or longitude is None:
            raise ValueError("Latitude and longitude are required for National Weather Service.")

        headers = {
            "Accept": "application/geo+json",
            "User-Agent": "HomePulse/3.6.1a (WeatherCenter)",
        }
        points_url = f"https://api.weather.gov/points/{latitude},{longitude}"
        points_payload = self.request_json(points_url, timeout_seconds, headers=headers)
        points_props = points_payload.get("properties") if isinstance(points_payload, dict) else None
        if not isinstance(points_props, dict):
            raise ValueError("Malformed response: points.properties missing")

        hourly_url = points_props.get("forecastHourly")
        daily_url = points_props.get("forecast")
        if not hourly_url or not daily_url:
            raise ValueError("Malformed response: forecast URLs missing from points endpoint")

        hourly_payload = self.request_json(hourly_url, timeout_seconds, headers=headers)
        daily_payload = self.request_json(daily_url, timeout_seconds, headers=headers)
        return self.payload_to_status(weather, hourly_payload, daily_payload)

    def payload_to_status(self, weather, hourly_payload, daily_payload):
        hourly_periods = self.periods_from_payload(hourly_payload)
        if not hourly_periods:
            raise ValueError("Malformed response: forecast hourly periods missing")

        current = hourly_periods[0]
        temperature = self.parse_float(current.get("temperature"))
        humidity = self.relative_humidity(current)
        wind_mph = self.parse_wind_mph(current.get("windSpeed"))
        condition = current.get("shortForecast") or current.get("detailedForecast") or "Forecast available"

        daily_periods = self.periods_from_payload(daily_payload)
        forecast_days = self.forecast_days(daily_periods)

        return {
            "enabled": True,
            "configured": True,
            "location_name": weather.get("location_name") or "Home",
            "latitude": weather.get("latitude") or None,
            "longitude": weather.get("longitude") or None,
            "provider": self.provider_key,
            "live_data": True,
            "temperature_f": temperature,
            "condition": condition,
            "cloud_cover_percent": None,
            "sunshine_percent": None,
            "humidity_percent": humidity,
            "wind_mph": wind_mph,
            "uv_index": None,
            "sunrise": None,
            "sunset": None,
            "forecast_days": forecast_days,
            "hourly": self.hourly_rows(hourly_periods),
            "last_updated": str(datetime.now()),
            "source": self.source_name,
            "error": None,
            "message": "Weather Center is receiving live National Weather Service data.",
        }

    @staticmethod
    def periods_from_payload(payload):
        props = payload.get("properties") if isinstance(payload, dict) else None
        periods = props.get("periods") if isinstance(props, dict) else None
        if isinstance(periods, list):
            return periods
        return []

    @staticmethod
    def relative_humidity(period):
        value = period.get("relativeHumidity") if isinstance(period, dict) else None
        if isinstance(value, dict):
            value = value.get("value")
        return WeatherProvider.parse_float(value)

    def forecast_days(self, daily_periods):
        if not daily_periods:
            return []

        rows = []
        for index, period in enumerate(daily_periods):
            if len(rows) >= 3:
                break
            if not isinstance(period, dict):
                continue
            if not period.get("isDaytime", False):
                continue

            date_text = str(period.get("startTime") or "")[:10] or period.get("name") or f"day-{index + 1}"
            night_period = None
            if index + 1 < len(daily_periods):
                candidate = daily_periods[index + 1]
                if isinstance(candidate, dict) and not candidate.get("isDaytime", True):
                    night_period = candidate

            rows.append({
                "date": date_text,
                "sunrise": None,
                "sunset": None,
                "temperature_max_f": self.parse_float(period.get("temperature")),
                "temperature_min_f": self.parse_float(night_period.get("temperature")) if night_period else None,
                "uv_index_max": None,
            })

        return rows

    def hourly_rows(self, hourly_periods):
        rows = []
        for period in hourly_periods[:48]:
            if not isinstance(period, dict):
                continue
            rows.append({
                "timestamp": period.get("startTime"),
                "temperature_f": self.parse_float(period.get("temperature")),
                "cloud_cover_percent": None,
                "humidity_percent": self.relative_humidity(period),
                "wind_mph": self.parse_wind_mph(period.get("windSpeed")),
                "uv_index": None,
            })
        return rows
