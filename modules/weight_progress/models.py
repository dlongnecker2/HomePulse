from dataclasses import dataclass
import json


@dataclass
class WeightMeasurement:
    captured_at: str
    source_timestamp: str
    source_entity: str
    weight_kg: float | None = None
    body_fat_percent: float | None = None
    fat_mass_kg: float | None = None
    fat_free_mass_kg: float | None = None
    muscle_mass_kg: float | None = None
    bone_mass_kg: float | None = None
    heart_rate_bpm: float | None = None
    scale_battery: str | None = None
    withings_goal_kg: float | None = None
    reading_hash: str | None = None
    metadata_json: str | None = None

    @classmethod
    def create(cls, **kwargs):
        metadata = kwargs.pop("metadata", None)
        if metadata is not None:
            kwargs["metadata_json"] = json.dumps(metadata, sort_keys=True)
        return cls(**kwargs)

    @classmethod
    def from_row(cls, row):
        return cls(
            captured_at=row["captured_at"],
            source_timestamp=row["source_timestamp"],
            source_entity=row["source_entity"],
            weight_kg=row["weight_kg"],
            body_fat_percent=row["body_fat_percent"],
            fat_mass_kg=row["fat_mass_kg"],
            fat_free_mass_kg=row["fat_free_mass_kg"],
            muscle_mass_kg=row["muscle_mass_kg"],
            bone_mass_kg=row["bone_mass_kg"],
            heart_rate_bpm=row["heart_rate_bpm"],
            scale_battery=row["scale_battery"],
            withings_goal_kg=row["withings_goal_kg"],
            reading_hash=row["reading_hash"],
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
            "captured_at": self.captured_at,
            "source_timestamp": self.source_timestamp,
            "source_entity": self.source_entity,
            "weight_kg": self.weight_kg,
            "body_fat_percent": self.body_fat_percent,
            "fat_mass_kg": self.fat_mass_kg,
            "fat_free_mass_kg": self.fat_free_mass_kg,
            "muscle_mass_kg": self.muscle_mass_kg,
            "bone_mass_kg": self.bone_mass_kg,
            "heart_rate_bpm": self.heart_rate_bpm,
            "scale_battery": self.scale_battery,
            "withings_goal_kg": self.withings_goal_kg,
            "reading_hash": self.reading_hash,
            "metadata": metadata,
        }
