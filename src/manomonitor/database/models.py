"""SQLAlchemy database models for WhosHere."""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all database models."""

    pass


class Asset(Base):
    """
    Tracked device (asset) model.

    Represents a WiFi device identified by its MAC address.
    """

    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mac_address: Mapped[str] = mapped_column(String(17), unique=True, nullable=False, index=True)
    nickname: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Vendor/manufacturer info (from OUI lookup)
    vendor: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    device_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    vendor_country: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)  # ISO country code
    is_virtual_machine: Mapped[bool] = mapped_column(Boolean, default=False)

    # Notification settings
    notify_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    signal_threshold: Mapped[int] = mapped_column(Integer, default=-65)

    # Tracking data
    first_seen: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )
    times_seen: Mapped[int] = mapped_column(Integer, default=1)
    last_signal_strength: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Notification tracking
    last_notified: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Metadata
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now()
    )

    # Calculated position (from bilateration)
    last_latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    position_accuracy: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # meters
    position_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    probe_logs: Mapped[list["ProbeLog"]] = relationship(
        "ProbeLog", back_populates="asset", cascade="all, delete-orphan"
    )
    ssid_history: Mapped[list["SSIDHistory"]] = relationship(
        "SSIDHistory", back_populates="asset", cascade="all, delete-orphan"
    )
    signal_readings: Mapped[list["SignalReading"]] = relationship(
        "SignalReading", back_populates="asset", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        name = self.nickname or self.mac_address
        return f"<Asset {name}>"

    @property
    def display_name(self) -> str:
        """Return nickname if set, otherwise MAC address."""
        return self.nickname or self.mac_address

    @property
    def vendor_display(self) -> str:
        """Return a display-friendly vendor name."""
        if self.vendor:
            # Shorten long vendor names
            words = self.vendor.split()[:2]
            result = " ".join(words)
            if len(result) > 25:
                result = result[:22] + "..."
            return result
        return "Unknown"

    @property
    def device_type_display(self) -> str:
        """Return device type or Unknown."""
        return self.device_type or "Unknown"

    @property
    def device_icon(self) -> str:
        """Return an emoji/icon based on device type."""
        icons = {
            "Mobile Device": "📱",
            "Computer": "💻",
            "Network Device": "🌐",
            "Smart Device": "🏠",
            "IoT Device": "📡",
            "Appliance": "🔌",
            "Entertainment": "📺",
            "Gaming Console": "🎮",
            "Wearable": "⌚",
            "Camera": "📷",
            "Printer": "🖨️",
            "Smart TV": "📺",
        }
        return icons.get(self.device_type, "❓")

    @property
    def is_present(self) -> bool:
        """Check if device was seen within the presence timeout."""
        from manomonitor.config import settings

        if self.last_seen is None:
            return False
        delta = datetime.utcnow() - self.last_seen
        return delta.total_seconds() < (settings.presence_timeout_minutes * 60)

    @property
    def minutes_since_seen(self) -> int:
        """Minutes since the device was last detected."""
        if self.last_seen is None:
            return -1
        delta = datetime.utcnow() - self.last_seen
        return int(delta.total_seconds() / 60)


class ProbeLog(Base):
    """
    WiFi probe request log entry.

    Records each probe request detected from a device.
    """

    __tablename__ = "probe_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )

    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False, index=True
    )
    signal_strength: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ssid: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Relationship
    asset: Mapped["Asset"] = relationship("Asset", back_populates="probe_logs")

    __table_args__ = (
        Index("ix_probe_logs_asset_timestamp", "asset_id", "timestamp"),
    )

    def __repr__(self) -> str:
        return f"<ProbeLog {self.asset_id} @ {self.timestamp}>"


class SSIDHistory(Base):
    """
    SSID history for a device.

    Tracks unique SSIDs (WiFi network names) that a device has probed for.
    """

    __tablename__ = "ssid_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )

    ssid: Mapped[str] = mapped_column(String(64), nullable=False)
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    last_seen: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now()
    )
    times_seen: Mapped[int] = mapped_column(Integer, default=1)

    # Relationship
    asset: Mapped["Asset"] = relationship("Asset", back_populates="ssid_history")

    __table_args__ = (
        Index("ix_ssid_history_asset_ssid", "asset_id", "ssid", unique=True),
    )

    def __repr__(self) -> str:
        return f"<SSIDHistory {self.ssid}>"


class Config(Base):
    """
    Application configuration stored in database.

    Key-value store for runtime configuration that can be changed via UI.
    """

    __tablename__ = "config"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<Config {self.key}={self.value}>"


class NotificationLog(Base):
    """
    Log of sent notifications.

    Tracks all notifications sent for auditing and debugging.
    """

    __tablename__ = "notification_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )

    notification_type: Mapped[str] = mapped_column(String(50), nullable=False)  # ifttt, homeassistant
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # sent, failed
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False, index=True
    )

    def __repr__(self) -> str:
        return f"<NotificationLog {self.notification_type} @ {self.timestamp}>"


class Monitor(Base):
    """
    A monitoring station/device in the multi-monitor setup.

    Each monitor has a known location and reports signal readings.
    """

    __tablename__ = "monitors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    api_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)

    # Location
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_local: Mapped[bool] = mapped_column(Boolean, default=False)  # True if this is the local monitor
    last_seen: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now()
    )

    # Relationships
    signal_readings: Mapped[list["SignalReading"]] = relationship(
        "SignalReading", back_populates="monitor", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Monitor {self.name} ({self.latitude}, {self.longitude})>"

    @property
    def is_online(self) -> bool:
        """Check if monitor was seen in the last 5 minutes."""
        if self.is_local:
            return True
        if self.last_seen is None:
            return False
        delta = datetime.utcnow() - self.last_seen
        return delta.total_seconds() < 300  # 5 minutes


class SignalReading(Base):
    """
    A signal strength reading from a specific monitor for a device.

    Used for bilateration to calculate device positions.
    """

    __tablename__ = "signal_readings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    monitor_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("monitors.id", ondelete="CASCADE"), nullable=False
    )

    signal_strength: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_distance: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # meters
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False, index=True
    )

    # Relationships
    asset: Mapped["Asset"] = relationship("Asset", back_populates="signal_readings")
    monitor: Mapped["Monitor"] = relationship("Monitor", back_populates="signal_readings")

    __table_args__ = (
        Index("ix_signal_readings_asset_monitor", "asset_id", "monitor_id"),
        # Note: timestamp already has index=True on the column definition
    )

    def __repr__(self) -> str:
        return f"<SignalReading {self.asset_id} from {self.monitor_id}: {self.signal_strength}dBm>"
