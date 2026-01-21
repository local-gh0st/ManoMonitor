# Multi-Monitor Setup Guide for ManoMonitor

This guide explains how to set up multiple ManoMonitor instances for device triangulation and accurate positioning.

## Overview

ManoMonitor uses a **primary/secondary architecture** for multi-monitor triangulation:

- **Primary Monitor**: Central instance that aggregates data and performs triangulation
- **Secondary Monitors**: Remote instances that report signal readings to the primary

### How It Works

1. Each monitor captures WiFi signals independently
2. Secondary monitors report readings to primary via REST API
3. Primary monitor aggregates readings from all monitors
4. Bilateration/triangulation calculates device positions using signal strength + monitor locations
5. Device positions displayed on interactive map

### Architecture Diagram

```
┌─────────────────┐         ┌─────────────────┐
│ Monitor #1      │         │ Monitor #2      │
│ (Living Room)   │         │ (Garage)        │
│                 │         │                 │
│ - Captures WiFi │         │ - Captures WiFi │
│ - Local DB      │◄────────┤ - Local DB      │
│ - Web UI        │  Reports│ - Reports to #1 │
│ - Triangulation │  via API│                 │
│ PRIMARY         │         │ SECONDARY       │
└─────────────────┘         └─────────────────┘
        ▲                            │
        │                            │
        └────────────────────────────┘
          Monitor #3 (Basement)
          - Captures WiFi
          - Local DB
          - Reports to #1
          SECONDARY
```

## Prerequisites

- 2-3+ Linux devices with WiFi adapters supporting monitor mode
- All devices on the same network (or accessible via IP)
- Known physical locations for each device (use Google Maps to get coordinates)

## Step-by-Step Setup

### 1. Install ManoMonitor on All Devices

On each device (primary and all secondaries):

```bash
# Clone repository
git clone https://github.com/local-gh0st/ManoMonitor.git
cd ManoMonitor

# Switch to the enhanced branch
git checkout claude/review-manomonitor-PocQ4

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -e .

# Install tshark if needed
sudo apt install tshark
```

### 2. Set Up Primary Monitor (Central Hub)

On your primary device (e.g., device with best network access or most central location):

```bash
cd ManoMonitor
cp .env.example .env
nano .env
```

Configure the primary monitor:

```bash
# Application
MANOMONITOR_HOST=0.0.0.0  # Important: allow external connections
MANOMONITOR_PORT=8080

# WiFi Interface (find with: ip link show | grep wlan)
MANOMONITOR_WIFI_INTERFACE=wlan1  # or wlan0, wlp3s0, etc.
MANOMONITOR_CAPTURE_ENABLED=true

# Network Monitoring
MANOMONITOR_ARP_MONITORING_ENABLED=true
MANOMONITOR_DHCP_MONITORING_ENABLED=true

# Monitor Location (CRITICAL - get from Google Maps)
MANOMONITOR_MONITOR_NAME=Living Room
MANOMONITOR_MONITOR_LATITUDE=37.7749    # Replace with YOUR latitude
MANOMONITOR_MONITOR_LONGITUDE=-122.4194 # Replace with YOUR longitude

# Enable map
MANOMONITOR_MAP_ENABLED=true

# Signal calibration (adjust based on your environment)
MANOMONITOR_SIGNAL_TX_POWER=-59         # Reference power at 1m
MANOMONITOR_SIGNAL_PATH_LOSS=3.0        # 2.0=open, 3.0=indoor, 4.0=obstructed
MANOMONITOR_SIGNAL_AVERAGING_WINDOW=5

# Auto-location detection (optional - manual is more accurate)
MANOMONITOR_AUTO_DETECT_LOCATION=false  # Set true to use GPS/WiFi geolocation
```

**Start the primary monitor:**

