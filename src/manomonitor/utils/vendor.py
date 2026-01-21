"""Enhanced MAC address vendor/manufacturer lookup with multiple data sources."""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import httpx
from mac_vendor_lookup import AsyncMacLookup, MacLookup

logger = logging.getLogger(__name__)


# Enhanced device type patterns with more categories
DEVICE_TYPE_PATTERNS = {
    # Vehicles / Cars (check first - more specific)
    r"tesla": "Vehicle",
    r"bmw|bayerische": "Vehicle",
    r"mercedes|daimler": "Vehicle",
    r"volkswagen|vw\s": "Vehicle",
    r"audi": "Vehicle",
    r"porsche": "Vehicle",
    r"ford\s+motor": "Vehicle",
    r"general\s+motors|gm\s|chevrolet|cadillac|buick": "Vehicle",
    r"toyota": "Vehicle",
    r"honda\s+motor": "Vehicle",
    r"nissan": "Vehicle",
    r"hyundai\s+motor": "Vehicle",
    r"kia\s+motor": "Vehicle",
    r"volvo\s+car": "Vehicle",
    r"jaguar|land\s+rover": "Vehicle",
    r"subaru": "Vehicle",
    r"mazda": "Vehicle",
    r"harman|jbl.*auto|samsung.*harman": "Vehicle",
    r"continental\s+auto": "Vehicle",
    r"bosch.*auto|bosch.*car": "Vehicle",
    r"denso": "Vehicle",
    r"aptiv|delphi": "Vehicle",
    r"rivian": "Vehicle",
    r"lucid": "Vehicle",
    r"polestar": "Vehicle",

    # Mobile phones
    r"apple": "Mobile Device",
    r"samsung.*electro": "Mobile Device",
    r"huawei": "Mobile Device",
    r"xiaomi": "Mobile Device",
    r"oneplus": "Mobile Device",
    r"oppo": "Mobile Device",
    r"vivo\s": "Mobile Device",
    r"google": "Mobile Device",
    r"motorola.*mobility": "Mobile Device",
    r"lg\s+electro": "Mobile Device",
    r"sony\s+mobile": "Mobile Device",
    r"zte": "Mobile Device",
    r"nokia": "Mobile Device",
    r"htc": "Mobile Device",
    r"realme": "Mobile Device",
    r"nothing\s+tech": "Mobile Device",
    r"fairphone": "Mobile Device",

    # Computers
    r"dell": "Computer",
    r"hewlett|hp\s|hp\sinc": "Computer",
    r"lenovo": "Computer",
    r"asus": "Computer",
    r"acer": "Computer",
    r"microsoft": "Computer",
    r"intel\s+corporate": "Computer",
    r"gigabyte": "Computer",
    r"msi\s": "Computer",
    r"asrock": "Computer",
    r"supermicro": "Computer",
    r"framework": "Computer",

    # Networking
    r"cisco": "Network Device",
    r"netgear": "Network Device",
    r"tp-link": "Network Device",
    r"d-link": "Network Device",
    r"ubiquiti": "Network Device",
    r"aruba": "Network Device",
    r"juniper": "Network Device",
    r"linksys": "Network Device",
    r"zyxel": "Network Device",
    r"mikrotik": "Network Device",
    r"fortinet": "Network Device",
    r"palo\s+alto": "Network Device",
    r"meraki": "Network Device",
    r"ruckus": "Network Device",
    r"eero": "Network Device",
    r"orbi|arlo.*net": "Network Device",
    r"synology": "Network Device",
    r"qnap": "Network Device",

    # IoT / Smart Home
    r"amazon": "Smart Device",
    r"ring\s": "Smart Device",
    r"nest\s|google.*nest": "Smart Device",
    r"sonos": "Smart Device",
    r"philips.*lighting|signify|hue": "Smart Device",
    r"tuya": "Smart Device",
    r"espressif": "IoT Device",
    r"raspberry": "IoT Device",
    r"arduino": "IoT Device",
    r"particle": "IoT Device",
    r"shelly": "Smart Device",
    r"smartthings": "Smart Device",
    r"wemo|belkin": "Smart Device",
    r"ecobee": "Smart Device",
    r"honeywell.*home": "Smart Device",
    r"ikea.*trad": "Smart Device",
    r"meross": "Smart Device",
    r"govee": "Smart Device",

    # Appliances
    r"whirlpool": "Appliance",
    r"lg\s+innotek": "Appliance",
    r"samsung.*home": "Appliance",
    r"haier": "Appliance",
    r"bosch|bsh\s": "Appliance",
    r"electrolux": "Appliance",
    r"ge\s+appliance": "Appliance",
    r"miele": "Appliance",
    r"siemens.*home": "Appliance",
    r"dyson": "Appliance",
    r"roomba|irobot": "Appliance",
    r"roborock": "Appliance",
    r"ecovacs": "Appliance",

    # Entertainment
    r"sony\s+(?!mobile)": "Entertainment",
    r"roku": "Entertainment",
    r"apple\s+tv": "Entertainment",
    r"nvidia.*shield": "Entertainment",
    r"chromecast": "Entertainment",
    r"fire\s+tv": "Entertainment",

    # Gaming
    r"nintendo": "Gaming Console",
    r"playstation|sie\s": "Gaming Console",
    r"xbox|microsoft.*xbox": "Gaming Console",
    r"valve": "Gaming Console",
    r"steam\s+deck": "Gaming Console",

    # Wearables
    r"fitbit": "Wearable",
    r"garmin": "Wearable",
    r"whoop": "Wearable",
    r"oura": "Wearable",
    r"polar\s+electro": "Wearable",

    # Cameras
    r"ring|arlo|wyze|eufy|reolink|hikvision|dahua": "Camera",
    r"nest.*cam|google.*cam": "Camera",
    r"blink": "Camera",
    r"logitech.*circle": "Camera",
    r"gopro": "Camera",
    r"dji": "Camera",

    # Printers
    r"canon|epson|brother|xerox|lexmark|ricoh|kyocera": "Printer",

    # TVs
    r"vizio|tcl|hisense|roku.*tv|lg.*tv|samsung.*tv": "Smart TV",
    r"sony.*bravia": "Smart TV",
    r"toshiba.*tv": "Smart TV",

    # Virtual Machines
    r"vmware": "Virtual Machine",
    r"virtualbox|oracle.*vm": "Virtual Machine",
    r"xen\s|xensource": "Virtual Machine",
    r"microsoft.*hyper-v": "Virtual Machine",
    r"parallels": "Virtual Machine",
    r"qemu": "Virtual Machine",
}


