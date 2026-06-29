from modules.power_adapters.base import PowerAdapter, PowerAdapterResult


class DryRunAdapter(PowerAdapter):
    adapter_type = "dry_run"
    label = "Dry Run"

    def status(self):
        return PowerAdapterResult(
            status="PASS",
            message="Dry-run adapter is available. No power command will be sent.",
            metadata={"adapter": self.adapter_type},
        )

    def turn_on(self):
        return self._dry_result("power_on")

    def turn_off(self):
        return self._dry_result("power_off")

    def cycle(self):
        return self._dry_result("cycle_power")

    def _dry_result(self, action):
        self.log.warning(f"Dry-run power adapter simulated {action}")
        return PowerAdapterResult(
            status="PASS",
            message=f"Dry run only - simulated {action}; no power command sent.",
            command_sent=False,
            device_responded=False,
            power_restored=False,
            metadata={"adapter": self.adapter_type, "action": action},
        )
