"""API routes for WhosHere."""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from manomonitor.capture.monitor import get_capture
from manomonitor.capture.network import get_arp_monitor, get_dhcp_monitor
from manomonitor.config import settings
from manomonitor.database.connection import get_db
from manomonitor.database.crud import (
    delete_asset,
    get_all_assets,
    get_all_config,
    get_asset_by_id,
    get_assets_count,
    get_config,
    get_notification_logs,
    get_probe_logs,
    get_ssid_history,
    get_statistics,
    purge_old_logs,
    set_config,
    update_asset,
)
from manomonitor.notifications import get_notification_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["api"])


# =============================================================================
# Pydantic Models (Request/Response schemas)
# =============================================================================


class AssetResponse(BaseModel):
    """Response model for an asset."""

    id: int
    mac_address: str
    nickname: Optional[str]
    vendor: Optional[str]
    device_type: Optional[str]
    notify_enabled: bool
    signal_threshold: int
    first_seen: datetime
    last_seen: datetime
    times_seen: int
    last_signal_strength: Optional[int]
    last_notified: Optional[datetime]
    notes: Optional[str]
    is_hidden: bool
    is_present: bool
    minutes_since_seen: int
    display_name: str
    vendor_display: str
    device_type_display: str
    device_icon: str

    class Config:
        from_attributes = True


class AssetListResponse(BaseModel):
    """Response model for list of assets."""

    items: list[AssetResponse]
    total: int
    limit: int
    offset: int


class AssetUpdateRequest(BaseModel):
    """Request model for updating an asset."""

    nickname: Optional[str] = Field(None, max_length=100)
    vendor: Optional[str] = Field(None, max_length=200)
    device_type: Optional[str] = Field(None, max_length=50)
    notify_enabled: Optional[bool] = None
    signal_threshold: Optional[int] = Field(None, ge=-100, le=0)
    notes: Optional[str] = None
    is_hidden: Optional[bool] = None


class SSIDResponse(BaseModel):
    """Response model for SSID history."""

    id: int
    ssid: str
    first_seen: datetime
    last_seen: datetime
    times_seen: int

    class Config:
        from_attributes = True


class ProbeLogResponse(BaseModel):
    """Response model for probe log entry."""

    id: int
    asset_id: int
    timestamp: datetime
    signal_strength: Optional[int]
    ssid: Optional[str]

    class Config:
        from_attributes = True


class NotificationLogResponse(BaseModel):
    """Response model for notification log."""

    id: int
    asset_id: Optional[int]
    notification_type: str
    status: str
    message: Optional[str]
    error: Optional[str]
    timestamp: datetime

    class Config:
        from_attributes = True


class StatsResponse(BaseModel):
    """Response model for statistics."""

    total_devices: int
    present_now: int
    notifications_enabled: int
    probes_today: int
    new_devices_today: int


class StatusResponse(BaseModel):
    """Response model for system status."""

    capture_running: bool
    arp_monitoring_running: bool
    dhcp_monitoring_running: bool
    notifications_running: bool
    wifi_interface: str
    database_url: str
    notifiers_configured: list[str]
    dhcp_lease_file: Optional[str] = None


class MessageResponse(BaseModel):
    """Generic message response."""

    message: str
    success: bool = True


# =============================================================================
# Asset Endpoints
# =============================================================================


