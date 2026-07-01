from dataclasses import asdict, dataclass


@dataclass
class VehicleStatus:
    enabled: bool = False
    configured: bool = False
    availability: str = "disabled"
    vehicle_name: str = "2025 Chevrolet Equinox EV"
    battery_percent: float | None = None
    range_mi: float | None = None
    plug_state: str | None = None
    charging_state: str | None = None
    odometer_mi: float | None = None
    lifetime_energy_kwh: float | None = None
    lifetime_efficiency_mi_per_kwh: float | None = None
    estimated_lifetime_cost: float | None = None
    cost_per_mile: float | None = None
    last_update: str | None = None
    message: str = "Vehicle Center is disabled"

    def to_dict(self):
        return asdict(self)
