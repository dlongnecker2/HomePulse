import asyncio


class TapoDiscovery:
    def __init__(self, log):
        self.log = log

    def discover(self):
        try:
            return asyncio.run(self._discover())
        except ImportError:
            self.log.exception("python-kasa is not installed; Tapo discovery unavailable")
            return []
        except Exception as exc:
            self.log.exception(f"Tapo discovery failed: {exc}")
            return []

    async def _discover(self):
        from kasa import DeviceType, Discover

        devices = await Discover.discover(discovery_timeout=5)
        results = []
        for host, device in devices.items():
            try:
                await device.update()
                device_type = getattr(device, "device_type", None)
                if device_type != DeviceType.Plug:
                    continue
                results.append({
                    "name": getattr(device, "alias", "") or "",
                    "ip": getattr(device, "host", host) or host,
                    "model": getattr(device, "model", "") or "",
                    "type": "plug",
                })
            except Exception as exc:
                self.log.warning(f"Skipping discovered Tapo device at {host}: {exc}")
            finally:
                try:
                    await device.disconnect()
                except Exception:
                    pass
        return results
