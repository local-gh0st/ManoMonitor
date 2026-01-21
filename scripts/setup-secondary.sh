#!/bin/bash
# Quick setup script for secondary monitors

set -e

echo "======================================"
echo "ManoMonitor Secondary Monitor Setup"
echo "======================================"
echo

# Get primary URL
read -p "Enter primary monitor URL (e.g., http://192.168.1.100:8080): " PRIMARY_URL
if [ -z "$PRIMARY_URL" ]; then
    echo "Error: PRIMARY_URL required"
    exit 1
fi

# Get monitor info
read -p "Enter name for this monitor (e.g., 'Garage', 'Basement'): " MONITOR_NAME
if [ -z "$MONITOR_NAME" ]; then
    MONITOR_NAME="Secondary"
fi

read -p "Enter latitude for this monitor: " LATITUDE
read -p "Enter longitude for this monitor: " LONGITUDE

if [ -z "$LATITUDE" ] || [ -z "$LONGITUDE" ]; then
    echo "Warning: No location provided. Using 0.0, 0.0"
    LATITUDE=0.0
    LONGITUDE=0.0
fi

read -p "Enter WiFi interface (default: wlan1): " WIFI_INTERFACE
if [ -z "$WIFI_INTERFACE" ]; then
    WIFI_INTERFACE="wlan1"
fi

echo
echo "Configuration:"
echo "  Primary URL: $PRIMARY_URL"
echo "  Monitor Name: $MONITOR_NAME"
echo "  Location: $LATITUDE, $LONGITUDE"
echo "  WiFi Interface: $WIFI_INTERFACE"
echo
read -p "Continue? (y/n): " CONFIRM
if [ "$CONFIRM" != "y" ]; then
    echo "Aborted"
    exit 0
fi

# Determine script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo
echo "Step 1: Configuring environment..."

# Update .env
cd "$PROJECT_DIR"
if [ ! -f .env ]; then
    cp .env.example .env
fi

# Update key settings in .env
sed -i "s/^MANOMONITOR_MONITOR_NAME=.*/MANOMONITOR_MONITOR_NAME=$MONITOR_NAME/" .env
sed -i "s/^MANOMONITOR_MONITOR_LATITUDE=.*/MANOMONITOR_MONITOR_LATITUDE=$LATITUDE/" .env
sed -i "s/^MANOMONITOR_MONITOR_LONGITUDE=.*/MANOMONITOR_MONITOR_LONGITUDE=$LONGITUDE/" .env
sed -i "s/^MANOMONITOR_WIFI_INTERFACE=.*/MANOMONITOR_WIFI_INTERFACE=$WIFI_INTERFACE/" .env

# Disable unnecessary features on secondary
sed -i "s/^MANOMONITOR_ARP_MONITORING_ENABLED=.*/MANOMONITOR_ARP_MONITORING_ENABLED=false/" .env
sed -i "s/^MANOMONITOR_DHCP_MONITORING_ENABLED=.*/MANOMONITOR_DHCP_MONITORING_ENABLED=false/" .env
sed -i "s/^MANOMONITOR_MAP_ENABLED=.*/MANOMONITOR_MAP_ENABLED=false/" .env

echo "✓ Environment configured"

echo
echo "Step 2: Setting up WiFi interface..."
sudo ip link set "$WIFI_INTERFACE" down
sudo iw "$WIFI_INTERFACE" set monitor control
sudo ip link set "$WIFI_INTERFACE" up
echo "✓ Interface $WIFI_INTERFACE set to monitor mode"

echo
echo "Step 3: Registering with primary monitor..."
source venv/bin/activate
./venv/bin/manomonitor monitor-register "$PRIMARY_URL" \
    --name "$MONITOR_NAME" \
    --lat "$LATITUDE" \
    --lon "$LONGITUDE"

# Extract API key from output
API_KEY=$(curl -s "$PRIMARY_URL/api/monitors" | grep -o '"api_key":"[^"]*"' | head -1 | cut -d'"' -f4)

if [ -z "$API_KEY" ]; then
    echo "Warning: Could not retrieve API key automatically"
    read -p "Enter the API key from the primary monitor: " API_KEY
fi

# Add API key to .env
echo "MANOMONITOR_API_KEY=$API_KEY" >> .env
sed -i "s/^MANOMONITOR_MONITOR_API_KEY=.*/MANOMONITOR_MONITOR_API_KEY=$API_KEY/" .env

echo "✓ Registered and configured"

echo
echo "Step 4: Setting up systemd services..."

# Create ManoMonitor service
sudo tee /etc/systemd/system/manomonitor.service > /dev/null << EOF
[Unit]
Description=ManoMonitor WiFi Device Tracking (Secondary)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$PROJECT_DIR
ExecStartPre=/bin/bash -c 'ip link set $WIFI_INTERFACE down && iw $WIFI_INTERFACE set monitor control && ip link set $WIFI_INTERFACE up'
ExecStart=$PROJECT_DIR/venv/bin/manomonitor run
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Create Reporter service
sudo tee /etc/systemd/system/manomonitor-reporter.service > /dev/null << EOF
[Unit]
Description=ManoMonitor Secondary Reporter
After=network.target manomonitor.service
Requires=manomonitor.service

[Service]
Type=simple
User=root
WorkingDirectory=$PROJECT_DIR
Environment="MANOMONITOR_PRIMARY_URL=$PRIMARY_URL"
Environment="MANOMONITOR_API_KEY=$API_KEY"
ExecStart=$PROJECT_DIR/venv/bin/python3 $PROJECT_DIR/scripts/secondary_reporter.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable manomonitor manomonitor-reporter

echo "✓ Systemd services created and enabled"

echo
echo "======================================"
echo "Setup Complete!"
echo "======================================"
echo
echo "Services configured:"
echo "  • manomonitor.service - Captures WiFi signals"
echo "  • manomonitor-reporter.service - Reports to primary"
echo
echo "To start now:"
echo "  sudo systemctl start manomonitor"
echo "  sudo systemctl start manomonitor-reporter"
echo
echo "To check status:"
echo "  sudo systemctl status manomonitor"
echo "  sudo systemctl status manomonitor-reporter"
echo
echo "To view logs:"
echo "  sudo journalctl -u manomonitor -f"
echo "  sudo journalctl -u manomonitor-reporter -f"
echo
echo "Web UI (optional): http://$(hostname -I | awk '{print $1}'):8080"
echo "Primary UI: $PRIMARY_URL"
echo
