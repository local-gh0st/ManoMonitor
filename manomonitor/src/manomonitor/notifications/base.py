"""Base notification interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from manomonitor.database.models import Asset


@dataclass
class NotificationResult:
    """Result of a notification attempt."""

    success: bool
    notifier_type: str
    message: Optional[str] = None
    error: Optional[str] = None


@dataclass
class NotificationPayload:
    """Data to be sent in a notification."""

    device_name: str
    mac_address: str
    signal_strength: Optional[int]
    event_type: str  # "detected", "new_device", etc.
    timestamp: str

    @classmethod
    def from_asset(cls, asset: Asset, event_type: str = "detected") -> "NotificationPayload":
        """Create a payload from an Asset."""
        from datetime import datetime

        return cls(
            device_name=asset.display_name,
            mac_address=asset.mac_address,
            signal_strength=asset.last_signal_strength,
            event_type=event_type,
            timestamp=datetime.utcnow().isoformat(),
        )


class BaseNotifier(ABC):
    """Abstract base class for notification providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the notifier name/type."""
        pass

    @property
    @abstractmethod
    def is_configured(self) -> bool:
        """Check if this notifier is properly configured."""
        pass

    @abstractmethod
    async def send(self, payload: NotificationPayload) -> NotificationResult:
        """
        Send a notification.

        Args:
            payload: The notification data to send.

        Returns:
            NotificationResult indicating success or failure.
        """
        pass

    async def test(self) -> NotificationResult:
        """Send a test notification."""
        test_payload = NotificationPayload(
            device_name="Test Device",
            mac_address="00:11:22:33:44:55",
            signal_strength=-50,
            event_type="test",
            timestamp="2024-01-01T00:00:00",
        )
        return await self.send(test_payload)
