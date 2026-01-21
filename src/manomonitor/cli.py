"""Command-line interface for ManoMonitor."""

import asyncio
import sys
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from manomonitor import __version__
from manomonitor.config import settings

app = typer.Typer(
    name="manomonitor",
    help="WiFi-based presence detection and proximity alert system",
    add_completion=False,
)
console = Console()


@app.command()
def run(
    host: str = typer.Option(settings.host, "--host", "-h", help="Host to bind to"),
    port: int = typer.Option(settings.port, "--port", "-p", help="Port to bind to"),
    debug: bool = typer.Option(settings.debug, "--debug", "-d", help="Enable debug mode"),
    no_capture: bool = typer.Option(False, "--no-capture", help="Disable WiFi capture on startup"),
):
    """Start the ManoMonitor server."""
    import uvicorn

    # Override settings
    settings.host = host
    settings.port = port
    settings.debug = debug
    settings.capture_enabled = not no_capture

    console.print(f"[bold green]Starting ManoMonitor v{__version__}[/bold green]")
    console.print(f"Server: http://{host}:{port}")
    console.print(f"Debug: {debug}")
    console.print(f"WiFi Capture: {'disabled' if no_capture else 'enabled'}")
    console.print()

    uvicorn.run(
        "manomonitor.main:app",
        host=host,
        port=port,
        reload=debug,
        log_level="debug" if debug else "info",
    )


