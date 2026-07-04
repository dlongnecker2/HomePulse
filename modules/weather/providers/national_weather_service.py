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
        grid_url = points_props.get("forecastGridData")
        if not hourly_url or not daily_url:
            raise ValueError("Malformed response: forecast URLs missing from points endpoint")

        hourly_payload = self.request_json(hourly_url, timeout_seconds, headers=headers)
        daily_payload = self.request_json(daily_url, timeout_seconds, headers=headers)
        grid_payload = None
        if grid_url:
            try:
                grid_payload = self.request_json(grid_url, timeout_seconds, headers=headers)
            except Exception:
                grid_payload = None
        return self.payload_to_status(weather, points_props, hourly_payload, daily_payload, grid_payload)

    def payload_to_status(self, weather, points_props, hourly_payload, daily_payload, grid_payload):
        hourly_periods = self.periods_from_payload(hourly_payload)
        if not hourly_periods:
            raise ValueError("Malformed response: forecast hourly periods missing")

        current = hourly_periods[0]
        temperature = self.parse_float(current.get("temperature"))
        humidity = self.relative_humidity(current)
        wind_mph = self.parse_wind_mph(current.get("windSpeed"))
        condition = current.get("shortForecast") or current.get("detailedForecast") or "Forecast available"
        current_precip = self.quantitative_value(current.get("probabilityOfPrecipitation"))

        cloud_cover = self.gridpoint_current_value(grid_payload, "skyCover")
        cloud_cover_estimated = False
        cloud_cover_estimation_method = None
        if cloud_cover is None:
            cloud_cover = self.estimate_cloud_cover_from_condition(condition)
            if cloud_cover is not None:
                cloud_cover_estimated = True
                cloud_cover_estimation_method = "estimated_from_condition_text"

        sunshine = round(max(0.0, min(100.0, 100.0 - cloud_cover)), 1) if cloud_cover is not None else None
        sunrise = self.extract_astronomical(points_props, "sunrise")
        sunset = self.extract_astronomical(points_props, "sunset")

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
            "feels_like_f": None,
            "apparent_temperature_f": None,
            "condition": condition,
            "cloud_cover_percent": cloud_cover,
            "cloud_cover_estimated": cloud_cover_estimated,
            "cloud_cover_estimation_method": cloud_cover_estimation_method,
            "sunshine_percent": sunshine,
            "precipitation_probability_percent": current_precip,
            "humidity_percent": humidity,
            "wind_mph": wind_mph,
            "uv_index": None,
            "sunrise": sunrise,
            "sunset": sunset,
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
            if len(rows) >= 7:
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
                "condition": period.get("shortForecast") or period.get("detailedForecast"),
                "temperature_max_f": self.parse_float(period.get("temperature")),
                "temperature_min_f": self.parse_float(night_period.get("temperature")) if night_period else None,
                "precipitation_probability_percent": self.quantitative_value(period.get("probabilityOfPrecipitation")),
                "precipitation_chance_percent": self.quantitative_value(period.get("probabilityOfPrecipitation")),
                "wind_mph": self.parse_wind_mph(period.get("windSpeed")),
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
                "precipitation_probability_percent": self.quantitative_value(period.get("probabilityOfPrecipitation")),
                "uv_index": None,
            })
        return rows

    @staticmethod
    def quantitative_value(field):
        value = field
        if isinstance(field, dict):
            value = field.get("value")
        number = WeatherProvider.parse_float(value)
        if number is None:
            return None
        return round(max(0.0, min(100.0, number)), 1)

    @staticmethod
    def extract_astronomical(points_props, key):
        astronomical = points_props.get("astronomicalData") if isinstance(points_props, dict) else None
        if isinstance(astronomical, dict):
            value = astronomical.get(key)
            if isinstance(value, str) and value:
                return value
        return None

    @staticmethod
    def estimate_cloud_cover_from_condition(condition):
        text = str(condition or "").strip().lower()
        if not text:
            return None
        if any(token in text for token in ("rain", "snow", "fog", "mist", "haze", "thunder", "showers", "drizzle")):
            return 90.0
        if "mostly sunny" in text:
            return 20.0
        if "partly cloudy" in text or "partly sunny" in text:
            return 40.0
        if "mostly cloudy" in text:
            return 75.0
        if "cloudy" in text or "overcast" in text:
            return 95.0
        if "sunny" in text or "clear" in text:
            return 5.0
        return None

    @staticmethod
    def gridpoint_current_value(grid_payload, field_name):
        props = grid_payload.get("properties") if isinstance(grid_payload, dict) else None
        field = props.get(field_name) if isinstance(props, dict) else None
        values = field.get("values") if isinstance(field, dict) else None
        if not isinstance(values, list) or not values:
            return None

        now_utc = datetime.now().astimezone()
        # Use most recent valid value by start timestamp; values are generally ordered chronologically.
        best_value = None
        best_time = None
        for item in values:
            if not isinstance(item, dict):
                continue
            valid_time = str(item.get("validTime") or "")
            start_text = valid_time.split("/", 1)[0]
            try:
                start_dt = datetime.fromisoformat(start_text.replace("Z", "+00:00"))
            except ValueError:
                continue
            if start_dt.tzinfo is None:
                continue

            numeric = WeatherProvider.parse_float(item.get("value"))
            if numeric is None:
                continue

            if start_dt <= now_utc and (best_time is None or start_dt >= best_time):
                best_time = start_dt
                best_value = numeric

        if best_value is None:
            for item in values:
                if not isinstance(item, dict):
                    continue
                first_numeric = WeatherProvider.parse_float(item.get("value"))
                if first_numeric is not None:
                    return round(max(0.0, min(100.0, first_numeric)), 1)
            return None

        return round(max(0.0, min(100.0, best_value)), 1)
