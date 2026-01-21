"""Geolocation utilities for automatic location detection.

Supports:
- USB GPS dongles (NMEA protocol, ~2-5m accuracy)
- Google Geolocation API with WiFi scanning (~10-50m accuracy)
- IP geolocation fallback (~5km accuracy)
"""

import asyncio
import glob
import logging
import os
import re
import subprocess
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class GeoLocation:
    """A geographic location with accuracy."""
    latitude: float
    longitude: float
    accuracy: float  # meters


@dataclass
class WifiAccessPoint:
    """A WiFi access point for geolocation."""
    mac_address: str  # BSSID
    signal_strength: int  # dBm
    channel: Optional[int] = None
    ssid: Optional[str] = None


# =============================================================================
# GPS Device Support
# =============================================================================


def find_gps_devices() -> list[str]:
    """
    Find connected GPS devices.

    Looks for common USB GPS device paths on Linux.
    Returns list of device paths (e.g., ['/dev/ttyACM0', '/dev/ttyUSB0'])
    """
    gps_devices = []

    # Common GPS device patterns
    patterns = [
        "/dev/ttyACM*",  # USB CDC ACM devices (common for GPS)
        "/dev/ttyUSB*",  # USB serial devices
        "/dev/gps*",     # Symlinked GPS devices
    ]

    for pattern in patterns:
        gps_devices.extend(glob.glob(pattern))

    # Filter to only include devices that exist and are readable
    valid_devices = []
    for device in gps_devices:
        if os.path.exists(device) and os.access(device, os.R_OK):
            valid_devices.append(device)

    return sorted(valid_devices)


def parse_nmea_coordinate(coord: str, direction: str) -> Optional[float]:
    """
    Parse NMEA coordinate format to decimal degrees.

    NMEA format: DDMM.MMMM or DDDMM.MMMM
    Examples: 4807.038,N -> 48.1173, 01131.000,E -> 11.5167
    """
    if not coord or not direction:
        return None

    try:
        # Find decimal point position
        dot_pos = coord.index('.')
        if dot_pos < 2:
            return None

        # Degrees are everything before the last 2 digits before decimal
        degrees = int(coord[:dot_pos - 2])
        # Minutes are the last 2 digits before decimal + decimal part
        minutes = float(coord[dot_pos - 2:])

        # Convert to decimal degrees
        decimal = degrees + (minutes / 60.0)

        # Apply direction
        if direction in ('S', 'W'):
            decimal = -decimal

        return decimal
    except (ValueError, IndexError):
        return None


def parse_nmea_gga(sentence: str) -> Optional[GeoLocation]:
    """
    Parse NMEA GGA sentence for position.

    Format: $GPGGA,time,lat,N/S,lon,E/W,quality,sats,hdop,alt,M,geoid,M,age,ref*checksum
    Example: $GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,47.0,M,,*47
    """
    try:
        # Remove checksum
        if '*' in sentence:
            sentence = sentence.split('*')[0]

        parts = sentence.split(',')
        if len(parts) < 10:
            return None

        # Check if we have a valid fix (quality > 0)
        quality = int(parts[6]) if parts[6] else 0
        if quality == 0:
            return None

        lat = parse_nmea_coordinate(parts[2], parts[3])
        lon = parse_nmea_coordinate(parts[4], parts[5])

        if lat is None or lon is None:
            return None

        # HDOP (horizontal dilution of precision) indicates accuracy
        # Lower is better: 1 = ideal, 2-5 = good, 5-10 = moderate
        hdop = float(parts[8]) if parts[8] else 5.0
        # Rough accuracy estimate: HDOP * 2.5 meters (typical GPS)
        accuracy = hdop * 2.5

        return GeoLocation(latitude=lat, longitude=lon, accuracy=accuracy)
    except (ValueError, IndexError) as e:
        logger.debug(f"Failed to parse GGA: {e}")
        return None


