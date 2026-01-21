"""Database CRUD (Create, Read, Update, Delete) operations."""

import logging
from datetime import datetime, timedelta
from typing import Optional, Sequence

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from manomonitor.config import settings
from manomonitor.database.models import Asset, Config, NotificationLog, ProbeLog, SSIDHistory

logger = logging.getLogger(__name__)


# =============================================================================
# Asset Operations
# =============================================================================


async def get_asset_by_mac(db: AsyncSession, mac_address: str) -> Optional[Asset]:
    """Get an asset by MAC address."""
    result = await db.execute(
        select(Asset).where(Asset.mac_address == mac_address.upper())
    )
    return result.scalar_one_or_none()


async def get_asset_by_id(db: AsyncSession, asset_id: int) -> Optional[Asset]:
    """Get an asset by ID."""
    result = await db.execute(select(Asset).where(Asset.id == asset_id))
    return result.scalar_one_or_none()


async def get_all_assets(
    db: AsyncSession,
    limit: int = 100,
    offset: int = 0,
    include_hidden: bool = False,
    search: Optional[str] = None,
    notify_only: bool = False,
    present_only: bool = False,
) -> Sequence[Asset]:
    """Get all assets with optional filtering."""
    query = select(Asset)

    # Apply filters
    if not include_hidden:
        query = query.where(Asset.is_hidden == False)

    if search:
        search_pattern = f"%{search}%"
        query = query.where(
            or_(
                Asset.mac_address.ilike(search_pattern),
                Asset.nickname.ilike(search_pattern),
                Asset.vendor.ilike(search_pattern),
                Asset.device_type.ilike(search_pattern),
                Asset.notes.ilike(search_pattern),
            )
        )

    if notify_only:
        query = query.where(Asset.notify_enabled == True)

    if present_only:
        # Consider "present" if seen within presence_timeout_minutes
        cutoff = datetime.utcnow() - timedelta(minutes=settings.presence_timeout_minutes)
        query = query.where(Asset.last_seen >= cutoff)

    # Order by last seen (most recent first)
    query = query.order_by(Asset.last_seen.desc()).offset(offset).limit(limit)

    result = await db.execute(query)
    return result.scalars().all()


async def get_assets_count(
    db: AsyncSession,
    include_hidden: bool = False,
    notify_only: bool = False,
) -> int:
    """Get total count of assets."""
    query = select(func.count(Asset.id))

    if not include_hidden:
        query = query.where(Asset.is_hidden == False)
    if notify_only:
        query = query.where(Asset.notify_enabled == True)

    result = await db.execute(query)
    return result.scalar() or 0


async def create_or_update_asset(
    db: AsyncSession,
    mac_address: str,
    signal_strength: Optional[int] = None,
    ssid: Optional[str] = None,
) -> tuple[Asset, bool]:
    """
    Create a new asset or update an existing one.

    Returns tuple of (asset, is_new).
    """
    mac_address = mac_address.upper()
    asset = await get_asset_by_mac(db, mac_address)
    is_new = asset is None

    if is_new:
        # Look up vendor info using enhanced multi-source lookup
        from manomonitor.utils.vendor import lookup_vendor

        vendor_info = await lookup_vendor(mac_address)

        # Create new asset with enhanced vendor info
        asset = Asset(
            mac_address=mac_address,
            signal_threshold=settings.default_signal_threshold,
            last_signal_strength=signal_strength,
            vendor=vendor_info.vendor,
            device_type=vendor_info.device_type,
            vendor_country=vendor_info.country,
            is_virtual_machine=vendor_info.is_virtual_machine,
        )
        db.add(asset)
        await db.flush()

        # Log with enhanced info
        device_info = vendor_info.vendor or "Unknown"
        if vendor_info.device_type:
            device_info += f" ({vendor_info.device_type})"
        if vendor_info.country:
            device_info += f" [{vendor_info.country}]"
        if vendor_info.is_virtual_machine:
            device_info += " [VM]"
        logger.info(f"New device discovered: {mac_address} - {device_info} [Source: {vendor_info.source}]")
    else:
        # Update existing asset
        asset.last_seen = datetime.utcnow()
        asset.times_seen += 1
        if signal_strength is not None:
            asset.last_signal_strength = signal_strength

    # Log the probe
    probe_log = ProbeLog(
        asset_id=asset.id,
        signal_strength=signal_strength,
        ssid=ssid,
    )
    db.add(probe_log)

    # Update SSID history if SSID is provided
    if ssid:
        await update_ssid_history(db, asset.id, ssid)

    return asset, is_new


