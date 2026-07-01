import json
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from modules.solar.models import SolarStatus


SOLAR_DEFAULTS = {
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
}

UNAVAILABLE_STATES = {"", "unknown", "unavailable", "none", "null"}


class SolarManager:
    def __init__(self, config, log):
        self.config = config
        self.log = log
        self._last_warning_at = {}

    def get_status(self):
        solar = self.solar_config()
        base = {
            "name": solar.get("name") or SOLAR_DEFAULTS["name"],
            "electricity_rate": self.electricity_rate(solar),
        }
        if not solar.get("enabled", False):
            return SolarStatus(**base).to_dict()

        entities = dict(solar.get("entities", {}))
        if not self.configured(entities):
            return SolarStatus(
                enabled=True,
                configured=False,
                status="Unknown",
                error="Solar Center is enabled but no Home Assistant entities are configured.",
                message="Solar Center enabled - add Home Assistant entity IDs in Settings.",
                **base,
            ).to_dict()

        states = self.read_entity_states(entities)
        current_kw = self.normalized_number(states.get("current_power_production"), "power")
        today_kwh = self.normalized_number(states.get("energy_production_today"), "energy_kwh")
        last_7_days_kwh = self.normalized_number(states.get("energy_production_last_seven_days"), "energy_kwh")
        lifetime_mwh = self.normalized_number(states.get("lifetime_energy_production"), "energy_mwh")
        ct_power_kw = self.normalized_number(states.get("production_ct_power"), "power")
        ct_energy_mwh = self.normalized_number(states.get("production_ct_energy_delivered"), "energy_mwh")
        rate = base["electricity_rate"]
        errors = [value.get("error") for value in states.values() if value.get("error")]
        error = "; ".join(errors) if errors and current_kw is None else None

        status = self.production_status(current_kw)
        message = self.status_message(status)
        lifetime_kwh = round(lifetime_mwh * 1000, 3) if lifetime_mwh is not None else None

        return SolarStatus(
            enabled=True,
            configured=True,
            status=status,
            current_production_kw=current_kw,
            current_production_w=round(current_kw * 1000) if current_kw is not None else None,
            production_today_kwh=today_kwh,
            production_last_7_days_kwh=last_7_days_kwh,
            lifetime_production_mwh=lifetime_mwh,
            lifetime_production_kwh=lifetime_kwh,
            production_ct_power_kw=ct_power_kw,
            production_ct_energy_delivered_mwh=ct_energy_mwh,
            estimated_value_today=self.estimated_value(today_kwh, rate),
            estimated_value_last_7_days=self.estimated_value(last_7_days_kwh, rate),
            estimated_lifetime_value=self.estimated_value(lifetime_kwh, rate),
            estimated_value_per_hour=self.estimated_value(current_kw, rate),
            last_updated=str(datetime.now()),
            error=error,
            message=message,
            **base,
        ).to_dict()

    def solar_config(self):
        solar = dict(self.config.get("solar", default={}))
        merged = dict(SOLAR_DEFAULTS)
        merged.update(solar)
        entities = dict(SOLAR_DEFAULTS["entities"])
        entities.update(solar.get("entities", {}))
        merged["entities"] = entities
        return merged

    @staticmethod
    def configured(entities):
        required = (
            "current_power_production",
            "energy_production_today",
            "energy_production_last_seven_days",
            "lifetime_energy_production",
        )
        return any(str(entities.get(key) or "").strip() for key in required)

    def electricity_rate(self, solar):
        override = self.parse_float(solar.get("cost_per_kwh_override"))
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
                f"Solar Center entity read skipped for {entity_id}: {message}",
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
                f"Solar Center could not read {entity_id}: {message}",
            )
            return self.empty_entity(entity_id=entity_id, error=message)
        except URLError as exc:
            message = f"Home Assistant unreachable: {exc.reason}"
            self.log_refresh_warning(
                "url:home_assistant",
                f"Solar Center could not read {entity_id}: {message}",
            )
            return self.empty_entity(entity_id=entity_id, error=message)
        except Exception as exc:
            self.log_refresh_warning(
                f"unexpected:{entity_id}:{type(exc).__name__}",
                f"Solar Center could not read {entity_id}: {exc}",
            )
            self.log.debug(f"Solar Center entity read traceback for {entity_id}", exc_info=True)
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
                f"Solar Center could not parse {measurement} value: {entity.get('state')!r}",
            )
            return None

        unit = str(entity.get("unit") or "").strip().lower()
        if measurement == "power":
            if unit in ("w", "watt", "watts"):
                value = value / 1000
            elif unit in ("mw", "megawatt", "megawatts"):
                value = value * 1000
            return round(value, 3)
        if measurement == "energy_kwh":
            if unit in ("wh", "watt-hour", "watt-hours"):
                value = value / 1000
            elif unit in ("mwh", "megawatt-hour", "megawatt-hours"):
                value = value * 1000
            return round(value, 3)
        if measurement == "energy_mwh":
            if unit in ("wh", "watt-hour", "watt-hours"):
                value = value / 1_000_000
            elif unit in ("kwh", "kilowatt-hour", "kilowatt-hours"):
                value = value / 1000
            return round(value, 6)
        return round(value, 3)

    @staticmethod
    def parse_float(value):
        if value in (None, ""):
            return None
        try:
            return float(str(value).strip().replace("$", "").replace(",", ""))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def estimated_value(kwh, rate):
        if kwh is None:
            return None
        return round(kwh * rate, 2)

    @staticmethod
    def production_status(current_kw):
        if current_kw is None:
            return "Unknown"
        if current_kw > 0.10:
            return "Producing"
        return "Standby / Night"

    @staticmethod
    def status_message(status):
        if status == "Producing":
            return "Solar Center is receiving live Enphase Envoy production data."
        if status == "Standby / Night":
            return "Solar Center is online and production is currently low."
        return "Waiting for Enphase Envoy solar data."

    def log_refresh_warning(self, key, message, seconds=300):
        now = datetime.now()
        last = self._last_warning_at.get(key)
        if not last or (now - last).total_seconds() >= seconds:
            self._last_warning_at[key] = now
            self.log.warning(message)
        else:
            self.log.debug(message)
