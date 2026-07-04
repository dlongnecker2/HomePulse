from dataclasses import dataclass, field
from datetime import datetime


SUPPORTED_DEVICE_TYPES = {
    "internet",
    "solar",
    "vehicle",
    "charger",
    "weather",
    "lighting",
    "garden",
    "climate",
    "security",
    "media",
    "sensor",
}


@dataclass
class RegisteredDevice:
    device_id: str
    name: str
    type: str
    plugin: str
    status: str = "registered"
    health: str = "unknown"
    last_update: str = field(default_factory=lambda: str(datetime.now()))
    capabilities: list = field(default_factory=list)

    def to_dict(self):
        return {
            "device_id": self.device_id,
            "name": self.name,
            "type": self.type,
            "plugin": self.plugin,
            "status": self.status,
            "health": self.health,
            "last_update": self.last_update,
            "capabilities": list(self.capabilities),
        }


class DeviceRegistry:
    def __init__(self):
        self._devices = {}

    def register(self, device_id, name, type, plugin, status="registered", health="unknown", capabilities=None):
        if type not in SUPPORTED_DEVICE_TYPES:
            raise ValueError(f"Unsupported device type: {type}")
        device = RegisteredDevice(
            device_id=device_id,
            name=name,
            type=type,
            plugin=plugin,
            status=status,
            health=health,
            capabilities=capabilities or [],
        )
        self._devices[device_id] = device
        return device

    def get(self, device_id):
        return self._devices.get(device_id)

    def all(self):
        return [device.to_dict() for device in self._devices.values()]

    def types(self):
        preferred = [
            "internet",
            "solar",
            "vehicle",
            "charger",
            "weather",
            "lighting",
            "garden",
            "climate",
            "security",
            "media",
            "sensor",
        ]
        seen = []
        for device in self._devices.values():
            if device.type not in seen:
                seen.append(device.type)
        return [type_name for type_name in preferred if type_name in seen] + [
            type_name for type_name in seen if type_name not in preferred
        ]