async def update_asset(
    db: AsyncSession,
    asset_id: int,
    nickname: Optional[str] = None,
    vendor: Optional[str] = None,
    device_type: Optional[str] = None,
    notify_enabled: Optional[bool] = None,
    signal_threshold: Optional[int] = None,
    notes: Optional[str] = None,
    is_hidden: Optional[bool] = None,
) -> Optional[Asset]:
    """Update an asset's settings."""
    asset = await get_asset_by_id(db, asset_id)
    if not asset:
        return None

    if nickname is not None:
        asset.nickname = nickname if nickname.strip() else None
    if vendor is not None:
        asset.vendor = vendor if vendor.strip() else None
    if device_type is not None:
        asset.device_type = device_type if device_type.strip() else None
    if notify_enabled is not None:
        asset.notify_enabled = notify_enabled
    if signal_threshold is not None:
        asset.signal_threshold = signal_threshold
    if notes is not None:
        asset.notes = notes if notes.strip() else None
    if is_hidden is not None:
        asset.is_hidden = is_hidden

    return asset


async def delete_asset(db: AsyncSession, asset_id: int) -> bool:
    """Delete an asset and all related data."""
    result = await db.execute(delete(Asset).where(Asset.id == asset_id))
    return result.rowcount > 0


async def update_asset_notification_time(db: AsyncSession, asset_id: int) -> None:
    """Update the last notification time for an asset."""
    await db.execute(
        update(Asset)
        .where(Asset.id == asset_id)
        .values(last_notified=datetime.utcnow())
    )


# =============================================================================
# SSID History Operations
# =============================================================================


async def update_ssid_history(db: AsyncSession, asset_id: int, ssid: str) -> None:
    """Update SSID history for an asset."""
    if not ssid or not ssid.strip():
        return

    result = await db.execute(
        select(SSIDHistory).where(
            SSIDHistory.asset_id == asset_id,
            SSIDHistory.ssid == ssid,
        )
    )
    ssid_entry = result.scalar_one_or_none()

    if ssid_entry:
        ssid_entry.last_seen = datetime.utcnow()
        ssid_entry.times_seen += 1
    else:
        ssid_entry = SSIDHistory(asset_id=asset_id, ssid=ssid)
        db.add(ssid_entry)


async def get_ssid_history(
    db: AsyncSession, asset_id: int
) -> Sequence[SSIDHistory]:
    """Get all SSIDs probed by an asset."""
    result = await db.execute(
        select(SSIDHistory)
        .where(SSIDHistory.asset_id == asset_id)
        .order_by(SSIDHistory.times_seen.desc())
    )
    return result.scalars().all()


# =============================================================================
# Notification Logic
# =============================================================================


async def get_assets_to_notify(db: AsyncSession) -> Sequence[Asset]:
    """
    Get assets that should trigger a notification.

    Criteria:
    - notify_enabled is True
    - last_seen within presence_timeout_minutes
    - signal_strength >= signal_threshold
    - last_notified is None OR was more than notification_cooldown_minutes ago
    """
    now = datetime.utcnow()
    presence_cutoff = now - timedelta(minutes=settings.presence_timeout_minutes)
    cooldown_cutoff = now - timedelta(minutes=settings.notification_cooldown_minutes)

    result = await db.execute(
        select(Asset).where(
            Asset.notify_enabled == True,
            Asset.last_seen >= presence_cutoff,
            Asset.last_signal_strength >= Asset.signal_threshold,
            or_(
                Asset.last_notified == None,
                Asset.last_notified <= cooldown_cutoff,
            ),
        )
    )
    return result.scalars().all()


async def get_newly_discovered_assets(
    db: AsyncSession, since_minutes: int = 5
) -> Sequence[Asset]:
    """Get assets discovered within the last N minutes."""
    cutoff = datetime.utcnow() - timedelta(minutes=since_minutes)
    result = await db.execute(
        select(Asset)
        .where(Asset.first_seen >= cutoff)
        .order_by(Asset.first_seen.desc())
    )
    return result.scalars().all()


# =============================================================================
# Probe Log Operations
# =============================================================================


async def get_probe_logs(
    db: AsyncSession,
    asset_id: Optional[int] = None,
    limit: int = 100,
    since: Optional[datetime] = None,
) -> Sequence[ProbeLog]:
    """Get probe logs with optional filtering."""
    query = select(ProbeLog)

    if asset_id:
        query = query.where(ProbeLog.asset_id == asset_id)
    if since:
        query = query.where(ProbeLog.timestamp >= since)

    query = query.order_by(ProbeLog.timestamp.desc()).limit(limit)

    result = await db.execute(query)
    return result.scalars().all()


async def purge_old_logs(db: AsyncSession, days: int) -> int:
    """Delete probe logs older than N days. Returns count of deleted rows."""
    if days <= 0:
        return 0

    cutoff = datetime.utcnow() - timedelta(days=days)
    result = await db.execute(
        delete(ProbeLog).where(ProbeLog.timestamp < cutoff)
    )
    count = result.rowcount
    if count > 0:
        logger.info(f"Purged {count} probe logs older than {days} days")
    return count


