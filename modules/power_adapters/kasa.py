import asyncio

from modules.power_adapters.base import PowerAdapter, PowerAdapterResult


class KasaAdapter(PowerAdapter):
    adapter_type = "kasa_legacy"
    label = "Kasa Legacy"
    deprecated_for = "TP-Link Tapo P125M firmware 1.4.x"

    def status(self):
        return asyncio.run(self._test_connection())

    def cycle(self):
        return asyncio.run(self._cycle_power())

    @classmethod
    def discover_devices(cls, log):
        try:
            return asyncio.run(cls._discover_devices(log))
        except ImportError:
            log.exception("python-kasa is not installed; Tapo discovery unavailable")
            return []
        except Exception as exc:
            log.exception(f"Tapo discovery failed: {exc}")
            return []

    @staticmethod
    async def _discover_devices(log):
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
                log.warning(f"Skipping discovered Tapo device at {host}: {exc}")
            finally:
                try:
                    await device.disconnect()
                except Exception:
                    pass
        return results

    async def _test_connection(self):
        try:
            device, attempts, recovery = await self._connect()
        except ImportError:
            return PowerAdapterResult(
                status="FAIL",
                message="python-kasa is not installed in this Python environment.",
                metadata={"adapter": self.adapter_type},
            )

        if not device:
            return self._failed_connection_result(attempts)

        try:
            await device.update()
            alias = getattr(device, "alias", recovery.get("recovery_device_ip", "Tapo plug"))
            metadata = {
                "adapter": self.adapter_type,
                "deprecated_for": self.deprecated_for,
                "host": recovery.get("recovery_device_ip"),
                "alias": alias,
                "is_on": getattr(device, "is_on", None),
                "attempts": attempts,
                **self._device_protocol_metadata(device),
            }
            return PowerAdapterResult(
                status="PASS",
                message=f"Kasa legacy connection succeeded for {alias}.",
                device_responded=True,
                metadata=metadata,
            )
        finally:
            await device.disconnect()

    async def _cycle_power(self):
        try:
            device, attempts, recovery = await self._connect()
        except ImportError:
            return PowerAdapterResult(
                status="FAIL",
                message="python-kasa is not installed in this Python environment.",
                metadata={"adapter": self.adapter_type},
            )

        if not device:
            return self._failed_connection_result(attempts)

        try:
            await device.update()
            alias = getattr(device, "alias", recovery.get("recovery_device_ip", "Tapo plug"))
            off_seconds = int(recovery.get("recovery_power_off_seconds", 10))
            wait_seconds = int(recovery.get("recovery_wait_after_power_on_seconds", 180))
            await device.turn_off()
            await asyncio.sleep(off_seconds)
            await device.turn_on()
            return PowerAdapterResult(
                status="PASS",
                message=f"Kasa legacy lamp power cycle command completed for {alias}.",
                command_sent=True,
                device_responded=True,
                power_restored=True,
                metadata={
                    "adapter": self.adapter_type,
                    "deprecated_for": self.deprecated_for,
                    "host": recovery.get("recovery_device_ip"),
                    "alias": alias,
                    "attempts": attempts,
                    "power_off_seconds": off_seconds,
                    "wait_after_power_on_seconds": wait_seconds,
                    **self._device_protocol_metadata(device),
                },
            )
        finally:
            await device.disconnect()

    async def _connect(self):
        from kasa import Device, DeviceConfig, DeviceConnectionParameters, DeviceEncryptionType, DeviceFamily, Discover
        from kasa.credentials import Credentials

        recovery = dict(self.config.get("router_reboot", default={}))
        host = recovery.get("recovery_device_ip")
        attempts = []
        if not host:
            attempts.append({"strategy": "configuration", "success": False, "error": "missing_ip"})
            return None, attempts, recovery

        credentials = None
        if recovery.get("kasa_username") and recovery.get("kasa_password"):
            credentials = Credentials(recovery.get("kasa_username"), recovery.get("kasa_password"))

        def on_attempt(connect_attempt, success):
            protocol, transport, device_class, https = connect_attempt
            entry = {
                "strategy": "try_connect_all",
                "protocol": protocol.__name__,
                "transport": transport.__name__,
                "device_class": device_class.__name__,
                "https": https,
                "success": success,
            }
            attempts.append(entry)
            self.log.info(
                "Kasa legacy protocol attempt: "
                f"{entry['protocol']} / {entry['transport']} / https={entry['https']} / success={success}"
            )

        try:
            device = await Discover.try_connect_all(host, timeout=10, credentials=credentials, on_attempt=on_attempt)
            if device:
                attempts.append({"strategy": "try_connect_all", "success": True})
                return device, attempts, recovery
        except Exception as exc:
            attempts.append({"strategy": "try_connect_all", "success": False, "error": str(exc)})
            self.log.warning(f"Kasa legacy try_connect_all failed for {host}: {exc}")

        try:
            device = await Discover.discover_single(host, discovery_timeout=10, timeout=10, credentials=credentials)
            attempts.append({"strategy": "discover_single", "success": True})
            return device, attempts, recovery
        except Exception as exc:
            attempts.append({"strategy": "discover_single", "success": False, "error": str(exc)})
            self.log.warning(f"Kasa legacy discover_single failed for {host}: {exc}")

        explicit_attempts = [
            ("configured", recovery.get("kasa_device_family", "SMART.TAPOPLUG"), recovery.get("kasa_encrypt_type", "KLAP"), int(recovery.get("kasa_login_version", 2)), False),
            ("tapo_aes_https", "SMART.TAPOPLUG", "AES", 2, True),
            ("tapo_aes_http", "SMART.TAPOPLUG", "AES", 2, False),
            ("tapo_klap_http", "SMART.TAPOPLUG", "KLAP", 2, False),
            ("legacy_xor", "IOT.SMARTPLUGSWITCH", "XOR", None, False),
        ]
        for strategy, family, encryption, login_version, https in explicit_attempts:
            try:
                connection_type = DeviceConnectionParameters(
                    DeviceFamily(family),
                    DeviceEncryptionType(encryption),
                    login_version,
                    https,
                )
                config = DeviceConfig(
                    host=host,
                    timeout=10,
                    credentials=credentials,
                    credentials_hash=recovery.get("kasa_credentials_hash") or None,
                    connection_type=connection_type,
                )
                attempts.append({
                    "strategy": strategy,
                    "family": family,
                    "encryption": encryption,
                    "login_version": login_version,
                    "https": https,
                    "success": False,
                })
                device = await Device.connect(config=config)
                attempts[-1]["success"] = True
                self.log.info(
                    "Kasa legacy explicit protocol succeeded: "
                    f"{strategy} / {family} / {encryption} / https={https}"
                )
                return device, attempts, recovery
            except Exception as exc:
                attempts[-1]["error"] = str(exc)
                self.log.warning(
                    "Kasa legacy explicit protocol failed: "
                    f"{strategy} / {family} / {encryption} / https={https} - {exc}"
                )
        return None, attempts, recovery

    @staticmethod
    def _failed_connection_result(attempts):
        text = " ".join(str(attempt.get("error", "")) for attempt in attempts)
        if "missing_ip" in text:
            return PowerAdapterResult(
                status="WARN",
                message="Tapo plug IP address is not configured.",
                metadata={
                    "adapter": "kasa_legacy",
                    "deprecated_for": KasaAdapter.deprecated_for,
                    "classification": "configuration_missing",
                    "attempts": attempts,
                },
            )
        metadata = {
            "adapter": "kasa_legacy",
            "deprecated_for": KasaAdapter.deprecated_for,
            "classification": "local_lan_unreliable",
            "suggested_path": "matter",
            "attempts": attempts,
        }
        if "TPAP" in text or "Unsupported device" in text:
            message = (
                "local_lan_unreliable: P125M firmware appears to require TPAP/Matter-capable control. "
                "Use the Matter adapter path when available."
            )
        else:
            message = (
                "local_lan_unreliable: Kasa legacy LAN control failed with all protocol attempts. "
                "Use the Matter adapter path when available."
            )
        return PowerAdapterResult(status="FAIL", message=message, metadata=metadata)

    @staticmethod
    def _device_protocol_metadata(device):
        config = getattr(device, "config", None)
        connection_type = getattr(config, "connection_type", None)
        protocol = getattr(device, "protocol", None)
        transport = getattr(protocol, "_transport", None) if protocol else None
        return {
            "device_family": str(getattr(connection_type, "device_family", "")),
            "encryption_type": str(getattr(connection_type, "encryption_type", "")),
            "login_version": getattr(connection_type, "login_version", None),
            "https": getattr(connection_type, "https", None),
            "protocol_class": protocol.__class__.__name__ if protocol else "unknown",
            "transport_class": transport.__class__.__name__ if transport else "unknown",
        }
