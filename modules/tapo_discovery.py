from modules.power_adapters import KasaAdapter


class TapoDiscovery:
    def __init__(self, log):
        self.log = log

    def discover(self):
        return KasaAdapter.discover_devices(self.log)
