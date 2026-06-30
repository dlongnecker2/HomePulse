import json
from copy import deepcopy
from pathlib import Path

CONFIG_FILE = Path("config.json")

DEFAULT_CONFIG = {
    "energy": {
        "enabled": False,
        "vehicle_name": "2025 Chevrolet Equinox EV",
        "charger_name": "ChargePoint Home Flex",
        "cost_per_kwh": 0.13,
        "estimated_miles_per_kwh": 3.5,
        "home_assistant_entities": {
            "status": "",
            "power_kw": "",
            "voltage": "",
            "current": "",
            "session_energy_kwh": "",
            "battery_percent": "",
        },
    },
}


class Config:
    def __init__(self):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            self.data = json.load(f)
        if self._merge_defaults(self.data, DEFAULT_CONFIG):
            self.save()

    def get(self, *keys, default=None):
        value = self.data
        try:
            for key in keys:
                value = value[key]
            return value
        except KeyError:
            if default is not None:
                return default
            raise

    def save(self):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)
            f.write("\n")

    def _merge_defaults(self, target, defaults):
        changed = False
        for key, value in defaults.items():
            if key not in target:
                target[key] = deepcopy(value)
                changed = True
            elif isinstance(target[key], dict) and isinstance(value, dict):
                changed = self._merge_defaults(target[key], value) or changed
        return changed
