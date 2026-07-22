import re
from collections import OrderedDict
from datetime import datetime
from urllib.error import HTTPError, URLError

from modules.garden.providers.base import GardenProvider


UNAVAILABLE_STATES = {"", "unknown", "unavailable", "none", "null"}
ACTIVE_ZONE_STATES = {"open", "opening", "on", "running", "watering", "active"}
RAIN_DELAY_ON_STATES = {"on", "true", "active", "enabled"}
DEFAULT_DISCOVERY_KEYWORDS = (
    "bhyve",
    "orbit",
    "sprinkler",
    "irrig",
    "watering",
    "rain delay",
    "smart_outdoor_timer",
)

CONTROLLER_PATTERNS = (
    re.compile(r"^(?:sensor|switch)\.(?P<prefix>.+?)_(?:next_watering|rain_delay)$", re.IGNORECASE),
)


class HomeAssistantGardenProvider(GardenProvider):
    provider_key = "home_assistant"
    source_name = "Home Assistant"

    def fetch_status(self, garden, timeout_seconds):
        recovery = self._router_recovery(garden)
        base_url = str(recovery.get("home_assistant_url") or "").rstrip("/")
        token = str(recovery.get("home_assistant_token") or "")
        if not base_url or not token:
            raise ValueError("Home Assistant URL or token is not configured.")

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload = self.request_json(f"{base_url}/api/states", timeout_seconds, headers=headers)
        rows = payload if isinstance(payload, list) else []

        provider_cfg = self._provider_config(garden)
        explicit = self._explicit_config(provider_cfg)
        discovery_keywords = self._discovery_keywords(provider_cfg.get("discovery_keywords"))

        controllers = self._discover_controllers(rows, explicit, discovery_keywords)
        zones = self._collect_zones(controllers)
        entity_count = len({row.get("entity_id") for row in rows if isinstance(row, dict) and self._is_irrigation_candidate(row, discovery_keywords)})

        if not controllers:
            return self._empty_status(
                entity_count=entity_count,
                configured=explicit["has_explicit_entities"],
                message="No irrigation entities were found in Home Assistant.",
            )

        active_zone = next((zone for zone in zones if zone["is_active"]), None)
        primary_controller = controllers[0]
        status = (
            f"{active_zone['zone_label']} running"
            if active_zone
            else "No active watering"
        )
        if active_zone:
            message = f"{active_zone['zone_label']} is currently running."
        else:
            message = "No active watering is currently running."

        discovery_status = (
            f"Discovered {len(controllers)} controller(s) and {len(zones)} zone(s) in Home Assistant."
        )
        integration = primary_controller.get("integration") or "Home Assistant"
        now = datetime.now().isoformat(timespec="seconds")
        return {
            "enabled": True,
            "configured": True,
            "status": status,
            "provider": self.provider_key,
            "selected_provider": self.provider_key,
            "source": self.source_name,
            "integration": integration,
            "live_data": True,
            "read_only": True,
            "controller_count": len(controllers),
            "zone_count": len(zones),
            "entity_count": entity_count,
            "controllers": controllers,
            "zones": zones,
            "active_controller": active_zone["controller_name"] if active_zone else primary_controller["controller_name"],
            "active_watering_zone": active_zone["zone_label"] if active_zone else None,
            "active_watering_zone_entity_id": active_zone["entity_id"] if active_zone else None,
            "next_watering_schedule": primary_controller.get("next_watering_schedule"),
            "rain_delay_active": primary_controller.get("rain_delay_active"),
            "rain_delay_until": primary_controller.get("rain_delay_until"),
            "discovery_status": discovery_status,
            "discovery_message": discovery_status,
            "controller_entity_ids": [controller["controller_entity_id"] for controller in controllers if controller.get("controller_entity_id")],
            "last_updated": now,
            "last_successful_refresh": now,
            "error": None,
            "message": message,
        }

    @staticmethod
    def _router_recovery(garden):
        recovery = garden.get("router_recovery") if isinstance(garden, dict) else None
        return recovery if isinstance(recovery, dict) else {}

    @staticmethod
    def _provider_config(garden):
        providers = garden.get("providers", {}) if isinstance(garden, dict) else {}
        provider_cfg = providers.get("home_assistant", {}) if isinstance(providers, dict) else {}
        return provider_cfg if isinstance(provider_cfg, dict) else {}

    @staticmethod
    def _explicit_config(provider_cfg):
        def _list(value):
            if isinstance(value, list):
                return [str(item).strip() for item in value if str(item).strip()]
            if isinstance(value, str) and value.strip():
                return [value.strip()]
            return []

        prefixes = _list(provider_cfg.get("controller_prefixes"))
        controller_ids = _list(provider_cfg.get("controller_entity_ids"))
        zone_ids = _list(provider_cfg.get("zone_entity_ids"))
        smart_watering_ids = _list(provider_cfg.get("smart_watering_entity_ids"))
        next_watering_ids = _list(provider_cfg.get("next_watering_entity_ids")) or _list(provider_cfg.get("next_watering_entity_id"))
        rain_delay_ids = _list(provider_cfg.get("rain_delay_entity_ids")) or _list(provider_cfg.get("rain_delay_entity_id"))

        has_explicit_entities = bool(prefixes or controller_ids or zone_ids or smart_watering_ids or next_watering_ids or rain_delay_ids)
        return {
            "controller_prefixes": prefixes,
            "controller_entity_ids": controller_ids,
            "zone_entity_ids": zone_ids,
            "smart_watering_entity_ids": smart_watering_ids,
            "next_watering_entity_ids": next_watering_ids,
            "rain_delay_entity_ids": rain_delay_ids,
            "controller_name": str(provider_cfg.get("controller_name") or "").strip(),
            "integration_name": str(provider_cfg.get("integration_name") or "").strip(),
            "has_explicit_entities": has_explicit_entities,
        }

    @staticmethod
    def _discovery_keywords(value):
        text = str(value or "").strip().lower()
        if not text:
            return DEFAULT_DISCOVERY_KEYWORDS
        tokens = [token.strip() for token in text.split(",") if token.strip()]
        return tuple(tokens or DEFAULT_DISCOVERY_KEYWORDS)

    @staticmethod
    def _entity_id(row):
        return str((row or {}).get("entity_id") or "").strip()

    @staticmethod
    def _friendly_name(row):
        attributes = (row or {}).get("attributes") if isinstance((row or {}).get("attributes"), dict) else {}
        return str(attributes.get("friendly_name") or "").strip()

    @staticmethod
    def _state(row):
        return str((row or {}).get("state") or "").strip()

    @staticmethod
    def _attributes(row):
        attributes = (row or {}).get("attributes")
        return attributes if isinstance(attributes, dict) else {}

    @classmethod
    def _is_irrigation_candidate(cls, row, keywords):
        entity_id = cls._entity_id(row).lower()
        friendly = cls._friendly_name(row).lower()
        blob = f"{entity_id} {friendly}"
        if any(keyword in blob for keyword in keywords):
            return True
        return entity_id.startswith(("valve.", "switch.smart_outdoor_timer_", "sensor.smart_outdoor_timer_"))

    @classmethod
    def _prefix_from_entity_id(cls, entity_id):
        text = str(entity_id or "").strip()
        if not text or "." not in text:
            return None
        for pattern in CONTROLLER_PATTERNS:
            match = pattern.match(text)
            if match:
                return match.group("prefix")
        return None

    @staticmethod
    def _unique(values):
        ordered = OrderedDict()
        for value in values:
            if value:
                ordered[str(value)] = None
        return list(ordered.keys())

    def _discover_controllers(self, rows, explicit, keywords):
        row_map = {self._entity_id(row): row for row in rows if self._entity_id(row)}
        prefixes = []
        prefixes.extend(explicit["controller_prefixes"])
        for entity_id in (
            explicit["controller_entity_ids"]
            + explicit["next_watering_entity_ids"]
            + explicit["rain_delay_entity_ids"]
            + explicit["zone_entity_ids"]
            + explicit["smart_watering_entity_ids"]
        ):
            prefix = self._prefix_from_entity_id(entity_id)
            if prefix:
                prefixes.append(prefix)

        for row in rows:
            if not self._is_irrigation_candidate(row, keywords):
                continue
            prefix = self._prefix_from_entity_id(self._entity_id(row))
            if prefix:
                prefixes.append(prefix)

        if not prefixes:
            prefixes.extend(self._prefixes_from_zone_rows(rows))

        prefixes = self._unique(prefixes)
        controllers = []
        for prefix in prefixes:
            controller = self._build_controller(prefix, rows, row_map, explicit, keywords)
            if controller is not None:
                controllers.append(controller)

        if not controllers and explicit["has_explicit_entities"]:
            controller = self._build_explicit_controller(rows, row_map, explicit)
            if controller is not None:
                controllers.append(controller)

        return controllers

    def _prefixes_from_zone_rows(self, rows):
        zone_stems = []
        for row in rows:
            entity_id = self._entity_id(row)
            if not entity_id.startswith("valve."):
                continue
            stem = entity_id.split(".", 1)[1]
            if stem.endswith("_zone"):
                stem = stem[:-5]
            parts = stem.split("_")
            if len(parts) > 1:
                zone_stems.append(parts[:-1])

        if not zone_stems:
            return []

        common = list(zone_stems[0])
        for parts in zone_stems[1:]:
            index = 0
            while index < len(common) and index < len(parts) and common[index] == parts[index]:
                index += 1
            common = common[:index]
            if not common:
                break

        if not common:
            return []
        return ["_".join(common)]

    def _build_controller(self, prefix, rows, row_map, explicit, keywords):
        controller_name = self._controller_name(prefix, rows, explicit)
        integration = explicit["integration_name"] or self._infer_integration(rows) or "Home Assistant"

        next_watering_row = self._match_row(
            rows,
            row_map,
            explicit["next_watering_entity_ids"],
            rf"^(?:sensor)\.{re.escape(prefix)}_next_watering$",
        )
        rain_delay_row = self._match_row(
            rows,
            row_map,
            explicit["rain_delay_entity_ids"],
            rf"^(?:switch)\.{re.escape(prefix)}_rain_delay$",
        )
        zone_rows = self._match_zone_rows(rows, explicit, prefix)
        smart_watering_rows = self._match_smart_watering_rows(rows, explicit, prefix)

        if not zone_rows and not next_watering_row and not rain_delay_row and not smart_watering_rows:
            return None

        zones = []
        for zone_row in zone_rows:
            zone = self._zone_payload(zone_row, controller_name, smart_watering_rows, prefix, integration)
            zones.append(zone)

        if not zones and not explicit["has_explicit_entities"]:
            return None

        active_zone = next((zone for zone in zones if zone["is_active"]), None)
        controller_state = "Connected" if zones or next_watering_row or rain_delay_row else "Unavailable"
        controller_message = (
            f"{active_zone['zone_label']} is currently running."
            if active_zone
            else "No active watering is currently running."
        )

        return {
            "controller_name": controller_name,
            "controller_entity_id": next_watering_row["entity_id"] if next_watering_row else (rain_delay_row["entity_id"] if rain_delay_row else (zones[0]["entity_id"] if zones else None)),
            "integration": integration,
            "device_id": self._first_value(zones, "device_id"),
            "online": True,
            "status": controller_state if zones else "Unavailable",
            "message": controller_message if zones else "No irrigation zones are available.",
            "active_watering_zone": active_zone["zone_label"] if active_zone else None,
            "active_watering_zone_entity_id": active_zone["entity_id"] if active_zone else None,
            "next_watering_schedule": self._read_timestamp_state(next_watering_row),
            "rain_delay_active": self._is_on(rain_delay_row) if rain_delay_row else None,
            "rain_delay_until": self._read_value_from_attributes(rain_delay_row, "until"),
            "zone_count": len(zones),
            "zones": zones,
            "manual_start_stop": {"start": False, "stop": False, "read_only": True},
            "read_only": True,
            "last_updated": datetime.now().isoformat(timespec="seconds"),
        }

    def _build_explicit_controller(self, rows, row_map, explicit):
        controller_name = explicit["controller_name"] or "Garden Controller"
        integration = explicit["integration_name"] or self._infer_integration(rows) or "Home Assistant"
        zone_rows = [row_map.get(entity_id) for entity_id in explicit["zone_entity_ids"] if row_map.get(entity_id)]
        zone_rows = [row for row in zone_rows if row]
        smart_watering_rows = [row_map.get(entity_id) for entity_id in explicit["smart_watering_entity_ids"] if row_map.get(entity_id)]
        smart_watering_rows = [row for row in smart_watering_rows if row]
        next_watering_row = next((row_map.get(entity_id) for entity_id in explicit["next_watering_entity_ids"] if row_map.get(entity_id)), None)
        rain_delay_row = next((row_map.get(entity_id) for entity_id in explicit["rain_delay_entity_ids"] if row_map.get(entity_id)), None)

        zones = [self._zone_payload(zone_row, controller_name, smart_watering_rows, self._prefix_from_entity_id(self._entity_id(zone_row)) or "", integration) for zone_row in zone_rows]
        active_zone = next((zone for zone in zones if zone["is_active"]), None)
        return {
            "controller_name": controller_name,
            "controller_entity_id": next_watering_row["entity_id"] if next_watering_row else (rain_delay_row["entity_id"] if rain_delay_row else (zones[0]["entity_id"] if zones else None)),
            "integration": integration,
            "device_id": self._first_value(zones, "device_id"),
            "online": True,
            "status": "Connected" if zones else "Unavailable",
            "message": "No active watering is currently running." if not active_zone else f"{active_zone['zone_label']} is currently running.",
            "active_watering_zone": active_zone["zone_label"] if active_zone else None,
            "active_watering_zone_entity_id": active_zone["entity_id"] if active_zone else None,
            "next_watering_schedule": self._read_timestamp_state(next_watering_row),
            "rain_delay_active": self._is_on(rain_delay_row) if rain_delay_row else None,
            "rain_delay_until": self._read_value_from_attributes(rain_delay_row, "until"),
            "zone_count": len(zones),
            "zones": zones,
            "manual_start_stop": {"start": False, "stop": False, "read_only": True},
            "read_only": True,
            "last_updated": datetime.now().isoformat(timespec="seconds"),
        }

    def _match_row(self, rows, row_map, explicit_ids, pattern):
        for entity_id in explicit_ids:
            if entity_id in row_map:
                return row_map[entity_id]
        regex = re.compile(pattern, re.IGNORECASE)
        return next((row for row in rows if regex.match(self._entity_id(row))), None)

    def _match_zone_rows(self, rows, explicit, prefix):
        explicit_ids = set(explicit["zone_entity_ids"])
        zone_rows = []
        pattern = re.compile(rf"^valve\.{re.escape(prefix)}_.+?_zone$", re.IGNORECASE)
        for row in rows:
            entity_id = self._entity_id(row)
            if entity_id in explicit_ids or pattern.match(entity_id):
                if entity_id.startswith("valve."):
                    zone_rows.append(row)
        return self._unique_rows(zone_rows)

    def _match_smart_watering_rows(self, rows, explicit, prefix):
        explicit_ids = set(explicit["smart_watering_entity_ids"])
        smart_rows = []
        pattern = re.compile(rf"^switch\.{re.escape(prefix)}_.+?_smart_watering$", re.IGNORECASE)
        for row in rows:
            entity_id = self._entity_id(row)
            if entity_id in explicit_ids or pattern.match(entity_id):
                if entity_id.startswith("switch."):
                    smart_rows.append(row)
        return self._unique_rows(smart_rows)

    @staticmethod
    def _unique_rows(rows):
        ordered = OrderedDict()
        for row in rows:
            if not isinstance(row, dict):
                continue
            entity_id = str(row.get("entity_id") or "").strip()
            if entity_id:
                ordered[entity_id] = row
        return list(ordered.values())

    def _zone_payload(self, row, controller_name, smart_watering_rows, prefix, integration):
        entity_id = self._entity_id(row)
        friendly_name = self._friendly_name(row)
        zone_label = self._strip_controller_prefix(friendly_name or self._humanize_entity_id(entity_id), controller_name)
        smart_row = self._smart_watering_row_for_zone(row, smart_watering_rows, prefix)
        state = self._state(row).lower()
        availability = "unavailable" if state in UNAVAILABLE_STATES else "available"
        remaining = self._read_value_from_attributes(row, "remaining") or self._read_value_from_attributes(row, "time_remaining") or self._read_value_from_attributes(row, "current_duration")
        current_duration = self._read_value_from_attributes(row, "duration") or self._read_value_from_attributes(row, "current_duration")
        is_active = state in ACTIVE_ZONE_STATES
        return {
            "entity_id": entity_id,
            "controller_name": controller_name,
            "controller_prefix": prefix,
            "friendly_name": friendly_name or zone_label,
            "zone_label": zone_label,
            "zone_name": zone_label,
            "state": self._normalized_zone_state(state),
            "availability": availability,
            "device_class": self._attributes(row).get("device_class"),
            "supported_features": self._attributes(row).get("supported_features"),
            "device_id": self._attributes(row).get("device_id"),
            "integration": integration,
            "smart_watering_entity_id": self._entity_id(smart_row) if smart_row else None,
            "smart_watering_state": self._normalized_switch_state(smart_row),
            "remaining_duration": remaining,
            "duration": current_duration,
            "manual_start_stop": {"start": False, "stop": False, "read_only": True},
            "read_only": True,
            "is_active": is_active,
            "status": "running" if is_active else "closed" if availability == "available" else "unavailable",
            "last_updated": datetime.now().isoformat(timespec="seconds"),
        }

    def _smart_watering_row_for_zone(self, zone_row, smart_watering_rows, prefix):
        zone_entity_id = self._entity_id(zone_row)
        zone_suffix = zone_entity_id.split(f"valve.{prefix}_", 1)[-1] if prefix and f"valve.{prefix}_" in zone_entity_id else zone_entity_id.split("valve.", 1)[-1]
        zone_base = zone_suffix[:-5] if zone_suffix.endswith("_zone") else zone_suffix
        expected = f"switch.{prefix}_{zone_base}_smart_watering" if prefix else None
        if expected:
            for row in smart_watering_rows:
                if self._entity_id(row) == expected:
                    return row
        zone_tokens = zone_base.split("_") if zone_base else []
        if zone_tokens:
            short_name = zone_tokens[-1]
            for row in smart_watering_rows:
                if short_name and short_name in self._entity_id(row):
                    return row
        return None

    def _collect_zones(self, controllers):
        zones = []
        for controller in controllers:
            zones.extend(controller.get("zones", []))
        return zones

    @staticmethod
    def _first_value(items, key):
        for item in items or []:
            value = item.get(key)
            if value not in (None, ""):
                return value
        return None

    @staticmethod
    def _read_timestamp_state(row):
        if not row:
            return None
        state = str(row.get("state") or "").strip()
        if not state or state.lower() in UNAVAILABLE_STATES:
            return None
        return state

    @staticmethod
    def _read_value_from_attributes(row, key):
        if not row:
            return None
        attributes = row.get("attributes") if isinstance(row.get("attributes"), dict) else {}
        value = attributes.get(key)
        if value in (None, ""):
            return None
        return value

    @staticmethod
    def _is_on(row):
        if not row:
            return False
        state = str(row.get("state") or "").strip().lower()
        return state in RAIN_DELAY_ON_STATES

    @staticmethod
    def _normalized_switch_state(row):
        if not row:
            return None
        state = str(row.get("state") or "").strip().lower()
        if state in UNAVAILABLE_STATES:
            return None
        if state in ("on", "true", "enabled"):
            return "on"
        if state in ("off", "false", "disabled"):
            return "off"
        return state

    @staticmethod
    def _normalized_zone_state(state):
        if state in UNAVAILABLE_STATES:
            return "unavailable"
        if state in ACTIVE_ZONE_STATES:
            return "running"
        if state in ("closed", "off", "idle"):
            return "closed"
        return state

    @staticmethod
    def _humanize_entity_id(entity_id):
        text = str(entity_id or "").strip()
        if not text or "." not in text:
            return "Garden Controller"
        name = text.split(".", 1)[1]
        name = name.replace("_", " ").strip()
        return name.title() if name else "Garden Controller"

    @staticmethod
    def _strip_controller_prefix(friendly_name, controller_name):
        text = str(friendly_name or "").strip()
        controller = str(controller_name or "").strip()
        if controller and text.lower().startswith(controller.lower()):
            trimmed = text[len(controller):].strip(" -_:")
            return trimmed or text
        return text or "Garden Zone"

    def _controller_name(self, prefix, rows, explicit):
        if explicit["controller_name"]:
            return explicit["controller_name"]
        for row in rows:
            entity_id = self._entity_id(row)
            if self._prefix_from_entity_id(entity_id) != prefix:
                continue
            friendly_name = self._friendly_name(row)
            if friendly_name:
                for suffix in (" Next watering", " Rain delay", " Smart watering", " Zone"):
                    if friendly_name.lower().endswith(suffix.lower()):
                        friendly_name = friendly_name[: -len(suffix)].strip()
                if friendly_name:
                    return friendly_name
        return self._humanize_entity_id(prefix)

    @staticmethod
    def _infer_integration(rows):
        parts = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            parts.append(str(row.get("entity_id") or "").lower())
            parts.append(str((row.get("attributes") or {}).get("friendly_name") or "").lower())
        text = " ".join(parts)
        if "orbit" in text or "bhyve" in text:
            return "Orbit B-hyve"
        return "Home Assistant"

    def _empty_status(self, entity_count, configured, message):
        now = datetime.now().isoformat(timespec="seconds")
        return {
            "enabled": True,
            "configured": bool(configured),
            "status": "No irrigation entities found",
            "provider": self.provider_key,
            "selected_provider": self.provider_key,
            "source": self.source_name,
            "integration": "Home Assistant",
            "live_data": True,
            "read_only": True,
            "controller_count": 0,
            "zone_count": 0,
            "entity_count": entity_count,
            "controllers": [],
            "zones": [],
            "active_controller": None,
            "active_watering_zone": None,
            "active_watering_zone_entity_id": None,
            "next_watering_schedule": None,
            "rain_delay_active": None,
            "rain_delay_until": None,
            "discovery_status": "No irrigation entities found in Home Assistant.",
            "discovery_message": "No irrigation entities found in Home Assistant.",
            "controller_entity_ids": [],
            "last_updated": now,
            "last_successful_refresh": now,
            "error": None,
            "message": message,
        }
