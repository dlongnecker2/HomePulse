from dataclasses import dataclass


@dataclass
class RebootResult:
    method: str
    dry_run: bool
    command_sent: bool
    router_responded: bool
    internet_restored: bool
    result: str
    elapsed_recovery_time: str
    router_uptime_before: str
    details: str


class RebootAdapter:
    device_type = "future_adapter"
    label = "Future Adapter"

    def __init__(self, config, log):
        self.config = config
        self.log = log

    def execute(self, reason):
        return self.disabled_result(
            "Real reboot adapter is disabled pending explicit approval",
            reason,
        )

    def disabled_result(self, result, reason):
        self.log.warning(f"{self.label} reboot adapter disabled. Reason: {reason}")
        return RebootResult(
            method=self.device_type,
            dry_run=True,
            command_sent=False,
            router_responded=False,
            internet_restored=False,
            result=result,
            elapsed_recovery_time="0s",
            router_uptime_before="Unavailable",
            details="No real router, SSH, HTTP, Matter, or power-switch command was executed.",
        )


class DryRunAdapter(RebootAdapter):
    device_type = "dry_run"
    label = "Dry Run"

    def execute(self, reason):
        self.log.warning(f"Dry-run router reboot simulated. Reason: {reason}")
        return RebootResult(
            method=self.device_type,
            dry_run=True,
            command_sent=False,
            router_responded=False,
            internet_restored=False,
            result="Dry run only - no reboot command sent",
            elapsed_recovery_time="0s",
            router_uptime_before="Unavailable",
            details="HomePulse simulated the router reboot because dry-run mode is enabled.",
        )


class TapoP125MMatterAdapter(RebootAdapter):
    device_type = "tapo_p125m_matter"
    label = "Tapo P125M Matter"

    def execute(self, reason):
        return self.disabled_result(
            "Tapo P125M Matter power cycling is not enabled in this release",
            reason,
        )


class GenericHttpAdapter(RebootAdapter):
    device_type = "generic_http"
    label = "Generic HTTP"


class SshAdapter(RebootAdapter):
    device_type = "ssh"
    label = "SSH"


class FutureAdapter(RebootAdapter):
    device_type = "future_adapter"
    label = "Future Adapter"


class RouterRebooter:
    adapters = {
        "dry_run": DryRunAdapter,
        "tapo_p125m_matter": TapoP125MMatterAdapter,
        "generic_http": GenericHttpAdapter,
        "http": GenericHttpAdapter,
        "ssh": SshAdapter,
        "smart_plug": FutureAdapter,
        "future_adapter": FutureAdapter,
    }

    def __init__(self, config, log):
        self.config = config
        self.log = log

    def execute(self, reason):
        adapter = self.adapter()
        if self.config.get("dry_run", default=True):
            adapter = DryRunAdapter(self.config, self.log)
        elif not self.real_reboot_enabled() and adapter.device_type != "dry_run":
            return adapter.disabled_result(
                "Real reboot is disabled; dry-run remains the safe mode",
                reason,
            )
        return adapter.execute(reason)

    def adapter(self):
        device_type = self.device_type()
        adapter_class = self.adapters.get(device_type, FutureAdapter)
        return adapter_class(self.config, self.log)

    def device_type(self):
        recovery = self.config.get("router_reboot", default={})
        return recovery.get("recovery_device_type") or recovery.get("method", "dry_run")

    def real_reboot_enabled(self):
        recovery = self.config.get("router_reboot", default={})
        return bool(recovery.get("real_reboot_enabled", False))

    def status(self):
        adapter = self.adapter()
        dry_run = self.config.get("dry_run", default=True) or adapter.device_type == "dry_run"
        return {
            "device_type": adapter.device_type,
            "label": adapter.label,
            "real_reboot_enabled": self.real_reboot_enabled() and not dry_run,
            "dry_run_active": dry_run,
        }
