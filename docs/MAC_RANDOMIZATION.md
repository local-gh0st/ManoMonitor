# MAC Address Randomization Detection

## Overview

Modern devices use **MAC address randomization** as a privacy feature. When scanning for WiFi networks, they broadcast probe requests with randomly-generated MAC addresses instead of their real hardware address. This makes tracking difficult but can also make presence detection confusing.

ManoMonitor includes intelligent **device fingerprinting** to detect and group randomized MACs that likely belong to the same physical device.

## Understanding MAC Randomization

### What is MAC Randomization?

- **Normal MAC**: `A4:83:E7:12:34:56` (globally unique, assigned by manufacturer)
- **Randomized MAC**: `02:A3:B4:C5:D6:E7` (temporary, changes periodically)

### How to Detect Randomized MACs

Randomized MACs have the "locally administered" bit set (bit 1 of first byte):

- First byte patterns: `X2`, `X6`, `XA`, `XE` (where X is any hex digit)
- Examples: `02:XX:XX`, `06:XX:XX`, `0A:XX:XX`, `0E:XX:XX`, `12:XX:XX`, etc.

### Why Devices Use It

- **Privacy**: Prevents tracking across different WiFi networks
- **Security**: Makes device fingerprinting harder
- **Standards**: Required by default on iOS 14+, Android 10+, Windows 10+

## How ManoMonitor Handles It

### Detection

ManoMonitor automatically detects randomized MACs by checking the locally-administered bit:

```python
def is_randomized_mac(mac_address: str) -> bool:
    """Check if MAC has locally-administered bit set."""
    first_byte = int(mac_address.split(":")[0], 16)
    return bool(first_byte & 0b00000010)
```

### Fingerprinting

Even though we **cannot reverse randomization** to get the real MAC, we can fingerprint devices based on:

1. **Signal Strength Patterns**
   - Same physical location = similar signal strength
   - Most reliable indicator for home networks

2. **Probe Timing**
   - Devices scan at characteristic intervals
   - iOS devices: ~every 5-15 seconds
   - Android devices: ~every 30-60 seconds

3. **SSID Lists**
   - Devices probe for known networks
   - Your phone probes for "Home WiFi", "Work WiFi", etc.
   - Same SSIDs = likely same device

4. **Vendor Patterns**
   - Some randomization keeps OUI (first 3 bytes)
   - Apple devices often use locally-administered Apple OUIs

### Grouping Algorithm

Devices are grouped using a **similarity score** (0.0 to 1.0):

| Factor | Weight | Description |
|--------|--------|-------------|
| Signal Strength | 40% | Devices in same location have similar signal |
| SSID Overlap | 30% | Probing for same networks indicates same owner |
| Probe Timing | 20% | Similar scan intervals suggest same OS/device |
| Vendor Prefix | 10% | MAC prefix patterns (if preserved) |

**Minimum confidence**: 60% to group MACs together

## Usage

### Automatic Analysis

Fingerprinting runs automatically when:
- New devices are discovered
- Every 10 detections (periodic re-analysis)

### Manual Analysis

Trigger full fingerprinting analysis:

```bash
manomonitor analyze-randomization
```

Output:
```
Analyzing devices for MAC randomization...

• 02:A3:B4:C5:D6:E7 - Randomized MAC detected
  → Grouped into: My iPhone (confidence: 85%)
• 06:11:22:33:44:55 - Randomized MAC detected
  → Grouped into: My iPhone (confidence: 92%)

Summary:
  Total devices: 15
  Randomized MACs: 8
  Grouped devices: 8
```

### View Device Groups

List all identified device groups:

```bash
manomonitor list-device-groups
```

Shows:
- All MACs in each group
- Confidence scores
- Last seen timestamps

### Database Migration

Apply the database changes:

```bash
# For SQLite (default)
sqlite3 data/manomonitor.db < migrations/003_add_mac_randomization_detection.sql

# Or let ManoMonitor auto-migrate on startup
manomonitor serve
```

## Privacy Considerations

### What We CAN'T Do

