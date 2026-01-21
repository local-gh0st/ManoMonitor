#!/usr/bin/env python3
"""Test script for enhanced vendor lookup."""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from manomonitor.utils.vendor import EnhancedVendorLookup


async def test_vendor_lookup():
    """Test vendor lookup with various MAC addresses."""

    # Test MAC addresses from different manufacturers
    test_macs = [
        ("00:1B:63:84:45:E6", "Apple iPhone"),
        ("3C:22:FB:00:00:00", "Apple Mac"),
        ("B8:27:EB:00:00:00", "Raspberry Pi Foundation"),
        ("AC:DE:48:00:11:22", "Apple"),
        ("00:50:56:00:00:00", "VMware (Virtual Machine)"),
        ("08:00:27:00:00:00", "Oracle VirtualBox (VM)"),
        ("DC:A6:32:00:00:00", "Raspberry Pi Trading"),
        ("28:CD:C1:00:00:00", "Espressif (IoT Device)"),
        ("CC:50:E3:00:00:00", "Samsung Electronics"),
        ("00:04:20:00:00:00", "Cisco Systems"),
        ("70:B3:D5:00:00:00", "Google"),
        ("24:F6:77:00:00:00", "Amazon Technologies"),
        ("F0:18:98:00:00:00", "Apple"),
    ]

    lookup = EnhancedVendorLookup()

    print("=" * 80)
    print("Enhanced MAC Address Vendor Lookup Test")
    print("=" * 80)
    print()
    print("Testing multi-source lookup with fallback:")
    print("  1. Local IEEE OUI database")
    print("  2. api.macvendors.com (free, no API key)")
    print("  3. maclookup.app (if API key configured)")
    print("  4. macaddress.io (if API key configured)")
    print()
    print("=" * 80)
    print()

    for mac, description in test_macs:
        print(f"Testing: {mac} ({description})")
        print("-" * 80)

        try:
            result = await lookup.lookup(mac)

            print(f"  MAC Address:       {mac}")
            print(f"  Vendor:            {result.vendor or 'Unknown'}")
            print(f"  Device Type:       {result.device_type or 'Unknown'}")
            print(f"  Country:           {result.country or 'N/A'}")
            print(f"  Virtual Machine:   {result.is_virtual_machine}")
            print(f"  Source:            {result.source}")

            if result.block_type:
                print(f"  Block Type:        {result.block_type}")

            if result.additional_info:
                print(f"  Additional Info:   {result.additional_info}")

            print()

            # Small delay to respect rate limits
            await asyncio.sleep(0.2)

        except Exception as e:
            print(f"  ERROR: {e}")
            print()

    print("=" * 80)
    print("Test completed!")
    print()
    print("Cache status:")
    print(f"  Cached entries: {len(lookup._cache)}")
    print()

    # Close HTTP client
    await lookup.close()

    print("If you see 'Unknown' for most vendors, consider:")
    print("  1. Checking internet connectivity")
    print("  2. The free api.macvendors.com may have rate limits")
    print("  3. Adding API keys to .env for macaddress.io or maclookup.app")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(test_vendor_lookup())
