import re
import socket
import subprocess
from statistics import mean
from dataclasses import dataclass


@dataclass
class NetworkHealth:
    status: str
    score: int
    latency: float
    packet_loss: float
    dns_ok: bool
    details: str


class NetworkMonitor:
    def __init__(self, config, log):
        self.config = config
        self.log = log
        self.targets = ["1.1.1.1", "8.8.8.8"]
        self.ping_count = 5

    def ping_target(self, host):
        result = subprocess.run(
            ["ping", "-n", str(self.ping_count), host],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore"
        )

        times = []

        for line in result.stdout.splitlines():
            match = re.search(r"time[=<]\s*(\d+)ms", line, re.IGNORECASE)
            if match:
                times.append(int(match.group(1)))

        sent = self.ping_count
        received = len(times)

        packet_loss = round((sent - received) / sent * 100, 1)

        if not times:
            return {
                "host": host,
                "latency": None,
                "packet_loss": 100.0
            }

        return {
            "host": host,
            "latency": mean(times),
            "packet_loss": packet_loss
        }

    def check_dns(self):
        try:
            socket.gethostbyname("www.google.com")
            return True
        except Exception:
            return False

    def check(self):
        ping_results = [self.ping_target(target) for target in self.targets]

        valid_latencies = [
            result["latency"]
            for result in ping_results
            if result["latency"] is not None
        ]

        if valid_latencies:
            latency = round(mean(valid_latencies), 1)
        else:
            latency = 999.0

        packet_loss = max(result["packet_loss"] for result in ping_results)

        dns_ok = self.check_dns()

        latency_threshold = self.config.get("thresholds", "latency_ms")
        packet_loss_threshold = self.config.get("thresholds", "packet_loss")

        score = 100
        problems = []

        if latency >= 999:
            score -= 60
            problems.append("No ping replies")
        elif latency > latency_threshold:
            score -= 25
            problems.append(f"High latency: {latency} ms")

        if packet_loss > packet_loss_threshold:
            score -= 35
            problems.append(f"Packet loss: {packet_loss}%")

        if not dns_ok:
            score -= 30
            problems.append("DNS failed")

        score = max(score, 0)

        if score >= 90:
            status = "Healthy"
        elif score >= 60:
            status = "Degraded"
        else:
            status = "Unhealthy"

        details = "OK" if not problems else "; ".join(problems)

        return NetworkHealth(
            status=status,
            score=score,
            latency=latency,
            packet_loss=packet_loss,
            dns_ok=dns_ok,
            details=details
        )
