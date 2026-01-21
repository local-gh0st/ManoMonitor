"""Utility modules for WhosHere."""

from manomonitor.utils.vendor import (
    EnhancedVendorLookup,
    VendorInfo,
    get_enhanced_vendor_lookup,
    lookup_vendor,
    lookup_vendor_sync,
)

# Backwards compatibility aliases
VendorLookup = EnhancedVendorLookup
get_vendor_lookup = get_enhanced_vendor_lookup

__all__ = [
    "VendorInfo",
    "VendorLookup",
    "EnhancedVendorLookup",
    "get_vendor_lookup",
    "get_enhanced_vendor_lookup",
    "lookup_vendor",
    "lookup_vendor_sync",
]
