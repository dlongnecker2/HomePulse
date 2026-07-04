from datetime import datetime

from modules.lighting.providers.base import LightingProvider


UNAVAILABLE_STATES = {"", "unavailable", "unknown", "none", "null"}


class HomeAssistantLightingProvider(LightingProvider):
    provider_key = "home_assistant"
    source_name = "Home Assistant"

    def fetch_status(self, lighting, timeout_seconds):
        recovery = self._router_recovery(lighting)
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

        providers = lighting.get("providers", {}) if isinstance(lighting, dict) else {}
        ha_cfg = providers.get("home_assistant", {}) if isinstance(providers, dict) else {}
        keywords = self.parse_keywords(ha_cfg.get("exterior_keywords"))

        lights = []
        for row in rows:
            light = self.normalize_light(row, keywords)
            if light:
                lights.append(light)

        total_lights = len(lights)
        lights_on = sum(1 for light in lights if light.get("state") == "on")
        lights_off = sum(1 for light in lights if light.get("state") == "off")
        unavailable_lights = sum(1 for light in lights if light.get("state") == "unavailable")

        exterior = [light for light in lights if light.get("is_exterior")]
        exterior_on = [light for light in exterior if light.get("state") == "on"]
        highlight = {
            "present": bool(exterior),
            "total": len(exterior),
            "on": len(exterior_on),
            "names": [light.get("friendly_name") for light in exterior[:5]],
            "govee_present": any("govee" in str(light.get("source") or "").lower() for light in exterior),
        }

        status = "Live" if total_lights else "No lights"
        message = "Lighting Center is receiving live Home Assistant light entity data."
        if not total_lights:
            message = "No light entities were found in Home Assistant."

        return {
            "enabled": True,
            "configured": True,
            "status": status,
            "provider": self.provider_key,
            "source": self.source_name,
            "live_data": True,
            "total_lights": total_lights,
            "lights_on": lights_on,
            "lights_off": lights_off,
            "unavailable_lights": unavailable_lights,
            "exterior_highlight": highlight,
            "lights": lights,
            "last_updated": str(datetime.now()),
            "error": None,
            "message": message,
        }

    @staticmethod
    def _router_recovery(lighting):
        recovery = lighting.get("router_recovery") if isinstance(lighting, dict) else None
        return recovery if isinstance(recovery, dict) else {}

    @staticmethod
    def parse_keywords(value):
        default_tokens = [
            "govee",
            "h706b",
            "exterior",
            "outdoor",
            "porch",
            "driveway",
            "deck",
            "spot",
            "side light",
            "back deck",
            "back spot",
        ]
        text = str(value or "").strip()
        if not text:
            return default_tokens
        tokens = [token.strip().lower() for token in text.split(",") if token.strip()]
        return tokens or default_tokens

    @classmethod
    def normalize_light(cls, row, keywords):
        if not isinstance(row, dict):
            return None
        entity_id = str(row.get("entity_id") or "").strip()
        if not entity_id.startswith("light."):
            return None

        attributes = row.get("attributes") if isinstance(row.get("attributes"), dict) else {}
        friendly_name = str(attributes.get("friendly_name") or entity_id)
        raw_state = str(row.get("state") or "").strip().lower()
        if raw_state == "on":
            state = "on"
        elif raw_state == "off":
            state = "off"
        else:
            state = "unavailable"

        brightness = attributes.get("brightness")
        brightness_percent = None
        number = LightingProvider.parse_float(brightness)
        if number is not None:
            brightness_percent = round(max(0.0, min(100.0, (number / 255.0) * 100.0)), 1)

        color_mode = attributes.get("color_mode")
        rgb_color = attributes.get("rgb_color")
        if isinstance(rgb_color, (list, tuple)):
            rgb_color = list(rgb_color)
        else:
            rgb_color = None

        text_blob = f"{entity_id} {friendly_name}".lower()
        source = cls.infer_source(entity_id, friendly_name, attributes)
        is_exterior = any(token in text_blob for token in keywords)

        return {
            "entity_id": entity_id,
            "friendly_name": friendly_name,
            "integration": source,
            "source": source,
            "state": state,
            "brightness": brightness,
            "brightness_percent": brightness_percent,
            "color_mode": color_mode,
            "rgb_color": rgb_color,
            "effect": attributes.get("effect"),
            "last_changed": row.get("last_changed"),
            "last_updated": row.get("last_updated"),
            "is_exterior": is_exterior,
        }

    @staticmethod
    def infer_source(entity_id, friendly_name, attributes):
        for key in ("integration", "source", "platform"):
            value = attributes.get(key) if isinstance(attributes, dict) else None
            if value:
                return str(value)

        text = f"{entity_id} {friendly_name}".lower()
        if "govee" in text or "h706b" in text:
            return "govee_via_home_assistant"
        if "leviton" in text or "decora" in text:
            return "leviton_via_home_assistant"
        return "home_assistant"
