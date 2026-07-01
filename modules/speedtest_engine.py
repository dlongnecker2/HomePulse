import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime


PROVIDER_UNAVAILABLE_MESSAGE = "Speed test provider unavailable"


@dataclass
class SpeedTestResult:
    download: float | None
    upload: float | None
    ping: float | None
    server: str | None
    timestamp: str
    status: str = "PASS"
    error: str = ""
    provider: str = ""
    error_type: str = ""
    error_message: str = ""

    @property
    def success(self):
        return self.status == "PASS"

    @property
    def failed(self):
        return not self.success


class SpeedTestEngine:
    def __init__(self, log):
        self.log = log

    def run(self):
        failures = []
        ookla_path = shutil.which("speedtest")
        if ookla_path:
            result = self._run_ookla_cli(ookla_path)
            if result.success:
                return result
            failures.append(result)
        else:
            self.log.info("Ookla speedtest CLI not found in PATH; using Python speedtest provider")

        result = self._run_python_speedtest()
        if result.success:
            return result
        failures.append(result)

        return self._combined_failure(failures)

    def _run_ookla_cli(self, executable):
        provider = "ookla_cli"
        timestamp = str(datetime.now())
        self.log.info("Starting speed test using Ookla CLI")
        command = [
            executable,
            "--format=json",
            "--accept-license",
            "--accept-gdpr",
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            if completed.returncode != 0:
                stderr = (completed.stderr or completed.stdout or "").strip()
                raise RuntimeError(stderr or f"Ookla CLI exited with code {completed.returncode}")
            payload = json.loads(completed.stdout)
            download_mbps = self._bandwidth_to_mbps(payload.get("download", {}).get("bandwidth"))
            upload_mbps = self._bandwidth_to_mbps(payload.get("upload", {}).get("bandwidth"))
            ping_ms = self._round_or_none(payload.get("ping", {}).get("latency"), 1)
            server_info = payload.get("server", {}) or {}
            server = self._server_label(
                server_info.get("name") or server_info.get("host"),
                server_info.get("location") or server_info.get("country"),
            )
            timestamp = str(datetime.now())
            self.log.info(
                f"Speed test complete via Ookla CLI | Download={download_mbps} Mbps | "
                f"Upload={upload_mbps} Mbps | Ping={ping_ms} ms | Server={server}"
            )
            return SpeedTestResult(download_mbps, upload_mbps, ping_ms, server, timestamp, provider=provider)
        except subprocess.TimeoutExpired as exc:
            return self._failed_result(provider, str(datetime.now()), "timeout", "Ookla speed test timed out", exc)
        except Exception as exc:
            return self._failed_result(
                provider,
                str(datetime.now()),
                self._classify_message(str(exc), exc),
                "Ookla speed test provider failed",
                exc,
            )

    def _run_python_speedtest(self):
        provider = "python_speedtest"
        timestamp = str(datetime.now())
        try:
            import speedtest
        except ImportError as exc:
            return self._failed_result(
                provider,
                timestamp,
                "provider_error",
                "Python speedtest provider is not installed. Run: pip install speedtest-cli",
                exc,
            )

        self.log.info("Starting speed test using Python speedtest provider")
        try:
            # Speedtest.net HTTP config calls can return 403; secure=True uses HTTPS and avoids that block.
            tester = speedtest.Speedtest(secure=True)
            tester.get_best_server()
            download_bps = tester.download()
            upload_bps = tester.upload()
            results = tester.results.dict()
            download_mbps = round(download_bps / 1_000_000, 1)
            upload_mbps = round(upload_bps / 1_000_000, 1)
            ping_ms = round(results.get("ping", 0), 1)
            server_info = results.get("server", {})
            server = self._server_label(server_info.get("sponsor"), server_info.get("name"))
            timestamp = str(datetime.now())
            self.log.info(
                f"Speed test complete via Python provider | Download={download_mbps} Mbps | "
                f"Upload={upload_mbps} Mbps | Ping={ping_ms} ms | Server={server}"
            )
            return SpeedTestResult(download_mbps, upload_mbps, ping_ms, server, timestamp, provider=provider)
        except Exception as exc:
            return self._failed_result(
                provider,
                str(datetime.now()),
                self._classify_python_exception(speedtest, exc),
                "Python speedtest provider failed",
                exc,
            )

    def _combined_failure(self, failures):
        failures = [failure for failure in failures if failure and failure.failed]
        if not failures:
            return self._safe_failure("unknown", "provider_error", "No speed test provider returned a result.")
        primary = failures[-1]
        details = "; ".join(
            f"{failure.provider}: {failure.error_type} - {failure.error_message}"
            for failure in failures
        )
        self.log.warning(f"{PROVIDER_UNAVAILABLE_MESSAGE}: {details}")
        return SpeedTestResult(
            download=None,
            upload=None,
            ping=None,
            server=PROVIDER_UNAVAILABLE_MESSAGE,
            timestamp=primary.timestamp,
            status="FAIL",
            error=f"{PROVIDER_UNAVAILABLE_MESSAGE}: {details}",
            provider=primary.provider,
            error_type=primary.error_type,
            error_message=primary.error_message,
        )

    def _failed_result(self, provider, timestamp, error_type, message, exc):
        error_message = self._user_message(error_type, exc, message)
        concise = f"{PROVIDER_UNAVAILABLE_MESSAGE} ({provider}/{error_type}): {error_message}"
        self.log.debug(concise, exc_info=True)
        return SpeedTestResult(
            download=None,
            upload=None,
            ping=None,
            server=PROVIDER_UNAVAILABLE_MESSAGE,
            timestamp=timestamp,
            status="FAIL",
            error=concise,
            provider=provider,
            error_type=error_type,
            error_message=error_message,
        )

    def _safe_failure(self, provider, error_type, message):
        timestamp = str(datetime.now())
        return SpeedTestResult(
            download=None,
            upload=None,
            ping=None,
            server=PROVIDER_UNAVAILABLE_MESSAGE,
            timestamp=timestamp,
            status="FAIL",
            error=f"{PROVIDER_UNAVAILABLE_MESSAGE}: {message}",
            provider=provider,
            error_type=error_type,
            error_message=message,
        )

    @staticmethod
    def _classify_python_exception(speedtest_module, exc):
        config_error = getattr(speedtest_module, "ConfigRetrievalError", None)
        best_server_error = getattr(speedtest_module, "SpeedtestBestServerFailure", None)
        if config_error and isinstance(exc, config_error):
            return "provider_blocked" if "403" in str(exc) else "provider_error"
        if best_server_error and isinstance(exc, best_server_error):
            return "no_test_server"
        if isinstance(exc, (TimeoutError, OSError)) and "timed out" in str(exc).lower():
            return "timeout"
        return SpeedTestEngine._classify_message(str(exc), exc)

    @staticmethod
    def _classify_message(message, exc=None):
        normalized = str(message or "").lower()
        if "403" in normalized or "forbidden" in normalized:
            return "provider_blocked"
        if "unable to connect to servers to test latency" in normalized or "best server" in normalized:
            return "no_test_server"
        if "timed out" in normalized or "timeout" in normalized or isinstance(exc, TimeoutError):
            return "timeout"
        return "provider_error"

    @staticmethod
    def _user_message(error_type, exc, fallback):
        if error_type == "provider_blocked":
            return "The speed test provider blocked the request (HTTP 403). Internet Health may still be healthy."
        if error_type == "no_test_server":
            return "The speed test provider could not find a reachable test server."
        if error_type == "timeout":
            return "The speed test provider timed out."
        detail = str(exc).strip()
        return f"{fallback}: {detail}" if detail else fallback

    @staticmethod
    def _bandwidth_to_mbps(value):
        if value is None:
            return None
        return round(float(value) * 8 / 1_000_000, 1)

    @staticmethod
    def _round_or_none(value, digits):
        if value is None:
            return None
        return round(float(value), digits)

    @staticmethod
    def _server_label(primary, secondary):
        primary = primary or "Unknown"
        secondary = secondary or "Unknown"
        return f"{primary} - {secondary}"
