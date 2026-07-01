import json
from copy import deepcopy
from pathlib import Path

CONFIG_FILE = Path("config.json")

DEFAULT_CONFIG = {
    "speedtest_interval_minutes": 60,
    "history": {
        "enabled": True,
        "snapshot_interval_minutes": 5,
        "retention_days": 365,
        "database": "data/homepulse_history.db",
    },
    "weather": {
        "enabled": True,
        "location_name": "Home",
        "latitude": "",
        "longitude": "",
        "provider": "placeholder",
    },
    "solar": {
        "enabled": False,
        "name": "Solar Center",
        "cost_per_kwh_override": "",
        "entities": {
            "current_power_production": "sensor.envoy_202306120601_current_power_production",
            "energy_production_today": "sensor.envoy_202306120601_energy_production_today",
            "energy_production_last_seven_days": "sensor.envoy_202306120601_energy_production_last_seven_days",
            "lifetime_energy_production": "sensor.envoy_202306120601_lifetime_energy_production",
            "production_ct_power": "sensor.envoy_202306120601_production_ct_power",
            "production_ct_energy_delivered": "sensor.envoy_202306120601_production_ct_energy_delivered",
        },
    },
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
        had_speedtest_interval = "speedtest_interval_minutes" in self.data
        changed = self._merge_defaults(self.data, DEFAULT_CONFIG)
        changed = self._normalize_speedtest_interval(had_speedtest_interval) or changed
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

    def _normalize_speedtest_interval(self, had_speedtest_interval=True):
        current = self.data.get("speedtest_interval_minutes")
        if not had_speedtest_interval:
            current = self._legacy_speedtest_interval()
        normalized = self.valid_speedtest_interval(current)
        changed = False
        if self.data.get("speedtest_interval_minutes") != normalized:
            self.data["speedtest_interval_minutes"] = normalized
            changed = True
        if self.data.get("speedtest_schedule_enabled", True):
            mode = self.speedtest_mode_for_interval(normalized)
            times = self.speedtest_times_for_minutes(normalized)
            if self.data.get("speedtest_schedule_mode") != mode:
                self.data["speedtest_schedule_mode"] = mode
                changed = True
            if self.data.get("speedtest_times") != times:
                self.data["speedtest_times"] = times
                changed = True
        return changed

    def _legacy_speedtest_interval(self):
        mode = self.data.get("speedtest_schedule_mode")
        mode_intervals = {
            "every_30_minutes": 30,
            "every_1_hour": 60,
            "every_3_hours": 180,
            "every_6_hours": 360,
        }
        if mode in mode_intervals:
            return mode_intervals[mode]
        return 60

    @staticmethod
    def valid_speedtest_interval(value):
        try:
            minutes = int(value)
        except (TypeError, ValueError):
            return 60
        if minutes < 30 or minutes > 1440:
            return 60
        return minutes

    @staticmethod
    def speedtest_mode_for_interval(interval):
        return {
            30: "every_30_minutes",
            60: "every_1_hour",
            180: "every_3_hours",
            360: "every_6_hours",
        }.get(interval, "interval")

    @staticmethod
    def speedtest_times_for_minutes(interval):
        times = []
        for minute_of_day in range(0, 24 * 60, interval):
            hour = minute_of_day // 60
            minute = minute_of_day % 60
            times.append(f"{hour:02d}:{minute:02d}")
        return times
