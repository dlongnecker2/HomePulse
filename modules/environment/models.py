from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class EnvironmentalEntity:
    entity_id: str
    domain: str
    entity_name: str
    display_name: str
    area_id: str
    area_name: str
    device_id: str
    device_name: str
    device_class: str | None = None
    state_class: str | None = None
    unit_of_measurement: str | None = None
    integration: str | None = None
    supported: bool = True
    confidence: float = 1.0
    label_source: str = "registry"
    support_reason: str = ""
    first_seen: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    last_seen: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    metadata: dict = field(default_factory=dict)

    def to_dict(self):
        return {
            "entity_id": self.entity_id,
            "domain": self.domain,
            "entity_name": self.entity_name,
            "display_name": self.display_name,
            "area_id": self.area_id,
            "area_name": self.area_name,
            "device_id": self.device_id,
            "device_name": self.device_name,
            "device_class": self.device_class,
            "state_class": self.state_class,
            "unit_of_measurement": self.unit_of_measurement,
            "integration": self.integration,
            "supported": self.supported,
            "confidence": self.confidence,
            "label_source": self.label_source,
            "support_reason": self.support_reason,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "metadata": dict(self.metadata),
        }


@dataclass
class EnvironmentalReading:
    entity_id: str
    domain: str
    raw_state: str | None
    raw_value: str | None
    unit_of_measurement: str | None
    parsed_number: float | None = None
    parsed_boolean: bool | None = None
    availability: str = "unknown"
    area_id: str = ""
    area_name: str = ""
    device_id: str = ""
    device_name: str = ""
    entity_name: str = ""
    label_source: str = "registry"
    confidence: float = 1.0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    metadata: dict = field(default_factory=dict)

    def to_dict(self):
        return {
            "entity_id": self.entity_id,
            "domain": self.domain,
            "raw_state": self.raw_state,
            "raw_value": self.raw_value,
            "unit_of_measurement": self.unit_of_measurement,
            "parsed_number": self.parsed_number,
            "parsed_boolean": self.parsed_boolean,
            "availability": self.availability,
            "area_id": self.area_id,
            "area_name": self.area_name,
            "device_id": self.device_id,
            "device_name": self.device_name,
            "entity_name": self.entity_name,
            "label_source": self.label_source,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
            "metadata": dict(self.metadata),
        }
