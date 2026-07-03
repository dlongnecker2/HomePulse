"""
Summary Cards Engine for HomePulse
===================================
Calculates KPI values for dashboard summary cards.
"""


class SummaryCardsEngine:
    """Computes KPI card values from system statuses."""

    @staticmethod
    def compute_summaries(statuses, history_service=None):
        """
        Compute summary card values.

        Parameters
        ----------
        statuses : dict with keys: internet, solar, vehicle, energy, weather
        history_service : HistoryService | None

        Returns
        -------
        dict with keys: solar, vehicle, energy, internet, weather
        """
        summaries = {
            "solar": SummaryCardsEngine._solar_summary(statuses.get("solar", {}), history_service),
            "vehicle": SummaryCardsEngine._vehicle_summary(statuses.get("vehicle", {}), history_service),
            "energy": SummaryCardsEngine._energy_summary(statuses.get("energy", {}), history_service),
            "internet": SummaryCardsEngine._internet_summary(statuses.get("internet", {}), history_service),
            "weather": SummaryCardsEngine._weather_summary(statuses.get("weather", {})),
        }
        return summaries

    @staticmethod
    def _solar_summary(solar, history_service=None):
        """Solar KPIs: peak production today, current production."""
        peak_today = None
        if history_service and solar.get("enabled"):
            try:
                points = history_service.get_metrics(
                    "solar", "current_production_kw", start_time=None, end_time=None
                )
                if points:
                    peak_today = max((p.get("value") for p in points if p.get("value") is not None), default=None)
            except Exception:
                pass

        return {
            "enabled": solar.get("enabled", False),
            "peak_today_kw": peak_today,
            "current_production_kw": solar.get("current_production_kw"),
            "production_today_kwh": solar.get("production_today_kwh"),
        }

    @staticmethod
    def _vehicle_summary(vehicle, history_service=None):
        """Vehicle KPIs: battery, range, charging power."""
        return {
            "enabled": vehicle.get("enabled", False),
            "battery_percent": vehicle.get("battery_percent"),
            "range_mi": vehicle.get("range_mi"),
            "charging_power_kw": vehicle.get("charging_power_kw"),
            "charging": vehicle.get("charging", False),
        }

    @staticmethod
    def _energy_summary(energy, history_service=None):
        """Energy KPIs: charging power, session cost."""
        return {
            "enabled": energy.get("enabled", False),
            "charging_power_kw": energy.get("power_kw"),
            "is_charging": energy.get("is_charging", False),
            "estimated_cost": energy.get("estimated_cost"),
            "session_energy_kwh": energy.get("session_energy_kwh"),
        }

    @staticmethod
    def _internet_summary(internet, history_service=None):
        """Internet KPIs: latency, uptime, packet loss."""
        return {
            "status": internet.get("status", "Unavailable"),
            "latency_ms": internet.get("latency_ms"),
            "packet_loss_percent": internet.get("packet_loss_percent"),
            "health_score": internet.get("health_score"),
        }

    @staticmethod
    def _weather_summary(weather):
        """Weather KPIs: temperature, cloud cover."""
        return {
            "enabled": weather.get("enabled", False),
            "temperature_f": weather.get("temperature_f"),
            "cloud_cover_percent": weather.get("cloud_cover_percent"),
            "condition": weather.get("condition"),
        }
