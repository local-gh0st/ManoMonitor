# ManoMonitor Scripts

Helper scripts for multi-monitor setup and management.

## Scripts

### `setup-secondary.sh`
Interactive setup wizard for secondary monitors.

**Usage:**
```bash
cd ManoMonitor
./scripts/setup-secondary.sh
```

This script will:
1. Prompt for primary monitor URL and monitor details
2. Configure `.env` with proper settings
3. Set WiFi interface to monitor mode
4. Register with the primary monitor
5. Create and enable systemd services
6. Start the monitor and reporter automatically

### `secondary_reporter.py`
Python daemon that reports signal readings from secondary monitor to primary.

**Usage:**
```bash
# Manual run
python3 scripts/secondary_reporter.py \
    --primary-url http://192.168.1.100:8080 \
    --api-key YOUR_API_KEY

# Or with environment variables
export MANOMONITOR_PRIMARY_URL=http://192.168.1.100:8080
export MANOMONITOR_API_KEY=your_api_key
python3 scripts/secondary_reporter.py

# With options
python3 scripts/secondary_reporter.py \
    --primary-url http://192.168.1.100:8080 \
    --api-key YOUR_API_KEY \
    --interval 30 \
    --batch-size 100 \
    --debug
```

**Options:**
- `--primary-url`: Primary monitor URL (required)
- `--api-key`: API key from primary (required)
- `--interval`: Report interval in seconds (default: 30)
- `--batch-size`: Max readings per report (default: 100)
- `--debug`: Enable debug logging

### `manomonitor-reporter.service`
systemd service template for running the reporter as a daemon.

**Installation:**
```bash
# Edit the service file to set your PRIMARY_URL and API_KEY
sudo nano scripts/manomonitor-reporter.service

# Copy to systemd directory
sudo cp scripts/manomonitor-reporter.service /etc/systemd/system/

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable manomonitor-reporter
sudo systemctl start manomonitor-reporter

# Check status
sudo systemctl status manomonitor-reporter
```

## Quick Start: Multi-Monitor Setup

### Primary Monitor

1. **Install and configure:**
```bash
git clone https://github.com/local-gh0st/ManoMonitor.git
cd ManoMonitor
git checkout claude/review-manomonitor-PocQ4
python3 -m venv venv
source venv/bin/activate
pip install -e .
cp .env.example .env
```

2. **Edit `.env` with your location:**
```bash
MANOMONITOR_MONITOR_NAME=Living Room
MANOMONITOR_MONITOR_LATITUDE=37.7749
MANOMONITOR_MONITOR_LONGITUDE=-122.4194
MANOMONITOR_HOST=0.0.0.0
```

3. **Start primary:**
```bash
sudo ./venv/bin/manomonitor run
```

4. **Get API key:**
```bash
./venv/bin/manomonitor monitor-info
# Note the API key - you'll need it for secondaries
```

### Secondary Monitors

**Option A: Automated Setup (Recommended)**
```bash
# Clone and install (same as primary)
git clone https://github.com/local-gh0st/ManoMonitor.git
cd ManoMonitor
git checkout claude/review-manomonitor-PocQ4
python3 -m venv venv
source venv/bin/activate
pip install -e .

# Run setup wizard
./scripts/setup-secondary.sh
# Follow prompts to configure
```

**Option B: Manual Setup**
```bash
# Configure .env
cp .env.example .env
nano .env  # Set MONITOR_NAME, LATITUDE, LONGITUDE, WIFI_INTERFACE

# Register with primary
./venv/bin/manomonitor monitor-register http://<primary-ip>:8080 \
    --name "Garage" \
    --lat 37.7751 \
    --lon -122.4190

# Start monitor
sudo ./venv/bin/manomonitor run &

# Start reporter
python3 scripts/secondary_reporter.py \
    --primary-url http://<primary-ip>:8080 \
    --api-key <api-key> &
```

## CLI Commands

New multi-monitor commands in `manomonitor` CLI:

### `manomonitor monitor-info`
Show this monitor's information and API key.

```bash
./venv/bin/manomonitor monitor-info
```

### `manomonitor monitor-list`
List all registered monitors with status.

```bash
./venv/bin/manomonitor monitor-list
```

### `manomonitor monitor-register`
Register this monitor with a primary monitor.

```bash
./venv/bin/manomonitor monitor-register http://192.168.1.100:8080 \
    --name "Basement" \
    --lat 37.7748 \
    --lon -122.4195
```

## Troubleshooting

### Secondary not reporting
```bash
# Check reporter status
sudo systemctl status manomonitor-reporter

# View logs
sudo journalctl -u manomonitor-reporter -f

# Test connectivity to primary
curl http://<primary-ip>:8080/api/status

# Test reporter manually
python3 scripts/secondary_reporter.py \
    --primary-url http://<primary-ip>:8080 \
    --api-key <api-key> \
    --debug
```

### Monitor not appearing online
```bash
# On primary, check monitors
./venv/bin/manomonitor monitor-list

# Check last_seen timestamp
curl http://localhost:8080/api/monitors | jq
```

### WiFi interface issues
```bash
# Check interface status
iw <interface> info

# Restart in monitor mode
sudo ip link set <interface> down
sudo iw <interface> set monitor control
sudo ip link set <interface> up

# Verify monitor mode
iw <interface> info | grep type
```

## Architecture

```
Primary Monitor (Living Room)
├── Captures WiFi signals locally
├── Runs web UI on port 8080
├── Stores all data in database
├── Performs triangulation
└── Exposes REST API for secondaries

Secondary Monitors (Garage, Basement, etc.)
├── Capture WiFi signals locally
├── Store readings in local database
├── Run secondary_reporter.py daemon
├── Report readings to primary via REST API
└── No web UI needed (optional)
```

## Advanced: Shared Database

Instead of API-based reporting, you can use a shared PostgreSQL database:

1. **Set up PostgreSQL on primary**
2. **Configure all monitors to use same database URL**
3. **Disable reporter service on secondaries**

See `MULTI_MONITOR_SETUP.md` for detailed instructions.
