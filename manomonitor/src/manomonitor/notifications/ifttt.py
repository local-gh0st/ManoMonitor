"""IFTTT webhook notification provider."""

import logging

import httpx

from manomonitor.config import settings
from manomonitor.notifications.base import BaseNotifier, NotificationPayload, NotificationResult

logger = logging.getLogger(__name__)


class IFTTTNotifier(BaseNotifier):
    """
    Send notifications via IFTTT Webhooks.

    IFTTT webhooks receive 3 values:
    - value1: Device name
    - value2: Event details (signal strength, MAC)
    - value3: Timestamp
    """

    WEBHOOK_URL = "https://maker.ifttt.com/trigger/{event}/with/key/{key}"

    def __init__(
        self,
        webhook_key: str = settings.ifttt_webhook_key,
        event_name: str = settings.ifttt_event_name,
    ):
        self.webhook_key = webhook_key
        self.event_name = event_name

    @property
    def name(self) -> str:
        return "ifttt"

    @property
    def is_configured(self) -> bool:
        return bool(settings.ifttt_enabled and self.webhook_key)

    async def send(self, payload: NotificationPayload) -> NotificationResult:
        """Send notification to IFTTT."""
        if not self.is_configured:
            return NotificationResult(
                success=False,
                notifier_type=self.name,
                error="IFTTT not configured",
            )

        url = self.WEBHOOK_URL.format(event=self.event_name, key=self.webhook_key)

        # IFTTT accepts value1, value2, value3
        data = {
            "value1": payload.device_name,
            "value2": f"Signal: {payload.signal_strength}dBm | MAC: {payload.mac_address}",
            "value3": payload.timestamp,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=data)

                if response.status_code == 200:
                    logger.info(f"IFTTT notification sent for {payload.device_name}")
                    return NotificationResult(
                        success=True,
                        notifier_type=self.name,
                        message=f"Notification sent: {payload.device_name}",
                    )
                else:
                    error = f"IFTTT returned {response.status_code}: {response.text}"
                    logger.error(error)
                    return NotificationResult(
                        success=False,
                        notifier_type=self.name,
                        error=error,
                    )

        except httpx.TimeoutException:
            error = "IFTTT request timed out"
            logger.error(error)
            return NotificationResult(
                success=False,
                notifier_type=self.name,
                error=error,
            )
        except Exception as e:
            error = f"IFTTT error: {e}"
            logger.error(error)
            return NotificationResult(
                success=False,
                notifier_type=self.name,
                error=error,
            )