```bash
# Put WiFi interface in monitor mode
sudo airmon-ng check kill
sudo ip link set wlan1 down
sudo iw wlan1 set monitor control
sudo ip link set wlan1 up

# Start ManoMonitor
sudo ./venv/bin/manomonitor run
```

**Get the API key from logs:**

Look for this in the startup output:
```
2026-01-21 12:00:00,000 - manomonitor.main - INFO - Monitor API key: 1234567890abcdef...
```

**Or retrieve it via API:**

```bash
# From another terminal
curl http://localhost:8080/api/monitors | jq
```

Save this API key - you'll need it for secondary monitors!

### 3. Set Up Secondary Monitors

On each secondary device:

```bash
cd ManoMonitor
cp .env.example .env
nano .env
```

Configure each secondary monitor:

```bash
# Application
MANOMONITOR_HOST=0.0.0.0
MANOMONITOR_PORT=8080

# WiFi Interface
MANOMONITOR_WIFI_INTERFACE=wlan1

# Network Monitoring (optional on secondaries)
MANOMONITOR_ARP_MONITORING_ENABLED=false  # Primary handles this
MANOMONITOR_DHCP_MONITORING_ENABLED=false

# Monitor Location (DIFFERENT for each secondary!)
MANOMONITOR_MONITOR_NAME=Garage           # Unique name
MANOMONITOR_MONITOR_LATITUDE=37.7751      # THIS device's location
MANOMONITOR_MONITOR_LONGITUDE=-122.4190   # THIS device's location

# Map (optional on secondaries)
MANOMONITOR_MAP_ENABLED=false  # Only primary needs UI
```

**Start the secondary monitor:**

```bash
# Put WiFi interface in monitor mode
sudo airmon-ng check kill
sudo ip link set wlan1 down
sudo iw wlan1 set monitor control
sudo ip link set wlan1 up

# Start ManoMonitor
sudo ./venv/bin/manomonitor run
```

### 4. Register Secondary Monitors with Primary

On each secondary device, register with the primary:

**Method A: Via API (Recommended)**

```bash
# Get the primary's IP address
PRIMARY_IP="192.168.1.100"  # Replace with primary's IP
PRIMARY_API_KEY="<api-key-from-primary>"

# Register this secondary monitor
curl -X POST http://${PRIMARY_IP}:8080/api/monitors/register \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Garage",
    "latitude": 37.7751,
    "longitude": -122.4190,
    "api_key": "'${PRIMARY_API_KEY}'"
  }'
```

**Method B: Via Web UI**

1. Open primary's web UI: `http://<primary-ip>:8080`
2. Go to Settings → Monitors
3. Click "Add Monitor"
4. Enter name, latitude, longitude
5. Use the same API key from primary

### 5. Configure Secondary to Report Readings

Each secondary needs to send signal readings to the primary. Create a reporting script:

```bash
# On secondary device
nano ~/report_to_primary.sh
```

Add this script:

```bash
#!/bin/bash

PRIMARY_IP="192.168.1.100"  # Replace with primary's IP
PRIMARY_API_KEY="<api-key>"  # From primary
LOCAL_DB="/home/user/ManoMonitor/data/manomonitor.db"

# Every 30 seconds, query local DB and report to primary
while true; do
    # Get recent signal readings from local DB
    READINGS=$(sqlite3 -json "$LOCAL_DB" \
        "SELECT mac_address, signal_strength
         FROM probe_logs
         WHERE timestamp >= datetime('now', '-30 seconds')
         GROUP BY mac_address
         ORDER BY timestamp DESC")

    # Send to primary
    if [ ! -z "$READINGS" ]; then
        curl -s -X POST "http://${PRIMARY_IP}:8080/api/monitors/report" \
            -H "Content-Type: application/json" \
            -d "{\"api_key\": \"${PRIMARY_API_KEY}\", \"readings\": ${READINGS}}"
    fi

    sleep 30
done
```

Make it executable and run:

```bash
chmod +x ~/report_to_primary.sh
./report_to_primary.sh &
```

