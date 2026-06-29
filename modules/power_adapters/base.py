from dataclasses import dataclass, field


@dataclass
class PowerAdapterResult:
    status: str
    message: str
    command_sent: bool = False
    device_responded: bool = False
    power_restored: bool = False
    elapsed_recovery_time: str = "0s"
    metadata: dict = field(default_factory=dict)


class PowerAdapter:
    adapter_type = "base"
    label = "Base"

    def __init__(self, config, log):
        self.config = config
        self.log = log

    def status(self):
        return PowerAdapterResult(
            status="WARN",
            message=f"{self.label} adapter status is not implemented.",
        )

    def test_connection(self):
        return self.status()

    def turn_on(self):
        return PowerAdapterResult(
            status="WARN",
            message=f"{self.label} adapter turn_on is not implemented.",
        )

    def turn_off(self):
        return PowerAdapterResult(
            status="WARN",
            message=f"{self.label} adapter turn_off is not implemented.",
        )

    def cycle(self):
        return PowerAdapterResult(
            status="WARN",
            message=f"{self.label} adapter cycle is not implemented.",
        )

    def power_on(self):
        return self.turn_on()

    def power_off(self):
        return self.turn_off()

    def cycle_power(self):
        return self.cycle()
