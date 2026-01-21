"""Main FastAPI application for ManoMonitor."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from manomonitor.api.routes import router as api_router
from manomonitor.api.websocket import router as ws_router
from manomonitor.capture.monitor import get_capture
from manomonitor.capture.network import get_arp_monitor, get_dhcp_monitor
from manomonitor.config import settings
from manomonitor.database.connection import close_db, init_db
from manomonitor.notifications import get_notification_manager
from manomonitor.web.views import router as web_router

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def _load_db_settings():
    """Load settings from database that override .env defaults."""
    from manomonitor.database.connection import get_db_context
    from manomonitor.database.crud import get_all_config

    async with get_db_context() as db:
        db_config = await get_all_config(db)

        if not db_config:
            logger.info("No saved settings in database, using defaults")
            return

        # Update settings object with DB values
        setting_map = {
            "wifi_interface": str,
            "monitor_name": str,
            "monitor_latitude": float,
            "monitor_longitude": float,
            "log_retention_days": int,
            "presence_timeout_minutes": int,
            "notification_cooldown_minutes": int,
            "default_signal_threshold": int,
            "signal_tx_power": int,
            "signal_path_loss": float,
            "signal_averaging_window": int,
        }

        updated = []
        for key, converter in setting_map.items():
            if key in db_config:
                try:
                    value = converter(db_config[key])
                    setattr(settings, key, value)
                    updated.append(key)
                except (ValueError, TypeError):
                    pass

        if updated:
            logger.info(f"Loaded settings from database: {', '.join(updated)}")


async def _setup_local_monitor():
    """Set up the local monitor with configured or auto-detected location."""
    import secrets
    from sqlalchemy import select
    from manomonitor.database.connection import get_db_context
    from manomonitor.database.models import Monitor

    lat = settings.monitor_latitude
    lon = settings.monitor_longitude
    method = "configured"

    # If not configured, try auto-detection
    if lat == 0.0 and lon == 0.0 and settings.auto_detect_location:
        from manomonitor.utils.geolocation import auto_detect_location, find_gps_devices

        logger.info("Monitor location not configured, attempting auto-detection...")

        # Check for GPS devices first
        gps_devices = find_gps_devices()
        if gps_devices and settings.gps_enabled:
            logger.info(f"Found GPS device(s): {gps_devices}")

        location = await auto_detect_location(
            google_api_key=settings.google_geolocation_api_key or None,
            interface=settings.wifi_interface,
            gps_device=settings.gps_device or None,
            gps_enabled=settings.gps_enabled,
        )
        if location:
            lat = location.latitude
            lon = location.longitude
            # Determine method based on accuracy
            if location.accuracy < 10:
                method = f"GPS ({location.accuracy:.1f}m accuracy)"
            elif location.accuracy < 100:
                method = f"WiFi ({int(location.accuracy)}m accuracy)"
            else:
                method = f"IP (~{int(location.accuracy/1000)}km accuracy)"
            logger.info(f"Auto-detected location: {lat}, {lon} via {method}")
        else:
            logger.warning("Auto-detection failed - monitor will not be registered")
            return

    if lat == 0.0 and lon == 0.0:
        logger.info("No location configured or detected - skipping local monitor setup")
        return

    # Get or create API key
    api_key = settings.monitor_api_key or secrets.token_hex(32)

    async with get_db_context() as db:
        # Check for existing local monitor
        result = await db.execute(select(Monitor).where(Monitor.is_local == True))
        monitor = result.scalar_one_or_none()

        from datetime import datetime

        if monitor:
            # Update existing
            monitor.name = settings.monitor_name
            monitor.latitude = lat
            monitor.longitude = lon
            monitor.api_key = api_key
            monitor.last_seen = datetime.utcnow()
            logger.info(f"Updated local monitor '{monitor.name}' at ({lat}, {lon}) [{method}]")
        else:
            # Create new local monitor
            monitor = Monitor(
                name=settings.monitor_name,
                api_key=api_key,
                latitude=lat,
                longitude=lon,
                is_active=True,
                is_local=True,
                last_seen=datetime.utcnow(),
            )
            db.add(monitor)
            logger.info(f"Registered local monitor '{settings.monitor_name}' at ({lat}, {lon}) [{method}]")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    logger.info("Starting ManoMonitor...")

    # Initialize database
    await init_db()
    logger.info("Database initialized")

    # Load settings from database (overrides .env defaults)
    await _load_db_settings()

    # Auto-setup local monitor if location is configured or auto-detect is enabled
    if settings.auto_detect_location or settings.monitor_latitude != 0.0:
        try:
            await _setup_local_monitor()
        except Exception as e:
            logger.warning(f"Failed to setup local monitor: {e}")
            logger.info("You can manually configure location in .env or call POST /api/monitors/setup-local")

    # Start WiFi capture if enabled
    capture = get_capture()
    if settings.capture_enabled:
        try:
            await capture.start()
            logger.info("WiFi capture started")
        except Exception as e:
            logger.error(f"Failed to start WiFi capture: {e}")
            logger.warning("Running without WiFi capture - configure manually or fix the error")

    # Start ARP monitoring if enabled
    arp_monitor = get_arp_monitor()
    if settings.arp_monitoring_enabled:
        try:
            arp_monitor._scan_interval = settings.arp_scan_interval
            await arp_monitor.start()
            logger.info("ARP monitoring started")
        except Exception as e:
            logger.error(f"Failed to start ARP monitoring: {e}")

    # Start DHCP monitoring if enabled
    dhcp_monitor = get_dhcp_monitor()
    if settings.dhcp_monitoring_enabled:
        try:
            if settings.dhcp_lease_file:
                dhcp_monitor.lease_file = settings.dhcp_lease_file
            dhcp_monitor._check_interval = settings.dhcp_check_interval
            await dhcp_monitor.start()
            logger.info("DHCP monitoring started")
        except Exception as e:
            logger.error(f"Failed to start DHCP monitoring: {e}")

    # Start notification manager
    manager = get_notification_manager()
    await manager.start()
    logger.info("Notification manager started")

    logger.info(f"ManoMonitor ready at http://{settings.host}:{settings.port}")

    yield

    # Shutdown
    logger.info("Shutting down ManoMonitor...")

    # Stop capture
    if capture.is_running:
        await capture.stop()

    # Stop ARP monitoring
    if arp_monitor.is_running:
        await arp_monitor.stop()

    # Stop DHCP monitoring
    if dhcp_monitor.is_running:
        await dhcp_monitor.stop()

    # Stop notification manager
    await manager.stop()

    # Close database
    await close_db()

    logger.info("ManoMonitor stopped")


# Create FastAPI app
app = FastAPI(
    title="ManoMonitor",
    description="WiFi-based presence detection and proximity alert system",
    version="2.0.0",
    lifespan=lifespan,
)

# Mount static files
app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")

# Include routers
app.include_router(api_router)
app.include_router(ws_router)
app.include_router(web_router)


def run():
    """Run the application with uvicorn."""
    import uvicorn

    uvicorn.run(
        "manomonitor.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="debug" if settings.debug else "info",
    )


if __name__ == "__main__":
    run()
