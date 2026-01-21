### Thank you CurtiB, original idea and implementation long long time ago https://github.com/curtbraz/WhosHere

# ManoMonitor

WiFi-based device tracking and proximity detection for your home network. Tracks devices via WiFi probe requests, ARP, and DHCP - shows them on a map and sends notifications when specific devices arrive or leave.

## What it is supposed to do

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
pip install -e .
cp .env.example .env
# Edit .env with your settings
manomonitor run
```

Or use the install script for a full system setup:
```bash
sudo ./install.sh
```

**First run:**
- Open `http://localhost:8080` in your browser
- Go to the Map page and click "Set Monitor Location" to place your monitor
- Devices will start appearing as they're detected

## Configuration

All settings use the `MANOMONITOR_` prefix in your `.env` file. Key ones:

- `MANOMONITOR_WIFI_INTERFACE` - Your WiFi interface (default: wlan0)
- `MANOMONITOR_DATABASE_URL` - SQLite by default, supports PostgreSQL
- `MANOMONITOR_IFTTT_WEBHOOK_KEY` - For push notifications
- `MANOMONITOR_HOMEASSISTANT_URL` / `_TOKEN` - For HA integration

Settings can also be changed in the web UI under Settings.

## Running without WiFi capture

If you don't have a monitor-mode capable adapter, run with `--no-capture`:

```bash
manomonitor run --no-capture
```

This still detects devices connected to your network via ARP/DHCP, just won't see devices that aren't connected.

## Multiple monitors

For better location accuracy, run ManoMonitor on multiple devices around your space. Each one needs its location configured, and they'll work together to triangulate device positions.
I have not tested this function fully yet so :shrug:

## License

MIT
