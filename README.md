### Thank you CurtiB, original idea and implementation long long time ago https://github.com/curtbraz/WhosHere

# ManoMonitor

WiFi-based device tracking and proximity detection for your home network. Tracks devices via WiFi probe requests, ARP, and DHCP - shows them on a map and sends notifications when specific devices arrive or leave.

## What it is **supposed** to do

- Detects devices via WiFi probe requests (even if they don't connect to your network)
- Tracks connected devices through ARP/DHCP monitoring
- Shows device locations on a map using signal strength triangulation
- Sends notifications via IFTTT or Home Assistant when tracked devices are detected
- Web UI for managing devices, viewing history, and configuring settings
- Identifies device manufacturers from MAC addresses
- Supports USB GPS dongles for accurate monitor positioning

## Setup

**Requirements:**
- Python 3.11+
- Linux (tested on Raspberry Pi, Ubuntu)
- WiFi adapter that supports monitor mode (for probe capture)
- `tshark` installed (`sudo apt install tshark`)

**Installation:**
```bash
git clone https://github.com/local-gh0st/ManoMonitor.git
cd ManoMonitor
python3 -m venv venv
source venv/bin/activate
pip install -e .
cp .env.example .env
# Edit .env with your settings
manomonitor run
```

Or use the install script for a full system setup (*this takes forever btw):
```bash
sudo ./install.sh
```

**First run:**
- Open `http://localhost:8080` in your browser
- You can set device name (default wlan0) in the web UI.
- Copy the example.env and edit the .env with your desired settings but really nothing needs to be set here initially. (can be done in Web UI)
- Go to the Map page and click "Set Monitor Location" to place your monitor
- Devices will start appearing as they're detected

## Configuration

All settings use the `MANOMONITOR_` prefix in your `.env` file. Key ones:

- `MANOMONITOR_WIFI_INTERFACE` - Your WiFi interface (default: wlan0)
- `MANOMONITOR_DATABASE_URL` - SQLite by default, supports PostgreSQL
- `MANOMONITOR_IFTTT_WEBHOOK_KEY` - For push notifications
- `MANOMONITOR_HOMEASSISTANT_URL` / `_TOKEN` - For HA integration
- IFTTT and HA integrations not tested at all, but capabilities may be for future edits.

Settings can also be changed in the web UI under Settings.

## Running without WiFi capture

If you don't have a monitor-mode capable adapter, run with `--no-capture`:

```bash
manomonitor run --no-capture
```

This still detects devices connected to your network via ARP/DHCP, just won't see devices that aren't connected.

## Multiple Monitors (Triangulation)

**Now fully supported with zero-config setup!**

Run ManoMonitor on 2-3+ devices to triangulate device positions using signal strength. The system uses a primary/secondary architecture with automatic discovery.

**Quick Setup:**

1. **Primary Monitor** (central hub):
```bash
git clone https://github.com/local-gh0st/ManoMonitor.git
cd ManoMonitor
python3 -m venv venv && source venv/bin/activate && pip install -e .
cp .env.example .env
# Edit .env: Set MONITOR_LATITUDE and MONITOR_LONGITUDE
sudo manomonitor run
```

2. **Secondary Monitors** (auto-configured):
```bash
git clone https://github.com/local-gh0st/ManoMonitor.git
cd ManoMonitor
python3 -m venv venv && source venv/bin/activate && pip install -e .

# Run the setup wizard - only needs primary URL!
./scripts/setup-secondary.sh
```

The setup wizard auto-detects:
- WiFi interface
- Monitor location (GPS/WiFi/IP geolocation)
- Primary monitor on network
- API key from primary

**See [MULTI_MONITOR_SETUP.md](MULTI_MONITOR_SETUP.md) for detailed documentation.**

## Enhanced Device Identification

ManoMonitor now uses multiple vendor databases for accurate device identification:

- **Local IEEE OUI database** (offline, fast)
- **api.macvendors.com** (free, 1000 req/day, no API key)
- **macaddress.io** (optional API key, rich data)
- **maclookup.app** (optional API key)

Provides:
- Manufacturer name
- Device type (Mobile, Computer, IoT, Vehicle, etc.)
- Country of origin
- Virtual machine detection

**Optional:** Add API keys to `.env` for enhanced data:
```bash
MANOMONITOR_MACADDRESS_IO_API_KEY=your_key
MANOMONITOR_MACLOOKUP_APP_API_KEY=your_key
```

Get free API keys:
- https://macaddress.io/ (1,000 requests/month)
- https://maclookup.app/ (1,000 requests/day)

## CLI Commands

Manage your monitors from the command line:

```bash
manomonitor run                    # Start the server
manomonitor devices                # List tracked devices
manomonitor monitor-info           # Show API key and monitor details
manomonitor monitor-list           # List all registered monitors
manomonitor monitor-register URL   # Register with primary monitor
manomonitor check                  # Verify dependencies
manomonitor config                 # Show current configuration
```

## License

MIT