@router.get("/assets", response_model=AssetListResponse)
async def list_assets(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None),
    include_hidden: bool = Query(False),
    notify_only: bool = Query(False),
    present_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    """Get list of all tracked devices."""
    assets = await get_all_assets(
        db,
        limit=limit,
        offset=offset,
        search=search,
        include_hidden=include_hidden,
        notify_only=notify_only,
        present_only=present_only,
    )
    total = await get_assets_count(db, include_hidden=include_hidden, notify_only=notify_only)

    return AssetListResponse(
        items=[
            AssetResponse(
                id=a.id,
                mac_address=a.mac_address,
                nickname=a.nickname,
                vendor=a.vendor,
                device_type=a.device_type,
                notify_enabled=a.notify_enabled,
                signal_threshold=a.signal_threshold,
                first_seen=a.first_seen,
                last_seen=a.last_seen,
                times_seen=a.times_seen,
                last_signal_strength=a.last_signal_strength,
                last_notified=a.last_notified,
                notes=a.notes,
                is_hidden=a.is_hidden,
                is_present=a.is_present,
                minutes_since_seen=a.minutes_since_seen,
                display_name=a.display_name,
            )
            for a in assets
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/assets/{asset_id}", response_model=AssetResponse)
async def get_asset(
    asset_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get a specific device by ID."""
    asset = await get_asset_by_id(db, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    return AssetResponse(
        id=asset.id,
        mac_address=asset.mac_address,
        nickname=asset.nickname,
        vendor=asset.vendor,
        device_type=asset.device_type,
        notify_enabled=asset.notify_enabled,
        signal_threshold=asset.signal_threshold,
        first_seen=asset.first_seen,
        last_seen=asset.last_seen,
        times_seen=asset.times_seen,
        last_signal_strength=asset.last_signal_strength,
        last_notified=asset.last_notified,
        notes=asset.notes,
        is_hidden=asset.is_hidden,
        is_present=asset.is_present,
        minutes_since_seen=asset.minutes_since_seen,
        display_name=asset.display_name,
        vendor_display=asset.vendor_display,
        device_type_display=asset.device_type_display,
        device_icon=asset.device_icon,
    )


@router.patch("/assets/{asset_id}", response_model=AssetResponse)
async def update_asset_endpoint(
    asset_id: int,
    update_data: AssetUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update a device's settings."""
    asset = await update_asset(
        db,
        asset_id=asset_id,
        nickname=update_data.nickname,
        vendor=update_data.vendor,
        device_type=update_data.device_type,
        notify_enabled=update_data.notify_enabled,
        signal_threshold=update_data.signal_threshold,
        notes=update_data.notes,
        is_hidden=update_data.is_hidden,
    )
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    return AssetResponse(
        id=asset.id,
        mac_address=asset.mac_address,
        nickname=asset.nickname,
        vendor=asset.vendor,
        device_type=asset.device_type,
        notify_enabled=asset.notify_enabled,
        signal_threshold=asset.signal_threshold,
        first_seen=asset.first_seen,
        last_seen=asset.last_seen,
        times_seen=asset.times_seen,
        last_signal_strength=asset.last_signal_strength,
        last_notified=asset.last_notified,
        notes=asset.notes,
        is_hidden=asset.is_hidden,
        is_present=asset.is_present,
        minutes_since_seen=asset.minutes_since_seen,
        display_name=asset.display_name,
        vendor_display=asset.vendor_display,
        device_type_display=asset.device_type_display,
        device_icon=asset.device_icon,
    )


@router.delete("/assets/{asset_id}", response_model=MessageResponse)
async def delete_asset_endpoint(
    asset_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a device and all its data."""
    success = await delete_asset(db, asset_id)
    if not success:
        raise HTTPException(status_code=404, detail="Asset not found")

    return MessageResponse(message="Asset deleted successfully")


@router.get("/assets/{asset_id}/ssids", response_model=list[SSIDResponse])
async def get_asset_ssids(
    asset_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get SSID history for a device."""
    asset = await get_asset_by_id(db, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    ssids = await get_ssid_history(db, asset_id)
    return [SSIDResponse.model_validate(s) for s in ssids]


@router.get("/assets/{asset_id}/logs", response_model=list[ProbeLogResponse])
async def get_asset_logs(
    asset_id: int,
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    """Get probe logs for a device."""
    asset = await get_asset_by_id(db, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    logs = await get_probe_logs(db, asset_id=asset_id, limit=limit)
    return [ProbeLogResponse.model_validate(log) for log in logs]


# =============================================================================
# Statistics & Status Endpoints
# =============================================================================


@router.get("/stats", response_model=StatsResponse)
async def get_stats(db: AsyncSession = Depends(get_db)):
    """Get system statistics."""
    stats = await get_statistics(db)
    return StatsResponse(**stats)


@router.get("/status", response_model=StatusResponse)
async def get_status():
    """Get system status."""
    capture = get_capture()
    manager = get_notification_manager()
    arp_monitor = get_arp_monitor()
    dhcp_monitor = get_dhcp_monitor()

    # Mask database URL password if present
    db_url = settings.database_url
    if "@" in db_url:
        # Hide password in connection string
        parts = db_url.split("@")
        prefix = parts[0].rsplit(":", 1)[0]
        db_url = f"{prefix}:***@{parts[1]}"

    return StatusResponse(
        capture_running=capture.is_running,
        arp_monitoring_running=arp_monitor.is_running,
        dhcp_monitoring_running=dhcp_monitor.is_running,
        notifications_running=manager.is_running,
        wifi_interface=settings.wifi_interface,
        database_url=db_url,
        notifiers_configured=[n.name for n in manager.notifiers],
        dhcp_lease_file=dhcp_monitor.lease_file,
    )


class DiagnosticsResponse(BaseModel):
    """Response model for system diagnostics."""

    arp_command_available: bool
    arp_error: Optional[str] = None
    arp_table_entries: int = 0
    arp_sample_entries: list[dict] = []
    dhcp_lease_file_found: bool
    dhcp_lease_file_path: Optional[str] = None
    dhcp_entries: int = 0
    tshark_available: bool
    wifi_interface_exists: bool
    wifi_interface_info: Optional[str] = None
    known_arp_macs: int = 0
    known_dhcp_macs: int = 0


@router.get("/diagnostics", response_model=DiagnosticsResponse)
async def get_diagnostics():
    """
    Get system diagnostics to troubleshoot device detection issues.

    This endpoint checks:
    - If the arp command is available and working
    - Current ARP table contents
    - If DHCP lease file is found and readable
    - If tshark is available for WiFi capture
    - WiFi interface status
    """
    import asyncio
    import shutil
    import subprocess

    arp_monitor = get_arp_monitor()
    dhcp_monitor = get_dhcp_monitor()
    capture = get_capture()

    result = DiagnosticsResponse(
        arp_command_available=False,
        dhcp_lease_file_found=False,
        tshark_available=bool(shutil.which("tshark")),
        wifi_interface_exists=False,
    )

    # Check ARP command
    ok, msg = arp_monitor.check_dependencies()
    result.arp_command_available = ok
    if not ok:
        result.arp_error = msg

    # Get ARP table entries
    if ok:
        try:
            entries = await arp_monitor._get_arp_table()
            result.arp_table_entries = len(entries)
            # Show first 5 entries as sample
            result.arp_sample_entries = [
                {"ip": ip, "mac": mac} for ip, mac in entries[:5]
            ]
        except Exception as e:
            result.arp_error = str(e)

    # Check DHCP lease file
    result.dhcp_lease_file_found = dhcp_monitor.lease_file is not None
    result.dhcp_lease_file_path = dhcp_monitor.lease_file

    # Get DHCP entries count if file exists
    if result.dhcp_lease_file_found:
        try:
            devices = await dhcp_monitor._read_leases()
            result.dhcp_entries = len(devices)
        except Exception:
            pass

    # Check WiFi interface
    ok, msg = capture.check_interface(settings.wifi_interface)
    result.wifi_interface_exists = ok
    result.wifi_interface_info = msg

    # Get known MAC counts
    result.known_arp_macs = len(arp_monitor._known_macs)
    result.known_dhcp_macs = len(dhcp_monitor._known_macs)

    return result


# =============================================================================
# Notification Endpoints
# =============================================================================


@router.get("/notifications/logs", response_model=list[NotificationLogResponse])
async def get_notifications(
    limit: int = Query(50, ge=1, le=200),
    asset_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Get notification history."""
    logs = await get_notification_logs(db, limit=limit, asset_id=asset_id)
    return [NotificationLogResponse.model_validate(log) for log in logs]


@router.post("/notifications/test", response_model=MessageResponse)
async def test_notifications():
    """Send a test notification through all configured providers."""
    manager = get_notification_manager()
    results = await manager.test_all()

    if not results:
        return MessageResponse(
            message="No notification providers configured",
            success=False,
        )

    success_count = sum(1 for r in results.values() if r.success)
    total = len(results)

    if success_count == total:
        return MessageResponse(message=f"All {total} notification(s) sent successfully")
    elif success_count > 0:
        return MessageResponse(
            message=f"{success_count}/{total} notifications sent",
            success=False,
        )
    else:
        errors = [f"{k}: {v.error}" for k, v in results.items() if v.error]
        return MessageResponse(
            message=f"All notifications failed: {'; '.join(errors)}",
            success=False,
        )


# =============================================================================
# Control Endpoints
# =============================================================================


@router.post("/capture/start", response_model=MessageResponse)
async def start_capture():
    """Start WiFi probe capture."""
    capture = get_capture()
    if capture.is_running:
        return MessageResponse(message="Capture already running")

    try:
        await capture.start()
        return MessageResponse(message="Capture started")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/capture/stop", response_model=MessageResponse)
async def stop_capture():
    """Stop WiFi probe capture."""
    capture = get_capture()
    if not capture.is_running:
        return MessageResponse(message="Capture not running")

    await capture.stop()
    return MessageResponse(message="Capture stopped")


@router.post("/maintenance/purge-logs", response_model=MessageResponse)
async def purge_logs(
    days: int = Query(default=30, ge=1),
    db: AsyncSession = Depends(get_db),
):
    """Purge probe logs older than N days."""
    count = await purge_old_logs(db, days)
    return MessageResponse(message=f"Purged {count} log entries older than {days} days")


# =============================================================================
# Monitor & Map Endpoints (Multi-Monitor Positioning)
# =============================================================================


class MonitorResponse(BaseModel):
    """Response model for a monitor."""
    id: int
    name: str
    latitude: float
    longitude: float
    is_active: bool
    is_local: bool
    is_online: bool
    last_seen: Optional[datetime]

    class Config:
        from_attributes = True


class MonitorRegisterRequest(BaseModel):
    """Request to register a new monitor."""
    name: str = Field(..., max_length=100)
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    api_key: Optional[str] = Field(None, max_length=64)


class SignalReportRequest(BaseModel):
    """Request to report signal readings from a monitor."""
    api_key: str
    readings: list[dict]  # [{"mac_address": "...", "signal_strength": -60}, ...]


class DevicePositionResponse(BaseModel):
    """Response model for device position on map."""
    id: int
    mac_address: str
    display_name: str
    device_icon: str
    device_type: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    accuracy: Optional[float]
    signal_strength: Optional[int]
    is_present: bool
    last_seen_minutes: int


class MapDataResponse(BaseModel):
    """Response model for map data."""
    monitors: list[MonitorResponse]
    devices: list[DevicePositionResponse]
    center_lat: float
    center_lon: float
    map_enabled: bool


@router.get("/monitors", response_model=list[MonitorResponse])
async def list_monitors(
    db: AsyncSession = Depends(get_db),
):
    """Get list of all monitors."""
    from sqlalchemy import select
    from manomonitor.database.models import Monitor

    result = await db.execute(select(Monitor).where(Monitor.is_active == True))
    monitors = result.scalars().all()

    return [
        MonitorResponse(
            id=m.id,
            name=m.name,
            latitude=m.latitude,
            longitude=m.longitude,
            is_active=m.is_active,
            is_local=m.is_local,
            is_online=m.is_online,
            last_seen=m.last_seen,
        )
        for m in monitors
    ]


@router.post("/monitors/register", response_model=MonitorResponse)
async def register_monitor(
    data: MonitorRegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """Register a new monitor or update existing."""
    import secrets
    from sqlalchemy import select
    from manomonitor.database.models import Monitor

    api_key = data.api_key or secrets.token_hex(32)

    # Check if monitor with this API key exists
    result = await db.execute(select(Monitor).where(Monitor.api_key == api_key))
    monitor = result.scalar_one_or_none()

    if monitor:
        # Update existing
        monitor.name = data.name
        monitor.latitude = data.latitude
        monitor.longitude = data.longitude
        monitor.last_seen = datetime.utcnow()
    else:
        # Create new
        monitor = Monitor(
            name=data.name,
            api_key=api_key,
            latitude=data.latitude,
            longitude=data.longitude,
            is_active=True,
            is_local=False,
            last_seen=datetime.utcnow(),
        )
        db.add(monitor)

    await db.flush()

    return MonitorResponse(
        id=monitor.id,
        name=monitor.name,
        latitude=monitor.latitude,
        longitude=monitor.longitude,
        is_active=monitor.is_active,
        is_local=monitor.is_local,
        is_online=monitor.is_online,
        last_seen=monitor.last_seen,
    )


@router.post("/monitors/report", response_model=MessageResponse)
async def report_signals(
    data: SignalReportRequest,
    db: AsyncSession = Depends(get_db),
):
    """Report signal readings from a remote monitor."""
    from sqlalchemy import select
    from manomonitor.database.models import Monitor, SignalReading, Asset
    from manomonitor.utils.positioning import signal_to_distance

    # Validate API key
    result = await db.execute(select(Monitor).where(Monitor.api_key == data.api_key))
    monitor = result.scalar_one_or_none()

    if not monitor:
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Update monitor last seen
    monitor.last_seen = datetime.utcnow()

    readings_added = 0
    for reading in data.readings:
        mac = reading.get("mac_address", "").upper()
        signal = reading.get("signal_strength")

        if not mac or signal is None:
            continue

        # Find or create asset
        result = await db.execute(select(Asset).where(Asset.mac_address == mac))
        asset = result.scalar_one_or_none()

        if not asset:
            # Create basic asset entry
            asset = Asset(mac_address=mac)
            db.add(asset)
            await db.flush()

        # Add signal reading
        distance = signal_to_distance(
            signal,
            tx_power=settings.signal_tx_power,
            path_loss_exponent=settings.signal_path_loss,
        )

        sr = SignalReading(
            asset_id=asset.id,
            monitor_id=monitor.id,
            signal_strength=signal,
            estimated_distance=distance,
            timestamp=datetime.utcnow(),
        )
        db.add(sr)
        readings_added += 1

    return MessageResponse(message=f"Recorded {readings_added} signal readings")


@router.get("/map/data", response_model=MapDataResponse)
async def get_map_data(
    db: AsyncSession = Depends(get_db),
):
    """Get all data needed for the device location map."""
    from sqlalchemy import select, desc
    from manomonitor.database.models import Monitor, Asset, SignalReading
    from manomonitor.utils.positioning import (
        GeoPoint, MonitorReading, calculate_position, signal_to_distance
    )

    # Get all active monitors
    result = await db.execute(select(Monitor).where(Monitor.is_active == True))
    monitors = result.scalars().all()

    monitor_responses = [
        MonitorResponse(
            id=m.id,
            name=m.name,
            latitude=m.latitude,
            longitude=m.longitude,
            is_active=m.is_active,
            is_local=m.is_local,
            is_online=m.is_online,
            last_seen=m.last_seen,
        )
        for m in monitors
    ]

    # Build monitor lookup
    monitor_lookup = {m.id: m for m in monitors}

    # Get present devices with their recent signal readings
    assets = await get_all_assets(db, limit=100, present_only=False, include_hidden=False)

    device_positions: list[DevicePositionResponse] = []

    for asset in assets:
        # Get recent signal readings for this asset (last 5 minutes)
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(minutes=5)

        result = await db.execute(
            select(SignalReading)
            .where(SignalReading.asset_id == asset.id)
            .where(SignalReading.timestamp >= cutoff)
            .order_by(desc(SignalReading.timestamp))
        )
        readings = result.scalars().all()

        # Build position from readings
        lat, lon, accuracy = None, None, None

        if readings and len(monitor_lookup) > 0:
            # Group by monitor and collect readings for averaging
            monitor_readings: dict[int, list[SignalReading]] = {}
            for r in readings:
                if r.monitor_id not in monitor_readings:
                    monitor_readings[r.monitor_id] = []
                # Collect up to averaging_window readings per monitor
                if len(monitor_readings[r.monitor_id]) < settings.signal_averaging_window:
                    monitor_readings[r.monitor_id].append(r)

            # Convert to MonitorReading objects with averaged signals
            position_readings = []
            for mid, readings_list in monitor_readings.items():
                if mid in monitor_lookup and readings_list:
                    m = monitor_lookup[mid]
                    # Average the signal strengths
                    avg_signal = sum(r.signal_strength for r in readings_list) // len(readings_list)
                    # Recalculate distance from averaged signal
                    avg_distance = signal_to_distance(
                        avg_signal,
                        settings.signal_tx_power,
                        settings.signal_path_loss,
                    )
                    position_readings.append(MonitorReading(
                        monitor_location=GeoPoint(m.latitude, m.longitude),
                        signal_strength=avg_signal,
                        estimated_distance=avg_distance,
                    ))

            if len(position_readings) >= 2:
                # Calculate center for preference
                center_lat = sum(m.latitude for m in monitors) / len(monitors)
                center_lon = sum(m.longitude for m in monitors) / len(monitors)

                estimate = calculate_position(
                    position_readings,
                    home_center=GeoPoint(center_lat, center_lon),
                )
                if estimate:
                    lat = estimate.location.latitude
                    lon = estimate.location.longitude
                    accuracy = estimate.accuracy

                    # Update asset position in DB
                    asset.last_latitude = lat
                    asset.last_longitude = lon
                    asset.position_accuracy = accuracy
                    asset.position_updated_at = datetime.utcnow()

            elif len(position_readings) == 1:
                # Single monitor - use monitor location with distance ring
                m = monitors[0] if monitors else None
                if m:
                    lat = m.latitude
                    lon = m.longitude
                    accuracy = signal_to_distance(
                        position_readings[0].signal_strength,
                        settings.signal_tx_power,
                        settings.signal_path_loss,
                    )

        # Use stored position if no recent readings
        if lat is None and asset.last_latitude is not None:
            lat = asset.last_latitude
            lon = asset.last_longitude
            accuracy = asset.position_accuracy

        # Fallback for present devices with no signal readings:
        # Place at monitor location so they still appear on map
        if lat is None and asset.is_present and monitors:
            m = monitors[0]
            lat = m.latitude
            lon = m.longitude
            # Use last signal strength to estimate distance, or default
            if asset.last_signal_strength:
                accuracy = signal_to_distance(
                    asset.last_signal_strength,
                    settings.signal_tx_power,
                    settings.signal_path_loss,
                )
            else:
                accuracy = 10.0  # Default 10m accuracy

        device_positions.append(DevicePositionResponse(
            id=asset.id,
            mac_address=asset.mac_address,
            display_name=asset.display_name,
            device_icon=asset.device_icon,
            device_type=asset.device_type,
            latitude=lat,
            longitude=lon,
            accuracy=accuracy,
            signal_strength=asset.last_signal_strength,
            is_present=asset.is_present,
            last_seen_minutes=asset.minutes_since_seen,
        ))

    # Calculate map center
    if monitors:
        center_lat = sum(m.latitude for m in monitors) / len(monitors)
        center_lon = sum(m.longitude for m in monitors) / len(monitors)
    elif settings.monitor_latitude != 0:
        center_lat = settings.monitor_latitude
        center_lon = settings.monitor_longitude
    else:
        center_lat = 0.0
        center_lon = 0.0

    return MapDataResponse(
        monitors=monitor_responses,
        devices=device_positions,
        center_lat=center_lat,
        center_lon=center_lon,
        map_enabled=settings.map_enabled,
    )


# =============================================================================
# Auto-Location Detection
# =============================================================================


class LocationDetectResponse(BaseModel):
    """Response for auto-detected location."""
    latitude: float
    longitude: float
    accuracy: float
    method: str  # "wifi", "ip", "configured"
    message: str


@router.post("/monitors/auto-detect-location", response_model=LocationDetectResponse)
async def auto_detect_monitor_location(
    db: AsyncSession = Depends(get_db),
):
    """
    Automatically detect this monitor's location.

    Priority:
    1. USB GPS device (~2-5m accuracy) - if connected
    2. Google Geolocation API (WiFi-based, ~10-50m accuracy) - requires API key
    3. IP Geolocation (fallback, ~5km accuracy) - no key required

    The detected location can be used to set up the local monitor.
    """
    from manomonitor.utils.geolocation import (
        auto_detect_location,
        find_gps_devices,
        geolocate_via_gps,
        geolocate_via_ip,
    )

    # Try GPS first (most accurate)
    if settings.gps_enabled:
        gps_devices = find_gps_devices()
        if gps_devices or settings.gps_device:
            location = await geolocate_via_gps(
                settings.gps_device or None,
                timeout=15.0,
            )
            if location:
                return LocationDetectResponse(
                    latitude=location.latitude,
                    longitude=location.longitude,
                    accuracy=location.accuracy,
                    method="gps",
                    message=f"Location detected via GPS (accuracy: ~{location.accuracy:.1f}m)",
                )

    # Try WiFi geolocation
    if settings.google_geolocation_api_key:
        from manomonitor.utils.geolocation import geolocate_via_google
        location = await geolocate_via_google(
            settings.google_geolocation_api_key,
            interface=settings.wifi_interface,
        )
        if location:
            return LocationDetectResponse(
                latitude=location.latitude,
                longitude=location.longitude,
                accuracy=location.accuracy,
                method="wifi",
                message=f"Location detected via WiFi (accuracy: ~{int(location.accuracy)}m)",
            )

    # Fallback to IP geolocation
    location = await geolocate_via_ip()
    if location:
        return LocationDetectResponse(
            latitude=location.latitude,
            longitude=location.longitude,
            accuracy=location.accuracy,
            method="ip",
            message=f"Location detected via IP address (city-level, ~{int(location.accuracy/1000)}km accuracy). For better accuracy, connect a USB GPS dongle.",
        )

    raise HTTPException(
        status_code=500,
        detail="Could not detect location. Check network connectivity or connect a GPS device.",
    )


@router.post("/monitors/setup-local", response_model=MonitorResponse)
async def setup_local_monitor(
    auto_detect: bool = Query(default=True, description="Auto-detect location if not configured"),
    db: AsyncSession = Depends(get_db),
):
    """
    Set up or update the local monitor with configured or auto-detected location.

    This endpoint:
    1. Uses configured lat/long if set in .env
    2. Falls back to auto-detection if enabled
    3. Creates/updates the local monitor in the database
    """
    import secrets
    from sqlalchemy import select
    from manomonitor.database.models import Monitor

    lat = settings.monitor_latitude
    lon = settings.monitor_longitude
    method = "configured"

    # If not configured, try auto-detection
    if (lat == 0.0 and lon == 0.0) and auto_detect:
        from manomonitor.utils.geolocation import auto_detect_location

        location = await auto_detect_location(
            google_api_key=settings.google_geolocation_api_key or None,
            interface=settings.wifi_interface,
            gps_device=settings.gps_device or None,
            gps_enabled=settings.gps_enabled,
        )
        if location:
            lat = location.latitude
            lon = location.longitude
            if location.accuracy < 10:
                method = f"GPS ({location.accuracy:.1f}m)"
            elif location.accuracy < 100:
                method = f"WiFi (~{int(location.accuracy)}m)"
            else:
                method = f"IP (~{int(location.accuracy/1000)}km)"

    if lat == 0.0 and lon == 0.0:
        raise HTTPException(
            status_code=400,
            detail="Monitor location not configured and auto-detection failed. Set WHOSHERE_MONITOR_LATITUDE and WHOSHERE_MONITOR_LONGITUDE in .env",
        )

    # Get or create API key
    api_key = settings.monitor_api_key or secrets.token_hex(32)

    # Check for existing local monitor
    result = await db.execute(select(Monitor).where(Monitor.is_local == True))
    monitor = result.scalar_one_or_none()

    if monitor:
        # Update existing
        monitor.name = settings.monitor_name
        monitor.latitude = lat
        monitor.longitude = lon
        monitor.api_key = api_key
        monitor.last_seen = datetime.utcnow()
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

    await db.flush()

    logger.info(f"Local monitor '{monitor.name}' set up at ({lat}, {lon}) via {method}")

    return MonitorResponse(
        id=monitor.id,
        name=monitor.name,
        latitude=monitor.latitude,
        longitude=monitor.longitude,
        is_active=monitor.is_active,
        is_local=monitor.is_local,
        is_online=monitor.is_online,
        last_seen=monitor.last_seen,
    )


# =============================================================================
# Settings Endpoints
# =============================================================================


class SettingsResponse(BaseModel):
    """Response model for application settings."""
    log_retention_days: int
    monitor_latitude: float
    monitor_longitude: float
    monitor_name: str
    presence_timeout_minutes: int
    notification_cooldown_minutes: int
    default_signal_threshold: int
    signal_tx_power: int
    signal_path_loss: float
    signal_averaging_window: int
    wifi_interface: str


class SettingsUpdateRequest(BaseModel):
    """Request model for updating settings."""
    log_retention_days: Optional[int] = Field(None, ge=0, le=365)
    monitor_latitude: Optional[float] = Field(None, ge=-90, le=90)
    monitor_longitude: Optional[float] = Field(None, ge=-180, le=180)
    monitor_name: Optional[str] = Field(None, max_length=100)
    presence_timeout_minutes: Optional[int] = Field(None, ge=1, le=1440)
    notification_cooldown_minutes: Optional[int] = Field(None, ge=1, le=1440)
    default_signal_threshold: Optional[int] = Field(None, ge=-100, le=0)
    signal_tx_power: Optional[int] = Field(None, ge=-100, le=0)
    signal_path_loss: Optional[float] = Field(None, ge=1.5, le=6.0)
    signal_averaging_window: Optional[int] = Field(None, ge=1, le=20)
    wifi_interface: Optional[str] = Field(None, max_length=50)


@router.get("/settings", response_model=SettingsResponse)
async def get_settings(
    db: AsyncSession = Depends(get_db),
):
    """Get current application settings."""
    # Get DB-stored settings (override defaults)
    db_config = await get_all_config(db)

    return SettingsResponse(
        log_retention_days=int(db_config.get("log_retention_days", settings.log_retention_days)),
        monitor_latitude=float(db_config.get("monitor_latitude", settings.monitor_latitude)),
        monitor_longitude=float(db_config.get("monitor_longitude", settings.monitor_longitude)),
        monitor_name=db_config.get("monitor_name", settings.monitor_name),
        presence_timeout_minutes=int(db_config.get("presence_timeout_minutes", settings.presence_timeout_minutes)),
        notification_cooldown_minutes=int(db_config.get("notification_cooldown_minutes", settings.notification_cooldown_minutes)),
        default_signal_threshold=int(db_config.get("default_signal_threshold", settings.default_signal_threshold)),
        signal_tx_power=int(db_config.get("signal_tx_power", settings.signal_tx_power)),
        signal_path_loss=float(db_config.get("signal_path_loss", settings.signal_path_loss)),
        signal_averaging_window=int(db_config.get("signal_averaging_window", settings.signal_averaging_window)),
        wifi_interface=db_config.get("wifi_interface", settings.wifi_interface),
    )


@router.patch("/settings", response_model=SettingsResponse)
async def update_settings(
    data: SettingsUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update application settings."""
    from sqlalchemy import select
    from manomonitor.database.models import Monitor

    # Update each provided setting
    updated = []

    if data.log_retention_days is not None:
        await set_config(db, "log_retention_days", str(data.log_retention_days))
        settings.log_retention_days = data.log_retention_days
        updated.append("log_retention_days")

    if data.monitor_latitude is not None:
        await set_config(db, "monitor_latitude", str(data.monitor_latitude))
        settings.monitor_latitude = data.monitor_latitude
        updated.append("monitor_latitude")

    if data.monitor_longitude is not None:
        await set_config(db, "monitor_longitude", str(data.monitor_longitude))
        settings.monitor_longitude = data.monitor_longitude
        updated.append("monitor_longitude")

    if data.monitor_name is not None:
        await set_config(db, "monitor_name", data.monitor_name)
        settings.monitor_name = data.monitor_name
        updated.append("monitor_name")

    if data.presence_timeout_minutes is not None:
        await set_config(db, "presence_timeout_minutes", str(data.presence_timeout_minutes))
        settings.presence_timeout_minutes = data.presence_timeout_minutes
        updated.append("presence_timeout_minutes")

    if data.notification_cooldown_minutes is not None:
        await set_config(db, "notification_cooldown_minutes", str(data.notification_cooldown_minutes))
        settings.notification_cooldown_minutes = data.notification_cooldown_minutes
        updated.append("notification_cooldown_minutes")

    if data.default_signal_threshold is not None:
        await set_config(db, "default_signal_threshold", str(data.default_signal_threshold))
        settings.default_signal_threshold = data.default_signal_threshold
        updated.append("default_signal_threshold")

    if data.signal_tx_power is not None:
        await set_config(db, "signal_tx_power", str(data.signal_tx_power))
        settings.signal_tx_power = data.signal_tx_power
        updated.append("signal_tx_power")

    if data.signal_path_loss is not None:
        await set_config(db, "signal_path_loss", str(data.signal_path_loss))
        settings.signal_path_loss = data.signal_path_loss
        updated.append("signal_path_loss")

    if data.signal_averaging_window is not None:
        await set_config(db, "signal_averaging_window", str(data.signal_averaging_window))
        settings.signal_averaging_window = data.signal_averaging_window
        updated.append("signal_averaging_window")

    if data.wifi_interface is not None:
        await set_config(db, "wifi_interface", data.wifi_interface)
        settings.wifi_interface = data.wifi_interface
        updated.append("wifi_interface")

    # If location changed, update local monitor if it exists
    if "monitor_latitude" in updated or "monitor_longitude" in updated:
        result = await db.execute(select(Monitor).where(Monitor.is_local == True))
        local_monitor = result.scalar_one_or_none()
        if local_monitor:
            local_monitor.latitude = settings.monitor_latitude
            local_monitor.longitude = settings.monitor_longitude
            local_monitor.last_seen = datetime.utcnow()
            logger.info(f"Updated local monitor location to ({settings.monitor_latitude}, {settings.monitor_longitude})")

    if "monitor_name" in updated:
        result = await db.execute(select(Monitor).where(Monitor.is_local == True))
        local_monitor = result.scalar_one_or_none()
        if local_monitor:
            local_monitor.name = settings.monitor_name

    logger.info(f"Settings updated: {', '.join(updated)}")

    # Return current settings
    return SettingsResponse(
        log_retention_days=settings.log_retention_days,
        monitor_latitude=settings.monitor_latitude,
        monitor_longitude=settings.monitor_longitude,
        monitor_name=settings.monitor_name,
        presence_timeout_minutes=settings.presence_timeout_minutes,
        notification_cooldown_minutes=settings.notification_cooldown_minutes,
        default_signal_threshold=settings.default_signal_threshold,
        signal_tx_power=settings.signal_tx_power,
        signal_path_loss=settings.signal_path_loss,
        signal_averaging_window=settings.signal_averaging_window,
        wifi_interface=settings.wifi_interface,
    )