❌ **Cannot recover real hardware MAC** - This is cryptographically protected
❌ **Cannot track across different networks** - Fingerprints are location-specific
❌ **Cannot bypass privacy protections** - This is by design

### What We CAN Do

✅ **Group MACs on YOUR network** - Track your own devices at home
✅ **Detect presence patterns** - Know when devices are home
✅ **Improve accuracy** - Reduce duplicate device entries
✅ **Provide confidence scores** - Show probability of matches

### Ethical Use

This feature is designed for:
- **Home network monitoring** - Track your own devices
- **Security monitoring** - Detect unauthorized access
- **Presence automation** - Trigger smart home actions

**Not intended for:**
- Tracking people without consent
- Public WiFi surveillance
- Commercial tracking

## Disabling MAC Randomization

If you prefer to use real MAC addresses (better accuracy):

### iPhone/iPad

1. Settings → WiFi
2. Tap (i) next to your network name
3. Turn OFF "Private Wi-Fi Address"

### Android

1. Settings → Network & Internet → WiFi
2. Tap your network name
3. Advanced → Privacy → Use device MAC

### Windows 10/11

1. Settings → Network & Internet → WiFi
2. Manage known networks
3. Select your network → Properties
4. Random hardware addresses → OFF

### macOS

1. System Preferences → Network → WiFi → Advanced
2. Uncheck "Use private Wi-Fi addresses"

## Technical Details

### Database Schema

```sql
-- Device groups table
CREATE TABLE device_groups (
    id INTEGER PRIMARY KEY,
    name VARCHAR(100),              -- User-assigned name
    primary_mac VARCHAR(17),        -- Most recent MAC for display
    confidence_score FLOAT,         -- Grouping confidence (0.0-1.0)
    fingerprint_data TEXT,          -- JSON fingerprint
    first_seen DATETIME,
    last_seen DATETIME,
    times_seen INTEGER
);

-- Add to assets table
ALTER TABLE assets ADD COLUMN is_randomized_mac BOOLEAN;
ALTER TABLE assets ADD COLUMN device_group_id INTEGER REFERENCES device_groups(id);
```

### Fingerprint Structure

```json
{
    "avg_signal": -45.5,
    "signal_var": 3.2,
    "avg_interval": 12.5,
    "interval_var": 2.1,
    "vendor_prefix": "02:A3:B4",
    "ssids": ["HomeWiFi", "WorkWiFi", "CoffeeShop"]
}
```

## Troubleshooting

### Too Many Duplicate Devices

**Cause**: Aggressive MAC randomization with low grouping confidence

**Solutions**:
1. Disable MAC randomization on your devices (most accurate)
2. Lower the confidence threshold in `mac_fingerprinting.py`
3. Manually group devices in the web UI (future feature)

### Devices Not Being Grouped

**Cause**: Not enough probe data to fingerprint

**Solutions**:
1. Wait for more probe requests (need 10+ probes)
2. Ensure devices are actively scanning (not connected)
3. Check signal strength is consistent

### False Positives (Wrong Grouping)

**Cause**: Multiple devices in same location with similar patterns

**Solutions**:
1. Increase confidence threshold to 70-80%
2. Disable randomization for better accuracy
3. Manually split groups using CLI/web UI

## API Endpoints

```
GET /api/device-groups
    List all device groups

GET /api/device-groups/{id}
    Get specific group details

POST /api/device-groups/{id}/merge
    Manually merge two groups

POST /api/device-groups/{id}/split
    Split a device group

PATCH /api/device-groups/{id}
    Update group name/settings
```

## Future Enhancements

- [ ] Machine learning for better fingerprinting
- [ ] Time-based patterns (work hours vs. home hours)
- [ ] Bluetooth correlation (BLE + WiFi MAC matching)
- [ ] User feedback loop (correct/incorrect groupings)
- [ ] Export device group mappings

## References

- [IEEE 802.11 MAC Randomization](https://www.wi-fi.org/knowledge-center/faq/what-is-mac-address-randomization)
- [Apple Privacy: MAC Address Randomization](https://support.apple.com/en-us/HT211227)
- [Android MAC Randomization](https://source.android.com/devices/tech/connect/wifi-mac-randomization)
