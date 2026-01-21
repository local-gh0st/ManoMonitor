"""MAC address vendor/manufacturer lookup utility."""

import logging
import re
from dataclasses import dataclass
from typing import Optional

from mac_vendor_lookup import AsyncMacLookup, MacLookup

logger = logging.getLogger(__name__)

# Common device type patterns based on vendor names
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
    r"harman|jbl.*auto|samsung.*harman": "Vehicle",  # Car audio/infotainment
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
}


@dataclass
class VendorInfo:
    """Information about a device vendor/manufacturer."""

    vendor: Optional[str] = None
    device_type: Optional[str] = None

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
            # Vehicles
            "tesla": "Tesla",
            "bmw": "BMW",
            "bayerische": "BMW",
            "mercedes": "Mercedes",
            "daimler": "Mercedes",
            "volkswagen": "VW",
            "ford motor": "Ford",
            "general motors": "GM",
            "toyota": "Toyota",
            "honda motor": "Honda",
            "hyundai motor": "Hyundai",
            "kia motor": "Kia",
            "volvo car": "Volvo",
            "rivian": "Rivian",
            "lucid": "Lucid",
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


def _guess_device_type(vendor: str) -> Optional[str]:
    """Guess device type based on vendor name patterns."""
    vendor_lower = vendor.lower()

    for pattern, device_type in DEVICE_TYPE_PATTERNS.items():
        if re.search(pattern, vendor_lower):
            return device_type

    return None


class VendorLookup:
    """
    MAC address vendor lookup service.

    Uses the IEEE OUI database to identify device manufacturers.
    """

    def __init__(self):
        self._sync_lookup: Optional[MacLookup] = None
        self._async_lookup: Optional[AsyncMacLookup] = None
        self._initialized = False

    def _init_sync(self) -> MacLookup:
        """Initialize synchronous lookup (downloads DB if needed)."""
        if self._sync_lookup is None:
            self._sync_lookup = MacLookup()
            try:
                # Try to use cached database first
                self._sync_lookup.update_vendors()
            except Exception as e:
                logger.warning(f"Could not update vendor database: {e}")
        return self._sync_lookup

    async def _init_async(self) -> AsyncMacLookup:
        """Initialize async lookup."""
        if self._async_lookup is None:
            self._async_lookup = AsyncMacLookup()
            if not self._initialized:
                try:
                    await self._async_lookup.update_vendors()
                    self._initialized = True
                except Exception as e:
                    logger.warning(f"Could not update vendor database: {e}")
        return self._async_lookup

    def lookup_sync(self, mac_address: str) -> VendorInfo:
        """
        Look up vendor information synchronously.

        Args:
            mac_address: MAC address (any format with colons, dashes, or no separator)

        Returns:
            VendorInfo with vendor name and guessed device type
        """
        try:
            lookup = self._init_sync()
            vendor = lookup.lookup(mac_address)
            device_type = _guess_device_type(vendor) if vendor else None
            return VendorInfo(vendor=vendor, device_type=device_type)
        except Exception as e:
            logger.debug(f"Vendor lookup failed for {mac_address}: {e}")
            return VendorInfo()

    async def lookup(self, mac_address: str) -> VendorInfo:
        """
        Look up vendor information asynchronously.

        Args:
            mac_address: MAC address (any format with colons, dashes, or no separator)

        Returns:
            VendorInfo with vendor name and guessed device type
        """
        try:
            lookup = await self._init_async()
            vendor = await lookup.lookup(mac_address)
            device_type = _guess_device_type(vendor) if vendor else None
            return VendorInfo(vendor=vendor, device_type=device_type)
        except Exception as e:
            logger.debug(f"Vendor lookup failed for {mac_address}: {e}")
            return VendorInfo()

    async def update_database(self) -> bool:
        """Update the vendor database from IEEE."""
        try:
            lookup = await self._init_async()
            await lookup.update_vendors()
            self._initialized = True
            logger.info("Vendor database updated successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to update vendor database: {e}")
            return False


# Singleton instance
_vendor_lookup: Optional[VendorLookup] = None


def get_vendor_lookup() -> VendorLookup:
    """Get or create the global VendorLookup instance."""
    global _vendor_lookup
    if _vendor_lookup is None:
        _vendor_lookup = VendorLookup()
    return _vendor_lookup


async def lookup_vendor(mac_address: str) -> VendorInfo:
    """Convenience function for async vendor lookup."""
    return await get_vendor_lookup().lookup(mac_address)


def lookup_vendor_sync(mac_address: str) -> VendorInfo:
    """Convenience function for sync vendor lookup."""
    return get_vendor_lookup().lookup_sync(mac_address)
