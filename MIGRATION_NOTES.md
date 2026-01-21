# Database Migration Notes

## Enhanced Vendor Lookup (v1.1.0)

### New Database Fields

The Asset table now includes additional fields for enhanced vendor information:

- `vendor_country` (String, 2 chars) - ISO country code of the vendor
- `is_virtual_machine` (Boolean) - Whether the device is a virtual machine

### Migration Steps

For existing ManoMonitor installations, you'll need to add these columns to your database:

**SQLite:**
```sql
ALTER TABLE assets ADD COLUMN vendor_country VARCHAR(2);
ALTER TABLE assets ADD COLUMN is_virtual_machine BOOLEAN DEFAULT 0;
```

**PostgreSQL:**
```sql
ALTER TABLE assets ADD COLUMN vendor_country VARCHAR(2);
ALTER TABLE assets ADD COLUMN is_virtual_machine BOOLEAN DEFAULT false;
```

### Configuration Changes

New optional configuration settings in `.env`:

```bash
# Enhanced MAC address vendor lookup
MANOMONITOR_MACADDRESS_IO_API_KEY=       # Optional: Get from https://macaddress.io/
MANOMONITOR_MACLOOKUP_APP_API_KEY=       # Optional: Get from https://maclookup.app/
MANOMONITOR_VENDOR_CACHE_DAYS=90         # Days to cache vendor lookups
```

### What's New

The enhanced vendor lookup system now:

1. **Multi-source lookup** - Tries multiple databases for better coverage:
   - Local IEEE OUI database (offline, fast)
   - api.macvendors.com (free, no API key, 1000 req/day)
   - maclookup.app (optional API key, 1000 req/day)
   - macaddress.io (optional API key, 1000 req/month)

2. **Enhanced information** - Provides:
   - More accurate manufacturer names
   - Better device type detection (Mobile, Computer, IoT, etc.)
   - Country information
   - Virtual machine detection
   - Block type (MA-L, MA-M, MA-S)

3. **Intelligent caching** - Caches results for 90 days (configurable) to minimize API usage

4. **Graceful fallback** - Works without API keys, gradually tries more sources as needed

### Backwards Compatibility

All changes are backwards compatible. The old `VendorLookup` class is aliased to `EnhancedVendorLookup`, so existing code continues to work without modification.
