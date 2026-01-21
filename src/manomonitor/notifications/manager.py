"""Notification manager that coordinates all notifiers."""

import asyncio
import logging
from typing import Optional

from manomonitor.config import settings
from manomonitor.database.connection import get_db_context
from manomonitor.database.crud import (
    get_assets_to_notify,
    get_newly_discovered_assets,
    log_notification,
    update_asset_notification_time,
)
from manomonitor.database.models import Asset
from manomonitor.notifications.base import BaseNotifier, NotificationPayload, NotificationResult
from manomonitor.notifications.homeassistant import HomeAssistantNotifier
from manomonitor.notifications.ifttt import IFTTTNotifier

logger = logging.getLogger(__name__)


class NotificationManager:
    """
    Manages all notification providers and handles notification logic.

    Runs periodic checks to find devices that should trigger notifications.
    """

    def __init__(self):
        self.notifiers: list[BaseNotifier] = []
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._check_interval = 5  # seconds

        # Initialize notifiers
        self._init_notifiers()

    def _init_notifiers(self) -> None:
        """Initialize all configured notifiers."""
        # IFTTT
        ifttt = IFTTTNotifier()
        if ifttt.is_configured:
            self.notifiers.append(ifttt)
            logger.info("IFTTT notifier enabled")

        # Home Assistant
        ha = HomeAssistantNotifier()
        if ha.is_configured:
            self.notifiers.append(ha)
            logger.info("Home Assistant notifier enabled")

        if not self.notifiers:
            logger.warning("No notification providers configured")

    def get_notifier(self, name: str) -> Optional[BaseNotifier]:
        """Get a specific notifier by name."""
        for notifier in self.notifiers:
            if notifier.name == name:
                return notifier
        return None

    async def send_all(
        self,
        payload: NotificationPayload,
        asset_id: Optional[int] = None,
    ) -> list[NotificationResult]:
        """
        Send notification through all configured providers.

        Args:
            payload: The notification data.
            asset_id: Optional asset ID for logging.

        Returns:
            List of results from each notifier.
        """
        if not self.notifiers:
            return []

        results = []

        for notifier in self.notifiers:
            result = await notifier.send(payload)
            results.append(result)

            # Log the notification attempt
            async with get_db_context() as db:
                await log_notification(
                    db,
                    asset_id=asset_id,
                    notification_type=notifier.name,
                    status="sent" if result.success else "failed",
                    message=result.message,
                    error=result.error,
                )

        return results

    async def notify_device(self, asset: Asset, event_type: str = "detected") -> list[NotificationResult]:
        """
        Send notifications for a specific device.

        Args:
            asset: The device to notify about.
            event_type: Type of event (detected, new_device, etc.)

        Returns:
            List of notification results.
        """
        payload = NotificationPayload.from_asset(asset, event_type)
        results = await self.send_all(payload, asset_id=asset.id)

        # Update last notified time if any notification succeeded
        if any(r.success for r in results):
            async with get_db_context() as db:
                await update_asset_notification_time(db, asset.id)

        return results

    async def _check_and_notify(self) -> None:
        """Check for devices that need notifications and send them."""
        try:
            async with get_db_context() as db:
                # Get devices with notifications enabled that meet criteria
                assets = await get_assets_to_notify(db)

                for asset in assets:
                    logger.info(f"Sending notification for {asset.display_name}")
                    await self.notify_device(asset, event_type="detected")

                # Check for newly discovered devices if enabled
                if settings.notify_new_devices:
                    new_assets = await get_newly_discovered_assets(db, since_minutes=1)
                    for asset in new_assets:
                        # Only notify if not already notified
                        if asset.last_notified is None:
                            logger.info(f"Sending new device notification for {asset.mac_address}")
                            await self.notify_device(asset, event_type="new_device")

        except Exception as e:
            logger.error(f"Error in notification check: {e}")

    async def _notification_loop(self) -> None:
        """Main notification checking loop."""
        logger.info("Starting notification manager")

        while self._running:
            await self._check_and_notify()
            await asyncio.sleep(self._check_interval)

    async def start(self) -> None:
        """Start the notification manager."""
        if self._running:
            logger.warning("Notification manager already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._notification_loop())
        logger.info("Notification manager started")

    async def stop(self) -> None:
        """Stop the notification manager."""
        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        logger.info("Notification manager stopped")

    @property
    def is_running(self) -> bool:
        """Check if manager is running."""
        return self._running and self._task is not None and not self._task.done()

    async def test_all(self) -> dict[str, NotificationResult]:
        """Test all configured notifiers."""
        results = {}
        for notifier in self.notifiers:
            results[notifier.name] = await notifier.test()
        return results


# Singleton instance
_manager_instance: Optional[NotificationManager] = None


def get_notification_manager() -> NotificationManager:
    """Get or create the global NotificationManager instance."""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = NotificationManager()
    return _manager_instance
