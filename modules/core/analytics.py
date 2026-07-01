"""
Analytics and Insights Service for HomePulse.

Generates simple, rule-based insights from current status and history data.
All insights are deterministic and safe - no external services or AI.
"""

from datetime import datetime, timedelta
from threading import Lock


class Insight:
    """Represents a single insight."""

    def __init__(self, category, title, description, severity="info", timestamp=None):
        """
        Initialize an insight.

        Args:
            category: Category of insight (system, internet, solar, vehicle, energy, weather)
            title: Short title for the insight
            description: Longer description
            severity: info, warning, or critical
            timestamp: When this insight was generated (defaults to now)
        """
        self.category = category
        self.title = title
        self.description = description
        self.severity = severity
        self.timestamp = timestamp or datetime.now()

    def to_dict(self):
        """Convert insight to dictionary."""
        return {
            "category": self.category,
            "title": self.title,
            "description": self.description,
            "severity": self.severity,
            "timestamp": self.timestamp.isoformat(),
        }


class AnalyticsService:
    """Generate insights from application state."""

    def __init__(self, application, log):
        """
        Initialize analytics service.

        Args:
            application: The Application instance
            log: Logger instance
        """
        self.application = application
        self.log = log
        self._lock = Lock()
        self._last_insights = []
        self._last_insights_time = None

    def generate_insights(self, max_insights=5):
        """
        Generate current insights from application state.

        Args:
            max_insights: Maximum number of insights to return

        Returns:
            List of Insight objects (up to max_insights, sorted by severity)
        """
        with self._lock:
            insights = []

            # Internet insights
            internet_insights = self._internet_insights()
            insights.extend(internet_insights)

            # Solar insights
            solar_insights = self._solar_insights()
            insights.extend(solar_insights)

            # Energy/ChargePoint insights
            energy_insights = self._energy_insights()
            insights.extend(energy_insights)

            # Vehicle insights
            vehicle_insights = self._vehicle_insights()
            insights.extend(vehicle_insights)

            # Weather insights
            weather_insights = self._weather_insights()
            insights.extend(weather_insights)

            # System insights
            system_insights = self._system_insights()
            insights.extend(system_insights)

            # Sort by severity (critical > warning > info) and then by timestamp (newest first)
            severity_order = {"critical": 0, "warning": 1, "info": 2}
            insights.sort(
                key=lambda x: (severity_order.get(x.severity, 3), -x.timestamp.timestamp())
            )

            # Return top N insights
            self._last_insights = insights[:max_insights]
            self._last_insights_time = datetime.now()
            return self._last_insights

    def get_insights(self, max_insights=5):
        """
        Get current insights (cached for up to 1 minute).

        Args:
            max_insights: Maximum number of insights to return

        Returns:
            List of Insight objects
        """
        with self._lock:
            # Regenerate if cache is stale (older than 1 minute)
            if (
                self._last_insights_time is None
                or (datetime.now() - self._last_insights_time).total_seconds() > 60
            ):
                return self.generate_insights(max_insights)
            return self._last_insights[:max_insights]

    # Internet insights
    def _internet_insights(self):
        """Generate internet-related insights."""
        insights = []
        try:
            status = self.application.status.get()
            internet = status.get("internet", {})

            if internet.get("status") == "Unhealthy":
                insights.append(
                    Insight(
                        "internet",
                        "Internet connection unhealthy",
                        f"Health status is degraded. {internet.get('details', 'Check internet connection.')}",
                        severity="critical",
                    )
                )
            elif internet.get("status") == "Degraded":
                insights.append(
                    Insight(
                        "internet",
                        "Internet connection degraded",
                        f"Performance is below expected levels. {internet.get('details', '')}",
                        severity="warning",
                    )
                )

            # Latency insight
            latency = internet.get("latency")
            if latency is not None and isinstance(latency, (int, float)):
                if latency > 100:
                    insights.append(
                        Insight(
                            "internet",
                            "High latency detected",
                            f"Latency is {latency}ms, which may affect interactive services.",
                            severity="warning",
                        )
                    )
                elif latency > 50:
                    insights.append(
                        Insight(
                            "internet",
                            "Elevated latency",
                            f"Latency is {latency}ms, slightly higher than typical.",
                            severity="info",
                        )
                    )

            # Packet loss insight
            packet_loss = internet.get("packet_loss")
            if packet_loss is not None and isinstance(packet_loss, (int, float)):
                if packet_loss > 5:
                    insights.append(
                        Insight(
                            "internet",
                            "Packet loss detected",
                            f"Packet loss is {packet_loss}%, which may cause connection issues.",
                            severity="warning",
                        )
                    )
                elif packet_loss > 0:
                    insights.append(
                        Insight(
                            "internet",
                            "Minor packet loss",
                            f"Packet loss is {packet_loss}%, which is generally acceptable.",
                            severity="info",
                        )
                    )
        except Exception as e:
            self.log.debug(f"Error generating internet insights: {e}")

        return insights

    # Solar insights
    def _solar_insights(self):
        """Generate solar-related insights."""
        insights = []
        try:
            solar_status = self.application.solar.get_status()

            if not solar_status.get("enabled"):
                return insights

            # Production insight
            power_now = solar_status.get("power_now")
            if power_now is not None and isinstance(power_now, (int, float)):
                if power_now > 100:
                    insights.append(
                        Insight(
                            "solar",
                            "Solar production active",
                            f"Currently generating {power_now}W of power.",
                            severity="info",
                        )
                    )
                elif power_now == 0:
                    # Check if it's nighttime or cloudy
                    weather_status = self.application.weather.get_status()
                    cloud_cover = weather_status.get("cloud_cover")

                    if cloud_cover and cloud_cover > 80:
                        insights.append(
                            Insight(
                                "solar",
                                "Solar production blocked by clouds",
                                f"Cloud cover is {cloud_cover}%, reducing solar production.",
                                severity="info",
                            )
                        )
                    else:
                        insights.append(
                            Insight(
                                "solar",
                                "Solar production inactive",
                                "No solar production at this time (night or minimal light).",
                                severity="info",
                            )
                        )

            # Daily production insight
            energy_today = solar_status.get("energy_today")
            if energy_today is not None and isinstance(energy_today, (int, float)):
                if energy_today > 0:
                    insights.append(
                        Insight(
                            "solar",
                            "Solar production today",
                            f"Generated {energy_today} kWh so far today.",
                            severity="info",
                        )
                    )
        except Exception as e:
            self.log.debug(f"Error generating solar insights: {e}")

        return insights

    # Energy/ChargePoint insights
    def _energy_insights(self):
        """Generate energy and ChargePoint-related insights."""
        insights = []
        try:
            energy_status = self.application.energy.get_status()

            if not energy_status.get("enabled"):
                return insights

            # ChargePoint charging state
            chargepoint = energy_status.get("chargepoint", {})
            if chargepoint.get("enabled"):
                session_active = chargepoint.get("session_active", False)
                if session_active:
                    battery_level = chargepoint.get("battery_level")
                    if battery_level is not None:
                        insights.append(
                            Insight(
                                "energy",
                                "ChargePoint session active",
                                f"Vehicle charging in progress. Battery: {battery_level}%",
                                severity="info",
                            )
                        )
                    else:
                        insights.append(
                            Insight(
                                "energy",
                                "ChargePoint session active",
                                "Vehicle charging in progress.",
                                severity="info",
                            )
                        )
                else:
                    insights.append(
                        Insight(
                            "energy",
                            "ChargePoint idle",
                            "No active charging session.",
                            severity="info",
                        )
                    )

            # Home energy consumption
            power_consumption = energy_status.get("power_consumption")
            if power_consumption is not None and isinstance(power_consumption, (int, float)):
                if power_consumption > 5000:
                    insights.append(
                        Insight(
                            "energy",
                            "High power consumption",
                            f"Currently consuming {power_consumption}W.",
                            severity="warning",
                        )
                    )
        except Exception as e:
            self.log.debug(f"Error generating energy insights: {e}")

        return insights

    # Vehicle insights
    def _vehicle_insights(self):
        """Generate vehicle-related insights."""
        insights = []
        try:
            vehicle_status = self.application.vehicle.get_status()

            if not vehicle_status.get("enabled"):
                return insights

            battery_level = vehicle_status.get("battery_level")
            if battery_level is not None and isinstance(battery_level, (int, float)):
                battery_threshold = 20  # Default threshold
                config_threshold = self.application.config.get("vehicle", "battery_warning_threshold")
                if config_threshold:
                    battery_threshold = int(config_threshold)

                if battery_level < battery_threshold:
                    insights.append(
                        Insight(
                            "vehicle",
                            "Vehicle battery low",
                            f"Battery level is {battery_level}%, below threshold of {battery_threshold}%.",
                            severity="warning",
                        )
                    )
                elif battery_level > 90:
                    insights.append(
                        Insight(
                            "vehicle",
                            "Vehicle battery charged",
                            f"Battery level is {battery_level}%.",
                            severity="info",
                        )
                    )

            # Charging state
            is_charging = vehicle_status.get("is_charging", False)
            if is_charging:
                insights.append(
                    Insight(
                        "vehicle",
                        "Vehicle charging",
                        "Vehicle is currently charging.",
                        severity="info",
                    )
                )
        except Exception as e:
            self.log.debug(f"Error generating vehicle insights: {e}")

        return insights

    # Weather insights
    def _weather_insights(self):
        """Generate weather-related insights."""
        insights = []
        try:
            weather_status = self.application.weather.get_status()

            if not weather_status.get("enabled"):
                return insights

            # Cloud cover insight
            cloud_cover = weather_status.get("cloud_cover")
            if cloud_cover is not None and isinstance(cloud_cover, (int, float)):
                if cloud_cover > 80:
                    insights.append(
                        Insight(
                            "weather",
                            "Heavy cloud cover",
                            f"Cloud cover is {cloud_cover}%. This may reduce solar production.",
                            severity="info",
                        )
                    )

            # Extreme weather
            temperature = weather_status.get("temperature")
            if temperature is not None and isinstance(temperature, (int, float)):
                if temperature > 35:
                    insights.append(
                        Insight(
                            "weather",
                            "Very hot weather",
                            f"Temperature is {temperature}°C. High temperature detected.",
                            severity="warning",
                        )
                    )
                elif temperature < 0:
                    insights.append(
                        Insight(
                            "weather",
                            "Freezing temperature",
                            f"Temperature is {temperature}°C. Below freezing.",
                            severity="warning",
                        )
                    )

            # Wind insight
            wind_speed = weather_status.get("wind_speed")
            if wind_speed is not None and isinstance(wind_speed, (int, float)):
                if wind_speed > 50:
                    insights.append(
                        Insight(
                            "weather",
                            "High wind speed",
                            f"Wind speed is {wind_speed} km/h. Strong winds detected.",
                            severity="warning",
                        )
                    )
        except Exception as e:
            self.log.debug(f"Error generating weather insights: {e}")

        return insights

    # System insights
    def _system_insights(self):
        """Generate system-related insights."""
        insights = []
        try:
            status = self.application.status.get()
            system = status.get("system", {})

            # Uptime insight
            started_at_str = system.get("started_at")
            if started_at_str:
                try:
                    started_at = datetime.fromisoformat(started_at_str)
                    uptime = datetime.now() - started_at
                    if uptime.total_seconds() < 300:  # Less than 5 minutes
                        insights.append(
                            Insight(
                                "system",
                                "HomePulse recently started",
                                "Application started less than 5 minutes ago. Data collection in progress.",
                                severity="info",
                            )
                        )
                except Exception:
                    pass

            # Check for recent router reboots
            router = status.get("router", {})
            reboot_count = router.get("reboot_count_today", 0)
            if reboot_count > 3:
                insights.append(
                    Insight(
                        "system",
                        "Multiple router reboots today",
                        f"Router has rebooted {reboot_count} times today. This may indicate hardware issues.",
                        severity="warning",
                    )
                )
            elif reboot_count > 0:
                insights.append(
                    Insight(
                        "system",
                        "Router reboot today",
                        f"Router rebooted {reboot_count} time(s) today.",
                        severity="info",
                    )
                )
        except Exception as e:
            self.log.debug(f"Error generating system insights: {e}")

        return insights
