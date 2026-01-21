# Multi-Monitor Setup Guide for ManoMonitor

Complete guide for setting up multiple ManoMonitor instances to enable device triangulation and accurate positioning.

## Table of Contents

1. [Overview](#overview)
2. [How It Works](#how-it-works)
3. [Prerequisites](#prerequisites)
4. [Quick Start](#quick-start)
5. [Primary Monitor Setup](#primary-monitor-setup)
6. [Secondary Monitor Setup](#secondary-monitor-setup)
7. [Verification](#verification)
8. [Calibration](#calibration)
9. [Troubleshooting](#troubleshooting)
10. [Advanced Configuration](#advanced-configuration)

## Overview

ManoMonitor uses a **primary/secondary architecture** for multi-monitor triangulation:

- **Primary Monitor** - Central hub with web UI that aggregates data and performs triangulation
- **Secondary Monitors** - Remote instances that capture WiFi signals and report readings to primary via REST API

### Architecture Diagram

```
                 ┌─────────────────────┐
                 │   PRIMARY MONITOR   │
                 │   (Living Room)     │
                 │                     │
                 │ • Web UI (8080)     │
                 │ • Database          │
                 │ • Triangulation     │
                 │ • Map Display       │
                 └──────────▲──────────┘
                            │
          ┌─────────────────┼─────────────────┐
          │                 │                 │
    HTTP API          HTTP API          HTTP API
          │                 │                 │
┌─────────▼────────┐ ┌─────▼────────┐ ┌──────▼───────┐
│ SECONDARY #1     │ │ SECONDARY #2  │ │ SECONDARY #3 │
│ (Garage)         │ │ (Basement)    │ │ (Bedroom)    │
│                  │ │               │ │              │
│ • WiFi Capture   │ │ • WiFi Capture│ │ • WiFi Cap   │
│ • Local DB       │ │ • Local DB    │ │ • Local DB   │
│ • Reporter       │ │ • Reporter    │ │ • Reporter   │
└──────────────────┘ └───────────────┘ └──────────────┘

     Each monitor reports signal readings every 30 seconds
```

### How It Works

1. **Signal Capture**
   - Each monitor independently captures WiFi probe requests
   - Signal strength (RSSI) is measured for each device
   - Data stored locally for reliability

2. **Data Reporting**
   - Secondary monitors report readings to primary every 30 seconds
   - HTTP REST API with authentication (API key)
   - Readings include: MAC address, signal strength, timestamp

3. **Position Calculation**
   - Primary aggregates readings from all monitors
   - RSSI converted to distance using calibrated path loss model
   - Bilateration (2 monitors) or trilateration (3+ monitors) calculates position
   - Results displayed on interactive map

4. **Accuracy Factors**
   - **Monitor Placement**: Spread monitors across your space for best coverage
   - **Signal Calibration**: Tune TX power and path loss for your environment
   - **Monitor Count**: 3+ monitors provide triangulation (most accurate)
   - **Physical Obstacles**: Walls, furniture affect signal propagation

## Prerequisites

### Hardware Requirements

**Per Monitor:**
- Linux device (Raspberry Pi, laptop, mini PC, etc.)
- WiFi adapter supporting monitor mode
  - Built-in WiFi on most Raspberry Pi models works
  - USB WiFi adapters: check compatibility
- Network connectivity (Ethernet or separate WiFi adapter)

**Recommended Configurations:**

**Option 1: Raspberry Pi (Most Common)**
- Raspberry Pi 3/4/5
- Built-in WiFi for monitoring
- Ethernet for network (preferred)
- Or USB WiFi dongle for network + built-in for monitoring

**Option 2: Dual-WiFi Setup**
- Any Linux device
- USB WiFi adapter for monitoring (monitor mode)
- Built-in WiFi or Ethernet for network
- Prevents network disconnection

**Option 3: Single WiFi (Advanced)**
- Linux device with one WiFi adapter
- Use monitor mode for scanning
- Connect to network via Ethernet
- Or accept network disconnection during monitoring

### Software Requirements

- Python 3.8+ (3.11+ recommended)
- `tshark` (Wireshark command-line)
- `git`
- Root/sudo access (for monitor mode)

### Network Requirements

- All monitors must reach the primary monitor's IP
- Same local network recommended
- Alternative: VPN (Tailscale, WireGuard) works but slower
- Firewall: Allow port 8080 (or your configured port)

### Location Requirements

- **Critical:** Accurate GPS coordinates for each monitor
- Use Google Maps: Right-click location → Copy coordinates
- Format: Decimal degrees (e.g., 37.7749, -122.4194)
- Precision: 6 decimal places (~0.1 meter accuracy)

##Quick Start

### Step 1: Install Primary Monitor

On your main device (e.g., desktop, always-on server):

```bash
# Install dependencies
sudo apt update
sudo apt install tshark python3-venv python3-pip git

# Clone repository
git clone https://github.com/local-gh0st/ManoMonitor.git
cd ManoMonitor

# Setup Python environment
python3 -m venv venv
source venv/bin/activate
pip install -e .

# Configure
cp .env.example .env
nano .env
```

**Essential `.env` configuration:**
```bash
# Listen on all interfaces for secondary connections
MANOMONITOR_HOST=0.0.0.0
MANOMONITOR_PORT=8080

# WiFi interface for monitoring
MANOMONITOR_WIFI_INTERFACE=wlan0  # Or wlan1, wlp3s0, etc.
MANOMONITOR_CAPTURE_ENABLED=true

# Monitor location (REQUIRED for triangulation)
MANOMONITOR_MONITOR_NAME=Living Room
MANOMONITOR_MONITOR_LATITUDE=37.774929      # YOUR latitude
MANOMONITOR_MONITOR_LONGITUDE=-122.419418   # YOUR longitude

# Enable map
MANOMONITOR_MAP_ENABLED=true
```

**Start primary:**
```bash
# Check safety (won't disconnect network)
manomonitor check

# Start server
sudo manomonitor run
```

**Get API key (needed for secondaries):**
```bash
# Method 1: Web UI
# Navigate to http://localhost:8080/monitors
# Copy API key from primary monitor section

# Method 2: Console
# Look for "Monitor API Key:" in startup output

# Method 3: CLI
manomonitor monitor-info
```

Save this API key - you'll need it for secondary monitors!

### Step 2: Install Secondary Monitors

On each secondary device (Raspberry Pi, laptop, etc.):

```bash
# Install dependencies
sudo apt update
sudo apt install tshark python3-venv python3-pip git

# Clone repository
git clone https://github.com/local-gh0st/ManoMonitor.git
cd ManoMonitor

# Setup Python environment
python3 -m venv venv
source venv/bin/activate
pip install -e .

# Run automated setup wizard
./scripts/setup-secondary.sh
```

**The setup wizard will:**

1. **WiFi Interface Detection**
   - Scans for available WiFi adapters
   - Checks which are safe to use (not your only connection)
   - Suggests disconnected interfaces
   - Prompts for manual selection if needed

2. **Monitor Name**
   - Default: hostname
   - Enter custom name (e.g., "Garage Monitor")

3. **Primary Monitor Connection**
   - Enter primary monitor URL (e.g., `http://192.168.1.100:8080`)
   - Tests connection
   - Auto-fetches API key from primary

4. **Location Configuration**
   - Option 1: Auto-detect (GPS, WiFi geolocation, or IP)
   - Option 2: Manual coordinates
   - Option 3: Skip (defaults to 0,0 - not recommended)

5. **Installation**
   - Creates `.env` file
   - Sets WiFi interface to monitor mode
   - Registers with primary
   - Installs systemd services
   - Starts services automatically

**Example run:**
```
======================================
ManoMonitor Secondary Monitor Setup
   (Automatic Configuration)
======================================

🔍 Auto-detecting WiFi interface...
✅ wlan1 - SAFE TO USE (Not connected)
❌ wlan0 - DANGEROUS (Your only connection)

Enter WiFi interface to use: wlan1
✓ Will use interface: wlan1

Monitor name (default: pi-garage): Garage
✓ Monitor name: Garage

📡 Primary Monitor Configuration
Enter primary monitor URL: http://192.168.1.100:8080
🔗 Testing connection to primary...
✓ Connected successfully

📍 Location Detection
1) Auto-detect (GPS/WiFi/IP)
2) Manual coordinates
3) Skip for now
Choose option: 2
Enter latitude: 37.775000
Enter longitude: -122.420000

==========================================
Configuration Summary
==========================================
  Monitor Name:    Garage
  WiFi Interface:  wlan1
  Primary URL:     http://192.168.1.100:8080
  Location:        37.775000, -122.420000
==========================================

Proceed with setup? (y/n): y

⚙️  Step 1: Configuring environment...
✓ Environment configured

📡 Step 2: Setting up WiFi interface...
✓ Interface wlan1 set to monitor mode

🔑 Step 3: Registering with primary...
✓ Retrieved API key
✓ Registered with primary

🔧 Step 4: Installing systemd services...
✓ Systemd services installed

Start services now? (y/n): y
✓ Services started!

✅ Setup Complete!
```

### Step 3: Verify Setup

**On Primary Monitor:**

1. **Web UI Check**
   ```
   Navigate to: http://<primary-ip>:8080/monitors
   ```
   You should see:
   - Primary monitor (your device)
   - All registered secondary monitors with status

2. **API Check**
   ```bash
   curl http://localhost:8080/api/monitors | jq
   ```

3. **Map View**
   ```
   Navigate to: http://<primary-ip>:8080/map
   ```
   All monitors should appear as pins on the map

**On Secondary Monitors:**

1. **Service Status**
   ```bash
   sudo systemctl status manomonitor-secondary
   sudo systemctl status manomonitor-reporter
   # Both should show "active (running)"
   ```

2. **Check Logs**
   ```bash
   # Capture logs
   sudo journalctl -u manomonitor-secondary -n 20 --no-pager

   # Reporter logs
   sudo journalctl -u manomonitor-reporter -n 20 --no-pager
   # Should show: "Successfully connected to primary"
   ```

3. **Database Check**
   ```bash
   sqlite3 ~/ManoMonitor/data/manomonitor.db "SELECT COUNT(*) FROM probe_logs;"
   # Should show increasing count as devices are detected
   ```

## Primary Monitor Setup

### Detailed Configuration

**`.env` settings for primary:**

```bash
# =============================================================================
# Application Settings
# =============================================================================
MANOMONITOR_APP_NAME=ManoMonitor
MANOMONITOR_HOST=0.0.0.0          # CRITICAL: Allow external connections
MANOMONITOR_PORT=8080
MANOMONITOR_DEBUG=false

# =============================================================================
# WiFi Capture
# =============================================================================
MANOMONITOR_WIFI_INTERFACE=wlan1   # Your monitor-mode interface
MANOMONITOR_CAPTURE_ENABLED=true

# =============================================================================
# Network Monitoring (Captures real MACs from connected devices)
# =============================================================================
MANOMONITOR_ARP_MONITORING_ENABLED=true
MANOMONITOR_ARP_SCAN_INTERVAL=30
MANOMONITOR_DHCP_MONITORING_ENABLED=true
MANOMONITOR_DHCP_CHECK_INTERVAL=60

# =============================================================================
# Monitor Location (CRITICAL - Get from Google Maps)
# =============================================================================
MANOMONITOR_MONITOR_NAME=Living Room Monitor
MANOMONITOR_MONITOR_LATITUDE=37.774929
MANOMONITOR_MONITOR_LONGITUDE=-122.419418

# =============================================================================
# Multi-Monitor & Mapping
# =============================================================================
MANOMONITOR_MAP_ENABLED=true
MANOMONITOR_MONITOR_API_KEY=  # Auto-generated on first run

# =============================================================================
# Signal Processing & Triangulation
# =============================================================================
# Reference signal strength at 1 meter (calibrate for your devices)
MANOMONITOR_SIGNAL_TX_POWER=-59

# Path loss exponent (environment-dependent)
# 2.0 = free space (outdoors)
# 3.0 = indoor (typical home)
# 4.0 = obstructed (many walls)
MANOMONITOR_SIGNAL_PATH_LOSS=3.0

# Number of readings to average for position calculation
MANOMONITOR_SIGNAL_AVERAGING_WINDOW=5

# =============================================================================
# Device Detection
# =============================================================================
MANOMONITOR_DEFAULT_SIGNAL_THRESHOLD=-65       # Min signal for "present"
MANOMONITOR_PRESENCE_TIMEOUT_MINUTES=5         # Time before "away"
MANOMONITOR_NOTIFICATION_COOLDOWN_MINUTES=60   # Min time between notifications

# =============================================================================
# Optional: Vendor Lookup API Keys (for enhanced device identification)
# =============================================================================
MANOMONITOR_MACADDRESS_IO_API_KEY=
MANOMONITOR_MACLOOKUP_APP_API_KEY=
MANOMONITOR_VENDOR_CACHE_DAYS=90

# =============================================================================
# Optional: Location Auto-Detection
# =============================================================================
MANOMONITOR_AUTO_DETECT_LOCATION=false
MANOMONITOR_GOOGLE_GEOLOCATION_API_KEY=
MANOMONITOR_GPS_ENABLED=false
MANOMONITOR_GPS_DEVICE=

# =============================================================================
# Optional: Notifications
# =============================================================================
MANOMONITOR_IFTTT_ENABLED=false
MANOMONITOR_IFTTT_WEBHOOK_KEY=
MANOMONITOR_HOMEASSISTANT_ENABLED=false
MANOMONITOR_HOMEASSISTANT_URL=
MANOMONITOR_HOMEASSISTANT_TOKEN=
```

### Starting as Systemd Service

For production use, install as a system service:

```bash
# Create service file
sudo nano /etc/systemd/system/manomonitor.service
```

```ini
[Unit]
Description=ManoMonitor WiFi Device Tracking (Primary)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/home/user/ManoMonitor
ExecStartPre=/bin/bash -c 'ip link set wlan1 down && iw wlan1 set monitor control && ip link set wlan1 up'
ExecStart=/home/user/ManoMonitor/venv/bin/manomonitor run
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

```bash
# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable manomonitor
sudo systemctl start manomonitor

# Check status
sudo systemctl status manomonitor

# View logs
sudo journalctl -u manomonitor -f
```

## Secondary Monitor Setup

### Automated Setup (Recommended)

The `setup-secondary.sh` script handles everything automatically. See [Quick Start](#quick-start) above.

### Manual Setup (Advanced)

If you prefer manual configuration or troubleshooting:

**1. Create `.env` file:**
```bash
cp .env.example .env
nano .env
```

**2. Configure for secondary:**
```bash
# WiFi Interface
MANOMONITOR_WIFI_INTERFACE=wlan1
MANOMONITOR_CAPTURE_ENABLED=true

# Primary Monitor Connection
MANOMONITOR_PRIMARY_URL=http://192.168.1.100:8080
MANOMONITOR_API_KEY=<paste API key from primary>

# This Monitor's Identity
MANOMONITOR_MONITOR_NAME=Garage Monitor
MANOMONITOR_MONITOR_LATITUDE=37.775000
MANOMONITOR_MONITOR_LONGITUDE=-122.420000

# Disable primary-only features
MANOMONITOR_HOST=127.0.0.1  # No need for external connections
MANOMONITOR_MAP_ENABLED=false
MANOMONITOR_ARP_MONITORING_ENABLED=false
MANOMONITOR_DHCP_MONITORING_ENABLED=false
```

**3. Put interface in monitor mode:**
```bash
sudo ip link set wlan1 down
sudo iw wlan1 set monitor control
sudo ip link set wlan1 up

# Verify
sudo iw dev wlan1 info
# Should show "type monitor"
```

**4. Start capture:**
```bash
sudo venv/bin/manomonitor run --no-web &
```

**5. Start reporter:**
```bash
python3 scripts/secondary_reporter.py
```

**6. Register with primary:**
```bash
venv/bin/manomonitor monitor-register \
  http://192.168.1.100:8080 \
  --name "Garage Monitor" \
  --lat 37.775000 \
  --lon -122.420000
```

### Systemd Services (Manual)

The setup script creates these automatically, but for manual installation:

**Capture service:**
```bash
sudo nano /etc/systemd/system/manomonitor-secondary.service
```

```ini
[Unit]
Description=ManoMonitor WiFi Device Tracking (Secondary)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/home/user/ManoMonitor
ExecStartPre=/bin/bash -c 'ip link set wlan1 down && iw wlan1 set monitor control && ip link set wlan1 up'
ExecStart=/home/user/ManoMonitor/venv/bin/manomonitor run --no-web
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

**Reporter service:**
```bash
sudo nano /etc/systemd/system/manomonitor-reporter.service
```

```ini
[Unit]
Description=ManoMonitor Secondary Reporter (Auto-Discovery)
After=network.target manomonitor-secondary.service

[Service]
Type=simple
User=root
WorkingDirectory=/home/user/ManoMonitor
ExecStart=/home/user/ManoMonitor/venv/bin/python3 /home/user/ManoMonitor/scripts/secondary_reporter.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

```bash
# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable manomonitor-secondary manomonitor-reporter
sudo systemctl start manomonitor-secondary manomonitor-reporter

# Check status
sudo systemctl status manomonitor-secondary
sudo systemctl status manomonitor-reporter
```

## Verification

### Check Primary Monitor

**1. Web UI - Monitors Page**
```
http://<primary-ip>:8080/monitors
```

Should show:
- Primary monitor with green "Online" badge
- All secondary monitors with status
- Last seen timestamps
- GPS coordinates

**2. Web UI - Map Page**
```
http://<primary-ip>:8080/map
```

Should show:
- Monitor pins at correct GPS locations
- Device pins (as they're detected)
- Accuracy circles around devices

**3. API Endpoints**
```bash
# List all monitors
curl http://localhost:8080/api/monitors | jq

# Get map data (monitors + devices)
curl http://localhost:8080/api/map/data | jq

# Check system status
curl http://localhost:8080/api/status | jq
```

### Check Secondary Monitors

**1. Service Status**
```bash
# Both should be active (running)
sudo systemctl status manomonitor-secondary
sudo systemctl status manomonitor-reporter
```

**2. Logs**
```bash
# Capture logs - should show device detections
sudo journalctl -u manomonitor-secondary -n 50 --no-pager

# Reporter logs - should show "Successfully connected"
sudo journalctl -u manomonitor-reporter -n 50 --no-pager
```

**3. Database**
```bash
# Check if capturing data
sqlite3 ~/ManoMonitor/data/manomonitor.db "SELECT COUNT(*) FROM probe_logs;"

# Check recent captures
sqlite3 ~/ManoMonitor/data/manomonitor.db "SELECT * FROM probe_logs ORDER BY timestamp DESC LIMIT 5;"
```

**4. Network Connection**
```bash
# Test primary connectivity
curl http://<primary-ip>:8080/api/status

# Test reporter is sending data
# Watch reporter logs for "Recorded X signal readings" messages
sudo journalctl -u manomonitor-reporter -f
```

### Verification Checklist

- [ ] Primary monitor web UI accessible
- [ ] API key retrieved from primary
- [ ] All secondary monitors listed in Monitors page
- [ ] All monitors show "Online" status
- [ ] Monitor locations correct on map
- [ ] Devices being detected on all monitors
- [ ] Signal readings appearing in primary database
- [ ] Device positions calculated and shown on map

## Calibration

### Signal Strength Calibration

For accurate distance estimation, calibrate these values:

**1. TX Power Calibration**

Place a known device (phone) exactly 1 meter from a monitor:

```bash
# On monitor, capture signal for 30 seconds
sudo tshark -i wlan1 -f "type mgt subtype probe-req" -T fields -e wlan.sa -e radiotap.dbm_antsignal

# Average the signal strengths
# Set this as MANOMONITOR_SIGNAL_TX_POWER in .env
```

Typical values:
- Phones: -55 to -60 dBm at 1m
- Laptops: -50 to -55 dBm at 1m
- IoT devices: -60 to -70 dBm at 1m

**2. Path Loss Exponent**

Test at known distances (1m, 2m, 5m, 10m):

```python
# Calculate path loss exponent
import math

def calculate_path_loss(rssi_1m, rssi_distance, distance):
    return (rssi_1m - rssi_distance) / (10 * math.log10(distance))

# Example:
# At 1m: -59 dBm
# At 5m: -72 dBm
path_loss = calculate_path_loss(-59, -72, 5)
print(f"Path Loss Exponent: {path_loss}")  # Should be ~2.6-3.5 indoors
```

Typical values:
- Open space: 2.0
- Typical home: 3.0
- Many walls: 4.0
- Dense environment: 4.5+

**3. Position Accuracy**

Test with device at known location:

1. Place phone at GPS coordinates you know
2. View on map - compare actual vs. calculated position
3. Adjust `SIGNAL_TX_POWER` and `SIGNAL_PATH_LOSS`
4. Repeat until accuracy improves

Tips:
- Higher TX power = smaller distance estimates
- Higher path loss = larger distance estimates
- Use `SIGNAL_AVERAGING_WINDOW=10` for more stable (but slower) updates

### Monitor Placement

**Best Practices:**

1. **Spread Out** - Place monitors at corners/edges of area
2. **Line of Sight** - Minimize walls between monitors
3. **Elevation** - Mount at same height (waist to chest level)
4. **Avoid Interference** - Keep away from microwaves, metal objects
5. **Stable Location** - Don't move monitors after calibration

**Example Layout (3 monitors, 2000 sq ft home):**
```
     North
        ↑

Monitor 1 ←────50ft────→ Monitor 2
(NW Corner)             (NE Corner)
    │                        │
  30ft                     30ft
    │                        │
    └─────────┬──────────────┘
              │
          Monitor 3
        (Center South)
```

## Troubleshooting

### Secondary Not Appearing in Primary UI

**1. Check network connectivity:**
```bash
# From secondary, ping primary
ping -c 4 <primary-ip>

# Test HTTP connection
curl http://<primary-ip>:8080/api/status
```

**2. Verify API key:**
```bash
# On secondary
cat ~/ManoMonitor/.env | grep API_KEY

# On primary
manomonitor monitor-info
# Keys should match
```

**3. Check reporter logs:**
```bash
sudo journalctl -u manomonitor-reporter -n 100 --no-pager | grep -i error
```

Common errors:
- `Connection refused` - Primary not running or firewall blocking
- `Invalid API key` - API key mismatch
- `Not registered` - Monitor not in primary database

**4. Re-register manually:**
```bash
cd ~/ManoMonitor
source venv/bin/activate
venv/bin/manomonitor monitor-register \
  http://<primary-ip>:8080 \
  --name "Secondary Name" \
  --lat <latitude> \
  --lon <longitude>
```

### No Signal Readings Reported

**1. Check capture is working:**
```bash
# On secondary
sudo journalctl -u manomonitor-secondary -n 50 | grep "New device"
# Should show device detections
```

**2. Check database:**
```bash
sqlite3 ~/ManoMonitor/data/manomonitor.db \
  "SELECT COUNT(*) FROM probe_logs WHERE timestamp > datetime('now', '-5 minutes');"
# Should be > 0
```

**3. Check reporter:**
```bash
sudo journalctl -u manomonitor-reporter -f
# Should show "Recorded X signal readings" every 30 seconds
```

**4. Restart services:**
```bash
sudo systemctl restart manomonitor-secondary
sudo systemctl restart manomonitor-reporter
```

### Inaccurate Positions

**1. Verify monitor locations:**
- Web UI → Monitors page
- Check GPS coordinates are correct
- Re-measure if needed

**2. Calibrate signal parameters:**
- See [Signal Strength Calibration](#signal-strength-calibration)
- Test at known distances
- Adjust TX power and path loss

**3. Check environment:**
- Metal objects nearby?
- Thick walls between monitors?
- Electronic interference?

**4. Add more monitors:**
- 2 monitors = bilateration (less accurate)
- 3+ monitors = trilateration (more accurate)
- More monitors = better accuracy

### Firewall Issues

**Allow ManoMonitor through firewall:**

**Ubuntu/Debian (ufw):**
```bash
sudo ufw allow 8080/tcp
sudo ufw reload
```

**CentOS/RHEL (firewalld):**
```bash
sudo firewall-cmd --permanent --add-port=8080/tcp
sudo firewall-cmd --reload
```

**Check if port is blocked:**
```bash
# On primary
sudo netstat -tlnp | grep 8080

# From secondary
telnet <primary-ip> 8080
# Should connect
```

### WiFi Interface Issues

**Interface won't stay in monitor mode:**
```bash
# Kill conflicting processes
sudo airmon-ng check kill

# Force monitor mode
sudo ip link set wlan1 down
sudo iw wlan1 set type monitor
sudo ip link set wlan1 up

# Verify
iw dev wlan1 info | grep type
```

**Driver doesn't support monitor mode:**
```bash
# Check capabilities
iw list | grep "Supported interface modes" -A 10

# If "monitor" not listed, you need a different adapter
```

**Recommended USB WiFi adapters:**
- Alfa AWUS036ACH (AC, dual-band)
- Alfa AWUS036NHA (N, 2.4GHz)
- TP-Link TL-WN722N v1 (N, 2.4GHz)
- Panda PAU09 (N, 2.4GHz)

### Database Issues

**Primary can't read secondary data:**

Secondary stores data locally, reporter sends it to primary. Check:

1. Reporter is sending:
   ```bash
   sudo journalctl -u manomonitor-reporter | grep "Recorded"
   ```

2. Primary is receiving:
   ```bash
   # On primary
   sqlite3 data/manomonitor.db \
     "SELECT COUNT(*) FROM signal_readings WHERE monitor_id > 1;"
   # Should increase over time
   ```

3. API endpoint works:
   ```bash
   curl -X POST http://<primary-ip>:8080/api/monitors/report \
     -H "Content-Type: application/json" \
     -d '{"api_key":"<your-key>","readings":[{"mac_address":"AA:BB:CC:DD:EE:FF","signal_strength":-50}]}'
   ```

## Advanced Configuration

### Custom Reporter Interval

Default is 30 seconds. To change:

```bash
# Edit reporter service
sudo nano /etc/systemd/system/manomonitor-reporter.service

# Modify ExecStart line:
ExecStart=/home/user/ManoMonitor/venv/bin/python3 /home/user/ManoMonitor/scripts/secondary_reporter.py --interval 15

# Reload and restart
sudo systemctl daemon-reload
sudo systemctl restart manomonitor-reporter
```

### Custom Database Path

```bash
# In .env on all monitors
MANOMONITOR_DATABASE_URL=sqlite+aiosqlite:////mnt/storage/manomonitor.db
```

### PostgreSQL Backend

For high-traffic deployments:

```bash
# Install PostgreSQL
sudo apt install postgresql postgresql-contrib

# Create database
sudo -u postgres createdb manomonitor
sudo -u postgres createuser manomonitor -P

# Grant permissions
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE manomonitor TO manomonitor;"

# Configure in .env
MANOMONITOR_DATABASE_URL=postgresql+asyncpg://manomonitor:password@localhost/manomonitor
```

### VPN/Remote Monitors

Use Tailscale or WireGuard for remote monitors:

**Tailscale:**
```bash
# Install on all monitors
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up

# Get Tailscale IP
tailscale ip -4

# Use Tailscale IP as PRIMARY_URL
MANOMONITOR_PRIMARY_URL=http://100.x.x.x:8080
```

Note: Tailscale adds latency (~10-50ms), may affect real-time positioning.

### Signal Debugging

**Enable verbose signal logging:**

```bash
# In .env
MANOMONITOR_DEBUG=true

# Restart and watch logs
sudo systemctl restart manomonitor-secondary
sudo journalctl -u manomonitor-secondary -f | grep signal
```

**Capture raw signals:**
```bash
# On any monitor
sudo tshark -i wlan1 -f "type mgt subtype probe-req" \
  -T fields -e frame.time -e wlan.sa -e radiotap.dbm_antsignal \
  > signals.log

# Analyze with Python/Excel
```

### Automated Backups

**Backup primary database:**
```bash
# Create backup script
cat > /home/user/backup-manomonitor.sh << 'EOF'
#!/bin/bash
BACKUP_DIR="/home/user/backups"
DATE=$(date +%Y%m%d_%H%M%S)
mkdir -p $BACKUP_DIR
sqlite3 /home/user/ManoMonitor/data/manomonitor.db ".backup '$BACKUP_DIR/manomonitor_$DATE.db'"
find $BACKUP_DIR -name "manomonitor_*.db" -mtime +7 -delete
EOF

chmod +x /home/user/backup-manomonitor.sh

# Add to cron (daily at 2 AM)
(crontab -l 2>/dev/null; echo "0 2 * * * /home/user/backup-manomonitor.sh") | crontab -
```

## Performance Tuning

### Optimize for Raspberry Pi

```bash
# In .env
MANOMONITOR_SIGNAL_AVERAGING_WINDOW=3  # Less CPU
MANOMONITOR_ARP_SCAN_INTERVAL=60       # Less frequent
MANOMONITOR_LOG_RETENTION_DAYS=7       # Less storage
```

### Optimize for High-Traffic

```bash
# In .env
MANOMONITOR_SIGNAL_AVERAGING_WINDOW=10  # More stable
# Use PostgreSQL instead of SQLite
# Add Redis for caching (future feature)
```

## Support

**Documentation:**
- Main README: [README.md](README.md)
- MAC Randomization: [docs/MAC_RANDOMIZATION.md](docs/MAC_RANDOMIZATION.md)

**GitHub:**
- Issues: https://github.com/local-gh0st/ManoMonitor/issues
- Discussions: https://github.com/local-gh0st/ManoMonitor/discussions

**Logs to Include When Reporting Issues:**
```bash
# Primary
sudo journalctl -u manomonitor -n 100 --no-pager > primary.log

# Secondary
sudo journalctl -u manomonitor-secondary -n 100 --no-pager > secondary-capture.log
sudo journalctl -u manomonitor-reporter -n 100 --no-pager > secondary-reporter.log

# Configuration
cat ~/ManoMonitor/.env | grep -v "KEY\|TOKEN" > config.txt
```
