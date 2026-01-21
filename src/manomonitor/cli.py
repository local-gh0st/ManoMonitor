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

    # Check database directory
    db_path = settings.get_database_path()
    if db_path:
        if db_path.parent.exists():
            console.print(f"[green]✓[/green] Database directory exists: {db_path.parent}")
        else:
            console.print(f"[yellow]![/yellow] Database directory will be created: {db_path.parent}")

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


if __name__ == "__main__":
    app()
