"""
Notification Manager for HomePulse.
Central service for managing notifications from timeline events and system alerts.

Features:
- In-memory notification storage with max capacity
- De-duplication to avoid spam
- Mark as read / clear operations
- Generate notifications from critical/warning events
- Optional persistence to database
"""

from datetime import datetime, timedelta
from collections import deque
from threading import Lock
from typing import Optional, List, Dict, Any
import hashlib

from modules.notifications.models import Notification


class NotificationManager:
    """
    Central notification management service.
    """

    def __init__(self, max_notifications=200, dedup_minutes=30):
        """
        Initialize notification manager.

        Parameters
        ----------
        max_notifications : int
            Maximum notifications to keep in memory
        dedup_minutes : int
            De-duplication window (suppress same notification within this time)
        """
        self.max_notifications = max_notifications
        self.dedup_minutes = dedup_minutes
        self._notifications = deque(maxlen=max_notifications)
        self._dedup_hashes = {}  # {hash: last_timestamp} for de-duplication
        self._lock = Lock()

    def add_notification(
        self,
        title: str,
        message: str = "",
        severity: str = "info",
        category: str = "system",
        source: str = "system",
        metadata: Optional[Dict[str, Any]] = None,
        check_dedup: bool = True,
    ) -> Optional[Notification]:
        """
        Add a notification.

        Parameters
        ----------
        title : str
            Notification title
        message : str
            Notification message
        severity : str
            Severity level (critical, warning, info, success)
        category : str
            Category (system, internet, solar, vehicle, energy, weather, home_assistant)
        source : str
            Source module
        metadata : dict | None
            Additional metadata
        check_dedup : bool
            Whether to check de-duplication

        Returns
        -------
        Notification or None if de-duplicated
        """
        # De-duplication check
        if check_dedup:
            dedup_key = f"{category}:{title}:{message}".lower()
            dedup_hash = hashlib.md5(dedup_key.encode()).hexdigest()
            now = datetime.now()

            with self._lock:
                last_time = self._dedup_hashes.get(dedup_hash)
                if last_time and (now - last_time).total_seconds() < self.dedup_minutes * 60:
                    return None  # De-duplicated

                self._dedup_hashes[dedup_hash] = now

        notification = Notification(
            title=title,
            message=message,
            severity=severity,
            category=category,
            source=source,
            metadata=metadata or {},
        )

        with self._lock:
            self._notifications.append(notification)

        return notification

    def get_notifications(
        self,
        limit: int = 50,
        unread_only: bool = False,
        severity: Optional[str] = None,
        hours_back: int = 24,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve notifications, newest first.

        Parameters
        ----------
        limit : int
            Maximum notifications to return
        unread_only : bool
            Only unread notifications
        severity : str | None
            Filter by severity (critical, warning, info, success)
        hours_back : int
            Only include notifications from past N hours

        Returns
        -------
        list of dict : Notifications in reverse chronological order
        """
        cutoff = datetime.now() - timedelta(hours=hours_back)
        results = []

        with self._lock:
            for notif in reversed(list(self._notifications)):
                if len(results) >= limit:
                    break

                try:
                    ts = datetime.fromisoformat(notif.timestamp.replace("Z", "+00:00").replace(" ", "T"))
                except (ValueError, TypeError, AttributeError):
                    ts = datetime.now()

                if ts < cutoff:
                    continue
                if unread_only and notif.read:
                    continue
                if severity and notif.severity != severity:
                    continue

                results.append(notif.to_dict())

        return results

    def get_unread_count(self) -> int:
        """Get count of unread notifications."""
        with self._lock:
            return sum(1 for n in self._notifications if not n.read)

    def mark_read(self, notification_id: str) -> bool:
        """
        Mark a notification as read.

        Returns
        -------
        bool : True if found and updated
        """
        with self._lock:
            for notif in self._notifications:
                if notif.id == notification_id:
                    notif.read = True
                    return True
        return False

    def mark_all_read(self) -> int:
        """
        Mark all notifications as read.

        Returns
        -------
        int : Count of updated notifications
        """
        count = 0
        with self._lock:
            for notif in self._notifications:
                if not notif.read:
                    notif.read = True
                    count += 1
        return count

    def clear(self) -> int:
        """
        Clear all notifications.

        Returns
        -------
        int : Count of cleared notifications
        """
        with self._lock:
            count = len(self._notifications)
            self._notifications.clear()
            self._dedup_hashes.clear()
        return count

    def notification_count(self) -> int:
        """Total notification count."""
        with self._lock:
            return len(self._notifications)

    def from_timeline_event(
        self,
        event: Dict[str, Any],
        severity_threshold: str = "warning",
    ) -> Optional[Notification]:
        """
        Generate a notification from a timeline event.

        Only creates notifications for critical/warning events.

        Parameters
        ----------
        event : dict
            Timeline event
        severity_threshold : str
            Minimum severity to create notification (warning, critical)

        Returns
        -------
        Notification or None
        """
        severity_order = {"critical": 0, "warning": 1, "info": 2, "success": 3}
        event_severity_level = severity_order.get(event.get("severity"), 3)
        threshold_level = severity_order.get(severity_threshold, 1)

        if event_severity_level > threshold_level:
            return None  # Event doesn't meet threshold

        return self.add_notification(
            title=event.get("title", "Event"),
            message=event.get("description", ""),
            severity=event.get("severity", "info"),
            category=event.get("category", "system"),
            source=event.get("source", "timeline"),
            metadata={"timeline_event_id": event.get("id")},
        )