@dataclass
class VendorInfo:
    """Information about a device vendor/manufacturer."""

    vendor: Optional[str] = None
    device_type: Optional[str] = None
    country: Optional[str] = None
    is_virtual_machine: bool = False
    block_type: Optional[str] = None  # MA-L, MA-M, MA-S
    source: str = "unknown"  # Which data source provided the info
    additional_info: dict = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        """Get a display-friendly name."""
        if self.vendor:
            return self.vendor
        return "Unknown"

    @property
    def short_name(self) -> str:
        """Get a shortened vendor name (first word or abbreviated)."""
        if not self.vendor:
            return "Unknown"

        # Common abbreviations
        abbreviations = {
            "apple": "Apple",
            "samsung electronics": "Samsung",
            "huawei technologies": "Huawei",
            "xiaomi communications": "Xiaomi",
            "google": "Google",
            "microsoft": "Microsoft",
            "intel corporate": "Intel",
            "amazon technologies": "Amazon",
            "lg electronics": "LG",
            "sony mobile": "Sony",
            "dell": "Dell",
            "hewlett packard": "HP",
            "lenovo": "Lenovo",
            "cisco systems": "Cisco",
            "tp-link": "TP-Link",
            "netgear": "Netgear",
            "raspberry pi": "Raspberry Pi",
            "espressif": "Espressif",
            "tesla": "Tesla",
            "bmw": "BMW",
            "mercedes": "Mercedes",
            "volkswagen": "VW",
            "ford motor": "Ford",
            "toyota": "Toyota",
        }

        vendor_lower = self.vendor.lower()
        for pattern, short in abbreviations.items():
            if pattern in vendor_lower:
                return short

        # Default: return first 2 words, max 20 chars
        words = self.vendor.split()[:2]
        result = " ".join(words)
        if len(result) > 20:
            result = result[:17] + "..."
        return result


def _guess_device_type(vendor: str, is_vm: bool = False) -> Optional[str]:
    """Guess device type based on vendor name patterns."""
    if is_vm:
        return "Virtual Machine"

    vendor_lower = vendor.lower()
    for pattern, device_type in DEVICE_TYPE_PATTERNS.items():
        if re.search(pattern, vendor_lower):
            return device_type

    return None


