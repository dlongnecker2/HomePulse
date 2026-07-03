"""
Alert Manager for HomePulse
============================
Detects active issues and generates alerts.

Alert types:
- Internet: latency high, packet loss, down, DNS issues
- Solar: production below expected, offline
- Vehicle: battery low, charging issues, offline
- Energy: charger offline, cost anomaly
- Weather: alerts (future)
- Home Assistant: connection issues
- System: disk space, database issues (future)
"""


class AlertManager:
    """Detects and manages active alerts."""

    # Alert severity thresholds
    LATENCY_WARNING_MS = 100
    LATENCY_CRITICAL_MS = 300
    PACKET_LOSS_WARNING = 2.0
    PACKET_LOSS_CRITICAL = 10.0
    BATTERY_LOW_PERCENT = 20

    def __init__(self, log=None):
        self.log = log or type("NullLogger", (), {"warning": lambda *a, **k: None})()

    def detect_alerts(self, statuses):
        """
        Detect active alerts across all systems.

        Parameters
        ----------
        statuses : dict with keys: internet, solar, vehicle, energy, weather, home_assistant

        Returns
        -------
        list of dicts with keys: severity, title, description, system, timestamp
        """
        alerts = []

        # Internet alerts
        internet = statuses.get("internet", {})
        if internet.get("status") == "Unhealthy":
            alerts.append(self._alert("critical", "Internet Down", "Internet connectivity lost.", "internet"))
        elif internet.get("status") == "Degraded":
            latency = internet.get("latency_ms")
            packet_loss = internet.get("packet_loss_percent")
            if latency and latency > self.LATENCY_CRITICAL_MS:
                alerts.append(
                    self._alert("critical", "High Internet Latency", f"{latency}ms latency detected.", "internet")
                )
            elif latency and latency > self.LATENCY_WARNING_MS:
                alerts.append(
                    self._alert("warning", "Elevated Internet Latency", f"{latency}ms latency detected.", "internet")
                )
            if packet_loss and packet_loss > self.PACKET_LOSS_CRITICAL:
                alerts.append(
                    self._alert("critical", "Packet Loss Critical", f"{packet_loss:.1f}% packet loss.", "internet")
                )
            elif packet_loss and packet_loss > self.PACKET_LOSS_WARNING:
                alerts.append(
                    self._alert("warning", "Packet Loss Detected", f"{packet_loss:.1f}% packet loss.", "internet")
                )

        # Home Assistant alerts
        ha = statuses.get("home_assistant", {})
        if ha.get("status") == "Unavailable" or not ha.get("enabled"):
            alerts.append(
                self._alert("critical", "Home Assistant Offline", "Home Assistant connection lost.", "home_assistant")
            )

        # Solar alerts
        solar = statuses.get("solar", {})
        if solar.get("enabled") and solar.get("status") == "Unavailable":
            alerts.append(self._alert("warning", "Solar Production Offline", "Solar data unavailable.", "solar"))

        # Vehicle alerts
        vehicle = statuses.get("vehicle", {})
        if vehicle.get("enabled"):
            battery = vehicle.get("battery_percent")
            if battery is not None and battery < self.BATTERY_LOW_PERCENT:
                alerts.append(
                    self._alert("warning", "Vehicle Battery Low", f"Battery at {battery}%.", "vehicle")
                )
            if vehicle.get("availability") == "home_assistant_unavailable":
                alerts.append(
                    self._alert("warning", "Vehicle Data Unavailable", "OnStar/Home Assistant offline.", "vehicle")
                )

        # Energy (ChargePoint) alerts
        energy = statuses.get("energy", {})
        if energy.get("enabled") and energy.get("status") == "Unavailable":
            alerts.append(self._alert("warning", "ChargePoint Offline", "ChargePoint data unavailable.", "energy"))

        # Weather alerts (future)
        weather = statuses.get("weather", {})
        if weather.get("enabled"):
            condition = str(weather.get("condition", "")).lower()
            if any(w in condition for w in ("severe", "warning", "tornado", "blizzard")):
                alerts.append(
                    self._alert("warning", "Weather Warning", f"Severe weather: {weather.get('condition')}", "weather")
                )

        return alerts

    @staticmethod
    def _alert(severity, title, description, system):
        """Create alert dict."""
        from datetime import datetime

        return {
            "severity": severity,
            "title": title,
            "description": description,
            "system": system,
            "timestamp": datetime.now().isoformat(),
        }

    @staticmethod
    def severity_priority(severity):
        """Return numeric priority for sorting (lower = higher priority)."""
        priority = {"critical": 0, "warning": 1, "info": 2}
        return priority.get(severity, 99)
