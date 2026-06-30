from dataclasses import dataclass
from datetime import datetime


@dataclass
class SpeedTestResult:
    download: float | None
    upload: float | None
    ping: float | None
    server: str | None
    timestamp: str
    status: str = "PASS"
    error: str = ""

    @property
    def failed(self):
        return self.status != "PASS"


class SpeedTestEngine:
    def __init__(self, log):
        self.log = log

    def run(self):
        timestamp = str(datetime.now())
        try:
            import speedtest
        except ImportError as exc:
            return self._failed_result(
                timestamp,
                "speedtest-cli is not installed. Run: pip install speedtest-cli",
                exc,
            )

        self.log.info("Starting speed test")
        config_error = getattr(speedtest, "ConfigRetrievalError", None)
        speedtest_error = getattr(speedtest, "SpeedtestException", None)
        config_errors = tuple(error for error in (config_error,) if error is not None)
        speedtest_errors = tuple(error for error in (speedtest_error,) if error is not None) + (
            OSError,
            TimeoutError,
        )
        try:
            tester = speedtest.Speedtest()
            tester.get_best_server()
            download_bps = tester.download()
            upload_bps = tester.upload()
            results = tester.results.dict()
            download_mbps = round(download_bps / 1_000_000, 1)
            upload_mbps = round(upload_bps / 1_000_000, 1)
            ping_ms = round(results.get("ping", 0), 1)
            server_info = results.get("server", {})
            server = f"{server_info.get('sponsor', 'Unknown')} - {server_info.get('name', 'Unknown')}"
            timestamp = str(datetime.now())
            self.log.info(
                f"Speed test complete | Download={download_mbps} Mbps | "
                f"Upload={upload_mbps} Mbps | Ping={ping_ms} ms | Server={server}"
            )
            return SpeedTestResult(download_mbps, upload_mbps, ping_ms, server, timestamp)
        except config_errors as exc:
            return self._failed_result(str(datetime.now()), "Speed test config retrieval failed", exc)
        except speedtest_errors as exc:
            return self._failed_result(str(datetime.now()), "Speed test provider failed", exc)
        except Exception as exc:
            return self._failed_result(str(datetime.now()), "Speed test failed unexpectedly", exc)

    def _failed_result(self, timestamp, message, exc):
        detail = f"{message}: {type(exc).__name__}: {exc}"
        self.log.exception(detail)
        return SpeedTestResult(
            download=None,
            upload=None,
            ping=None,
            server="Unavailable",
            timestamp=timestamp,
            status="FAIL",
            error=detail,
        )
