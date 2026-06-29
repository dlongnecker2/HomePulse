from modules.power_adapters.cloud import CloudAdapter
from modules.power_adapters.dry_run import DryRunAdapter
from modules.power_adapters.kasa import KasaAdapter
from modules.power_adapters.matter_adapter import MatterAdapter


class PowerAdapterFactory:
    adapters = {
        "dry_run": DryRunAdapter,
        "matter": MatterAdapter,
        "matter_bridge": MatterAdapter,
        "cloud": CloudAdapter,
        "kasa_legacy": KasaAdapter,
        "kasa_tapo": KasaAdapter,
        "tapo_p125m_matter": MatterAdapter,
    }

    @classmethod
    def create(cls, config, log, mode=None):
        recovery = config.get("router_reboot", default={})
        selected = mode or recovery.get("recovery_control_mode") or recovery.get("method", "dry_run")
        adapter_class = cls.adapters.get(selected, DryRunAdapter)
        return adapter_class(config, log)
