import json
from copy import deepcopy
from pathlib import Path

CONFIG_FILE = Path("config.json")

DEFAULT_CONFIG = {
    "energy": {
        "enabled": False,
        "vehicle_name": "2025 Chevrolet Equinox EV",
        "charger_name": "Juice Box",
        "cost_per_kwh": 0.13,
        "estimated_miles_per_kwh": 3.5,
        "alerts": {
            "enabled": False,
            "notify_on_start": True,
            "notify_on_stop": True,
        },
        "home_assistant_entities": {
            "status": "sensor.juice_box_cph50_charging_status",
            "power_kw": "sensor.juice_box_cph50_power_output",
            "voltage": "",
            "current": "",
            "session_energy_kwh": "sensor.juice_box_cph50_energy_output",
            "battery_percent": "",
            "charging_time": "sensor.juice_box_cph50_charging_time",
            "miles_added": "sensor.juice_box_cph50_miles_added",
            "miles_per_hour_added": "sensor.juice_box_cph50_miles_hour_added",
            "charge_cost": "sensor.juice_box_cph50_charge_cost",
            "network": "sensor.juice_box_cph50_network",
        },
    },
    "vehicle": {
        "enabled": False,
        "name": "2025 Chevrolet Equinox EV",
        "cost_per_kwh_override": "",
        "entities": {
            "battery_percent": "sensor.2025_chevrolet_equinox_ev_2025_chevrolet_equinox_ev_charge_state",
            "ev_range": "sensor.2025_chevrolet_equinox_ev_2025_chevrolet_equinox_ev_ev_range_mi",
            "plug_state": "binary_sensor.2025_chevrolet_equinox_ev_2025_chevrolet_equinox_ev_ev_plug_state",
            "charging_state": "binary_sensor.2025_chevrolet_equinox_ev_2025_chevrolet_equinox_ev_ev_charge_state",
            "odometer": "sensor.2025_chevrolet_equinox_ev_2025_chevrolet_equinox_ev_odo_read_mi",
            "lifetime_energy": "sensor.2025_chevrolet_equinox_ev_2025_chevrolet_equinox_ev_lifetime_energy_used",
        },
    },
}

ENERGY_ENTITY_DEFAULTS = DEFAULT_CONFIG["energy"]["home_assistant_entities"]


class Config:
    def __init__(self):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            self.data = json.load(f)
        changed = self._merge_defaults(self.data, DEFAULT_CONFIG)
        changed = self._fill_blank_energy_entities() or changed
        if changed:
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

    def _fill_blank_energy_entities(self):
        entities = self.data.setdefault("energy", {}).setdefault("home_assistant_entities", {})
        changed = False
        for key, value in ENERGY_ENTITY_DEFAULTS.items():
            if value and not str(entities.get(key, "")).strip():
                entities[key] = value
                changed = True
        return changed
