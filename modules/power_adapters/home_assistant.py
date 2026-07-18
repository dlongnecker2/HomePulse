import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from modules.power_adapters.base import PowerAdapter, PowerAdapterResult


class HomeAssistantAdapter(PowerAdapter):
    adapter_type = "home_assistant"
    label = "Home Assistant"

    def test_connection(self):
        state_result = self.get_state()
        if state_result.status != "PASS":
            return state_result
        state = state_result.metadata.get("state")
        return PowerAdapterResult(
            status="PASS",
            message=f"Connected. Entity state is {state}.",
            device_responded=True,
            power_restored=state == "on",
            metadata=state_result.metadata,
        )

    def status(self):
        return self.test_connection()

    def get_state(self, timeout_seconds=15):
        validation = self._validate_settings()
        if validation:
            return PowerAdapterResult(
                status=validation["status"],
                message=validation["message"],
                metadata={"adapter": self.adapter_type, **validation["metadata"]},
            )

        recovery = self._recovery()
        entity_id = self._entity_id(recovery)
        try:
            response = self._request(f"/api/states/{entity_id}", method="GET", timeout=timeout_seconds)
            state = response.get("state")
            return PowerAdapterResult(
                status="PASS",
                message=f"Home Assistant entity {entity_id} is {state}.",
                device_responded=True,
                power_restored=state == "on",
                metadata={
                    "adapter": self.adapter_type,
                    "entity_id": entity_id,
                    "state": state,
                    "attributes": response.get("attributes", {}),
                },
            )
        except HTTPError as exc:
            if exc.code == 404:
                message = f"Invalid entity ID: Home Assistant entity {entity_id} was not found."
            elif exc.code in (401, 403):
                message = "Home Assistant token was rejected. Check the configured access token."
            else:
                message = f"Home Assistant state request failed: HTTP {exc.code}."
            return PowerAdapterResult(
                status="FAIL",
                message=message,
                device_responded=True,
                metadata={"adapter": self.adapter_type, "entity_id": entity_id, "status_code": exc.code},
            )
        except URLError as exc:
            return PowerAdapterResult(
                status="FAIL",
                message=f"Home Assistant unreachable: {exc.reason}.",
                metadata={"adapter": self.adapter_type, "entity_id": entity_id},
            )
        except Exception as exc:
            return PowerAdapterResult(
                status="FAIL",
                message=f"Home Assistant state request failed: {exc}.",
                metadata={"adapter": self.adapter_type, "entity_id": entity_id},
            )

    def turn_on(self):
        return self._call_switch_service("turn_on")

    def turn_off(self):
        return self._call_switch_service("turn_off")

    def cycle_power(self):
        return self.cycle()

    def cycle(self):
        validation = self._validate_settings()
        if validation:
            return PowerAdapterResult(
                status=validation["status"],
                message=validation["message"],
                metadata={"adapter": self.adapter_type, **validation["metadata"]},
            )
        recovery = self._recovery()
        off_seconds = int(recovery.get("recovery_power_off_seconds", 10))
        wait_after_on_seconds = int(recovery.get("recovery_wait_after_power_on_seconds", 180))

        off_result = self.turn_off()
        if off_result.status != "PASS":
            return PowerAdapterResult(
                status=off_result.status,
                message=f"Power cycle failure: Home Assistant switch could not be turned off. {off_result.message}",
                command_sent=off_result.command_sent,
                device_responded=off_result.device_responded,
                power_restored=False,
                metadata={"adapter": self.adapter_type, "off": off_result.metadata},
            )

        time.sleep(off_seconds)
        on_result = self.turn_on()
        if on_result.status != "PASS":
            return PowerAdapterResult(
                status=on_result.status,
                message=f"Power cycle failure: Home Assistant switch could not be turned back on. {on_result.message}",
                command_sent=off_result.command_sent or on_result.command_sent,
                device_responded=on_result.device_responded,
                power_restored=False,
                elapsed_recovery_time=f"{off_seconds}s",
                metadata={"adapter": self.adapter_type, "off": off_result.metadata, "on": on_result.metadata},
            )

        state_result = self._wait_for_state("on", timeout_seconds=10)
        restored = state_result.status == "PASS" and state_result.metadata.get("state") == "on"
        return PowerAdapterResult(
            status="PASS" if restored else "FAIL",
            message=(
                "Power cycle success: Home Assistant switch turned off, turned on, and returned to ON."
                if restored
                else f"Power cycle failure: Home Assistant switch did not confirm ON. {state_result.message}"
            ),
            command_sent=True,
            device_responded=on_result.device_responded or state_result.device_responded,
            power_restored=restored,
            elapsed_recovery_time=f"{off_seconds + wait_after_on_seconds}s",
            metadata={
                "adapter": self.adapter_type,
                "power_off_seconds": off_seconds,
                "wait_after_power_on_seconds": wait_after_on_seconds,
                "elapsed_recovery_time": f"{off_seconds + wait_after_on_seconds}s",
                "off": off_result.metadata,
                "on": on_result.metadata,
                "confirmed_state": state_result.metadata,
            },
        )

    def _call_switch_service(self, service):
        validation = self._validate_settings()
        if validation:
            return PowerAdapterResult(
                status=validation["status"],
                message=validation["message"],
                metadata={"adapter": self.adapter_type, "service": service, **validation["metadata"]},
            )

        recovery = self._recovery()
        entity_id = self._entity_id(recovery)
        try:
            response = self._request(
                f"/api/services/switch/{service}",
                method="POST",
                payload={"entity_id": entity_id},
                timeout=20,
            )
            return PowerAdapterResult(
                status="PASS",
                message=f"Home Assistant switch.{service} call succeeded.",
                command_sent=True,
                device_responded=True,
                power_restored=service == "turn_on",
                metadata={
                    "adapter": self.adapter_type,
                    "service": service,
                    "entity_id": entity_id,
                    "response": response,
                },
            )
        except HTTPError as exc:
            if exc.code == 404:
                message = f"Invalid entity ID: Home Assistant entity {entity_id} was not found."
            elif exc.code in (401, 403):
                message = "Home Assistant token was rejected. Check the configured access token."
            else:
                message = f"Home Assistant switch.{service} failed: HTTP {exc.code}."
            return PowerAdapterResult(
                status="FAIL",
                message=message,
                command_sent=True,
                device_responded=True,
                metadata={"adapter": self.adapter_type, "service": service, "status_code": exc.code},
            )
        except URLError as exc:
            return PowerAdapterResult(
                status="FAIL",
                message=f"Home Assistant unreachable: {exc.reason}.",
                metadata={"adapter": self.adapter_type, "service": service},
            )
        except Exception as exc:
            return PowerAdapterResult(
                status="FAIL",
                message=f"Home Assistant switch.{service} failed: {exc}.",
                metadata={"adapter": self.adapter_type, "service": service},
            )

    def _wait_for_state(self, expected_state, timeout_seconds):
        deadline = time.monotonic() + timeout_seconds
        last_result = None
        while time.monotonic() <= deadline:
            last_result = self.get_state()
            if last_result.status == "PASS" and last_result.metadata.get("state") == expected_state:
                return last_result
            time.sleep(1)
        return last_result or self.get_state()

    def _request(self, path, method="GET", payload=None, timeout=15):
        recovery = self._recovery()
        url = f"{recovery['home_assistant_url'].rstrip('/')}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {recovery['home_assistant_token']}",
                "Content-Type": "application/json",
            },
        )
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return json.loads(body) if body else {}

    def _validate_settings(self):
        recovery = self._recovery()
        if not recovery.get("home_assistant_url"):
            return {
                "status": "WARN",
                "message": "Home Assistant URL is required.",
                "metadata": {"missing": ["home_assistant_url"]},
            }
        if not recovery.get("home_assistant_token"):
            return {
                "status": "WARN",
                "message": "Missing token: enter a Home Assistant long-lived access token.",
                "metadata": {"missing": ["home_assistant_token"]},
            }
        entity_id = self._entity_id(recovery)
        if not entity_id:
            return {
                "status": "WARN",
                "message": "Recovery Entity ID is required.",
                "metadata": {"missing": ["recovery_entity_id"]},
            }
        if not self._valid_entity_id(entity_id):
            return {
                "status": "FAIL",
                "message": "Invalid entity ID: enter a Home Assistant switch entity such as switch.office_router_plug.",
                "metadata": {"entity_id": entity_id},
            }
        return None

    def _recovery(self):
        recovery = dict(self.config.get("router_reboot", default={}))
        if not recovery.get("recovery_entity_id") and recovery.get("matter_entity_id"):
            recovery["recovery_entity_id"] = recovery.get("matter_entity_id")
        return recovery

    @staticmethod
    def _entity_id(recovery):
        return recovery.get("recovery_entity_id") or recovery.get("matter_entity_id")

    @staticmethod
    def _valid_entity_id(entity_id):
        return isinstance(entity_id, str) and entity_id.startswith("switch.") and len(entity_id.split(".", 1)[1]) > 0
