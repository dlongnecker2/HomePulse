from modules.power_adapters.cloud import CloudAdapter
from modules.power_adapters.dry_run import DryRunAdapter
from modules.power_adapters.home_assistant import HomeAssistantAdapter
from modules.power_adapters.kasa import KasaAdapter


class PowerAdapterFactory:
    adapters = {
        "dry_run": DryRunAdapter,
        "home_assistant": HomeAssistantAdapter,
        "matter": HomeAssistantAdapter,
        "matter_bridge": HomeAssistantAdapter,
        "cloud": CloudAdapter,
        "kasa_legacy": KasaAdapter,
        "kasa_tapo": KasaAdapter,
        "tapo_p125m_matter": HomeAssistantAdapter,
    }

    @classmethod
    def create(cls, config, log, mode=None):
        recovery = config.get("router_reboot", default={})
        selected = mode or recovery.get("recovery_control_mode") or recovery.get("method", "dry_run")
        adapter_class = cls.adapters.get(selected, DryRunAdapter)
        return adapter_class(config, log)