### 6. Verify Multi-Monitor Setup

On the **primary** device:

**Check registered monitors:**
```bash
curl http://localhost:8080/api/monitors | jq
```

Should show all monitors with their locations and online status.

**View map data:**
```bash
curl http://localhost:8080/api/map/data | jq
```

Should show devices with readings from multiple monitors.

**Open Web UI:**
```
http://<primary-ip>:8080/map
```

You should see:
- All monitors on the map with their locations
- Devices being tracked
- Position estimates from triangulation

## Signal Calibration

For accurate positioning, calibrate the signal-to-distance conversion:

### 1. Place a Test Device at Known Distances

Place a phone/device at known distances from a monitor:
- 1 meter
- 3 meters
- 5 meters
- 10 meters

### 2. Record Signal Strengths

On the monitor, check signal readings:

```bash
curl http://localhost:8080/api/assets | jq '.[] | {mac: .mac_address, signal: .last_signal_strength}'
```

### 3. Adjust Calibration

Edit `.env` on primary:

```bash
# If distances are underestimated, increase TX_POWER (more negative)
MANOMONITOR_SIGNAL_TX_POWER=-65  # Was -59

# If distances are overestimated, decrease TX_POWER (less negative)
MANOMONITOR_SIGNAL_TX_POWER=-55  # Was -59

# Adjust path loss for your environment:
# 2.0 = Free space / outdoor
# 2.5 = Office / minimal walls
# 3.0 = Typical home / multiple walls (DEFAULT)
# 3.5 = Concrete/brick walls
# 4.0 = Dense construction / metal
MANOMONITOR_SIGNAL_PATH_LOSS=3.5
```

Restart primary and test again.

## Troubleshooting

### Monitors Not Showing as Online

Check connectivity:
```bash
# From secondary
ping <primary-ip>
curl http://<primary-ip>:8080/api/status
```

Verify API key matches and last_seen timestamp is recent.

### Poor Position Accuracy

1. **Verify monitor locations are accurate**
   - Use Google Maps to get precise lat/long
   - Double-check no typos in coordinates

2. **Calibrate signal parameters**
   - See calibration section above

3. **Add more monitors**
   - 2 monitors = 1 intersection point (bilateration)
   - 3+ monitors = multiple intersections, averaged (triangulation)
   - More monitors = better accuracy

4. **Check signal averaging**
   - Increase `SIGNAL_AVERAGING_WINDOW` for smoother results
   - Decrease for faster updates

### Devices Not Being Detected

- Ensure WiFi interfaces are in monitor mode (`iw <interface> info`)
- Check monitor is on correct channel for your devices
- Verify tshark is capturing (`sudo tshark -i wlan1 -c 5`)

### Secondary Not Reporting

Check the report script:
```bash
# On secondary, check if script is running
ps aux | grep report_to_primary

# Test manually
curl -X POST http://<primary-ip>:8080/api/monitors/report \
  -H "Content-Type: application/json" \
  -d '{"api_key": "<key>", "readings": [{"mac_address": "AA:BB:CC:DD:EE:FF", "signal_strength": -60}]}'
```

## Advanced Configuration

### Shared PostgreSQL Database (Alternative Architecture)

Instead of API reporting, use a shared PostgreSQL database:

**1. Set up PostgreSQL on primary:**
```bash
sudo apt install postgresql
sudo -u postgres createdb manomonitor
sudo -u postgres psql -c "CREATE USER manomonitor WITH PASSWORD 'password';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE manomonitor TO manomonitor;"
```

**2. Configure all monitors to use shared DB:**

On all devices (primary and secondaries):
```bash
# Edit .env
MANOMONITOR_DATABASE_URL=postgresql+asyncpg://manomonitor:password@<primary-ip>:5432/manomonitor
```

**3. Allow remote PostgreSQL connections:**