def parse_nmea_rmc(sentence: str) -> Optional[GeoLocation]:
    """
    Parse NMEA RMC sentence for position.

    Format: $GPRMC,time,status,lat,N/S,lon,E/W,speed,course,date,mag,E/W*checksum
    Example: $GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A
    """
    try:
        # Remove checksum
        if '*' in sentence:
            sentence = sentence.split('*')[0]

        parts = sentence.split(',')
        if len(parts) < 8:
            return None

        # Check if status is Active (A) not Void (V)
        if parts[2] != 'A':
            return None

        lat = parse_nmea_coordinate(parts[3], parts[4])
        lon = parse_nmea_coordinate(parts[5], parts[6])

        if lat is None or lon is None:
            return None

        # RMC doesn't have HDOP, use default accuracy
        return GeoLocation(latitude=lat, longitude=lon, accuracy=5.0)
    except (ValueError, IndexError) as e:
        logger.debug(f"Failed to parse RMC: {e}")
        return None


async def read_gps_location(
    device_path: Optional[str] = None,
    timeout: float = 10.0,
    baud_rate: int = 9600,
) -> Optional[GeoLocation]:
    """
    Read location from a GPS device.

    Args:
        device_path: Path to GPS device (auto-detected if None)
        timeout: Max seconds to wait for a valid fix
        baud_rate: Serial baud rate (9600 is standard for NMEA)

    Returns:
        GeoLocation if valid fix obtained, None otherwise
    """
    # Find device if not specified
    if device_path is None:
        devices = find_gps_devices()
        if not devices:
            logger.debug("No GPS devices found")
            return None
        device_path = devices[0]
        logger.info(f"Auto-detected GPS device: {device_path}")

    if not os.path.exists(device_path):
        logger.error(f"GPS device not found: {device_path}")
        return None

    try:
        # Try using pyserial if available
        try:
            import serial
            return await _read_gps_serial(device_path, timeout, baud_rate)
        except ImportError:
            logger.debug("pyserial not installed, using cat fallback")

        # Fallback: use cat to read from device
        return await _read_gps_cat(device_path, timeout)

    except Exception as e:
        logger.error(f"Failed to read GPS: {e}")
        return None


async def _read_gps_serial(
    device_path: str,
    timeout: float,
    baud_rate: int,
) -> Optional[GeoLocation]:
    """Read GPS using pyserial."""
    import serial

    try:
        ser = serial.Serial(
            device_path,
            baudrate=baud_rate,
            timeout=1.0,
        )
    except serial.SerialException as e:
        logger.error(f"Failed to open GPS device: {e}")
        return None

    try:
        start_time = asyncio.get_event_loop().time()

        while (asyncio.get_event_loop().time() - start_time) < timeout:
            # Run blocking read in thread pool
            line = await asyncio.get_event_loop().run_in_executor(
                None, ser.readline
            )

            if not line:
                continue

            try:
                sentence = line.decode('ascii', errors='ignore').strip()
            except Exception:
                continue

            # Try to parse as GGA (preferred, has accuracy)
            if sentence.startswith('$GPGGA') or sentence.startswith('$GNGGA'):
                location = parse_nmea_gga(sentence)
                if location:
                    logger.info(f"GPS fix: {location.latitude}, {location.longitude} (accuracy: {location.accuracy}m)")
                    return location

            # Try RMC as fallback
            elif sentence.startswith('$GPRMC') or sentence.startswith('$GNRMC'):
                location = parse_nmea_rmc(sentence)
                if location:
                    logger.info(f"GPS fix: {location.latitude}, {location.longitude}")
                    return location

        logger.warning("GPS timeout - no valid fix obtained")
        return None

    finally:
        ser.close()


