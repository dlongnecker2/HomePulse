"""
Timeline Service for HomePulse
===============================
Records and retrieves events from throughout the home monitoring lifecycle.
Supports extensibility — any module can record events without knowing storage details.

Architecture:
- In-memory ring buffer (max 500 events) for fast Home page access
- Optional database persistence for long-term history
- De-duplication to prevent event spam
- Queryable by category, severity, time range
- Thread-safe append operations
- Scrolls newest first
"""

from datetime import datetime, timedelta
from collections import deque
from threading import Lock
import hashlib
import uuid


class TimelineService:
    """
    In-memory event timeline for HomePulse observational events.
    """

    # Event categories
    CAT_SYSTEM = "system"
    CAT_INTERNET = "internet"
    CAT_SOLAR = "solar"
    CAT_VEHICLE = "vehicle"
    CAT_ENERGY = "energy"
    CAT_WEATHER = "weather"
    CAT_RECOVERY = "recovery"
    CAT_HOME_ASSISTANT = "home_assistant"
    CAT_LIGHTING = "lighting"
    CAT_NOTIFICATION = "notification"

    # Severity levels (lower value = more severe)
    SEV_CRITICAL = "critical"  # System down, immediate attention
    SEV_WARNING = "warning"  # Issue requires investigation
    SEV_INFO = "info"  # Normal operational event
    SEV_SUCCESS = "success"  # Positive event (e.g., connection restored)

    def __init__(self, max_events=500, dedup_minutes=10):
        self.max_events = max_events
        self.dedup_minutes = dedup_minutes
        self._events = deque(maxlen=max_events)
        self._dedup_hashes = {}  # {hash: last_timestamp} for de-duplication
        self._lock = Lock()

    def record_event(self, category, title, description="", severity="info", timestamp=None, source="system", check_dedup=True, metadata=None):
        """
        Record an event.

        Parameters
        ----------
        category : str
            Event category (use CAT_* constants)
        title : str
            Short event title (e.g., "Internet Down")
        description : str
            Optional detailed description
        severity : str
            Severity level (use SEV_* constants)
        timestamp : datetime | None
            Event timestamp; defaults to now()
        source : str
            Source module or component
        check_dedup : bool
            Whether to check de-duplication (default True)
        metadata : dict | None
            Additional event metadata

        Returns
        -------
        dict : The recorded event, or None if de-duplicated
        """
        if timestamp is None:
            timestamp = datetime.now()
        elif isinstance(timestamp, str):
            try:
                timestamp = datetime.fromisoformat(timestamp.replace(" ", "T"))
            except (ValueError, TypeError):
                timestamp = datetime.now()

        # De-duplication check
        if check_dedup:
            dedup_key = f"{category}:{title}:{description}".lower()
            dedup_hash = hashlib.md5(dedup_key.encode()).hexdigest()
            now = datetime.now()

            with self._lock:
                last_time = self._dedup_hashes.get(dedup_hash)
                if last_time and (now - last_time).total_seconds() < self.dedup_minutes * 60:
                    return None  # De-duplicated

                self._dedup_hashes[dedup_hash] = now

        event = {
            "id": str(uuid.uuid4()),
            "category": str(category).strip(),
            "title": str(title).strip(),
            "description": str(description).strip(),
            "severity": str(severity).strip().lower(),
            "timestamp": timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp),
            "source": str(source).strip(),
            "metadata": metadata or {},
        }

        with self._lock:
            self._events.append(event)

        # Optional: persist to database (feature for future)
        # For now, in-memory ring buffer is sufficient

        return event

    def set_database(self, database):
        """Reserve for future database persistence."""
        pass

    def get_events(self, category=None, severity=None, limit=100, hours_back=24):
        """
        Retrieve events, newest first.

        Parameters
        ----------
        category : str | None
            Filter by category; None = all
        severity : str | list | None
            Filter by severity; None = all
        limit : int
            Maximum events to return
        hours_back : int
            Only include events from the past N hours

        Returns
        -------
        list of dict : Events in reverse chronological order (newest first)
        """
        cutoff = datetime.now() - timedelta(hours=hours_back)
        severities = {severity} if isinstance(severity, str) else set(severity or [])

        with self._lock:
            results = []
            for event in reversed(list(self._events)):
                if len(results) >= limit:
                    break

                try:
                    ts = datetime.fromisoformat(
                        event["timestamp"].replace("Z", "+00:00").replace(" ", "T")
                    )
                except (ValueError, TypeError, AttributeError):
                    ts = datetime.now()

                if ts < cutoff:
                    continue
                if category and event.get("category") != category:
                    continue
                if severities and event.get("severity") not in severities:
                    continue

                results.append(event)

        return results

    def get_summary(self, hours_back=24):
        """
        Get a summary of all events in the past N hours.

        Returns
        -------
        dict with keys: total, by_category, by_severity, most_recent
        """
        events = self.get_events(limit=10000, hours_back=hours_back)
        by_category = {}
        by_severity = {}

        for event in events:
            cat = event.get("category", "unknown")
            sev = event.get("severity", "info")
            by_category[cat] = by_category.get(cat, 0) + 1
            by_severity[sev] = by_severity.get(sev, 0) + 1

        return {
            "total": len(events),
            "by_category": by_category,
            "by_severity": by_severity,
            "most_recent": events[0] if events else None,
            "older_cutoff_hours": hours_back,
        }

    def clear(self):
        """Clear all events (for testing)."""
        with self._lock:
            self._events.clear()

    def event_count(self):
        """Return current event count."""
        with self._lock:
            return len(self._events)
