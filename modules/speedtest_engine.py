from dataclasses import dataclass
from datetime import datetime


@dataclass
class SpeedTestResult:
    download: float
    upload: float
    ping: float
    server: str
    timestamp: str


class SpeedTestEngine:
    def __init__(self, log):
        self.log = log

    def run(self):
        try:
            import speedtest
        except ImportError as exc:
            raise RuntimeError(
                "speedtest-cli is not installed. Run: pip install speedtest-cli"
            ) from exc

        self.log.info("Starting speed test")

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

        return SpeedTestResult(
            download=download_mbps,
            upload=upload_mbps,
            ping=ping_ms,
            server=server,
            timestamp=timestamp
        )
