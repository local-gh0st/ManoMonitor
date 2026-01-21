"""Web views for HTMX-based UI."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from manomonitor.capture.monitor import get_capture
from manomonitor.config import settings
from manomonitor.database.connection import get_db
from manomonitor.database.crud import (
    get_all_assets,
    get_asset_by_id,
    get_assets_count,
    get_notification_logs,
    get_ssid_history,
    get_statistics,
    update_asset,
)
from manomonitor.notifications import get_notification_manager

router = APIRouter(tags=["web"])

# Initialize templates
templates = Jinja2Templates(directory=str(settings.templates_dir))


# Custom template filters
def format_datetime(value: datetime | None) -> str:
    """Format datetime for display."""
    if value is None:
        return "Never"
    return value.strftime("%Y-%m-%d %H:%M:%S")


def format_relative_time(minutes: int) -> str:
    """Format minutes as relative time string."""
    if minutes < 0:
        return "Unknown"
    if minutes == 0:
        return "Just now"
    if minutes == 1:
        return "1 minute ago"
    if minutes < 60:
        return f"{minutes} minutes ago"
    hours = minutes // 60
    if hours == 1:
        return "1 hour ago"
    if hours < 24:
        return f"{hours} hours ago"
    days = hours // 24
    if days == 1:
        return "1 day ago"
    return f"{days} days ago"


def format_signal(signal: int | None) -> str:
    """Format signal strength with quality indicator."""
    if signal is None:
        return "N/A"
    if signal >= -50:
        quality = "Excellent"
    elif signal >= -60:
        quality = "Good"
    elif signal >= -70:
        quality = "Fair"
    else:
        quality = "Weak"
    return f"{signal} dBm ({quality})"


# Register filters
templates.env.filters["datetime"] = format_datetime
templates.env.filters["relative_time"] = format_relative_time
templates.env.filters["signal"] = format_signal

# Register globals (built-in functions for templates)
templates.env.globals["min"] = min
templates.env.globals["max"] = max


# =============================================================================
# Main Pages
# =============================================================================


@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Main dashboard page."""
    stats = await get_statistics(db)
    capture = get_capture()
    manager = get_notification_manager()

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "stats": stats,
            "capture_running": capture.is_running,
            "notifications_running": manager.is_running,
            "settings": settings,
        },
    )


@router.get("/devices", response_class=HTMLResponse)
async def devices_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Devices list page."""
    return templates.TemplateResponse(
        "devices.html",
        {"request": request, "settings": settings},
    )


@router.get("/device/{asset_id}", response_class=HTMLResponse)
async def device_detail_page(
    request: Request,
    asset_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Device detail page."""
    asset = await get_asset_by_id(db, asset_id)
    if not asset:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": "Device not found"},
            status_code=404,
        )

    ssids = await get_ssid_history(db, asset_id)

    return templates.TemplateResponse(
        "device_detail.html",
        {
            "request": request,
            "asset": asset,
            "ssids": ssids,
            "settings": settings,
        },
    )


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
):
    """Settings page."""
    manager = get_notification_manager()

    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "settings": settings,
            "notifiers": [n.name for n in manager.notifiers],
        },
    )


@router.get("/notifications", response_class=HTMLResponse)
async def notifications_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Notifications log page."""
    logs = await get_notification_logs(db, limit=100)

    return templates.TemplateResponse(
        "notifications.html",
        {"request": request, "logs": logs},
    )


@router.get("/map", response_class=HTMLResponse)
async def map_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Device location map page."""
    from sqlalchemy import select
    from manomonitor.database.models import Monitor

    # Get monitors
    result = await db.execute(select(Monitor).where(Monitor.is_active == True))
    monitors = result.scalars().all()

    # Calculate center
    if monitors:
        center_lat = sum(m.latitude for m in monitors) / len(monitors)
        center_lon = sum(m.longitude for m in monitors) / len(monitors)
    elif settings.monitor_latitude != 0:
        center_lat = settings.monitor_latitude
        center_lon = settings.monitor_longitude
    else:
        center_lat = 0.0
        center_lon = 0.0

    return templates.TemplateResponse(
        "map.html",
        {
            "request": request,
            "monitors": monitors,
            "center_lat": center_lat,
            "center_lon": center_lon,
            "map_enabled": settings.map_enabled,
            "settings": settings,
        },
    )


# =============================================================================
# HTMX Partials
# =============================================================================