@app.command()
def check():
    """Check system dependencies and configuration."""
    import subprocess
    from pathlib import Path
    from manomonitor.capture.monitor import ProbeCapture

    console.print("[bold]Checking ManoMonitor dependencies...[/bold]\n")

    # Check tshark
    ok, msg = ProbeCapture.check_dependencies()
    if ok:
        console.print("[green]✓[/green] tshark installed")
    else:
        console.print(f"[red]✗[/red] {msg}")

    # Check WiFi interface
    ok, msg = ProbeCapture.check_interface(settings.wifi_interface)
    if ok:
        console.print(f"[green]✓[/green] WiFi interface {settings.wifi_interface} available")
    else:
        console.print(f"[red]✗[/red] {msg}")

    # Check interface safety for monitor mode
    console.print("\n[bold]Interface Safety Check:[/bold]")
    script_path = Path(__file__).parent.parent.parent / "scripts" / "check_wifi_safety.py"
    if script_path.exists():
        try:
            result = subprocess.run(
                [sys.executable, str(script_path), settings.wifi_interface],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.stdout:
                for line in result.stdout.split('\n'):
                    if line.strip():
                        console.print(line)

            if result.returncode == 1:
                console.print("\n[red]✗[/red] Interface is NOT SAFE for monitor mode!")
                console.print("[yellow]⚠️  Using this interface will disconnect your network[/yellow]")
                console.print("\n[bold]Recommendations:[/bold]")
                console.print("  • Use a USB WiFi adapter for monitoring")
                console.print("  • Connect via Ethernet cable")
                console.print("  • Disable WiFi capture: MANOMONITOR_CAPTURE_ENABLED=false")
            elif result.returncode == 2:
                console.print("\n[yellow]⚠️  Interface is currently connected - use with caution[/yellow]")
            else:
                console.print("\n[green]✓[/green] Interface is safe for monitor mode")
        except Exception as e:
            console.print(f"[yellow]![/yellow] Could not check interface safety: {e}")
    else:
        console.print("[yellow]![/yellow] Safety check script not found")

    # Check database directory
    db_path = settings.get_database_path()
    if db_path:
        if db_path.parent.exists():
            console.print(f"\n[green]✓[/green] Database directory exists: {db_path.parent}")
        else:
            console.print(f"\n[yellow]![/yellow] Database directory will be created: {db_path.parent}")

    # Check notification configuration
    console.print("\n[bold]Notification Configuration:[/bold]")

    if settings.ifttt_enabled and settings.ifttt_webhook_key:
        console.print("[green]✓[/green] IFTTT configured")
    else:
        console.print("[yellow]![/yellow] IFTTT not configured")

    if settings.homeassistant_enabled and settings.homeassistant_token:
        console.print("[green]✓[/green] Home Assistant configured")
    else:
        console.print("[yellow]![/yellow] Home Assistant not configured")

    console.print()


@app.command()
def init_db():
    """Initialize the database."""

    async def _init():
        from manomonitor.database.connection import init_db as db_init

        await db_init()
        console.print("[green]✓[/green] Database initialized successfully")

    asyncio.run(_init())


@app.command()
def devices(
    limit: int = typer.Option(20, "--limit", "-l", help="Number of devices to show"),
    present: bool = typer.Option(False, "--present", "-p", help="Show only present devices"),
):
    """List tracked devices."""

    async def _list():
        from manomonitor.database.connection import get_db_context, init_db
        from manomonitor.database.crud import get_all_assets

        await init_db()

        async with get_db_context() as db:
            assets = await get_all_assets(db, limit=limit, present_only=present)

            if not assets:
                console.print("No devices found")
                return

            table = Table(title="Tracked Devices")
            table.add_column("ID", style="dim")
            table.add_column("Name")
            table.add_column("MAC Address")
            table.add_column("Vendor")
            table.add_column("Type")
            table.add_column("Signal")
            table.add_column("Last Seen")
            table.add_column("Notify")

            for asset in assets:
                signal = f"{asset.last_signal_strength} dBm" if asset.last_signal_strength else "N/A"
                notify = "[green]Yes[/green]" if asset.notify_enabled else "[dim]No[/dim]"
                vendor = asset.vendor_display if asset.vendor else "[dim]Unknown[/dim]"
                device_type = asset.device_type or "[dim]Unknown[/dim]"

                # Format last seen
                if asset.is_present:
                    last_seen = f"[green]{asset.minutes_since_seen}m ago[/green]"
                else:
                    last_seen = f"[dim]{asset.minutes_since_seen}m ago[/dim]"

                table.add_row(
                    str(asset.id),
                    asset.display_name,
                    asset.mac_address,
                    vendor,
                    device_type,
                    signal,
                    last_seen,
                    notify,
                )

            console.print(table)

    asyncio.run(_list())


@app.command()
def test_notify(
    provider: Optional[str] = typer.Option(None, "--provider", "-p", help="Test specific provider (ifttt, homeassistant)"),
):
    """Send a test notification."""

    async def _test():
        from manomonitor.notifications import get_notification_manager

        manager = get_notification_manager()

        if not manager.notifiers:
            console.print("[red]No notification providers configured[/red]")
            return

        if provider:
            notifier = manager.get_notifier(provider)
            if not notifier:
                console.print(f"[red]Provider '{provider}' not found[/red]")
                return
            result = await notifier.test()
            if result.success:
                console.print(f"[green]✓[/green] {provider}: {result.message}")
            else:
                console.print(f"[red]✗[/red] {provider}: {result.error}")
        else:
            results = await manager.test_all()
            for name, result in results.items():
                if result.success:
                    console.print(f"[green]✓[/green] {name}: {result.message}")
                else:
                    console.print(f"[red]✗[/red] {name}: {result.error}")

    asyncio.run(_test())


@app.command()
def refresh_vendors():
    """Refresh vendor/manufacturer info for all devices."""

    async def _refresh():
        from manomonitor.database.connection import get_db_context, init_db
        from manomonitor.database.crud import refresh_all_vendor_info
        from manomonitor.utils.vendor import get_vendor_lookup

        await init_db()

        # Update vendor database first
        console.print("Updating vendor database from IEEE...")
        lookup = get_vendor_lookup()
        await lookup.update_database()

        console.print("Refreshing device vendor info...")
        async with get_db_context() as db:
            updated = await refresh_all_vendor_info(db)

        console.print(f"[green]✓[/green] Updated vendor info for {updated} devices")

    asyncio.run(_refresh())


@app.command()
def version():
    """Show version information."""
    console.print(f"ManoMonitor v{__version__}")


@app.command()
def config():
    """Show current configuration."""
    table = Table(title="ManoMonitor Configuration")
    table.add_column("Setting", style="cyan")
    table.add_column("Value")

    # Core settings
    table.add_row("Host", settings.host)
    table.add_row("Port", str(settings.port))
    table.add_row("Debug", str(settings.debug))
    table.add_row("WiFi Interface", settings.wifi_interface)
    table.add_row("Database", settings.database_url.split("///")[-1] if "sqlite" in settings.database_url else settings.database_url)

    # Detection settings
    table.add_row("Default Signal Threshold", f"{settings.default_signal_threshold} dBm")
    table.add_row("Presence Timeout", f"{settings.presence_timeout_minutes} minutes")
    table.add_row("Notification Cooldown", f"{settings.notification_cooldown_minutes} minutes")
    table.add_row("Notify New Devices", str(settings.notify_new_devices))

    # Notifications
    table.add_row("IFTTT Enabled", str(settings.ifttt_enabled))
    table.add_row("Home Assistant Enabled", str(settings.homeassistant_enabled))

    console.print(table)


@app.command()
def monitor_info():
    """Show this monitor's information and API key."""

    async def _show():
        from manomonitor.database.connection import get_db_context, init_db
        from manomonitor.database.models import Monitor
        from sqlalchemy import select

        await init_db()

        async with get_db_context() as db:
            # Get local monitor
            stmt = select(Monitor).where(Monitor.is_local == True)
            result = await db.execute(stmt)
            monitor = result.scalar_one_or_none()

            if not monitor:
                console.print("[yellow]Local monitor not initialized yet.[/yellow]")
                console.print("Start the server with 'manomonitor run' first.")
                return

            console.print("\n[bold]This Monitor's Information:[/bold]\n")

            table = Table(show_header=False, box=None)
            table.add_column("Key", style="cyan")
            table.add_column("Value")

            table.add_row("Name", monitor.name)
            table.add_row("Location", f"{monitor.latitude:.6f}, {monitor.longitude:.6f}")
            table.add_row("API Key", f"[bold green]{monitor.api_key}[/bold green]")
            table.add_row("Status", "[green]Local[/green]" if monitor.is_local else "Remote")
            table.add_row("Created", monitor.created_at.strftime("%Y-%m-%d %H:%M:%S"))

            console.print(table)
            console.print("\n[bold]Setup Instructions:[/bold]")
            console.print("1. Share the API key with secondary monitors")
            console.print("2. Secondary monitors use this to register and report readings")
            console.print(f"3. Registration URL: http://<this-ip>:{settings.port}/api/monitors/register\n")

    asyncio.run(_show())


@app.command()
def monitor_list():
    """List all registered monitors."""

    async def _list():
        from manomonitor.database.connection import get_db_context, init_db
        from manomonitor.database.models import Monitor
        from sqlalchemy import select

        await init_db()

        async with get_db_context() as db:
            stmt = select(Monitor).order_by(Monitor.is_local.desc(), Monitor.name)
            result = await db.execute(stmt)
            monitors = result.scalars().all()

            if not monitors:
                console.print("No monitors registered yet")
                return

            table = Table(title="Registered Monitors")
            table.add_column("Name", style="cyan")
            table.add_column("Location")
            table.add_column("Status")
            table.add_column("Type")
            table.add_column("Last Seen")

            for monitor in monitors:
                # Location
                location = f"{monitor.latitude:.4f}, {monitor.longitude:.4f}"

                # Status
                if monitor.is_local:
                    status = "[green]●[/green] Local"
                elif monitor.is_online:
                    status = "[green]●[/green] Online"
                else:
                    status = "[dim]●[/dim] Offline"

                # Type
                mon_type = "[bold]Primary[/bold]" if monitor.is_local else "Secondary"

                # Last seen
                if monitor.is_local:
                    last_seen = "N/A"
                elif monitor.last_seen:
                    delta = (asyncio.get_event_loop().time() - monitor.last_seen.timestamp()) / 60
                    last_seen = f"{int(delta)}m ago"
                else:
                    last_seen = "Never"

                table.add_row(
                    monitor.name,
                    location,
                    status,
                    mon_type,
                    last_seen,
                )

            console.print(table)
            console.print(f"\n[dim]Total: {len(monitors)} monitors ({sum(1 for m in monitors if m.is_online)} online)[/dim]")

    asyncio.run(_list())


@app.command()
def monitor_register(
    primary_url: str = typer.Argument(..., help="Primary monitor URL (e.g., http://192.168.1.100:8080)"),
    name: str = typer.Option(settings.monitor_name, "--name", "-n", help="Name for this monitor"),
    latitude: Optional[float] = typer.Option(None, "--lat", help="Monitor latitude"),
    longitude: Optional[float] = typer.Option(None, "--lon", help="Monitor longitude"),
):
    """Register this monitor with a primary monitor."""

    async def _register():
        import httpx

        # Get location
        lat = latitude or settings.monitor_latitude
        lon = longitude or settings.monitor_longitude

        if lat == 0.0 or lon == 0.0:
            console.print("[yellow]Warning: Monitor location is 0.0, 0.0[/yellow]")
            console.print("Set location in .env or use --lat and --lon flags")
            console.print("Example: --lat 37.7749 --lon -122.4194\n")

        console.print(f"Registering monitor '{name}' with primary at {primary_url}...")

        # Get API key from primary first
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Try to get primary's monitor info
                response = await client.get(f"{primary_url}/api/monitors")
                response.raise_for_status()
                monitors = response.json()

                # Find local/primary monitor
                primary_monitor = next((m for m in monitors if m.get("is_local")), None)
                if not primary_monitor:
                    console.print("[red]Could not find primary monitor's API key[/red]")
                    console.print("Run 'manomonitor monitor-info' on the primary to get the API key")
                    return

                api_key = primary_monitor.get("api_key")
                if not api_key:
                    console.print("[red]Primary monitor has no API key[/red]")
                    return

                # Register this monitor
                payload = {
                    "name": name,
                    "latitude": lat,
                    "longitude": lon,
                    "api_key": api_key,
                }

                response = await client.post(
                    f"{primary_url}/api/monitors/register",
                    json=payload,
                )
                response.raise_for_status()
                result = response.json()

                console.print(f"[green]✓[/green] Successfully registered monitor '{name}'")
                console.print(f"  Location: {lat:.6f}, {lon:.6f}")
                console.print(f"  API Key: {api_key}")

                # Save API key to settings
                console.print("\n[bold]Next steps:[/bold]")
                console.print(f"1. Add to .env: MANOMONITOR_MONITOR_API_KEY={api_key}")
                console.print(f"2. Start reporter: python3 scripts/secondary_reporter.py --primary-url {primary_url} --api-key {api_key}")

        except httpx.HTTPError as e:
            console.print(f"[red]✗[/red] Failed to register: {e}")
        except Exception as e:
            console.print(f"[red]✗[/red] Error: {e}")

    asyncio.run(_register())


if __name__ == "__main__":
    app()
