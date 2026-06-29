from modules.power_adapters.base import PowerAdapter, PowerAdapterResult


class CloudAdapter(PowerAdapter):
    adapter_type = "cloud"
    label = "Cloud"

    def status(self):
        return PowerAdapterResult(
            status="WARN",
            message="Cloud adapter is a placeholder and is not implemented yet.",
            metadata={"adapter": self.adapter_type, "implemented": False},
        )

    def cycle(self):
        return PowerAdapterResult(
            status="WARN",
            message="Cloud power cycling is not implemented. No command was sent.",
            metadata={"adapter": self.adapter_type, "implemented": False},
        )
