import json
import re
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
        self._inverter_cache = None
        self._inverter_cache_at = None

    def get_status(self, include_inverter_details=False):
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
        inverter_details = self.read_envoy_inverter_details() if include_inverter_details else {
            "panel_count": None,
            "inverter_count": None,
            "microinverters_installed": None,
            "microinverters_online": None,
            "inverters": [],
            "inverter_data_available": False,
            "inverter_data_message": "Not reported by Envoy",
        }

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
            panel_count=inverter_details["panel_count"],
            inverter_count=inverter_details["inverter_count"],
            microinverters_installed=inverter_details["microinverters_installed"],
            microinverters_online=inverter_details["microinverters_online"],
            inverters=inverter_details["inverters"],
            inverter_data_available=inverter_details["inverter_data_available"],
            inverter_data_message=inverter_details["inverter_data_message"],
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

    def read_envoy_inverter_details(self):
        cache_ttl_seconds = 60
        now = datetime.now()
        if self._inverter_cache and self._inverter_cache_at:
            age = (now - self._inverter_cache_at).total_seconds()
            if age < cache_ttl_seconds:
                return dict(self._inverter_cache)

        unavailable = {
            "panel_count": None,
            "inverter_count": None,
            "microinverters_installed": None,
            "microinverters_online": None,
            "inverters": [],
            "inverter_data_available": False,
            "inverter_data_message": "Not reported by Envoy",
        }

        recovery = self.config.get("router_reboot", default={})
        base_url = str(recovery.get("home_assistant_url", "")).rstrip("/")
        token = recovery.get("home_assistant_token", "")
        if not base_url or not token:
            unavailable["inverter_data_message"] = "Not reported by Envoy (Home Assistant connection is not configured)."
            self._inverter_cache = dict(unavailable)
            self._inverter_cache_at = now
            return unavailable

        request = Request(
            f"{base_url}/api/states",
            method="GET",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=3) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
        except Exception as exc:
            self.log_refresh_warning(
                "envoy:states",
                f"Solar Center could not read Envoy inverter details: {exc}",
            )
            unavailable["inverter_data_message"] = "Not reported by Envoy (inverter endpoint data unavailable)."
            self._inverter_cache = dict(unavailable)
            self._inverter_cache_at = now
            return unavailable

        inverters_by_id = {}
        active_microinverters = None
        site_reporting = None
        site_not_reporting = None
        site_unknown = None

        for entity in payload if isinstance(payload, list) else []:
            entity_id = str(entity.get("entity_id") or "").lower()
            state = entity.get("state")
            attributes = entity.get("attributes") or {}

            if entity_id.startswith("sensor.inverter_"):
                inverter_id = entity_id.removeprefix("sensor.inverter_")
                if not inverter_id:
                    continue
                record = inverters_by_id.setdefault(inverter_id, {"id": inverter_id})
                record["reported_state"] = state
                record.setdefault("status", "Reported")

            elif entity_id.startswith("sensor.iq_microinverters_") and entity_id.endswith("_lifetime_energy"):
                match = re.match(r"sensor\.iq_microinverters_(.+)_lifetime_energy$", entity_id)
                if not match:
                    continue
                inverter_id = match.group(1)
                lifetime_kwh = self.parse_float(state)
                record = inverters_by_id.setdefault(inverter_id, {"id": inverter_id})
                record["lifetime_kwh"] = lifetime_kwh
                status_code = str(attributes.get("status_code") or attributes.get("status") or "").strip().lower()
                status_text = str(attributes.get("status_text") or "").strip()
                mapped_status = self.map_inverter_status(status_code, status_text)
                record["status"] = mapped_status
                if status_text:
                    record["status_detail"] = status_text

            elif entity_id.startswith("sensor.site_") and "active_microinverters" in entity_id:
                active_value = self.parse_float(state)
                if active_value is not None:
                    active_microinverters = int(round(active_value))

            elif entity_id.startswith("sensor.site_") and "microinverter_connectivity_status" in entity_id:
                site_reporting = self.parse_float(attributes.get("reporting_inverters"))
                site_not_reporting = self.parse_float(attributes.get("not_reporting_inverters"))
                site_unknown = self.parse_float(attributes.get("unknown_inverters"))

        inverters = sorted(inverters_by_id.values(), key=lambda item: item.get("id") or "")
        online_count = sum(1 for inverter in inverters if inverter.get("status") == "Online") if inverters else None
        offline_count = sum(1 for inverter in inverters if inverter.get("status") == "Offline") if inverters else None
        installed_count = len(inverters) if inverters else None

        if installed_count is None and active_microinverters is not None:
            installed_count = active_microinverters

        if online_count is None and site_reporting is not None:
            online_count = int(round(site_reporting))

        if installed_count is None and site_reporting is not None:
            candidates = [site_reporting, site_not_reporting, site_unknown]
            total = sum(int(round(value)) for value in candidates if value is not None)
            if total > 0:
                installed_count = total

        if installed_count is None:
            unavailable["inverter_data_message"] = "Not reported by Envoy"
            self._inverter_cache = dict(unavailable)
            self._inverter_cache_at = now
            return unavailable

        message = (
            "Per-inverter availability is reported by Envoy telemetry and may not match panel-level health in the Enphase app."
        )
        if offline_count and offline_count > 0:
            message = (
                "Per-inverter availability is reported by Envoy telemetry and may not match panel-level health in the Enphase app. "
                f"Envoy explicitly reports {offline_count} inverter(s) offline/faulted."
            )

        result = {
            "panel_count": installed_count,
            "inverter_count": installed_count,
            "microinverters_installed": installed_count,
            "microinverters_online": online_count,
            "inverters": inverters,
            "inverter_data_available": True,
            "inverter_data_message": message,
        }
        self._inverter_cache = dict(result)
        self._inverter_cache_at = now
        return result

    @staticmethod
    def map_inverter_status(status_code, status_text):
        status_blob = " ".join(part for part in (status_code, status_text) if part).strip().lower()
        if not status_blob:
            return "Reported"

        offline_tokens = (
            "offline",
            "fault",
            "faulted",
            "disabled",
            "disable",
        )
        online_tokens = (
            "online",
            "normal",
            "producing",
            "production",
            "active",
            "running",
            "ok",
        )

        if any(token in status_blob for token in offline_tokens):
            return "Offline"
        if any(token in status_blob for token in online_tokens):
            return "Online"
        return "Reported"

    def get_inverter_performance(self, range_key="today", metric="power"):
        normalized_range = self.normalize_performance_range(range_key)
        normalized_metric = self.normalize_performance_metric(metric)
        timestamp = str(datetime.now())

        details = self.read_envoy_inverter_details()
        inverters = details.get("inverters") or []
        inverter_ids = [item.get("id") for item in inverters if item.get("id")]

        summary = self.build_inverter_summary(inverters, normalized_metric)
        insights = self.build_inverter_insights(inverters, summary)

        reason = (
            "Historical per-inverter telemetry is not currently exposed by this Envoy endpoint. "
            "Only current and lifetime inverter telemetry is available."
        )

        return {
            "data_available": False,
            "message": reason,
            "reason": reason,
            "timestamp": timestamp,
            "range": normalized_range,
            "metric": normalized_metric,
            "inverters": inverter_ids,
            "series": [],
            "summary": summary,
            "insights": insights,
        }

    @staticmethod
    def normalize_performance_range(range_key):
        value = str(range_key or "today").strip().lower()
        valid = {"today", "this_week", "this_month", "this_year"}
        return value if value in valid else "today"

    @staticmethod
    def normalize_performance_metric(metric):
        value = str(metric or "power").strip().lower()
        valid = {"power", "energy", "lifetime_kwh"}
        return value if value in valid else "power"

    def build_inverter_summary(self, inverters, metric):
        if not inverters:
            return []

        lifetimes = [self.parse_float(item.get("lifetime_kwh")) for item in inverters]
        lifetimes = [value for value in lifetimes if value is not None]
        max_lifetime = max(lifetimes) if lifetimes else None

        rows = []
        for item in inverters:
            inverter_id = item.get("id")
            status = item.get("status") or "Unknown"
            lifetime_kwh = self.parse_float(item.get("lifetime_kwh"))
            current_power = self.parse_float(item.get("reported_state"))

            performance_percent = None
            if max_lifetime and lifetime_kwh is not None and max_lifetime > 0:
                performance_percent = round((lifetime_kwh / max_lifetime) * 100, 1)

            rows.append({
                "inverter_id": inverter_id,
                "status": status,
                "peak_power": None,
                "energy": lifetime_kwh if metric in ("energy", "lifetime_kwh") else None,
                "lifetime_kwh": lifetime_kwh,
                "current_power": current_power if metric == "power" else None,
                "performance_percent": performance_percent,
            })

        return sorted(rows, key=lambda row: row.get("inverter_id") or "")

    @staticmethod
    def build_inverter_insights(inverters, summary):
        insights = []
        if not inverters:
            return [{"level": "info", "title": "Unknown", "message": "No inverter telemetry rows were reported by Envoy."}]

        offline = [item for item in inverters if (item.get("status") or "") == "Offline"]
        if offline:
            insights.append({
                "level": "warning",
                "title": "Needs Attention",
                "message": f"Envoy explicitly reports {len(offline)} inverter(s) as offline/faulted/disabled.",
            })
        else:
            insights.append({
                "level": "ok",
                "title": "All Good",
                "message": "Envoy does not explicitly report offline/faulted/disabled inverters.",
            })

        percentages = [row.get("performance_percent") for row in summary if row.get("performance_percent") is not None]
        if len(percentages) >= 2:
            spread = max(percentages) - min(percentages)
            if spread <= 15:
                insights.append({
                    "level": "ok",
                    "title": "System Balance",
                    "message": "Lifetime production is reasonably balanced across reported inverters.",
                })
            else:
                insights.append({
                    "level": "info",
                    "title": "System Balance",
                    "message": "Lifetime production spread is wider; panel orientation, shading, and age can cause this.",
                })

        insights.append({
            "level": "info",
            "title": "Midday Dip",
            "message": "Historical per-inverter curve data is unavailable from this Envoy endpoint, so midday dip analysis is limited.",
        })
        return insights

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
