from dataclasses import dataclass
from datetime import datetime
import json


@dataclass
class MetricSnapshot:
    timestamp: str
    module: str
    metric: str
    value: float
    unit: str | None = None
    source: str | None = None
    metadata_json: str | None = None

    @classmethod
    def create(cls, module, metric, value, unit=None, source=None, metadata=None, timestamp=None):
        metadata_json = json.dumps(metadata, sort_keys=True) if metadata else None
        return cls(
            timestamp=timestamp or str(datetime.now()),
            module=str(module),
            metric=str(metric),
            value=float(value),
            unit=unit,
            source=source,
            metadata_json=metadata_json,
        )

    @classmethod
    def from_row(cls, row):
        return cls(
            timestamp=row["timestamp"],
            module=row["module"],
            metric=row["metric"],
            value=row["value"],
            unit=row["unit"],
            source=row["source"],
            metadata_json=row["metadata_json"],
        )

    def to_dict(self):
        metadata = None
        if self.metadata_json:
            try:
                metadata = json.loads(self.metadata_json)
            except json.JSONDecodeError:
                metadata = None
        return {
            "timestamp": self.timestamp,
            "module": self.module,
            "metric": self.metric,
            "value": self.value,
            "unit": self.unit,
            "source": self.source,
            "metadata": metadata,
        }
