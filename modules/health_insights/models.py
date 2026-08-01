"""Normalized, storage-neutral Health Insights models.

These models deliberately preserve missing values as ``None``. The audit does
not interpret missing nutrition as zero intake or missing activity as
inactivity.
"""

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class DailyHealthInsight:
    local_date: str
    timezone: str
    nutrition_calories: float | None = None
    protein_grams: float | None = None
    carbohydrate_grams: float | None = None
    fat_grams: float | None = None
    fiber_grams: float | None = None
    sodium_milligrams: float | None = None
    nutrition_complete: bool = False
    nutrition_source: str | None = None
    nutrition_platform: str | None = None
    nutrition_record_count: int = 0
    steps: int | None = None
    total_calories_burned: float | None = None
    active_energy_calories: float | None = None
    active_minutes: int | None = None
    active_zone_minutes: int | None = None
    distance_miles: float | None = None
    exercise_session_count: int = 0
    exercise_minutes: float | None = None
    exercise_calories: float | None = None
    activity_complete: bool = False
    activity_source: str | None = None
    sleep_minutes: int | None = None
    sleep_hours: float | None = None
    awake_minutes: int | None = None
    sleep_session_count: int = 0
    sleep_complete: bool = False
    sleep_source: str | None = None
    weight_pounds: float | None = None
    seven_day_average_weight_pounds: float | None = None
    body_fat_percentage: float | None = None
    muscle_percentage: float | None = None
    visceral_fat_index: float | None = None
    weight_available: bool = False
    weight_source: str | None = None
    is_current_day: bool = False
    nutrition_activity_weight_complete: bool = False
    data_status: str = "incomplete"
    first_imported_at: str | None = None
    last_refreshed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DailyNutrition:
    local_date: str
    calories_kcal: float | None = None
    protein_g: float | None = None
    carbohydrates_g: float | None = None
    fat_g: float | None = None
    fiber_g: float | None = None
    sodium_mg: float | None = None
    water_ml: float | None = None
    record_count: int = 0
    completeness: str = "unknown"
    source_platforms: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DailyActivity:
    local_date: str
    steps: int | None = None
    exercise_minutes: float | None = None
    active_energy_kcal: float | None = None
    total_calories_kcal: float | None = None
    active_minutes: int | None = None
    active_zone_minutes: int | None = None
    distance_meters: float | None = None
    source_platforms: list[str] = field(default_factory=list)

    @property
    def expenditure_source_of_truth(self) -> float | None:
        """Return overall expenditure without adding overlapping components."""
        return self.total_calories_kcal

    def estimated_calorie_balance(self, calories_consumed: float | None) -> float | None:
        if calories_consumed is None or self.total_calories_kcal is None:
            return None
        return calories_consumed - self.total_calories_kcal

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExerciseSession:
    record_key: str
    local_date: str | None
    start_time: str | None
    end_time: str | None
    exercise_type: str | None
    category: str
    active_minutes: float | None
    calories_kcal: float | None
    distance_meters: float | None
    steps: int | None
    active_zone_minutes: int | None
    source_platform: str
    update_time: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DailySleep:
    local_date: str
    sleep_minutes: int | None = None
    start_time: str | None = None
    end_time: str | None = None
    deep_minutes: int | None = None
    light_minutes: int | None = None
    rem_minutes: int | None = None
    awake_minutes: int | None = None
    source_platforms: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
