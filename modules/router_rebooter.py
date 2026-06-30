from dataclasses import dataclass

from modules.power_adapters import DryRunAdapter, PowerAdapterFactory


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


class RouterRebooter:
    def __init__(self, config, log):
        self.config = config
        self.log = log

    def execute(self, reason):
        adapter = self.adapter()
        if self.config.get("dry_run", default=True) or not self.real_reboot_enabled():
            adapter = DryRunAdapter(self.config, self.log)

        power_result = adapter.cycle()
        return RebootResult(
            method=adapter.adapter_type,
            dry_run=adapter.adapter_type == "dry_run",
            command_sent=power_result.command_sent,
            router_responded=power_result.device_responded,
            internet_restored=power_result.power_restored,
            result=power_result.message,
            elapsed_recovery_time=power_result.elapsed_recovery_time,
            router_uptime_before="Unavailable",
            details=power_result.message,
        )

    def adapter(self):
        return PowerAdapterFactory.create(self.config, self.log, self.control_mode())

    def control_mode(self):
        recovery = self.config.get("router_reboot", default={})
        if recovery.get("recovery_control_mode"):
            return recovery["recovery_control_mode"]
        device_type = recovery.get("recovery_device_type") or recovery.get("method", "dry_run")
        if device_type == "home_assistant":
            return "home_assistant"
        if device_type in ("tapo_p125m_matter", "matter", "matter_bridge"):
            return "home_assistant"
        if device_type in ("kasa_tapo", "kasa_legacy"):
            return "kasa_legacy"
        if device_type == "cloud":
            return "cloud"
        return "dry_run"

    def real_reboot_enabled(self):
        recovery = self.config.get("router_reboot", default={})
        return bool(recovery.get("real_reboot_enabled", False))

    def status(self):
        adapter = self.adapter()
        dry_run = self.config.get("dry_run", default=True) or adapter.adapter_type == "dry_run"
        return {
            "device_type": adapter.adapter_type,
            "label": adapter.label,
            "real_reboot_enabled": self.real_reboot_enabled() and not dry_run,
            "dry_run_active": dry_run,
        }
