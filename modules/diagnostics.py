import smtplib
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from email.message import EmailMessage

from modules.power_adapters import KasaAdapter, MatterAdapter


@dataclass
class DiagnosticResult:
    test_name: str
    status: str
    message: str
    duration_ms: int
    timestamp: str
    metadata: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


class Diagnostics:
    def __init__(self, application):
        self.application = application
        self.log = application.log
        self.registry = {
            "smtp_test": self.smtp_test,
            "internet_ping_test": self.internet_ping_test,
            "speed_test": self.speed_test,
            "tapo_connection_test": self.tapo_connection_test,
            "tapo_power_cycle_test": self.tapo_power_cycle_test,
            "database_test": self.database_test,
            "scheduler_test": self.scheduler_test,
            "log_write_test": self.log_write_test,
        }

    def run_test(self, test_name, **kwargs):
        started = time.perf_counter()
        timestamp = str(datetime.now())
        test = self.registry.get(test_name)
        if not test:
            return self._finalize(
                DiagnosticResult(
                    test_name=test_name,
                    status="FAIL",
                    message=f"Unknown diagnostic test: {test_name}",
                    duration_ms=0,
                    timestamp=timestamp,
                ),
                started,
            )

        try:
            self._current_overrides = kwargs.get("overrides", {})
            result = test(timestamp=timestamp, **kwargs)
        except Exception as exc:
            self.log.exception(f"Diagnostic test failed unexpectedly: {test_name} - {exc}")
            result = DiagnosticResult(
                test_name=test_name,
                status="FAIL",
                message=f"{test_name} failed unexpectedly: {exc}",
                duration_ms=0,
                timestamp=timestamp,
            )
        finally:
            self._current_overrides = {}
        return self._finalize(result, started)

    def run_full_diagnostics(self, overrides=None):
        tests = [
            "database_test",
            "scheduler_test",
            "log_write_test",
            "internet_ping_test",
            "smtp_test",
            "tapo_connection_test",
            "speed_test",
        ]
        results = [self.run_test(test_name, overrides=overrides or {}) for test_name in tests]
        failed = sum(1 for result in results if result.status == "FAIL")
        warned = sum(1 for result in results if result.status == "WARN")
        status = "FAIL" if failed else "WARN" if warned else "PASS"
        summary = DiagnosticResult(
            test_name="full_diagnostics",
            status=status,
            message=f"Full diagnostics complete: {len(results) - failed - warned} pass, {warned} warn, {failed} fail",
            duration_ms=sum(result.duration_ms for result in results),
            timestamp=str(datetime.now()),
            metadata={"results": [result.to_dict() for result in results]},
        )
        self._log_result(summary)
        return summary

    def smtp_test(self, timestamp, **kwargs):
        email = dict(self.application.config.get("email", default={}))
        email_overrides = dict(kwargs.get("overrides", {}).get("email", {}))
        if not email_overrides.get("password"):
            email_overrides.pop("password", None)
        email.update(email_overrides)
        if not email.get("enabled"):
            return DiagnosticResult(
                "smtp_test",
                "WARN",
                "SMTP email is disabled in Settings.",
                0,
                timestamp,
            )

        required = ["smtp_host", "from_address", "to_address"]
        missing = [key for key in required if not email.get(key)]
        if missing:
            return DiagnosticResult(
                "smtp_test",
                "FAIL",
                f"SMTP is missing required setting(s): {', '.join(missing)}",
                0,
                timestamp,
            )

        message = EmailMessage()
        message["Subject"] = "HomePulse - SMTP Diagnostic Test"
        message["From"] = email.get("from_address", "")
        message["To"] = email.get("to_address", "")
        message.set_content(f"HomePulse SMTP diagnostic test sent at {timestamp}.")

        host = email.get("smtp_host")
        port = int(email.get("smtp_port", 587))
        with smtplib.SMTP(host, port, timeout=20) as server:
            if email.get("use_tls", True):
                server.starttls()
            if email.get("username"):
                server.login(email.get("username"), email.get("password", ""))
            server.send_message(message)

        return DiagnosticResult(
            "smtp_test",
            "PASS",
            f"SMTP test email sent to {email.get('to_address')}.",
            0,
            timestamp,
            {"host": host, "port": port},
        )

    def internet_ping_test(self, timestamp, **kwargs):
        result = self.application.network.check()
        status = "PASS" if result.status == "Healthy" else "WARN" if result.status == "Degraded" else "FAIL"
        return DiagnosticResult(
            "internet_ping_test",
            status,
            result.details,
            0,
            timestamp,
            {
                "latency": result.latency,
                "packet_loss": result.packet_loss,
                "dns_ok": result.dns_ok,
                "score": result.score,
            },
        )

    def speed_test(self, timestamp, **kwargs):
        result = self.application.speedtest.run()
        self.application.status.update_speedtest(
            download=result.download,
            upload=result.upload,
            ping=result.ping,
            server=result.server,
            last_run=result.timestamp,
        )
        self.application.db.add_speed_test(
            timestamp=result.timestamp,
            download=result.download,
            upload=result.upload,
            ping=result.ping,
            server=result.server,
        )
        return DiagnosticResult(
            "speed_test",
            "PASS",
            f"Speed test complete: {result.download} down / {result.upload} up / {result.ping} ms.",
            0,
            timestamp,
            {
                "download": result.download,
                "upload": result.upload,
                "ping": result.ping,
                "server": result.server,
            },
        )

    def tapo_connection_test(self, timestamp, **kwargs):
        return self._run_async_tapo_test(timestamp, power_cycle=False)

    def tapo_power_cycle_test(self, timestamp, confirmed=False, **kwargs):
        if not confirmed:
            return DiagnosticResult(
                "tapo_power_cycle_test",
                "WARN",
                "Tapo power-cycle test was not run because confirmation was not checked.",
                0,
                timestamp,
            )
        return self._run_async_tapo_test(timestamp, power_cycle=True)

    def database_test(self, timestamp, **kwargs):
        self.application.db.conn.execute("SELECT 1").fetchone()
        return DiagnosticResult(
            "database_test",
            "PASS",
            "SQLite connection responded successfully.",
            0,
            timestamp,
            {
                "health_checks": self.application.db.count_rows("health_checks"),
                "speed_tests": self.application.db.count_rows("speed_tests"),
                "events": self.application.db.count_rows("events"),
            },
        )

    def scheduler_test(self, timestamp, **kwargs):
        jobs = [job["name"] for job in self.application.scheduler.jobs]
        status = "PASS" if jobs else "WARN"
        message = f"{len(jobs)} scheduler job(s) registered." if jobs else "No scheduler jobs are registered."
        return DiagnosticResult(
            "scheduler_test",
            status,
            message,
            0,
            timestamp,
            {"jobs": jobs},
        )

    def log_write_test(self, timestamp, **kwargs):
        self.log.info("HomePulse diagnostic log_write_test marker")
        return DiagnosticResult(
            "log_write_test",
            "PASS",
            "Log write marker was emitted successfully.",
            0,
            timestamp,
        )

    def _run_async_tapo_test(self, timestamp, power_cycle):
        recovery = dict(self.application.config.get("router_reboot", default={}))
        recovery_overrides = dict(getattr(self, "_current_overrides", {}).get("router_reboot", {}))
        if not recovery_overrides.get("kasa_password"):
            recovery_overrides.pop("kasa_password", None)
        recovery.update(recovery_overrides)
        original = self.application.config.data.get("router_reboot")
        self.application.config.data["router_reboot"] = recovery
        try:
            adapter = self._power_diagnostic_adapter(recovery)
            power_result = adapter.cycle() if power_cycle else adapter.status()
        finally:
            self.application.config.data["router_reboot"] = original

        return DiagnosticResult(
            "tapo_power_cycle_test" if power_cycle else "tapo_connection_test",
            power_result.status,
            power_result.message,
            0,
            timestamp,
            power_result.metadata,
        )

    def _power_diagnostic_adapter(self, recovery):
        mode = recovery.get("recovery_control_mode")
        if mode == "kasa_legacy":
            return KasaAdapter(self.application.config, self.log)
        if (
            mode == "matter_bridge"
            or recovery.get("home_assistant_url")
            or recovery.get("home_assistant_token")
            or recovery.get("matter_entity_id")
        ):
            return MatterAdapter(self.application.config, self.log)
        return KasaAdapter(self.application.config, self.log)

    def _finalize(self, result, started):
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        self._log_result(result)
        return result

    def _log_result(self, result):
        message = f"{result.test_name}: {result.status} - {result.message}"
        self.log.info(f"Diagnostic {message}")
        try:
            self.application.db.add_event(
                timestamp=result.timestamp,
                event_type="diagnostic_test",
                message=message,
            )
        except Exception as exc:
            self.log.exception(f"Could not write diagnostic result to SQLite: {exc}")

    def latest_result(self):
        event = self.application.db.latest_event("diagnostic_test")
        if not event:
            return None
        test_name = event["message"].split(":", 1)[0] if ":" in event["message"] else "diagnostic_test"
        return {
            "test_name": test_name,
            "status": self._status_from_message(event["message"]),
            "timestamp": event["timestamp"],
            "message": event["message"],
        }

    @staticmethod
    def _status_from_message(message):
        if ": PASS -" in message:
            return "PASS"
        if ": WARN -" in message:
            return "WARN"
        if ": FAIL -" in message:
            return "FAIL"
        return "WARN"
