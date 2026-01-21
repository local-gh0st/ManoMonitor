"""Home Assistant notification provider."""

import logging
from typing import Optional

import httpx

from manomonitor.config import settings
from manomonitor.notifications.base import BaseNotifier, NotificationPayload, NotificationResult

logger = logging.getLogger(__name__)


class HomeAssistantNotifier(BaseNotifier):
    """
    Send notifications via Home Assistant REST API.

    Uses the notify service to send notifications through any
    configured notification integration in Home Assistant.
    """

    def __init__(
        self,
        base_url: str = settings.homeassistant_url,
        token: str = settings.homeassistant_token,
        notify_service: str = settings.homeassistant_notify_service,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.notify_service = notify_service

    @property
    def name(self) -> str:
        return "homeassistant"

    @property
    def is_configured(self) -> bool:
        return bool(settings.homeassistant_enabled and self.token and self.base_url)

    def _get_headers(self) -> dict:
        """Get HTTP headers for Home Assistant API."""
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    async def send(self, payload: NotificationPayload) -> NotificationResult:
        """Send notification to Home Assistant."""
        if not self.is_configured:
            return NotificationResult(
                success=False,
                notifier_type=self.name,
                error="Home Assistant not configured",
            )

        # Build the notification message
        if payload.event_type == "new_device":
            title = "New Device Detected"
            message = f"New device discovered: {payload.device_name} ({payload.mac_address})"
        elif payload.event_type == "test":
            title = "WhosHere Test"
            message = "This is a test notification from WhosHere"
        else:
            title = f"{payload.device_name} Detected"
            message = f"{payload.device_name} is nearby (Signal: {payload.signal_strength}dBm)"

        # Convert service name to API endpoint
        # notify.notify -> /api/services/notify/notify
        service_parts = self.notify_service.split(".")
        if len(service_parts) != 2:
            return NotificationResult(
                success=False,
                notifier_type=self.name,
                error=f"Invalid notify service format: {self.notify_service}",
            )

        domain, service = service_parts
        url = f"{self.base_url}/api/services/{domain}/{service}"

        data = {
            "title": title,
            "message": message,
            "data": {
                "device_name": payload.device_name,
                "mac_address": payload.mac_address,
                "signal_strength": payload.signal_strength,
                "event_type": payload.event_type,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    url,
                    json=data,
                    headers=self._get_headers(),
                )

                if response.status_code in (200, 201):
                    logger.info(f"Home Assistant notification sent for {payload.device_name}")
                    return NotificationResult(
                        success=True,
                        notifier_type=self.name,
                        message=f"Notification sent: {payload.device_name}",
                    )
                elif response.status_code == 401:
                    error = "Home Assistant authentication failed - check your token"
                    logger.error(error)
                    return NotificationResult(
                        success=False,
                        notifier_type=self.name,
                        error=error,
                    )
                else:
                    error = f"Home Assistant returned {response.status_code}: {response.text}"
                    logger.error(error)
                    return NotificationResult(
                        success=False,
                        notifier_type=self.name,
                        error=error,
                    )

        except httpx.TimeoutException:
            error = "Home Assistant request timed out"
            logger.error(error)
            return NotificationResult(
                success=False,
                notifier_type=self.name,
                error=error,
            )
        except httpx.ConnectError:
            error = f"Could not connect to Home Assistant at {self.base_url}"
            logger.error(error)
            return NotificationResult(
                success=False,
                notifier_type=self.name,
                error=error,
            )
        except Exception as e:
            error = f"Home Assistant error: {e}"
            logger.error(error)
            return NotificationResult(
                success=False,
                notifier_type=self.name,
                error=error,
            )

    async def check_connection(self) -> tuple[bool, str]:
        """Check if we can connect to Home Assistant."""
        if not self.is_configured:
            return False, "Home Assistant not configured"

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"{self.base_url}/api/",
                    headers=self._get_headers(),
                )

                if response.status_code == 200:
                    return True, "Connected to Home Assistant"
                elif response.status_code == 401:
                    return False, "Authentication failed - check your token"
                else:
                    return False, f"Unexpected response: {response.status_code}"

        except httpx.ConnectError:
            return False, f"Could not connect to {self.base_url}"
        except Exception as e:
            return False, f"Error: {e}"

    async def fire_event(
        self,
        event_type: str,
        event_data: Optional[dict] = None,
    ) -> NotificationResult:
        """
        Fire a Home Assistant event.

        This can be used to trigger automations based on device detection.
        """
        if not self.is_configured:
            return NotificationResult(
                success=False,
                notifier_type=self.name,
                error="Home Assistant not configured",
            )

        url = f"{self.base_url}/api/events/{event_type}"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    url,
                    json=event_data or {},
                    headers=self._get_headers(),
                )

                if response.status_code == 200:
                    return NotificationResult(
                        success=True,
                        notifier_type=self.name,
                        message=f"Event fired: {event_type}",
                    )
                else:
                    return NotificationResult(
                        success=False,
                        notifier_type=self.name,
                        error=f"Failed to fire event: {response.status_code}",
                    )

        except Exception as e:
            return NotificationResult(
                success=False,
                notifier_type=self.name,
                error=f"Error firing event: {e}",
            )
