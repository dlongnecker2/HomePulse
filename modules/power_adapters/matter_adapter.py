import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from modules.power_adapters.base import PowerAdapter, PowerAdapterResult


class MatterAdapter(PowerAdapter):
    adapter_type = "matter_bridge"
    label = "Matter Bridge"

    def status(self):
        recovery = self.config.get("router_reboot", default={})
        missing = [
            key for key in ("home_assistant_url", "home_assistant_token", "matter_entity_id")
            if not recovery.get(key)
        ]
        if missing:
            return PowerAdapterResult(
                status="WARN",
                message=f"Home Assistant Matter bridge is missing: {', '.join(missing)}.",
                metadata={"adapter": self.adapter_type, "missing": missing},
            )
        return PowerAdapterResult(
            status="PASS",
            message="Home Assistant Matter bridge settings are present.",
            device_responded=True,
            metadata={
                "adapter": self.adapter_type,
                "home_assistant_url": recovery.get("home_assistant_url"),
                "entity_id": recovery.get("matter_entity_id"),
            },
        )

    def turn_on(self):
        return self._call_switch_service("turn_on")

    def turn_off(self):
        return self._call_switch_service("turn_off")

    def cycle(self):
        recovery = self.config.get("router_reboot", default={})
        off_seconds = int(recovery.get("recovery_power_off_seconds", 10))
        wait_seconds = int(recovery.get("recovery_wait_after_power_on_seconds", 180))
        off_result = self.turn_off()
        if off_result.status != "PASS":
            return off_result
        time.sleep(off_seconds)
        on_result = self.turn_on()
        status = "PASS" if on_result.status == "PASS" else on_result.status
        return PowerAdapterResult(
            status=status,
            message=(
                "Matter bridge cycle command completed."
                if status == "PASS"
                else f"Matter bridge cycle failed during power on: {on_result.message}"
            ),
            command_sent=off_result.command_sent or on_result.command_sent,
            device_responded=on_result.device_responded,
            power_restored=on_result.status == "PASS",
            elapsed_recovery_time=f"{off_seconds + wait_seconds}s",
            metadata={
                "adapter": self.adapter_type,
                "power_off_seconds": off_seconds,
                "wait_after_power_on_seconds": wait_seconds,
                "off": off_result.metadata,
                "on": on_result.metadata,
            },
        )

    def _call_switch_service(self, service):
        recovery = self.config.get("router_reboot", default={})
        missing = [
            key for key in ("home_assistant_url", "home_assistant_token", "matter_entity_id")
            if not recovery.get(key)
        ]
        if missing:
            return PowerAdapterResult(
                status="WARN",
                message=f"Home Assistant Matter bridge is missing: {', '.join(missing)}.",
                metadata={"adapter": self.adapter_type, "missing": missing, "service": service},
            )

        base_url = recovery["home_assistant_url"].rstrip("/")
        url = f"{base_url}/api/services/switch/{service}"
        payload = json.dumps({"entity_id": recovery["matter_entity_id"]}).encode("utf-8")
        request = Request(
            url,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {recovery['home_assistant_token']}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                body = response.read(500).decode("utf-8", errors="replace")
                return PowerAdapterResult(
                    status="PASS",
                    message=f"Home Assistant switch.{service} call succeeded.",
                    command_sent=True,
                    device_responded=True,
                    power_restored=service == "turn_on",
                    metadata={
                        "adapter": self.adapter_type,
                        "service": service,
                        "status_code": response.status,
                        "entity_id": recovery["matter_entity_id"],
                        "response": body,
                    },
                )
        except HTTPError as exc:
            return PowerAdapterResult(
                status="FAIL",
                message=f"Home Assistant switch.{service} failed: HTTP {exc.code}.",
                command_sent=True,
                metadata={"adapter": self.adapter_type, "service": service, "status_code": exc.code},
            )
        except URLError as exc:
            return PowerAdapterResult(
                status="FAIL",
                message=f"Home Assistant switch.{service} failed: {exc.reason}.",
                metadata={"adapter": self.adapter_type, "service": service},
            )
        except Exception as exc:
            return PowerAdapterResult(
                status="FAIL",
                message=f"Home Assistant switch.{service} failed: {exc}.",
                metadata={"adapter": self.adapter_type, "service": service},
            )
