import json
from urllib.request import Request, urlopen


class LightingProvider:
    provider_key = "base"
    source_name = "Unknown"

    def fetch_status(self, lighting, timeout_seconds):
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
