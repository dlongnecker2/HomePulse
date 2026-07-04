import json
import re
from urllib.request import Request, urlopen


class WeatherProvider:
    provider_key = "base"
    source_name = "Unknown"

    def fetch_status(self, weather, timeout_seconds):
        raise NotImplementedError()

    @staticmethod
    def request_json(url, timeout_seconds, headers=None):
        request = Request(url=url, method="GET", headers=headers or {})
        with urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))

    @staticmethod
    def parse_float(value):
        try:
            if value in (None, ""):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def first_value(values):
        if isinstance(values, list) and values:
            return values[0]
        return None

    @staticmethod
    def item_at(values, index):
        if isinstance(values, list) and index < len(values):
            return values[index]
        return None

    @staticmethod
    def parse_wind_mph(value):
        if value in (None, ""):
            return None
        if isinstance(value, (int, float)):
            return round(float(value), 1)

        text = str(value).strip().lower()
        matches = re.findall(r"\d+(?:\.\d+)?", text)
        if not matches:
            return None

        numbers = [float(item) for item in matches]
        if not numbers:
            return None

        return round(sum(numbers) / len(numbers), 1)
