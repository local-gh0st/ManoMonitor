# ManoMonitor

**WiFi-based device tracking and proximity detection for your home network.**

Tracks devices via WiFi probe requests, ARP, and DHCP. Shows devices on a map using signal triangulation. Sends notifications when tracked devices arrive or leave.

> **Credit:** Original idea and implementation by [CurtiB/WhosHere](https://github.com/curtbraz/WhosHere) - heavily extended and modernized.

## Key Features

### Device Detection
- **📡 WiFi Probe Capture** - Detects devices even if they don't connect to your network
- **🔍 ARP/DHCP Monitoring** - Tracks all connected devices with real MAC addresses
- **🧬 MAC Address Randomization Detection** - Groups randomized MACs as single device
- **🏷️ Enhanced Vendor Identification** - Multi-source MAC lookup with device type detection
- **🔔 Smart Notifications** - IFTTT and Home Assistant integration

### Multi-Monitor Triangulation
- **📍 Signal-Based Positioning** - Triangulate device locations using 2+ monitors
- **🗺️ Interactive Map** - Real-time device positions on OpenStreetMap
- **🤖 Zero-Config Setup** - Auto-discovery and registration for secondary monitors
- **📊 Position Accuracy** - RSSI-to-distance conversion with calibration

### Modern Web UI
- **💻 Responsive Dashboard** - Real-time stats and device list
- **⚙️ Monitor Management** - View all monitors, API keys, and status
- **🎨 Dark Mode** - HTMX-powered reactive UI
- **📈 Device History** - SSID probes and signal strength over time

## Quick Start

### Requirements
- **OS:** Linux (tested on Ubuntu, Debian, Raspberry Pi OS)
- **Python:** 3.8+ (3.11+ recommended)
- **WiFi:** Adapter supporting monitor mode
- **Dependencies:** `tshark` (Wireshark command-line tool)

### Installation

**Install system dependencies:**
```bash
sudo apt update
sudo apt install tshark python3-venv python3-pip git
```

**Clone and install:**
```bash
git clone https://github.com/local-gh0st/ManoMonitor.git
cd ManoMonitor
python3 -m venv venv
source venv/bin/activate
pip install -e .
```

**Configure:**
```bash
cp .env.example .env
nano .env  # Edit with your settings
```

Key settings to configure:
```bash
# WiFi Interface (check with: ip link show | grep wlan)
MANOMONITOR_WIFI_INTERFACE=wlan0

# Monitor Location (get from Google Maps right-click)
MANOMONITOR_MONITOR_NAME=My Monitor
MANOMONITOR_MONITOR_LATITUDE=37.7749
MANOMONITOR_MONITOR_LONGITUDE=-122.4194

# Optional: Enable notifications
MANOMONITOR_IFTTT_WEBHOOK_KEY=your_ifttt_key
MANOMONITOR_HOMEASSISTANT_URL=http://homeassistant.local:8123
MANOMONITOR_HOMEASSISTANT_TOKEN=your_ha_token
```

**Run:**
```bash
# Check dependencies and WiFi interface safety
manomonitor check

# Start the server
sudo manomonitor run
```

Open http://localhost:8080 in your browser!

### First-Time Setup

1. **Monitor Location** - Set your monitor's GPS coordinates in `.env` or web UI Settings
2. **WiFi Interface** - Ensure you're using the correct interface (not your only connection!)
3. **Devices** - As devices appear, add nicknames and enable notifications
4. **Map** - View the Map page to see device positions (requires location configured)

## Multi-Monitor Setup (Triangulation)

Run ManoMonitor on 2-3+ devices to triangulate device positions using signal strength.

### Architecture

- **Primary Monitor** - Central hub with web UI, performs triangulation
- **Secondary Monitors** - Report signal readings to primary via API

### Setup Primary Monitor

Standard installation (above). Make sure to:
- Set `MANOMONITOR_HOST=0.0.0.0` to allow secondary connections
- Configure accurate GPS coordinates
- Start with `sudo manomonitor run`

**Get your API key:**
- Web UI: Navigate to **Monitors** page → copy API key
- Console: Look for "Monitor API Key:" in startup logs
- CLI: Run `manomonitor monitor-info`

### Setup Secondary Monitors

**Automatic setup (recommended):**
```bash
# Clone and install (same as primary)
git clone https://github.com/local-gh0st/ManoMonitor.git
cd ManoMonitor
python3 -m venv venv
source venv/bin/activate
pip install -e .

# Run the automated setup wizard
./scripts/setup-secondary.sh
```

The wizard will:
1. Auto-detect safe WiFi interfaces
2. Prompt for primary monitor URL
3. Auto-fetch API key from primary
4. Configure location (auto-detect or manual)
5. Register with primary
6. Install and start systemd services

**Manual setup:**
```bash
cp .env.example .env
nano .env
```

Configure:
```bash
MANOMONITOR_WIFI_INTERFACE=wlan1
MANOMONITOR_PRIMARY_URL=http://192.168.1.100:8080
MANOMONITOR_API_KEY=<from primary>
MANOMONITOR_MONITOR_NAME=Secondary Monitor
MANOMONITOR_MONITOR_LATITUDE=37.7750
MANOMONITOR_MONITOR_LONGITUDE=-122.4195
```

Start services:
```bash
# Start capture
sudo manomonitor run &

# Start reporter (sends data to primary)
python3 scripts/secondary_reporter.py
```

**See [MULTI_MONITOR_SETUP.md](MULTI_MONITOR_SETUP.md) for detailed documentation.**

## MAC Address Randomization

Modern devices (iOS 14+, Android 10+, Windows 10+) randomize MAC addresses for privacy. ManoMonitor detects this and groups related MACs.

### Features

- **Automatic Detection** - Identifies locally-administered MACs
- **Device Fingerprinting** - Groups randomized MACs by behavior:
  - Signal strength patterns (same location = same device)
  - Probe timing (scan intervals)
  - SSID overlap (networks probed)
- **Confidence Scoring** - Shows probability of correct grouping (0-100%)

### Usage

```bash
# Analyze all devices for randomization
manomonitor analyze-randomization

# View device groups
manomonitor list-device-groups
```

**Web UI:** Device groups will show in the Devices list with grouped MACs.

**Disable Randomization** (for better accuracy):
- **iPhone:** Settings → WiFi → (i) → Private Wi-Fi Address → OFF
- **Android:** Settings → WiFi → Network → Privacy → Use device MAC
- **Windows:** Settings → Network → WiFi → Manage known networks → Random hardware addresses → OFF

**See [docs/MAC_RANDOMIZATION.md](docs/MAC_RANDOMIZATION.md) for technical details.**

## Enhanced Device Identification

ManoMonitor uses multiple vendor databases with intelligent fallback:

### Data Sources

1. **Local IEEE OUI** - Offline, fast, always available
2. **api.macvendors.com** - Free, 1000 req/day, no API key needed
3. **maclookup.app** - Free tier: 1000 req/day with API key
4. **macaddress.io** - Free tier: 1000 req/month with API key

### Information Provided

- Manufacturer name (e.g., "Apple, Inc.")
- Device type (Mobile, Computer, IoT, Vehicle, Gaming Console, etc.)
- Country of origin (ISO code)
- Virtual machine detection

### API Keys (Optional)

Add to `.env` for enhanced data:
```bash
MANOMONITOR_MACADDRESS_IO_API_KEY=your_key_here
MANOMONITOR_MACLOOKUP_APP_API_KEY=your_key_here
MANOMONITOR_VENDOR_CACHE_DAYS=90
```

Get free keys:
- https://macaddress.io/signup (1,000/month free)
- https://maclookup.app/api (1,000/day free)

## WiFi Interface Safety

ManoMonitor includes safety checks to prevent accidentally disconnecting your network connection.

### Safety Features

- **Connection Detection** - Identifies if interface is your only connection
- **Interactive Prompts** - Asks for confirmation if risky
- **Force Flags** - Override with `--force` if you know what you're doing
- **Safe Interface Suggestions** - Recommends disconnected adapters

### Safety Check

```bash
# Check if an interface is safe to use
python3 scripts/check_wifi_safety.py wlan0

# CLI command with safety check
manomonitor check
```

### Setup Script Safety

The secondary setup script automatically:
- Detects all WiFi interfaces
- Checks which are connected
- Suggests safe interfaces
- Warns if you're about to disconnect

**Override:** `./scripts/setup-secondary.sh --force`

## CLI Commands

```bash
# Server
manomonitor run                    # Start web server and capture
manomonitor run --no-capture       # Start without WiFi capture (ARP/DHCP only)

# Device Management
manomonitor devices                # List all tracked devices
manomonitor config                 # Show current configuration
manomonitor check                  # Verify dependencies and safety

# Monitor Management
manomonitor monitor-info           # Show API key and monitor details
manomonitor monitor-list           # List all registered monitors
manomonitor monitor-register URL   # Register with a primary monitor

# MAC Randomization
manomonitor analyze-randomization  # Detect and group randomized MACs
manomonitor list-device-groups     # Show device groups
```

## Configuration

All settings use the `MANOMONITOR_` prefix in `.env`:

### Application
- `MANOMONITOR_HOST` - Bind address (default: 0.0.0.0)
- `MANOMONITOR_PORT` - Web server port (default: 8080)
- `MANOMONITOR_DEBUG` - Enable debug logging (default: false)

### WiFi Capture
- `MANOMONITOR_WIFI_INTERFACE` - Monitor mode interface (default: wlan0)
- `MANOMONITOR_CAPTURE_ENABLED` - Enable probe capture (default: true)

### Network Monitoring
- `MANOMONITOR_ARP_MONITORING_ENABLED` - Track connected devices (default: true)
- `MANOMONITOR_ARP_SCAN_INTERVAL` - Seconds between ARP scans (default: 30)
- `MANOMONITOR_DHCP_MONITORING_ENABLED` - Parse DHCP leases (default: true)
- `MANOMONITOR_DHCP_CHECK_INTERVAL` - Seconds between DHCP checks (default: 60)

### Monitor Location
- `MANOMONITOR_MONITOR_NAME` - Display name (default: Primary)
- `MANOMONITOR_MONITOR_LATITUDE` - GPS latitude (default: 0.0)
- `MANOMONITOR_MONITOR_LONGITUDE` - GPS longitude (default: 0.0)
- `MANOMONITOR_MONITOR_API_KEY` - Authentication key (auto-generated)

### Multi-Monitor (Secondary Only)
- `MANOMONITOR_PRIMARY_URL` - Primary monitor URL (e.g., http://192.168.1.100:8080)
- `MANOMONITOR_API_KEY` - Authentication key from primary

### Signal Processing
- `MANOMONITOR_SIGNAL_TX_POWER` - Reference power at 1m (default: -59 dBm)
- `MANOMONITOR_SIGNAL_PATH_LOSS` - Path loss exponent (default: 3.0)
  - 2.0 = open space
  - 3.0 = indoor (typical)
  - 4.0 = obstructed
- `MANOMONITOR_SIGNAL_AVERAGING_WINDOW` - Readings to average (default: 5)

### Presence Detection
- `MANOMONITOR_DEFAULT_SIGNAL_THRESHOLD` - Minimum signal for "present" (default: -65 dBm)
- `MANOMONITOR_PRESENCE_TIMEOUT_MINUTES` - Minutes before "away" (default: 5)
- `MANOMONITOR_NOTIFICATION_COOLDOWN_MINUTES` - Min time between notifications (default: 60)

### Location Detection
- `MANOMONITOR_AUTO_DETECT_LOCATION` - Auto-detect GPS on startup (default: false)
- `MANOMONITOR_GOOGLE_GEOLOCATION_API_KEY` - For WiFi-based location
- `MANOMONITOR_GPS_ENABLED` - Enable USB GPS dongles (default: false)
- `MANOMONITOR_GPS_DEVICE` - GPS device path (default: auto-detect)

### Notifications
- `MANOMONITOR_IFTTT_ENABLED` - Enable IFTTT (default: false)
- `MANOMONITOR_IFTTT_WEBHOOK_KEY` - IFTTT webhook key
- `MANOMONITOR_IFTTT_EVENT_NAME` - Event name (default: manomonitor_device)
- `MANOMONITOR_HOMEASSISTANT_ENABLED` - Enable HA (default: false)
- `MANOMONITOR_HOMEASSISTANT_URL` - HA server URL
- `MANOMONITOR_HOMEASSISTANT_TOKEN` - Long-lived access token
- `MANOMONITOR_HOMEASSISTANT_NOTIFY_SERVICE` - Notification service (default: notify.notify)

## Database

ManoMonitor uses SQLite by default (portable, zero-config). PostgreSQL is also supported.

### Migrations

When updating ManoMonitor, check for database migrations:

```bash
# Check current schema version
sqlite3 data/manomonitor.db "SELECT name FROM sqlite_master WHERE type='table';"

# Apply migrations
ls migrations/*.sql
sqlite3 data/manomonitor.db < migrations/001_initial.sql
sqlite3 data/manomonitor.db < migrations/002_add_vendor_fields.sql
sqlite3 data/manomonitor.db < migrations/003_add_mac_randomization_detection.sql
```

**PostgreSQL:**
```bash
MANOMONITOR_DATABASE_URL=postgresql+asyncpg://user:pass@localhost/manomonitor
```

## Troubleshooting

### No Devices Detected

1. **Check WiFi interface:**
   ```bash
   manomonitor check
   ip link show | grep wlan
   ```

2. **Verify monitor mode:**
   ```bash
   sudo iw dev wlan0 info | grep type
   # Should show "type monitor"
   ```

3. **Test tshark:**
   ```bash
   sudo tshark -i wlan0 -f "type mgt subtype probe-req" -c 10
   ```

4. **Check ARP/DHCP monitoring:**
   - Web UI → Diagnostics page
   - Check ARP table: `arp -a`
   - Check DHCP leases: `cat /var/lib/dhcp/dhcpd.leases`

### Secondary Monitor Not Showing

1. **Check primary connection:**
   ```bash
   curl http://<primary-ip>:8080/api/status
   ```

2. **Verify API key:**
   ```bash
   curl http://<primary-ip>:8080/api/monitors/local-api-key
   ```

3. **Check reporter logs:**
   ```bash
   sudo journalctl -u manomonitor-reporter -f
   ```

4. **Verify registration:**
   - Primary web UI → Monitors page
   - Should show secondary monitor listed

### Interface Won't Enter Monitor Mode

1. **Check driver support:**
   ```bash
   iw list | grep "Supported interface modes" -A 8
   # Should list "monitor"
   ```

2. **Try different tool:**
   ```bash
   # Method 1: airmon-ng
   sudo airmon-ng check kill
   sudo airmon-ng start wlan0

   # Method 2: iw (preferred)
   sudo ip link set wlan0 down
   sudo iw wlan0 set monitor control
   sudo ip link set wlan0 up
   ```

3. **Check for conflicting processes:**
   ```bash
   sudo airmon-ng check
   # Kill listed processes or use --force flag
   ```

### Permission Denied Errors

ManoMonitor needs root for monitor mode. Run with `sudo`:
```bash
sudo venv/bin/manomonitor run
```

Or install as systemd service (handles permissions automatically):
```bash
sudo ./install.sh
```

## Development

### Project Structure

```
ManoMonitor/
├── src/manomonitor/
│   ├── api/              # FastAPI routes and websockets
│   ├── capture/          # WiFi probe, ARP, DHCP monitoring
│   ├── database/         # SQLAlchemy models and CRUD
│   ├── notifications/    # IFTTT, Home Assistant integrations
│   ├── utils/            # Vendor lookup, geolocation, fingerprinting
│   ├── web/              # Web UI views (HTMX)
│   ├── cli.py            # Typer CLI commands
│   ├── config.py         # Pydantic settings
│   └── main.py           # FastAPI app and startup logic
├── scripts/              # Helper scripts
│   ├── setup-secondary.sh      # Auto-setup wizard
│   ├── secondary_reporter.py   # Secondary → Primary reporter
│   └── check_wifi_safety.py    # Safety checks
├── templates/            # Jinja2 HTML templates
├── static/               # CSS, JS, images
├── migrations/           # Database migration SQL
└── docs/                 # Additional documentation
```

### Running Tests

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run with coverage
pytest --cov=manomonitor
```

### Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

MIT License - see [LICENSE](LICENSE) for details.

## Acknowledgments

- Original concept: [CurtiB/WhosHere](https://github.com/curtbraz/WhosHere)
- Built with: FastAPI, SQLAlchemy, HTMX, Tailwind CSS, Leaflet
- MAC vendor data: IEEE, macvendors.com, macaddress.io, maclookup.app
