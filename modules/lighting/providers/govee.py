from datetime import datetime
from urllib.parse import urlencode

from modules.lighting.providers.base import LightingProvider


class GoveeLightingProvider(LightingProvider):
    provider_key = "govee"
    source_name = "Govee Developer API"

    def fetch_status(self, lighting, timeout_seconds):
        providers = lighting.get("providers", {}) if isinstance(lighting, dict) else {}
        govee_cfg = providers.get("govee", {}) if isinstance(providers, dict) else {}
        api_key = str(govee_cfg.get("api_key") or "").strip()
        if not api_key:
            raise ValueError("Govee API key is required.")

        name_filter = str(govee_cfg.get("device_name_filter") or "").strip().lower()
        headers = {"Govee-API-Key": api_key, "Accept": "application/json"}

        devices_payload = self.request_json("https://developer-api.govee.com/v1/devices", timeout_seconds, headers=headers)
        devices = self.parse_devices(devices_payload)
        if name_filter:
            devices = [device for device in devices if name_filter in str(device.get("device_name", "")).lower()]

        for device in devices:
            state_payload = self.fetch_device_state(device, headers, timeout_seconds)
            self.apply_state(device, state_payload)

        online_count = sum(1 for device in devices if device.get("online") is True)
        power_on_count = sum(1 for device in devices if str(device.get("power_state") or "").lower() == "on")
        missing_scene_count = sum(1 for device in devices if device.get("scene_name_available") is False)

        message = "Lighting Center is receiving live Govee device data."
        if not devices:
            message = "No Govee devices matched the current filter."
        elif missing_scene_count:
            message = "Lighting Center is receiving live Govee data; scene name unavailable from provider for some devices."

        return {
            "enabled": True,
            "configured": True,
            "status": "Live" if devices else "No devices",
            "provider": self.provider_key,
            "source": self.source_name,
            "live_data": True,
            "device_count": len(devices),
            "online_count": online_count,
            "power_on_count": power_on_count,
            "devices": devices,
            "scene_note": "scene name unavailable from provider" if missing_scene_count else None,
            "last_updated": str(datetime.now()),
            "error": None,
            "message": message,
        }

    def fetch_device_state(self, device, headers, timeout_seconds):
        device_id = device.get("device_id")
        model = device.get("model")
        if not device_id or not model:
            return None

        query = urlencode({"device": device_id, "model": model})
        url = f"https://developer-api.govee.com/v1/devices/state?{query}"
        try:
            return self.request_json(url, timeout_seconds, headers=headers)
        except Exception:
            return None

    @staticmethod
    def parse_devices(payload):
        data = payload.get("data") if isinstance(payload, dict) else None
        rows = data.get("devices") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            return []

        devices = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            device_id = str(row.get("device") or "").strip()
            devices.append({
                "device_name": row.get("deviceName") or "Unknown Govee Device",
                "device_id": device_id,
                "device_id_masked": GoveeLightingProvider.mask_device_id(device_id),
                "model": row.get("model"),
                "controllable": bool(row.get("controllable", False)),
                "retrievable": bool(row.get("retrievable", False)),
                "online": None,
                "power_state": None,
                "brightness_percent": None,
                "color": None,
                "color_temperature_kelvin": None,
                "mode": None,
                "scene_or_effect": None,
                "scene_name_available": False,
            })
        return devices

    @staticmethod
    def apply_state(device, payload):
        if not isinstance(device, dict) or not isinstance(payload, dict):
            return

        data = payload.get("data") if isinstance(payload, dict) else None
        properties = data.get("properties") if isinstance(data, dict) else None
        if not isinstance(properties, list):
            return

        for entry in properties:
            if not isinstance(entry, dict) or not entry:
                continue
            key = next(iter(entry.keys()))
            value = entry.get(key)
            key_lower = str(key).strip().lower()

            if key_lower == "online":
                device["online"] = bool(value) if isinstance(value, bool) else str(value).strip().lower() in ("online", "true", "1")
                continue

            if key_lower in ("powerstate", "power"):
                device["power_state"] = str(value).strip() if value is not None else None
                continue

            if key_lower == "brightness":
                number = LightingProvider.parse_float(value)
                if number is not None:
                    device["brightness_percent"] = round(max(0.0, min(100.0, number)), 1)
                continue

            if key_lower in ("colorteminkelvin", "color_temperature_kelvin"):
                number = LightingProvider.parse_float(value)
                if number is not None:
                    device["color_temperature_kelvin"] = round(number)
                continue

            if key_lower == "color" and isinstance(value, dict):
                red = value.get("r")
                green = value.get("g")
                blue = value.get("b")
                if all(channel is not None for channel in (red, green, blue)):
                    device["color"] = f"rgb({red}, {green}, {blue})"
                continue

            if key_lower == "mode":
                text = str(value).strip() if value is not None else None
                device["mode"] = text
                if text:
                    device["scene_or_effect"] = text
                    device["scene_name_available"] = True
                continue

            if key_lower in ("scene", "effect") and value is not None:
                text = str(value).strip()
                if text:
                    device["scene_or_effect"] = text
                    device["scene_name_available"] = True

    @staticmethod
    def mask_device_id(device_id):
        text = str(device_id or "").strip()
        if len(text) <= 4:
            return text
        return f"...{text[-4:]}"