# =============================================================================
# Notification Log Operations
# =============================================================================


async def log_notification(
    db: AsyncSession,
    asset_id: Optional[int],
    notification_type: str,
    status: str,
    message: Optional[str] = None,
    error: Optional[str] = None,
) -> NotificationLog:
    """Log a notification attempt."""
    log_entry = NotificationLog(
        asset_id=asset_id,
        notification_type=notification_type,
        status=status,
        message=message,
        error=error,
    )
    db.add(log_entry)
    return log_entry


async def get_notification_logs(
    db: AsyncSession,
    limit: int = 50,
    asset_id: Optional[int] = None,
) -> Sequence[NotificationLog]:
    """Get recent notification logs."""
    query = select(NotificationLog)

    if asset_id:
        query = query.where(NotificationLog.asset_id == asset_id)

    query = query.order_by(NotificationLog.timestamp.desc()).limit(limit)

    result = await db.execute(query)
    return result.scalars().all()


# =============================================================================
# Statistics
# =============================================================================


async def get_statistics(db: AsyncSession) -> dict:
    """Get overall statistics."""
    now = datetime.utcnow()
    presence_cutoff = now - timedelta(minutes=settings.presence_timeout_minutes)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Total assets
    total_assets = await db.execute(select(func.count(Asset.id)))

    # Present now
    present_now = await db.execute(
        select(func.count(Asset.id)).where(Asset.last_seen >= presence_cutoff)
    )

    # With notifications enabled
    notify_enabled = await db.execute(
        select(func.count(Asset.id)).where(Asset.notify_enabled == True)
    )

    # Probes today
    probes_today = await db.execute(
        select(func.count(ProbeLog.id)).where(ProbeLog.timestamp >= today_start)
    )

    # New devices today
    new_today = await db.execute(
        select(func.count(Asset.id)).where(Asset.first_seen >= today_start)
    )

    return {
        "total_devices": total_assets.scalar() or 0,
        "present_now": present_now.scalar() or 0,
        "notifications_enabled": notify_enabled.scalar() or 0,
        "probes_today": probes_today.scalar() or 0,
        "new_devices_today": new_today.scalar() or 0,
    }


# =============================================================================
# Vendor Operations
# =============================================================================


async def update_asset_vendor(
    db: AsyncSession,
    asset_id: int,
    vendor: Optional[str],
    device_type: Optional[str],
) -> Optional[Asset]:
    """Update vendor info for an asset."""
    asset = await get_asset_by_id(db, asset_id)
    if not asset:
        return None

    asset.vendor = vendor
    asset.device_type = device_type
    return asset


async def get_assets_without_vendor(db: AsyncSession) -> Sequence[Asset]:
    """Get all assets that don't have vendor info."""
    result = await db.execute(
        select(Asset).where(Asset.vendor == None)
    )
    return result.scalars().all()


async def refresh_all_vendor_info(db: AsyncSession) -> int:
    """
    Refresh vendor info for all assets.

    Returns the number of assets updated.
    """
    from manomonitor.utils.vendor import lookup_vendor

    assets = await db.execute(select(Asset))
    updated = 0

    for asset in assets.scalars():
        vendor_info = await lookup_vendor(asset.mac_address)
        if vendor_info.vendor != asset.vendor or vendor_info.device_type != asset.device_type:
            asset.vendor = vendor_info.vendor
            asset.device_type = vendor_info.device_type
            updated += 1
            logger.debug(f"Updated vendor for {asset.mac_address}: {vendor_info.vendor}")

    if updated > 0:
        logger.info(f"Updated vendor info for {updated} devices")

    return updated


# =============================================================================
# Config Operations
# =============================================================================


async def get_config(db: AsyncSession, key: str) -> Optional[str]:
    """Get a config value by key."""
    result = await db.execute(select(Config).where(Config.key == key))
    config = result.scalar_one_or_none()
    return config.value if config else None


async def set_config(
    db: AsyncSession,
    key: str,
    value: str,
    description: Optional[str] = None,
) -> Config:
    """Set a config value (create or update)."""
    result = await db.execute(select(Config).where(Config.key == key))
    config = result.scalar_one_or_none()

    if config:
        config.value = value
        if description is not None:
            config.description = description
    else:
        config = Config(key=key, value=value, description=description)
        db.add(config)

    return config


async def get_all_config(db: AsyncSession) -> dict[str, str]:
    """Get all config values as a dictionary."""
    result = await db.execute(select(Config))
    return {c.key: c.value for c in result.scalars()}


async def delete_config(db: AsyncSession, key: str) -> bool:
    """Delete a config value."""
    result = await db.execute(delete(Config).where(Config.key == key))
    return result.rowcount > 0