@router.get("/htmx/devices-table", response_class=HTMLResponse)
async def htmx_devices_table(
    request: Request,
    search: Optional[str] = Query(None),
    show_hidden: bool = Query(False),
    notify_only: bool = Query(False),
    present_only: bool = Query(False),
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=10, le=100),
    db: AsyncSession = Depends(get_db),
):
    """HTMX partial for devices table."""
    offset = (page - 1) * per_page

    assets = await get_all_assets(
        db,
        limit=per_page,
        offset=offset,
        search=search,
        include_hidden=show_hidden,
        notify_only=notify_only,
        present_only=present_only,
    )
    total = await get_assets_count(db, include_hidden=show_hidden, notify_only=notify_only)
    total_pages = (total + per_page - 1) // per_page

    return templates.TemplateResponse(
        "partials/devices_table.html",
        {
            "request": request,
            "assets": assets,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "search": search,
            "show_hidden": show_hidden,
            "notify_only": notify_only,
            "present_only": present_only,
        },
    )


@router.get("/htmx/stats", response_class=HTMLResponse)
async def htmx_stats(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """HTMX partial for stats display."""
    stats = await get_statistics(db)
    capture = get_capture()

    return templates.TemplateResponse(
        "partials/stats.html",
        {
            "request": request,
            "stats": stats,
            "capture_running": capture.is_running,
        },
    )


@router.get("/htmx/device-row/{asset_id}", response_class=HTMLResponse)
async def htmx_device_row(
    request: Request,
    asset_id: int,
    db: AsyncSession = Depends(get_db),
):
    """HTMX partial for a single device row."""
    asset = await get_asset_by_id(db, asset_id)
    if not asset:
        return HTMLResponse("")

    return templates.TemplateResponse(
        "partials/device_row.html",
        {"request": request, "asset": asset},
    )


@router.get("/htmx/device-edit/{asset_id}", response_class=HTMLResponse)
async def htmx_device_edit_form(
    request: Request,
    asset_id: int,
    db: AsyncSession = Depends(get_db),
):
    """HTMX partial for device edit form."""
    asset = await get_asset_by_id(db, asset_id)
    if not asset:
        return HTMLResponse("Device not found", status_code=404)

    return templates.TemplateResponse(
        "partials/device_edit_form.html",
        {"request": request, "asset": asset, "settings": settings},
    )


@router.post("/htmx/device-update/{asset_id}", response_class=HTMLResponse)
async def htmx_device_update(
    request: Request,
    asset_id: int,
    nickname: str = Form(""),
    notify_enabled: bool = Form(False),
    signal_threshold: int = Form(-65),
    notes: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """HTMX handler for device update."""
    asset = await update_asset(
        db,
        asset_id=asset_id,
        nickname=nickname if nickname.strip() else None,
        notify_enabled=notify_enabled,
        signal_threshold=signal_threshold,
        notes=notes if notes.strip() else None,
    )

    if not asset:
        return HTMLResponse("Device not found", status_code=404)

    return templates.TemplateResponse(
        "partials/device_row.html",
        {"request": request, "asset": asset},
    )


@router.post("/htmx/toggle-notify/{asset_id}", response_class=HTMLResponse)
async def htmx_toggle_notify(
    request: Request,
    asset_id: int,
    db: AsyncSession = Depends(get_db),
):
    """HTMX handler to toggle notifications for a device."""
    asset = await get_asset_by_id(db, asset_id)
    if not asset:
        return HTMLResponse("Device not found", status_code=404)

    await update_asset(db, asset_id=asset_id, notify_enabled=not asset.notify_enabled)

    # Re-fetch to get updated state
    asset = await get_asset_by_id(db, asset_id)

    return templates.TemplateResponse(
        "partials/device_row.html",
        {"request": request, "asset": asset},
    )


@router.post("/htmx/toggle-hidden/{asset_id}", response_class=HTMLResponse)
async def htmx_toggle_hidden(
    request: Request,
    asset_id: int,
    db: AsyncSession = Depends(get_db),
):
    """HTMX handler to toggle hidden status for a device."""
    asset = await get_asset_by_id(db, asset_id)
    if not asset:
        return HTMLResponse("Device not found", status_code=404)

    await update_asset(db, asset_id=asset_id, is_hidden=not asset.is_hidden)

    # Return empty to remove from list if now hidden
    asset = await get_asset_by_id(db, asset_id)
    if asset.is_hidden:
        return HTMLResponse("")

    return templates.TemplateResponse(
        "partials/device_row.html",
        {"request": request, "asset": asset},
    )


@router.get("/htmx/present-devices", response_class=HTMLResponse)
async def htmx_present_devices(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """HTMX partial for present devices list (dashboard widget)."""
    assets = await get_all_assets(db, limit=10, present_only=True)

    return templates.TemplateResponse(
        "partials/present_devices.html",
        {"request": request, "assets": assets},
    )
