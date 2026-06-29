from datetime import datetime
from threading import Lock


class StatusManager:
    def __init__(self):
        now = str(datetime.now())
        self._lock = Lock()
        self._status = {
            "app_name": "HomePulse",
            "app_subtitle": "Home Reliability Dashboard",
            "version": "2.8.0",
            "internet": {
                "status": "Starting",
                "score": None,
                "latency": None,
                "packet_loss": None,
                "dns_ok": None,
                "details": "Application starting",
                "last_check": None,
            },
            "speedtest": {
                "download": None,
                "upload": None,
                "ping": None,
                "server": None,
                "last_run": None,
            },
            "router": {
                "status": "Monitoring",
                "last_reboot": None,
                "reboot_count_today": 0,
            },
            "system": {
                "started_at": now,
                "last_update": now,
            },
        }

    def update_internet(self, status, score, latency, packet_loss, dns_ok, details, last_check):
        with self._lock:
            self._status["internet"].update({
                "status": status,
                "score": score,
                "latency": latency,
                "packet_loss": packet_loss,
                "dns_ok": dns_ok,
                "details": details,
                "last_check": last_check,
            })
            self._status["system"]["last_update"] = str(datetime.now())

    def update_speedtest(self, download, upload, ping, server, last_run):
        with self._lock:
            self._status["speedtest"].update({
                "download": download,
                "upload": upload,
                "ping": ping,
                "server": server,
                "last_run": last_run,
            })
            self._status["system"]["last_update"] = str(datetime.now())

    def get(self):
        with self._lock:
            return {
                "app_name": self._status["app_name"],
                "app_subtitle": self._status["app_subtitle"],
                "version": self._status["version"],
                "internet": dict(self._status["internet"]),
                "speedtest": dict(self._status["speedtest"]),
                "router": dict(self._status["router"]),
                "system": dict(self._status["system"]),
            }
