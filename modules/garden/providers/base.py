import json
from urllib.request import Request, urlopen


class GardenProvider:
    provider_key = "base"
    source_name = "Unknown"

    def fetch_status(self, garden, timeout_seconds):
        raise NotImplementedError()

    @staticmethod
    def request_json(url, timeout_seconds, headers=None, method="GET", body=None):
        request = Request(url=url, method=method, headers=headers or {}, data=body)
        with urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))
