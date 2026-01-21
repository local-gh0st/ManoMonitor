"""Network-based device detection via ARP and DHCP monitoring.

This module detects devices that actually connect to the local network,
which reveals their real MAC address (not randomized like probe requests).
"""

import asyncio
import logging
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, Callable, Optional

from manomonitor.config import settings
from manomonitor.database.connection import get_db_context
from manomonitor.database.crud import create_or_update_asset

logger = logging.getLogger(__name__)


@dataclass
class NetworkDevice:
    """Represents a device detected on the network."""

    mac_address: str
    ip_address: Optional[str]
    hostname: Optional[str]
    detection_method: str  # 'arp', 'dhcp', 'scan'
    timestamp: datetime

    def __repr__(self) -> str:
        return f"<NetworkDevice {self.mac_address} ({self.ip_address})>"


class ARPMonitor:
    """
    Monitors ARP table for connected devices.

    ARP (Address Resolution Protocol) maps IP addresses to MAC addresses.
    When a device connects to the network, it appears in the ARP table.
    """

    def __init__(
        self,
        interface: Optional[str] = None,
        on_device: Optional[Callable[[NetworkDevice], None]] = None,
    ):
        self.interface = interface or settings.wifi_interface
        self.on_device = on_device
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._known_macs: set[str] = set()
        self._scan_interval = 30  # seconds between scans

        # Regex to parse ARP table entries
        # Format: IP address HW type Flags HW address Mask Device
        self._arp_pattern = re.compile(
            r"(\d+\.\d+\.\d+\.\d+)\s+\S+\s+\S+\s+([0-9a-fA-F:]{17})"
        )

    @staticmethod
    def check_dependencies() -> tuple[bool, str]:
        """Check if required tools are available."""
        # Check for arp command
        try:
            result = subprocess.run(
                ["which", "arp"],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                return False, "arp command not found. Install with: sudo apt install net-tools"
        except Exception as e:
            return False, f"Error checking dependencies: {e}"

        return True, "All dependencies available"

    async def _get_arp_table(self) -> list[tuple[str, str]]:
        """Get current ARP table entries. Returns list of (ip, mac) tuples."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "arp", "-n",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()

            entries = []
            for line in stdout.decode().split("\n"):
                match = self._arp_pattern.search(line)
                if match:
                    ip = match.group(1)
                    mac = match.group(2).upper()
                    # Skip incomplete entries
                    if mac != "00:00:00:00:00:00":
                        entries.append((ip, mac))

            return entries
        except Exception as e:
            logger.error(f"Error reading ARP table: {e}")
            return []

    async def _scan_network(self) -> None:
        """Perform a network scan to populate ARP table."""
        try:
            # Get local subnet
            proc = await asyncio.create_subprocess_exec(
                "ip", "route", "show", "default",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()

            # Try to ping broadcast to populate ARP
            # This is a quick way to discover active devices
            proc = await asyncio.create_subprocess_exec(
                "ping", "-c", "1", "-b", "255.255.255.255",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
        except Exception as e:
            logger.debug(f"Network scan error (non-fatal): {e}")

    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        logger.info("Starting ARP monitoring loop")

        while self._running:
            try:
                # Optionally trigger a scan to populate ARP table
                await self._scan_network()

                # Get current ARP entries
                entries = await self._get_arp_table()

                for ip, mac in entries:
                    # Check if this is a new device
                    is_new = mac not in self._known_macs
                    self._known_macs.add(mac)

                    # Create device object
                    device = NetworkDevice(
                        mac_address=mac,
                        ip_address=ip,
                        hostname=None,
                        detection_method="arp",
                        timestamp=datetime.utcnow(),
                    )

                    # Store in database
                    async with get_db_context() as db:
                        asset, created = await create_or_update_asset(
                            db,
                            mac_address=mac,
                            signal_strength=None,  # No signal strength from ARP
                            ssid=None,
                        )

                        if created:
                            logger.info(f"New network device: {mac} ({ip})")

                    # Call callback
                    if self.on_device:
                        try:
                            self.on_device(device)
                        except Exception as e:
                            logger.error(f"Error in device callback: {e}")

            except Exception as e:
                logger.error(f"Error in ARP monitoring: {e}")

            await asyncio.sleep(self._scan_interval)

    async def start(self) -> None:
        """Start ARP monitoring."""
        if self._running:
            logger.warning("ARP monitor already running")
            return

        ok, msg = self.check_dependencies()
        if not ok:
            logger.warning(f"ARP monitoring disabled: {msg}")
            return

        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("ARP monitoring started")

    async def stop(self) -> None:
        """Stop ARP monitoring."""
        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        logger.info("ARP monitoring stopped")

    @property
    def is_running(self) -> bool:
        """Check if monitoring is running."""
        return self._running and self._task is not None and not self._task.done()


class DHCPMonitor:
    """
    Monitors DHCP lease file for connected devices.

    When devices connect and get an IP via DHCP, they're recorded in the lease file.
    This provides hostname information in addition to MAC and IP.
    """

    # Common DHCP lease file locations
    LEASE_FILE_PATHS = [
        "/var/lib/dhcp/dhcpd.leases",
        "/var/lib/dhcpcd/dhcpcd-*.lease",
        "/var/lib/NetworkManager/dhclient-*.lease",
        "/var/lib/dhclient/dhclient.leases",
        "/tmp/dhcp.leases",  # OpenWrt
        "/var/lib/misc/dnsmasq.leases",  # dnsmasq
    ]

    def __init__(
        self,
        lease_file: Optional[str] = None,
        on_device: Optional[Callable[[NetworkDevice], None]] = None,
    ):
        self.lease_file = lease_file
        self.on_device = on_device
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._known_macs: set[str] = set()
        self._check_interval = 60  # seconds

        # Try to find lease file if not specified
        if not self.lease_file:
            self.lease_file = self._find_lease_file()

    def _find_lease_file(self) -> Optional[str]:
        """Try to find the DHCP lease file."""
        import glob

        for pattern in self.LEASE_FILE_PATHS:
            matches = glob.glob(pattern)
            for match in matches:
                if Path(match).exists():
                    logger.info(f"Found DHCP lease file: {match}")
                    return match

        logger.warning("No DHCP lease file found")
        return None

    async def _parse_dnsmasq_leases(self, content: str) -> list[NetworkDevice]:
        """Parse dnsmasq-style lease file."""
        devices = []
        # Format: timestamp mac ip hostname client-id
        for line in content.strip().split("\n"):
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 4:
                try:
                    timestamp = datetime.fromtimestamp(int(parts[0]))
                    mac = parts[1].upper()
                    ip = parts[2]
                    hostname = parts[3] if parts[3] != "*" else None

                    devices.append(NetworkDevice(
                        mac_address=mac,
                        ip_address=ip,
                        hostname=hostname,
                        detection_method="dhcp",
                        timestamp=timestamp,
                    ))
                except (ValueError, IndexError):
                    continue

        return devices

    async def _parse_isc_leases(self, content: str) -> list[NetworkDevice]:
        """Parse ISC DHCP-style lease file."""
        devices = []

        # Simple regex-based parsing
        lease_blocks = re.findall(
            r"lease\s+(\d+\.\d+\.\d+\.\d+)\s*\{([^}]+)\}",
            content,
            re.DOTALL
        )

        for ip, block in lease_blocks:
            mac_match = re.search(r"hardware\s+ethernet\s+([0-9a-fA-F:]+)", block)
            hostname_match = re.search(r'client-hostname\s+"([^"]+)"', block)
            time_match = re.search(r"starts\s+\d+\s+(\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2})", block)

            if mac_match:
                mac = mac_match.group(1).upper()
                hostname = hostname_match.group(1) if hostname_match else None

                timestamp = datetime.utcnow()
                if time_match:
                    try:
                        timestamp = datetime.strptime(time_match.group(1), "%Y/%m/%d %H:%M:%S")
                    except ValueError:
                        pass

                devices.append(NetworkDevice(
                    mac_address=mac,
                    ip_address=ip,
                    hostname=hostname,
                    detection_method="dhcp",
                    timestamp=timestamp,
                ))

        return devices

    async def _read_leases(self) -> list[NetworkDevice]:
        """Read and parse DHCP lease file."""
        if not self.lease_file or not Path(self.lease_file).exists():
            return []

        try:
            content = Path(self.lease_file).read_text()

            # Detect format and parse
            if "lease " in content and "hardware ethernet" in content:
                return await self._parse_isc_leases(content)
            else:
                return await self._parse_dnsmasq_leases(content)

        except Exception as e:
            logger.error(f"Error reading DHCP leases: {e}")
            return []

    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        logger.info(f"Starting DHCP monitoring (lease file: {self.lease_file})")

        while self._running:
            try:
                devices = await self._read_leases()

                for device in devices:
                    is_new = device.mac_address not in self._known_macs
                    self._known_macs.add(device.mac_address)

                    # Store in database
                    async with get_db_context() as db:
                        asset, created = await create_or_update_asset(
                            db,
                            mac_address=device.mac_address,
                            signal_strength=None,
                            ssid=None,
                        )

                        if created:
                            logger.info(
                                f"New DHCP device: {device.mac_address} "
                                f"({device.ip_address}, {device.hostname or 'no hostname'})"
                            )

                    if self.on_device:
                        try:
                            self.on_device(device)
                        except Exception as e:
                            logger.error(f"Error in device callback: {e}")

            except Exception as e:
                logger.error(f"Error in DHCP monitoring: {e}")

            await asyncio.sleep(self._check_interval)

    async def start(self) -> None:
        """Start DHCP monitoring."""
        if self._running:
            logger.warning("DHCP monitor already running")
            return

        if not self.lease_file:
            logger.warning("DHCP monitoring disabled: no lease file found")
            return

        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("DHCP monitoring started")

    async def stop(self) -> None:
        """Stop DHCP monitoring."""
        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        logger.info("DHCP monitoring stopped")

    @property
    def is_running(self) -> bool:
        """Check if monitoring is running."""
        return self._running and self._task is not None and not self._task.done()


# Singleton instances
_arp_monitor: Optional[ARPMonitor] = None
_dhcp_monitor: Optional[DHCPMonitor] = None


def get_arp_monitor() -> ARPMonitor:
    """Get or create the global ARPMonitor instance."""
    global _arp_monitor
    if _arp_monitor is None:
        _arp_monitor = ARPMonitor()
    return _arp_monitor


def get_dhcp_monitor() -> DHCPMonitor:
    """Get or create the global DHCPMonitor instance."""
    global _dhcp_monitor
    if _dhcp_monitor is None:
        _dhcp_monitor = DHCPMonitor()
    return _dhcp_monitor
