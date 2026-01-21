"""Configuration management using Pydantic Settings."""

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Calculate package root at module load time
# This is the directory containing pyproject.toml (3 levels up from this file)
# config.py -> manomonitor -> src -> WhosHere (root)
_PACKAGE_ROOT = Path(__file__).parent.parent.parent


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="MANOMONITOR_",
        case_sensitive=False,
    )

    # Application
    app_name: str = "ManoMonitor"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8080
    secret_key: str = Field(default="change-me-in-production-use-random-string")

    # Database (use empty string for default SQLite in data_dir)
    database_url: str = Field(
        default="",
        description="Database connection string. Leave empty for default SQLite, or use postgresql+asyncpg:// for PostgreSQL",
    )

    # WiFi Capture
    wifi_interface: str = Field(
        default="wlan0",
        description="WiFi interface to use for monitoring (must support monitor mode)",
    )
    capture_enabled: bool = Field(
        default=True,
        description="Enable WiFi probe capture on startup",
    )

    # Network Monitoring (ARP/DHCP)
    arp_monitoring_enabled: bool = Field(
        default=True,
        description="Enable ARP table monitoring for connected devices (real MAC addresses)",
    )
    arp_scan_interval: int = Field(
        default=30,
        description="Seconds between ARP table scans",
        ge=5,
        le=300,
    )
    dhcp_monitoring_enabled: bool = Field(
        default=True,
        description="Enable DHCP lease file monitoring for connected devices",
    )
    dhcp_check_interval: int = Field(
        default=60,
        description="Seconds between DHCP lease file checks",
        ge=10,
        le=600,
    )
    dhcp_lease_file: str = Field(
        default="",
        description="Path to DHCP lease file (auto-detected if empty)",
    )

    # Detection Settings
    default_signal_threshold: int = Field(
        default=-65,
        description="Default signal strength threshold in dBm (higher = closer)",
        ge=-100,
        le=0,
    )
    presence_timeout_minutes: int = Field(
        default=5,
        description="Minutes without detection before device considered 'away'",
    )
    notification_cooldown_minutes: int = Field(
        default=60,
        description="Minutes to wait before sending another notification for same device",
    )
    notify_new_devices: bool = Field(
        default=False,
        description="Send notification when a new (unknown) device is detected",
    )

    # IFTTT Notifications
    ifttt_enabled: bool = False
    ifttt_webhook_key: str = Field(
        default="",
        description="IFTTT Webhook key (from https://ifttt.com/maker_webhooks)",
    )
    ifttt_event_name: str = Field(
        default="manomonitor_detected",
        description="IFTTT event name to trigger",
    )

    # Home Assistant Notifications
    homeassistant_enabled: bool = False
    homeassistant_url: str = Field(
        default="http://homeassistant.local:8123",
        description="Home Assistant base URL",
    )
    homeassistant_token: str = Field(
        default="",
        description="Home Assistant Long-Lived Access Token",
    )
    homeassistant_notify_service: str = Field(
        default="notify.notify",
        description="Home Assistant notification service to call",
    )

    # Data Retention
    log_retention_days: int = Field(
        default=30,
        description="Days to keep detailed probe logs (0 = forever)",
    )

    # Monitor Location (for multi-monitor positioning)
    monitor_name: str = Field(
        default="Primary",
        description="Name for this monitor (e.g., 'Living Room', 'Garage')",
    )
    monitor_latitude: float = Field(
        default=0.0,
        description="Latitude of this monitor's location (use Google Maps to find)",
    )
    monitor_longitude: float = Field(
        default=0.0,
        description="Longitude of this monitor's location (use Google Maps to find)",
    )
    monitor_api_key: str = Field(
        default="",
        description="API key for this monitor (auto-generated if empty). Used for multi-monitor sync.",
    )
    map_enabled: bool = Field(
        default=True,
        description="Enable the device location map feature",
    )
    # Signal-to-distance calibration
    signal_tx_power: int = Field(
        default=-59,
        description="Reference signal strength at 1 meter (calibrate for your devices)",
        ge=-100,
        le=0,
    )
    signal_path_loss: float = Field(
        default=3.0,
        description="Path loss exponent (2=free space, 3=indoor, 4=obstructed)",
        ge=1.5,
        le=6.0,
    )
    signal_averaging_window: int = Field(
        default=5,
        description="Number of signal readings to average for positioning (1=disabled)",
        ge=1,
        le=20,
    )

    # Auto-location detection
    google_geolocation_api_key: str = Field(
        default="",
        description="Google Geolocation API key for automatic location detection (optional)",
    )
    auto_detect_location: bool = Field(
        default=True,
        description="Automatically detect monitor location on startup if not configured",
    )
    gps_enabled: bool = Field(
        default=True,
        description="Enable USB GPS device for location detection (most accurate)",
    )
    gps_device: str = Field(
        default="",
        description="GPS device path (auto-detected if empty, e.g., /dev/ttyACM0)",
    )

    # Paths (relative to package root by default)
    data_dir: Path = Field(default_factory=lambda: _PACKAGE_ROOT / "data")
    static_dir: Path = Field(default_factory=lambda: _PACKAGE_ROOT / "static")
    templates_dir: Path = Field(default_factory=lambda: _PACKAGE_ROOT / "templates")

    @field_validator("data_dir", "static_dir", "templates_dir", mode="before")
    @classmethod
    def resolve_path(cls, v: str | Path) -> Path:
        """Convert string paths to Path objects."""
        return Path(v)

    def get_database_url(self) -> str:
        """Get the resolved database URL with absolute paths for SQLite."""
        if self.database_url:
            # User provided a custom URL
            if self.database_url.startswith("sqlite"):
                # Make SQLite paths absolute if they're relative
                parts = self.database_url.split("///")
                if len(parts) == 2 and parts[1].startswith("./"):
                    db_path = self.data_dir / parts[1][2:]
                    return f"sqlite+aiosqlite:///{db_path}"
            return self.database_url
        # Default: SQLite in data_dir
        db_path = self.data_dir / "manomonitor.db"
        return f"sqlite+aiosqlite:///{db_path}"

    def get_database_path(self) -> Path | None:
        """Get the SQLite database file path if using SQLite."""
        url = self.get_database_url()
        if url.startswith("sqlite"):
            db_path = url.split("///")[-1]
            return Path(db_path)
        return None


# Global settings instance
settings = Settings()