async def _read_gps_cat(device_path: str, timeout: float) -> Optional[GeoLocation]:
    """Read GPS using cat command (fallback when pyserial not available)."""
    try:
        # Configure serial port using stty
        await asyncio.create_subprocess_exec(
            "stty", "-F", device_path, "9600", "raw", "-echo",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except Exception:
        pass  # May fail if no stty, try anyway

    try:
        proc = await asyncio.create_subprocess_exec(
            "cat", device_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )

        start_time = asyncio.get_event_loop().time()
        buffer = ""

        while (asyncio.get_event_loop().time() - start_time) < timeout:
            try:
                # Read with timeout
                data = await asyncio.wait_for(
                    proc.stdout.read(256),
                    timeout=2.0
                )
                if not data:
                    break

                buffer += data.decode('ascii', errors='ignore')

                # Process complete lines
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    sentence = line.strip()

                    if sentence.startswith('$GPGGA') or sentence.startswith('$GNGGA'):
                        location = parse_nmea_gga(sentence)
                        if location:
                            proc.terminate()
                            logger.info(f"GPS fix: {location.latitude}, {location.longitude}")
                            return location

                    elif sentence.startswith('$GPRMC') or sentence.startswith('$GNRMC'):
                        location = parse_nmea_rmc(sentence)
                        if location:
                            proc.terminate()
                            logger.info(f"GPS fix: {location.latitude}, {location.longitude}")
                            return location

            except asyncio.TimeoutError:
                continue

        proc.terminate()
        logger.warning("GPS timeout - no valid fix obtained")
        return None

    except Exception as e:
        logger.error(f"GPS cat read failed: {e}")
        return None


async def geolocate_via_gps(
    device_path: Optional[str] = None,
    timeout: float = 15.0,
) -> Optional[GeoLocation]:
    """
    Get location from USB GPS device.

    Args:
        device_path: Path to GPS device (auto-detected if None)
        timeout: Max seconds to wait for valid GPS fix

    Returns:
        GeoLocation with ~2-5m accuracy, or None if no GPS or no fix
    """
    devices = find_gps_devices()
    if not devices and device_path is None:
        logger.debug("No GPS devices detected")
        return None

    logger.info(f"Attempting GPS location from {device_path or devices[0]}...")
    return await read_gps_location(device_path, timeout)


# =============================================================================
# WiFi Geolocation
# =============================================================================


async def scan_wifi_networks(interface: str = "wlan0") -> list[WifiAccessPoint]:
    """
    Scan for nearby WiFi networks.

    Uses iwlist or nmcli to scan for access points.
    Requires root/sudo for iwlist scan.
    """
    access_points: list[WifiAccessPoint] = []

    # Try nmcli first (doesn't require root for scanning)
    try:
        proc = await asyncio.create_subprocess_exec(
            "nmcli", "-t", "-f", "BSSID,SIGNAL,CHAN,SSID", "device", "wifi", "list",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode == 0:
            for line in stdout.decode().strip().split("\n"):
                if not line:
                    continue
                parts = line.split(":")
                if len(parts) >= 3:
                    bssid = parts[0].replace("\\", "").upper()
                    # nmcli shows signal as percentage (0-100), convert to rough dBm
                    try:
                        signal_pct = int(parts[1])
                        # Rough conversion: 100% ~ -30dBm, 0% ~ -90dBm
                        signal_dbm = -90 + int(signal_pct * 0.6)
                        channel = int(parts[2]) if parts[2] else None
                        ssid = ":".join(parts[3:]) if len(parts) > 3 else None

                        if bssid and len(bssid) == 17:  # Valid MAC format
                            access_points.append(WifiAccessPoint(
                                mac_address=bssid,
                                signal_strength=signal_dbm,
                                channel=channel,
                                ssid=ssid,
                            ))
                    except (ValueError, IndexError):
                        continue

            if access_points:
                logger.info(f"Found {len(access_points)} WiFi networks via nmcli")
                return access_points
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.debug(f"nmcli scan failed: {e}")

    # Try iwlist (requires root)
    try:
        proc = await asyncio.create_subprocess_exec(
            "sudo", "iwlist", interface, "scan",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode == 0:
            output = stdout.decode()

            # Parse iwlist output
            current_bssid = None
            current_signal = None
            current_channel = None
            current_ssid = None

            for line in output.split("\n"):
                line = line.strip()

                # Cell line contains BSSID
                if "Cell" in line and "Address:" in line:
                    # Save previous AP
                    if current_bssid and current_signal:
                        access_points.append(WifiAccessPoint(
                            mac_address=current_bssid,
                            signal_strength=current_signal,
                            channel=current_channel,
                            ssid=current_ssid,
                        ))

                    match = re.search(r"Address:\s*([0-9A-Fa-f:]{17})", line)
                    if match:
                        current_bssid = match.group(1).upper()
                    current_signal = None
                    current_channel = None
                    current_ssid = None

                # Signal level
                elif "Signal level" in line:
                    match = re.search(r"Signal level[=:](-?\d+)", line)
                    if match:
                        current_signal = int(match.group(1))

                # Channel
                elif "Channel:" in line:
                    match = re.search(r"Channel:(\d+)", line)
                    if match:
                        current_channel = int(match.group(1))

                # SSID
                elif "ESSID:" in line:
                    match = re.search(r'ESSID:"([^"]*)"', line)
                    if match:
                        current_ssid = match.group(1)

            # Don't forget last AP
            if current_bssid and current_signal:
                access_points.append(WifiAccessPoint(
                    mac_address=current_bssid,
                    signal_strength=current_signal,
                    channel=current_channel,
                    ssid=current_ssid,
                ))

            if access_points:
                logger.info(f"Found {len(access_points)} WiFi networks via iwlist")
                return access_points
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.debug(f"iwlist scan failed: {e}")

    # Try iw (modern replacement for iwlist)
    try:
        proc = await asyncio.create_subprocess_exec(
            "sudo", "iw", interface, "scan",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode == 0:
            output = stdout.decode()

            current_bssid = None
            current_signal = None

            for line in output.split("\n"):
                line = line.strip()

                if line.startswith("BSS "):
                    if current_bssid and current_signal:
                        access_points.append(WifiAccessPoint(
                            mac_address=current_bssid,
                            signal_strength=current_signal,
                        ))

                    match = re.search(r"BSS ([0-9a-fA-F:]{17})", line)
                    if match:
                        current_bssid = match.group(1).upper()
                    current_signal = None

                elif "signal:" in line:
                    match = re.search(r"signal:\s*(-?\d+)", line)
                    if match:
                        current_signal = int(match.group(1))

            if current_bssid and current_signal:
                access_points.append(WifiAccessPoint(
                    mac_address=current_bssid,
                    signal_strength=current_signal,
                ))

            if access_points:
                logger.info(f"Found {len(access_points)} WiFi networks via iw")
                return access_points
    except Exception as e:
        logger.debug(f"iw scan failed: {e}")

    logger.warning("No WiFi networks found - geolocation will fail")
    return access_points


async def geolocate_via_google(
    api_key: str,
    wifi_access_points: Optional[list[WifiAccessPoint]] = None,
    interface: str = "wlan0",
) -> Optional[GeoLocation]:
    """
    Get location using Google Geolocation API.

    Args:
        api_key: Google Cloud API key with Geolocation API enabled
        wifi_access_points: Pre-scanned WiFi networks (will scan if not provided)
        interface: WiFi interface to use for scanning

    Returns:
        GeoLocation or None if geolocation fails
    """
    if not api_key:
        logger.error("Google API key required for geolocation")
        return None

    # Scan for WiFi networks if not provided
    if wifi_access_points is None:
        wifi_access_points = await scan_wifi_networks(interface)

    if not wifi_access_points:
        logger.error("No WiFi access points found for geolocation")
        return None

    # Build request for Google Geolocation API
    # https://developers.google.com/maps/documentation/geolocation/overview
    request_body = {
        "considerIp": True,  # Also use IP as fallback
        "wifiAccessPoints": [
            {
                "macAddress": ap.mac_address,
                "signalStrength": ap.signal_strength,
                **({"channel": ap.channel} if ap.channel else {}),
            }
            for ap in wifi_access_points[:20]  # API accepts max ~20 APs
        ]
    }

    url = f"https://www.googleapis.com/geolocation/v1/geolocate?key={api_key}"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json=request_body,
                timeout=30.0,
            )

            if response.status_code == 200:
                data = response.json()
                location = data.get("location", {})
                accuracy = data.get("accuracy", 100)

                lat = location.get("lat")
                lng = location.get("lng")

                if lat is not None and lng is not None:
                    logger.info(f"Geolocation successful: {lat}, {lng} (accuracy: {accuracy}m)")
                    return GeoLocation(
                        latitude=lat,
                        longitude=lng,
                        accuracy=accuracy,
                    )
            else:
                error_data = response.json() if response.content else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"Google Geolocation API error: {error_msg}")

    except httpx.RequestError as e:
        logger.error(f"Network error during geolocation: {e}")
    except Exception as e:
        logger.error(f"Geolocation failed: {e}")

    return None


async def geolocate_via_ip() -> Optional[GeoLocation]:
    """
    Fallback: Get approximate location via IP address.

    Note: This is very inaccurate (city level, ~1-10km).
    Only use as a fallback or for initial setup hints.
    """
    try:
        async with httpx.AsyncClient() as client:
            # Use ip-api.com (free, no key required)
            response = await client.get(
                "http://ip-api.com/json/?fields=lat,lon,accuracy",
                timeout=10.0,
            )

            if response.status_code == 200:
                data = response.json()
                lat = data.get("lat")
                lon = data.get("lon")

                if lat is not None and lon is not None:
                    logger.info(f"IP geolocation: {lat}, {lon} (city-level accuracy)")
                    return GeoLocation(
                        latitude=lat,
                        longitude=lon,
                        accuracy=5000,  # ~5km typical city-level accuracy
                    )
    except Exception as e:
        logger.error(f"IP geolocation failed: {e}")

    return None


async def auto_detect_location(
    google_api_key: Optional[str] = None,
    interface: str = "wlan0",
    gps_device: Optional[str] = None,
    gps_enabled: bool = True,
) -> Optional[GeoLocation]:
    """
    Auto-detect location using best available method.

    Priority:
    1. USB GPS device (~2-5m accuracy) - if connected
    2. Google Geolocation API (WiFi-based, ~10-50m accuracy) - requires API key
    3. IP Geolocation (fallback, ~5km accuracy)

    Args:
        google_api_key: Optional Google Cloud API key
        interface: WiFi interface for scanning
        gps_device: Optional GPS device path (auto-detected if None)
        gps_enabled: Whether to try GPS detection

    Returns:
        GeoLocation or None
    """
    # Try GPS first (most accurate)
    if gps_enabled:
        gps_devices = find_gps_devices()
        if gps_devices or gps_device:
            logger.info("GPS device detected, attempting GPS fix...")
            location = await geolocate_via_gps(gps_device, timeout=15.0)
            if location:
                logger.info(f"Location from GPS: {location.latitude}, {location.longitude} (~{location.accuracy}m)")
                return location
            else:
                logger.warning("GPS detected but no fix obtained (may need clear sky view)")

    # Try Google Geolocation API (requires API key)
    if google_api_key:
        logger.info("Trying WiFi geolocation via Google API...")
        location = await geolocate_via_google(google_api_key, interface=interface)
        if location:
            return location

    # Fallback to IP geolocation (least accurate)
    logger.info("Falling back to IP geolocation (city-level accuracy)")
    return await geolocate_via_ip()
