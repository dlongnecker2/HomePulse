import json
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from modules.vehicle.models import VehicleStatus


VEHICLE_DEFAULTS = {
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
}

UNAVAILABLE_STATES = {"", "unknown", "unavailable", "none", "null"}


class VehicleManager:
    def __init__(self, config, log):
        self.config = config
        self.log = log
        self._last_warning_at = {}

    def get_status(self):
        vehicle = self.vehicle_config()
        base = {"vehicle_name": vehicle.get("name") or VEHICLE_DEFAULTS["name"]}
        if not vehicle.get("enabled", False):
            return VehicleStatus(**base).to_dict()

        entities = dict(vehicle.get("entities", {}))
        configured = self.configured(entities)
        if not configured:
            return VehicleStatus(
                enabled=True,
                configured=False,
                availability="unconfigured",
                message="Vehicle Center enabled - add Home Assistant entity IDs in Settings.",
                **base,
            ).to_dict()

        states = self.read_entity_states(entities)
        battery_percent = self.normalized_number(states.get("battery_percent"), "percent")
        range_mi = self.normalized_number(states.get("ev_range"), "distance")
        odometer_mi = self.normalized_number(states.get("odometer"), "distance")
        lifetime_energy_kwh = self.normalized_number(states.get("lifetime_energy"), "energy")
        electricity_rate = self.electricity_rate(vehicle)

        lifetime_efficiency = None
        if odometer_mi is not None and lifetime_energy_kwh and lifetime_energy_kwh > 0:
            lifetime_efficiency = round(odometer_mi / lifetime_energy_kwh, 2)

        estimated_lifetime_cost = None
        if lifetime_energy_kwh is not None:
            estimated_lifetime_cost = round(lifetime_energy_kwh * electricity_rate, 2)

        cost_per_mile = None
        if estimated_lifetime_cost is not None and odometer_mi and odometer_mi > 0:
            cost_per_mile = round(estimated_lifetime_cost / odometer_mi, 3)

        configured_keys = [key for key, value in entities.items() if str(value or "").strip()]
        available_keys = [key for key in configured_keys if self.state_available(states.get(key))]
        errors = [states.get(key, {}).get("error", "") for key in configured_keys if states.get(key, {}).get("error")]
        availability, message = self.availability_message(configured_keys, available_keys, errors)

        return VehicleStatus(
            enabled=True,
            configured=True,
            availability=availability,
            battery_percent=battery_percent,
            range_mi=range_mi,
            plug_state=self.plug_state(states.get("plug_state")),
            charging_state=self.charging_state(states.get("charging_state")),
            odometer_mi=odometer_mi,
            lifetime_energy_kwh=lifetime_energy_kwh,
            lifetime_efficiency_mi_per_kwh=lifetime_efficiency,
            estimated_lifetime_cost=estimated_lifetime_cost,
            cost_per_mile=cost_per_mile,
            last_update=str(datetime.now()),
            message=message,
            **base,
        ).to_dict()

    def vehicle_config(self):
        vehicle = dict(self.config.get("vehicle", default={}))
        merged = dict(VEHICLE_DEFAULTS)
        merged.update(vehicle)
        entities = dict(VEHICLE_DEFAULTS["entities"])
        entities.update(vehicle.get("entities", {}))
        merged["entities"] = entities
        return merged

    @staticmethod
    def configured(entities):
        return any(str(value or "").strip() for value in entities.values())

    def electricity_rate(self, vehicle):
        override = self.parse_float(vehicle.get("cost_per_kwh_override"))
        if override is not None and override >= 0:
            return override
        energy = self.config.get("energy", default={})
        rate = self.parse_float(energy.get("cost_per_kwh"))
        return rate if rate is not None and rate >= 0 else 0.13

    def read_entity_states(self, entities):
        states = {}
        for key, entity_id in entities.items():
            entity_id = str(entity_id or "").strip()
            if not entity_id:
                states[key] = self.empty_entity()
                continue
            states[key] = self.read_home_assistant_state(entity_id)
        return states

    def read_home_assistant_state(self, entity_id):
        recovery = self.config.get("router_reboot", default={})
        base_url = str(recovery.get("home_assistant_url", "")).rstrip("/")
        token = recovery.get("home_assistant_token", "")
        if not base_url or not token:
            message = "Home Assistant URL or token is not configured."
            self.log_refresh_warning(
                "config:home_assistant",
                f"Vehicle Center entity read skipped for {entity_id}: {message}",
            )
            return self.empty_entity(entity_id=entity_id, error=message)

        request = Request(
            f"{base_url}/api/states/{entity_id}",
            method="GET",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
                attributes = payload.get("attributes") or {}
                return {
                    "entity_id": entity_id,
                    "state": payload.get("state"),
                    "unit": attributes.get("unit_of_measurement"),
                }
        except HTTPError as exc:
            message = "entity not found" if exc.code == 404 else f"HTTP {exc.code}"
            self.log_refresh_warning(
                f"http:{entity_id}:{exc.code}",
                f"Vehicle Center could not read {entity_id}: {message}",
            )
            return self.empty_entity(entity_id=entity_id, error=message)
        except URLError as exc:
            message = f"Home Assistant unreachable: {exc.reason}"
            self.log_refresh_warning(
                "url:home_assistant",
                f"Vehicle Center could not read {entity_id}: {message}",
            )
            return self.empty_entity(entity_id=entity_id, error=message)
        except Exception as exc:
            self.log_refresh_warning(
                f"unexpected:{entity_id}:{type(exc).__name__}",
                f"Vehicle Center could not read {entity_id}: {exc}",
            )
            self.log.debug(f"Vehicle Center entity read traceback for {entity_id}", exc_info=True)
            return self.empty_entity(entity_id=entity_id, error=str(exc))

    @staticmethod
    def empty_entity(entity_id="", error=""):
        return {"entity_id": entity_id, "state": None, "unit": None, "error": error}

    @staticmethod
    def state_available(entity):
        if not entity:
            return False
        state = str(entity.get("state") if isinstance(entity, dict) else entity).strip().lower()
        return state not in UNAVAILABLE_STATES

    def normalized_number(self, entity, measurement):
        if not self.state_available(entity):
            return None
        value = self.parse_float(entity.get("state"))
        if value is None:
            self.log_refresh_warning(
                f"parse:{measurement}:{entity.get('entity_id', '')}",
                f"Vehicle Center could not parse {measurement} value: {entity.get('state')!r}",
            )
            return None

        unit = str(entity.get("unit") or "").strip().lower()
        if measurement == "energy" and unit in ("wh", "watt-hour", "watt-hours"):
            value = value / 1000
        if measurement == "percent":
            return round(max(0, min(value, 100)), 1)
        if measurement == "energy":
            return round(value, 1)
        return round(value, 1)

    @staticmethod
    def parse_float(value):
        if value in (None, ""):
            return None
        try:
            return float(str(value).strip().replace("$", "").replace(",", ""))
        except (TypeError, ValueError):
            return None

    def plug_state(self, entity):
        if not self.state_available(entity):
            return None
        state = str(entity.get("state")).strip().lower()
        if state in ("on", "true", "plugged", "plugged in", "connected"):
            return "Plugged In"
        if state in ("off", "false", "unplugged", "disconnected"):
            return "Unplugged"
        return str(entity.get("state")).strip()

    def charging_state(self, entity):
        if not self.state_available(entity):
            return None
        state = str(entity.get("state")).strip().lower()
        if state in ("on", "true", "charging", "active"):
            return "Charging"
        if state in ("off", "false", "not charging", "idle", "complete", "completed"):
            return "Not charging"
        return str(entity.get("state")).strip()

    @staticmethod
    def availability_message(configured_keys, available_keys, errors):
        if not available_keys:
            normalized_errors = " ".join(errors).lower()
            if "home assistant" in normalized_errors or "http" in normalized_errors:
                return "home_assistant_unavailable", "Home Assistant is unavailable for Vehicle Center."
            return "waiting", "Waiting for vehicle data."
        if len(available_keys) < len(configured_keys):
            return "partial", "Vehicle Center is receiving partial vehicle data."
        return "live", "Vehicle Center is receiving live vehicle data."

    def get_unified_status(self, energy_status=None, base_status=None):
        """
        Return vehicle status merged with ChargePoint / Energy Center data.
        Falls back to Chevrolet-only data when energy_status is None or
        when the Energy Center is disabled / unconfigured.
        Never raises.
        """
        from modules.vehicle.state_engine import merge_vehicle_state
        base = dict(base_status) if base_status is not None else self.get_status()
        try:
            merged = merge_vehicle_state(base, energy_status or {})
            base.update(merged)
        except Exception as exc:
            self.log.debug(f"Vehicle state merge failed (non-fatal): {exc}")
            # Provide minimal convenience booleans even if merge fails
            base.setdefault("plugged_in", base.get("plug_state") == "Plugged In")
            base.setdefault("charging", base.get("charging_state") == "Charging")
            base.setdefault("charging_power_kw", None)
            base.setdefault("session_energy_kwh", None)
            base.setdefault("estimated_miles_added", None)
            base.setdefault("estimated_cost", None)
            base.setdefault("charger_name", None)
            base.setdefault("charger_status", None)
            base.setdefault("charging_time", None)
            base.setdefault("miles_per_hour_added", None)
            base.setdefault("sources", {})
        return base

    def log_refresh_warning(self, key, message, seconds=300):
        now = datetime.now()
        last = self._last_warning_at.get(key)
        if not last or (now - last).total_seconds() >= seconds:
            self._last_warning_at[key] = now
            self.log.warning(message)
        else:
            self.log.debug(message)