class EnhancedVendorLookup:
    """
    Enhanced MAC address vendor lookup with multiple data sources.

    Tries multiple sources in order:
    1. Local IEEE OUI database (mac-vendor-lookup)
    2. api.macvendors.com (free, no API key)
    3. maclookup.app (optional API key)
    4. macaddress.io (optional API key)

    Results are cached in memory to avoid rate limits.
    """

    def __init__(
        self,
        macaddress_io_api_key: Optional[str] = None,
        maclookup_app_api_key: Optional[str] = None,
        cache_duration_days: int = 90,
    ):
        self._macaddress_io_key = macaddress_io_api_key
        self._maclookup_app_key = maclookup_app_api_key
        self._cache_duration = timedelta(days=cache_duration_days)

        # In-memory cache
        self._cache: dict[str, tuple[VendorInfo, datetime]] = {}

        # IEEE OUI lookup
        self._sync_lookup: Optional[MacLookup] = None
        self._async_lookup: Optional[AsyncMacLookup] = None
        self._ieee_initialized = False

        # HTTP client
        self._http_client: Optional[httpx.AsyncClient] = None

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=10.0,
                follow_redirects=True,
            )
        return self._http_client

    async def close(self):
        """Close HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    def _normalize_mac(self, mac_address: str) -> str:
        """Normalize MAC address to uppercase with colons."""
        # Remove any separators
        mac = re.sub(r"[:\-\.]", "", mac_address.upper())
        # Add colons every 2 characters
        return ":".join(mac[i : i + 2] for i in range(0, 12, 2))

    def _is_cache_valid(self, cached_time: datetime) -> bool:
        """Check if cached entry is still valid."""
        return datetime.utcnow() - cached_time < self._cache_duration

    async def _lookup_ieee_oui(self, mac_address: str) -> Optional[VendorInfo]:
        """Look up using local IEEE OUI database."""
        try:
            if self._async_lookup is None:
                self._async_lookup = AsyncMacLookup()
                if not self._ieee_initialized:
                    await self._async_lookup.update_vendors()
                    self._ieee_initialized = True

            vendor = await self._async_lookup.lookup(mac_address)
            if vendor:
                device_type = _guess_device_type(vendor)
                return VendorInfo(
                    vendor=vendor,
                    device_type=device_type,
                    source="ieee_oui",
                )
        except Exception as e:
            logger.debug(f"IEEE OUI lookup failed for {mac_address}: {e}")
        return None

    async def _lookup_macvendors_com(self, mac_address: str) -> Optional[VendorInfo]:
        """Look up using api.macvendors.com (free, no API key needed)."""
        try:
            client = await self._get_http_client()
            url = f"https://api.macvendors.com/{mac_address}"

            response = await client.get(url)
            if response.status_code == 200:
                vendor = response.text.strip()
                device_type = _guess_device_type(vendor)
                return VendorInfo(
                    vendor=vendor,
                    device_type=device_type,
                    source="macvendors.com",
                )
            elif response.status_code == 429:
                logger.warning("api.macvendors.com rate limit exceeded")
        except Exception as e:
            logger.debug(f"macvendors.com lookup failed for {mac_address}: {e}")
        return None

    async def _lookup_maclookup_app(self, mac_address: str) -> Optional[VendorInfo]:
        """Look up using maclookup.app API."""
        if not self._maclookup_app_key:
            return None

        try:
            client = await self._get_http_client()
            # Extract OUI (first 6 characters)
            oui = mac_address.replace(":", "")[:6]
            url = f"https://api.maclookup.app/v2/macs/{oui}"

            headers = {}
            if self._maclookup_app_key:
                headers["X-Authentication-Token"] = self._maclookup_app_key

            response = await client.get(url, headers=headers)
            if response.status_code == 200:
                data = response.json()
                vendor = data.get("company")
                if vendor:
                    device_type = _guess_device_type(vendor)
                    return VendorInfo(
                        vendor=vendor,
                        device_type=device_type,
                        country=data.get("country"),
                        block_type=data.get("blockType"),
                        source="maclookup.app",
                        additional_info={
                            "blockStart": data.get("blockStart"),
                            "blockEnd": data.get("blockEnd"),
                            "blockSize": data.get("blockSize"),
                        },
                    )
        except Exception as e:
            logger.debug(f"maclookup.app lookup failed for {mac_address}: {e}")
        return None

    async def _lookup_macaddress_io(self, mac_address: str) -> Optional[VendorInfo]:
        """Look up using macaddress.io API (requires API key)."""
        if not self._macaddress_io_key:
            return None

        try:
            client = await self._get_http_client()
            url = f"https://api.macaddress.io/v1"
            params = {
                "apiKey": self._macaddress_io_key,
                "output": "json",
                "search": mac_address,
            }

            response = await client.get(url, params=params)
            if response.status_code == 200:
                data = response.json()

                vendor_details = data.get("vendorDetails", {})
                mac_details = data.get("macAddressDetails", {})

                vendor = vendor_details.get("companyName")
                if vendor:
                    is_vm = mac_details.get("virtualMachine") == "true"
                    device_type = _guess_device_type(vendor, is_vm)

                    return VendorInfo(
                        vendor=vendor,
                        device_type=device_type,
                        country=vendor_details.get("countryCode"),
                        is_virtual_machine=is_vm,
                        source="macaddress.io",
                        additional_info={
                            "companyAddress": vendor_details.get("companyAddress"),
                            "transmissionType": mac_details.get("transmissionType"),
                            "administrationType": mac_details.get("administrationType"),
                        },
                    )
        except Exception as e:
            logger.debug(f"macaddress.io lookup failed for {mac_address}: {e}")
        return None

    async def lookup(self, mac_address: str) -> VendorInfo:
        """
        Look up vendor information using multiple data sources.

        Tries sources in order until one succeeds:
        1. Memory cache
        2. IEEE OUI database
        3. api.macvendors.com
        4. maclookup.app (if API key configured)
        5. macaddress.io (if API key configured)

        Args:
            mac_address: MAC address in any format

        Returns:
            VendorInfo with vendor details or empty info if not found
        """
        normalized_mac = self._normalize_mac(mac_address)

        # Check memory cache
        if normalized_mac in self._cache:
            cached_info, cached_time = self._cache[normalized_mac]
            if self._is_cache_valid(cached_time):
                logger.debug(f"Cache hit for {normalized_mac}")
                return cached_info

        # Try data sources in order
        sources = [
            self._lookup_ieee_oui,
            self._lookup_macvendors_com,
            self._lookup_maclookup_app,
            self._lookup_macaddress_io,
        ]

        for source_func in sources:
            try:
                result = await source_func(normalized_mac)
                if result and result.vendor:
                    # Cache the result
                    self._cache[normalized_mac] = (result, datetime.utcnow())
                    logger.info(
                        f"Vendor lookup for {normalized_mac}: {result.vendor} "
                        f"({result.device_type or 'Unknown type'}) from {result.source}"
                    )
                    return result
            except Exception as e:
                logger.debug(f"Lookup source {source_func.__name__} failed: {e}")
                continue

        # No result found
        logger.debug(f"No vendor info found for {normalized_mac}")
        empty_info = VendorInfo(source="none")
        self._cache[normalized_mac] = (empty_info, datetime.utcnow())
        return empty_info

    def lookup_sync(self, mac_address: str) -> VendorInfo:
        """
        Synchronous wrapper for lookup (uses only IEEE OUI database).

        For full multi-source lookup, use async lookup() method.
        """
        try:
            if self._sync_lookup is None:
                self._sync_lookup = MacLookup()
                try:
                    self._sync_lookup.update_vendors()
                except Exception as e:
                    logger.warning(f"Could not update vendor database: {e}")

            vendor = self._sync_lookup.lookup(mac_address)
            device_type = _guess_device_type(vendor) if vendor else None
            return VendorInfo(
                vendor=vendor,
                device_type=device_type,
                source="ieee_oui",
            )
        except Exception as e:
            logger.debug(f"Sync vendor lookup failed for {mac_address}: {e}")
            return VendorInfo()

    async def update_ieee_database(self) -> bool:
        """Update the IEEE OUI database."""
        try:
            if self._async_lookup is None:
                self._async_lookup = AsyncMacLookup()
            await self._async_lookup.update_vendors()
            self._ieee_initialized = True
            logger.info("IEEE OUI database updated successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to update IEEE OUI database: {e}")
            return False

    def clear_cache(self):
        """Clear the in-memory cache."""
        self._cache.clear()
        logger.info("Vendor lookup cache cleared")


# Singleton instance
_enhanced_lookup: Optional[EnhancedVendorLookup] = None


def get_enhanced_vendor_lookup() -> EnhancedVendorLookup:
    """Get or create the global EnhancedVendorLookup instance."""
    global _enhanced_lookup
    if _enhanced_lookup is None:
        # Try to get API keys and settings from config
        try:
            from manomonitor.config import settings

            _enhanced_lookup = EnhancedVendorLookup(
                macaddress_io_api_key=settings.macaddress_io_api_key or None,
                maclookup_app_api_key=settings.maclookup_app_api_key or None,
                cache_duration_days=settings.vendor_cache_days,
            )
        except Exception:
            # Fallback without config
            _enhanced_lookup = EnhancedVendorLookup()
    return _enhanced_lookup


async def lookup_vendor(mac_address: str) -> VendorInfo:
    """Convenience function for async vendor lookup with multiple sources."""
    return await get_enhanced_vendor_lookup().lookup(mac_address)


def lookup_vendor_sync(mac_address: str) -> VendorInfo:
    """Convenience function for sync vendor lookup (IEEE OUI only)."""
    return get_enhanced_vendor_lookup().lookup_sync(mac_address)
