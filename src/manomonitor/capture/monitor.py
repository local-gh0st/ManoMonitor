"""WiFi probe request capture using tshark."""

import asyncio
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import AsyncGenerator, Callable, Optional

from manomonitor.config import settings
from manomonitor.database.connection import get_db_context
from manomonitor.database.crud import create_or_update_asset

logger = logging.getLogger(__name__)


@dataclass
class ProbeRequest:
    """Represents a captured WiFi probe request."""

    mac_address: str
    signal_strength: Optional[int]
    ssid: Optional[str]
    timestamp: datetime

    def __repr__(self) -> str:
        return f"<Probe {self.mac_address} signal={self.signal_strength} ssid={self.ssid}>"


class ProbeCapture:
    """
    Captures WiFi probe requests using tshark.

    Probe requests are broadcast by WiFi devices searching for networks.
    They contain the device's MAC address, and optionally the SSID being searched.
    """

    def __init__(
        self,
        interface: str = settings.wifi_interface,
        on_probe: Optional[Callable[[ProbeRequest], None]] = None,
    ):
        self.interface = interface
        self.on_probe = on_probe
        self._process: Optional[asyncio.subprocess.Process] = None
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # Regex to parse tshark output
        # Format: MAC_ADDRESS\tSIGNAL_STRENGTH\tSSID
        self._line_pattern = re.compile(
            r"^([0-9a-fA-F:]{17})\t(-?\d+)?\t?(.*)$"
        )

    @staticmethod
    def check_dependencies() -> tuple[bool, str]:
        """Check if required tools are available."""
        # Check tshark
        if not shutil.which("tshark"):
            return False, "tshark not found. Install with: sudo apt install tshark"

        # Check interface tools
        if not shutil.which("ip"):
            return False, "ip command not found. Install with: sudo apt install iproute2"

        return True, "All dependencies available"

    @staticmethod
    def check_interface(interface: str) -> tuple[bool, str]:
        """Check if the WiFi interface exists and can be used."""
        try:
            result = subprocess.run(
                ["ip", "link", "show", interface],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                return False, f"Interface {interface} not found"

            # Check if interface supports monitor mode
            result = subprocess.run(
                ["iw", interface, "info"],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                return False, f"Cannot get info for {interface}. Is it a WiFi interface?"

            return True, f"Interface {interface} is available"
        except Exception as e:
            return False, f"Error checking interface: {e}"

    @staticmethod
    async def set_monitor_mode(interface: str) -> tuple[bool, str]:
        """Set the WiFi interface to monitor mode."""
        try:
            commands = [
                ["ip", "link", "set", interface, "down"],
                ["iw", interface, "set", "monitor", "control"],
                ["ip", "link", "set", interface, "up"],
            ]

            for cmd in commands:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await proc.communicate()
                if proc.returncode != 0:
                    # Try alternative method
                    if "monitor" in cmd:
                        alt_cmd = ["iwconfig", interface, "mode", "monitor"]
                        proc = await asyncio.create_subprocess_exec(
                            *alt_cmd,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                        )
                        _, stderr = await proc.communicate()
                        if proc.returncode != 0:
                            return False, f"Failed to set monitor mode: {stderr.decode()}"

            logger.info(f"Set {interface} to monitor mode")
            return True, f"Interface {interface} set to monitor mode"
        except Exception as e:
            return False, f"Error setting monitor mode: {e}"

    def _build_tshark_command(self) -> list[str]:
        """Build the tshark command for capturing probe requests."""
        return [
            "tshark",
            "-i", self.interface,
            "-l",  # Line-buffered output
            "-n",  # Don't resolve names
            "-Y", "wlan.fc.type_subtype == 4",  # Probe requests only
            "-T", "fields",
            "-e", "wlan.sa",  # Source MAC address
            "-e", "wlan_radio.signal_dbm",  # Signal strength
            "-e", "wlan.ssid",  # SSID being probed
            "-E", "separator=\t",
        ]

    def _parse_line(self, line: str) -> Optional[ProbeRequest]:
        """Parse a line of tshark output into a ProbeRequest."""
        line = line.strip()
        if not line:
            return None

        match = self._line_pattern.match(line)
        if not match:
            logger.debug(f"Could not parse line: {line}")
            return None

        mac_address = match.group(1).upper()
        signal_str = match.group(2)
        ssid = match.group(3).strip() if match.group(3) else None

        # Parse signal strength
        signal_strength = None
        if signal_str:
            try:
                signal_strength = int(signal_str)
            except ValueError:
                pass

        return ProbeRequest(
            mac_address=mac_address,
            signal_strength=signal_strength,
            ssid=ssid if ssid else None,
            timestamp=datetime.utcnow(),
        )

    async def _capture_loop(self) -> AsyncGenerator[ProbeRequest, None]:
        """Generator that yields captured probe requests."""
        cmd = self._build_tshark_command()
        logger.info(f"Starting capture: {' '.join(cmd)}")

        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        while self._running and self._process.stdout:
            try:
                line = await asyncio.wait_for(
                    self._process.stdout.readline(),
                    timeout=1.0,
                )
                if not line:
                    if self._process.returncode is not None:
                        logger.error(f"tshark exited with code {self._process.returncode}")
                        break
                    continue

                probe = self._parse_line(line.decode("utf-8", errors="ignore"))
                if probe:
                    yield probe

            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Error in capture loop: {e}")
                await asyncio.sleep(1)

    async def _process_probes(self) -> None:
        """Main loop to process captured probes."""
        logger.info("Starting probe processing loop")

        async for probe in self._capture_loop():
            try:
                # Store in database
                async with get_db_context() as db:
                    asset, is_new = await create_or_update_asset(
                        db,
                        mac_address=probe.mac_address,
                        signal_strength=probe.signal_strength,
                        ssid=probe.ssid,
                    )

                    if is_new:
                        logger.info(f"New device: {probe.mac_address}")

                # Call callback if provided
                if self.on_probe:
                    try:
                        self.on_probe(probe)
                    except Exception as e:
                        logger.error(f"Error in probe callback: {e}")

            except Exception as e:
                logger.error(f"Error processing probe: {e}")

    async def start(self) -> None:
        """Start capturing probes in the background."""
        if self._running:
            logger.warning("Capture already running")
            return

        # Check dependencies
        ok, msg = self.check_dependencies()
        if not ok:
            raise RuntimeError(msg)

        # Check interface
        ok, msg = self.check_interface(self.interface)
        if not ok:
            raise RuntimeError(msg)

        # Set monitor mode
        ok, msg = await self.set_monitor_mode(self.interface)
        if not ok:
            raise RuntimeError(msg)

        self._running = True
        self._task = asyncio.create_task(self._process_probes())
        logger.info(f"Probe capture started on {self.interface}")

    async def stop(self) -> None:
        """Stop capturing probes."""
        self._running = False

        if self._process:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
            self._process = None

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        logger.info("Probe capture stopped")

    @property
    def is_running(self) -> bool:
        """Check if capture is running."""
        return self._running and self._task is not None and not self._task.done()


# Singleton instance
_capture_instance: Optional[ProbeCapture] = None


def get_capture() -> ProbeCapture:
    """Get or create the global ProbeCapture instance."""
    global _capture_instance
    if _capture_instance is None:
        _capture_instance = ProbeCapture()
    return _capture_instance
