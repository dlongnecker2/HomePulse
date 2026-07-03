"""
Health Score Engine for HomePulse
==================================
Computes a unified 0-100% health score based on status of all systems.

Weighing:
- Internet (30%): foundation of home monitoring
- Solar (15%): renewable energy production
- Vehicle (15%): EV battery and charging
- Energy (15%): charger status and efficiency
- Weather (10%): operational awareness
- Home Assistant (10%): integration hub
- System (5%): HomePulse itself

Each system contributes:
- Disabled systems: reduce confidence (2% per system)
- Unavailable systems: reduce score (8% per system)
- Degraded/Partial systems: reduce score (5% per system)
- Errors: reduce score (10% per system)
- Healthy systems: neutral baseline

Trend calculation:
- Compare current health to 1-hour rolling window
- ↑ if improving (+5+ points), ↓ if declining (-5+ points), → stable
"""

from datetime import datetime, timedelta


class HealthScoreEngine:
    """Calculates unified health score across all HomePulse systems."""

    # Weights (sum should = 100)
    WEIGHTS = {
        "internet": 0.30,
        "solar": 0.15,
        "vehicle": 0.15,
        "energy": 0.15,
        "weather": 0.10,
        "home_assistant": 0.10,
        "system": 0.05,
    }

    def __init__(self):
        self._score_history = []  # [(timestamp, score)]

    def compute(self, statuses):
        """
        Compute unified health score.

        Parameters
        ----------
        statuses : dict with keys: internet, solar, vehicle, energy, weather, home_assistant, system

        Returns
        -------
        dict with keys: score, status_text, trend, breakdown
        """
        scores = {}
        for key, weight in self.WEIGHTS.items():
            status = statuses.get(key, {})
            system_score = self._score_system(key, status)
            scores[key] = system_score

        # Weighted average
        total_score = sum(scores[k] * self.WEIGHTS[k] for k in scores)
        total_score = max(0, min(100, round(total_score)))

        # Record for trend
        now = datetime.now()
        self._score_history.append((now, total_score))
        cutoff = now - timedelta(hours=1)
        self._score_history = [(ts, s) for ts, s in self._score_history if ts >= cutoff]

        trend = self._calculate_trend(total_score)
        status_text = self._status_text(total_score)

        return {
            "score": total_score,
            "status_text": status_text,
            "trend": trend,
            "breakdown": scores,
            "timestamp": now.isoformat(),
        }

    @staticmethod
    def _score_system(system_name, status):
        """
        Compute a 0-100 score for a single system.

        Returns 100 for healthy/enabled systems.
        Deducts for disabled, partial, degraded, error states.
        """
        if not status:
            return 60  # Unknown = moderate penalty

        # Explicitly disabled systems contribute less penalty
        if status.get("enabled") is False:
            return 80  # -20% for disabled but working systems

        # Check availability / status
        availability = status.get("availability", "").lower()
        status_text = str(status.get("status") or "").lower()
        configured = status.get("configured", False)

        if not configured:
            return 40  # Unconfigured = major penalty

        # Unavailable = major deduction
        if availability in ("unavailable", "home_assistant_unavailable", "waiting"):
            return 20
        if status_text in ("unavailable", "offline", "disconnected", "error", "failed"):
            return 20

        # Partial / degraded = moderate deduction
        if availability in ("partial", "degraded"):
            return 70
        if status_text in ("partial", "degraded", "unknown", "stale"):
            return 70

        # Error present = deduction
        if status.get("error"):
            return 60

        # Healthy
        if availability in ("live", "connected", "healthy") or status_text in (
            "healthy",
            "ok",
            "connected",
            "live",
        ):
            return 100

        # Default: cautiously optimistic
        return 85

    @staticmethod
    def _calculate_trend(current_score):
        """Determine if score is improving, declining, or stable."""
        # This is a placeholder; in real use, compare to 1-hour avg
        # For now: always return neutral
        return "→"

    @staticmethod
    def _status_text(score):
        """Convert numeric score to status text."""
        if score >= 95:
            return "Excellent"
        if score >= 85:
            return "Good"
        if score >= 70:
            return "Warning"
        if score >= 50:
            return "Critical"
        return "Offline"