On primary:
```bash
# Edit postgresql.conf
sudo nano /etc/postgresql/*/main/postgresql.conf
# Set: listen_addresses = '*'

# Edit pg_hba.conf
sudo nano /etc/postgresql/*/main/pg_hba.conf
# Add: host manomonitor manomonitor 192.168.1.0/24 md5

sudo systemctl restart postgresql
```

This way, all monitors write to the same database directly (no API reporting needed).

### Automated Monitoring with systemd

Create systemd service on each device:

```bash
sudo nano /etc/systemd/system/manomonitor.service
```

```ini
[Unit]
Description=ManoMonitor WiFi Device Tracking
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/home/user/ManoMonitor
ExecStartPre=/bin/bash -c 'ip link set wlan1 down && iw wlan1 set monitor control && ip link set wlan1 up'
ExecStart=/home/user/ManoMonitor/venv/bin/manomonitor run
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable manomonitor
sudo systemctl start manomonitor
```

## Testing the Setup

### 1. Walk Test

1. Take a phone/device and walk around your space
2. Watch the map on primary: `http://<primary-ip>:8080/map`
3. Device position should update and follow you
4. Check accuracy by comparing map position to your actual location

### 2. Multiple Devices

Place 2-3 devices at known locations and verify:
- All devices appear on map
- Positions are reasonably accurate
- Signal strengths make sense (closer = stronger)

### 3. Monitor Coverage

Check signal readings from each monitor:

```bash
curl http://<primary-ip>:8080/api/map/data | jq '.devices[] | {mac: .mac, readings: .readings}'
```

Should show readings from multiple monitors for each device.

## Tips for Best Results

1. **Monitor Placement**:
   - Place monitors at corners/edges of your space
   - Avoid clustering monitors together
   - Higher placement = better range

2. **Accurate Locations**:
   - Use GPS coordinates, not approximations
   - Use Google Maps: right-click → "What's here?"
   - Record to 6 decimal places (~0.1 meter accuracy)

3. **Calibration**:
   - Start with defaults
   - Test with known device at known distances
   - Adjust TX_POWER and PATH_LOSS iteratively

4. **Monitor Count**:
   - 1 monitor: Direction + distance estimate only
   - 2 monitors: Single intersection (bilateration)
   - 3+ monitors: Multiple intersections averaged (best accuracy)

5. **Environment**:
   - Walls, metal, water affect signal propagation
   - Calibrate per-environment for best results
   - Consider different PATH_LOSS for different rooms

---

## Quick Reference: Command Summary

**Primary Setup:**
```bash
git clone https://github.com/local-gh0st/ManoMonitor.git && cd ManoMonitor
git checkout claude/review-manomonitor-PocQ4
python3 -m venv venv && source venv/bin/activate && pip install -e .
cp .env.example .env
# Edit .env with primary config
sudo airmon-ng check kill
sudo ip link set wlan1 down && sudo iw wlan1 set monitor control && sudo ip link set wlan1 up
sudo ./venv/bin/manomonitor run
# Note the API key from logs
```

**Secondary Setup:**
```bash
# Same install steps as primary
# Edit .env with secondary config (different location!)
sudo ip link set wlan1 down && sudo iw wlan1 set monitor control && sudo ip link set wlan1 up
sudo ./venv/bin/manomonitor run

# Register with primary
curl -X POST http://<primary-ip>:8080/api/monitors/register \
  -H "Content-Type: application/json" \
  -d '{"name": "Garage", "latitude": XX.XXXX, "longitude": -YY.YYYY, "api_key": "<primary-key>"}'
```

**Check Status:**
```bash
curl http://<primary-ip>:8080/api/monitors | jq
curl http://<primary-ip>:8080/api/map/data | jq
```

**Web UI:**
```
http://<primary-ip>:8080/map
```

---

Need help? Check logs: `sudo journalctl -u manomonitor -f` or run with `MANOMONITOR_DEBUG=true`
