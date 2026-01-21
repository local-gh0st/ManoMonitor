"""WebSocket support for real-time updates."""

import asyncio
import json
import logging
from datetime import datetime
from typing import Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from manomonitor.database.connection import get_db_context
from manomonitor.database.crud import get_all_assets, get_statistics

logger = logging.getLogger(__name__)
router = APIRouter()


class ConnectionManager:
    """Manages WebSocket connections for real-time updates."""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self._broadcast_task: asyncio.Task | None = None
        self._running = False

    async def connect(self, websocket: WebSocket) -> None:
        """Accept a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")

        # Start broadcast task if not running
        if not self._running:
            await self.start_broadcast()

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection."""
        self.active_connections.discard(websocket)
        logger.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")

        # Stop broadcast if no connections
        if not self.active_connections and self._running:
            asyncio.create_task(self.stop_broadcast())

    async def broadcast(self, message: dict) -> None:
        """Send a message to all connected clients."""
        if not self.active_connections:
            return

        message_json = json.dumps(message, default=str)
        disconnected = set()

        for connection in self.active_connections:
            try:
                await connection.send_text(message_json)
            except Exception:
                disconnected.add(connection)

        # Remove disconnected clients
        self.active_connections -= disconnected

    async def _broadcast_loop(self) -> None:
        """Periodically broadcast device updates."""
        while self._running:
            try:
                async with get_db_context() as db:
                    # Get current stats
                    stats = await get_statistics(db)

                    # Get recently seen devices (present)
                    assets = await get_all_assets(db, limit=20, present_only=True)

                    # Build update message
                    message = {
                        "type": "update",
                        "timestamp": datetime.utcnow().isoformat(),
                        "stats": stats,
                        "present_devices": [
                            {
                                "id": a.id,
                                "name": a.display_name,
                                "mac": a.mac_address,
                                "signal": a.last_signal_strength,
                                "minutes_ago": a.minutes_since_seen,
                            }
                            for a in assets
                        ],
                    }

                    await self.broadcast(message)

            except Exception as e:
                logger.error(f"Error in broadcast loop: {e}")

            await asyncio.sleep(5)  # Update every 5 seconds

    async def start_broadcast(self) -> None:
        """Start the broadcast loop."""
        if self._running:
            return
        self._running = True
        self._broadcast_task = asyncio.create_task(self._broadcast_loop())
        logger.info("WebSocket broadcast started")

    async def stop_broadcast(self) -> None:
        """Stop the broadcast loop."""
        self._running = False
        if self._broadcast_task:
            self._broadcast_task.cancel()
            try:
                await self._broadcast_task
            except asyncio.CancelledError:
                pass
        logger.info("WebSocket broadcast stopped")


# Global connection manager
manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates."""
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive, handle incoming messages
            data = await websocket.receive_text()

            # Handle ping/pong
            if data == "ping":
                await websocket.send_text("pong")

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)
