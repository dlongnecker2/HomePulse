DEFAULT_WEIGHT_PROGRESS_CONFIG = {
    "enabled": True,
    "database": "data/weight_progress.db",
    "display_unit": "lb",
    "starting_weight": None,
    "goal_weight": 220,
    "entities": {
        "weight": "sensor.withings_weight",
        "body_fat": "sensor.withings_fat_ratio",
        "withings_goal": "sensor.withings_weight_goal",
        "fat_mass": "sensor.withings_fat_mass",
        "fat_free_mass": "sensor.withings_fat_free_mass",
        "muscle_mass": "sensor.withings_muscle_mass",
        "bone_mass": "sensor.withings_bone_mass",
        "heart_rate": "sensor.withings_heart_pulse",
        "battery": "sensor.withings_battery",
    },
}
