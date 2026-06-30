from dataclasses import asdict, dataclass


@dataclass
class EnergyStatus:
    enabled: bool = False
    configured: bool = False
    vehicle_name: str = "2025 Chevrolet Equinox EV"
    charger_name: str = "ChargePoint Home Flex"
    status: str = "Disabled"
    is_charging: bool = False
    power_kw: float = 0
    voltage: float | None = None
    current: float | None = None
    battery_percent: float | None = None
    session_energy_kwh: float = 0
    estimated_cost: float = 0
    estimated_miles_added: float = 0
    last_update: str | None = None
    message: str = "Energy Center is disabled"

    def to_dict(self):
        return asdict(self)
