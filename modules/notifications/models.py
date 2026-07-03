"""
Notification models for HomePulse.
"""

from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Optional, Dict, Any
import uuid


@dataclass
class Notification:
    """
    User-facing notification model.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    title: str = ""
    message: str = ""
    severity: str = "info"  # critical, warning, info, success
    category: str = "system"  # system, internet, solar, vehicle, energy, weather, home_assistant
    source: str = "system"  # module that triggered the notification
    read: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @staticmethod
    def from_dict(data):
        """Create from dictionary."""
        return Notification(**{k: v for k, v in data.items() if k in Notification.__dataclass_fields__})
