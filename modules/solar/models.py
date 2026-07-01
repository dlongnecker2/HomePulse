from dataclasses import asdict, dataclass


@dataclass
class SolarStatus:
    enabled: bool = False
    configured: bool = False
    name: str = "Solar Center"
    status: str = "Disabled"
    current_production_kw: float | None = None
    current_production_w: int | None = None
    production_today_kwh: float | None = None
    production_last_7_days_kwh: float | None = None
    lifetime_production_mwh: float | None = None
    lifetime_production_kwh: float | None = None
    production_ct_power_kw: float | None = None
    production_ct_energy_delivered_mwh: float | None = None
    estimated_value_today: float | None = None
    estimated_value_last_7_days: float | None = None
    estimated_lifetime_value: float | None = None
    estimated_value_per_hour: float | None = None
    electricity_rate: float = 0.13
    last_updated: str | None = None
    source: str = "Enphase Envoy"
    error: str | None = None
    message: str = "Solar Center is disabled"

    def to_dict(self):
        return asdict(self)
