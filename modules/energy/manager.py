import json
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from modules.energy.models import EnergyStatus
from modules.energy.pricing import estimate_cost, estimate_miles_added


ENERGY_DEFAULTS = {
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
}

CHARGING_STATUS_TEXT = {"charging", "plugged in charging", "active"}
UNAVAILABLE_STATES = {"", "unknown", "unavailable", "none", "null"}


class EnergyManager:
    def __init__(self, config, log):
        self.config = config
        self.log = log

    def get_status(self):
        energy = self.energy_config()
        base = {
            "vehicle_name": energy.get("vehicle_name") or ENERGY_DEFAULTS["vehicle_name"],
            "charger_name": energy.get("charger_name") or ENERGY_DEFAULTS["charger_name"],
        }

        if not energy.get("enabled", False):
            return EnergyStatus(**base).to_dict()

        entities = dict(energy.get("home_assistant_entities", {}))
        configured = self.configured(entities)
        if not configured:
            return EnergyStatus(
                enabled=True,
                configured=False,
                status="Unavailable",
                message="Energy Center enabled — add Home Assistant entity IDs in Settings.",
                **base,
            ).to_dict()

        states = self.read_entity_states(entities)
        session_energy = self.normalized_number(states.get("session_energy_kwh"), "energy", default=0)
        power_kw = self.normalized_number(states.get("power_kw"), "power", default=0)
        status_text = self.status_text(states.get("status"), power_kw)
        is_charging = self.is_charging(status_text, power_kw)
        any_live_data = any(
            self.state_available(states.get(key))
            for key in ("status", "power_kw", "voltage", "current", "session_energy_kwh", "battery_percent")
        )

        if not any_live_data:
            status_text = "Unavailable"
            message = "Waiting for charger data."
        elif is_charging:
            status_text = "Charging"
            message = "Energy Center is receiving live charging data."
        else:
            status_text = "Not Charging"
            message = "Energy Center is receiving live charger data."

        return EnergyStatus(
            enabled=True,
            configured=True,
            status=status_text,
            is_charging=is_charging,
            power_kw=power_kw,
            voltage=self.normalized_number(states.get("voltage"), "voltage"),
            current=self.normalized_number(states.get("current"), "current"),
            battery_percent=self.normalized_number(states.get("battery_percent"), "percent"),
            session_energy_kwh=session_energy,
            estimated_cost=estimate_cost(session_energy, energy.get("cost_per_kwh", 0.13)),
            estimated_miles_added=estimate_miles_added(
                session_energy,
                energy.get("estimated_miles_per_kwh", 3.5),
            ),
            last_update=str(datetime.now()),
            message=message,
            **base,
        ).to_dict()

    def energy_config(self):
        energy = dict(self.config.get("energy", default={}))
        merged = dict(ENERGY_DEFAULTS)
        merged.update(energy)
        entities = dict(ENERGY_DEFAULTS["home_assistant_entities"])
        entities.update(energy.get("home_assistant_entities", {}))
        merged["home_assistant_entities"] = entities
        return merged

    @staticmethod
    def configured(entities):
        return bool(str(entities.get("status") or "").strip() or str(entities.get("power_kw") or "").strip())

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
            self.log.warning(f"Energy Center entity read skipped for {entity_id}: {message}")
            return self.empty_entity(error=message)

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
            message = f"HTTP {exc.code}"
            if exc.code == 404:
                message = "entity not found"
            self.log.warning(f"Energy Center could not read {entity_id}: {message}")
            return self.empty_entity(entity_id=entity_id, error=message)
        except URLError as exc:
            message = f"Home Assistant unreachable: {exc.reason}"
            self.log.warning(f"Energy Center could not read {entity_id}: {message}")
            return self.empty_entity(entity_id=entity_id, error=message)
        except Exception as exc:
            self.log.exception(f"Energy Center could not read {entity_id}: {exc}")
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

    def status_text(self, entity, power_kw):
        if self.state_available(entity):
            return str(entity.get("state")).strip()
        return "Charging" if float(power_kw or 0) > 0.5 else "Not Charging"

    def normalized_number(self, entity, measurement, default=None):
        if not self.state_available(entity):
            return default
        state = entity.get("state")
        unit = str(entity.get("unit") or "").strip().lower()
        try:
            value = float(state)
        except (TypeError, ValueError):
            self.log.warning(f"Energy Center could not parse {measurement} value: {state!r}")
            return default

        if measurement == "power":
            if unit in ("w", "watt", "watts"):
                value = value / 1000
            return round(value, 3)
        if measurement == "energy":
            if unit in ("wh", "watt-hour", "watt-hours"):
                value = value / 1000
            return round(value, 3)
        if measurement == "percent":
            return round(max(0, min(value, 100)), 1)
        return round(value, 2)

    @staticmethod
    def is_charging(status, power_kw):
        normalized = str(status or "").strip().lower()
        return normalized in CHARGING_STATUS_TEXT or float(power_kw or 0) > 0.5
