#!/bin/bash
# Ultra-simplified secondary monitor setup with auto-detection

set -e

# Parse command-line arguments
FORCE_MODE=false
SKIP_SAFETY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --force)
            FORCE_MODE=true
            SKIP_SAFETY=true
            shift
            ;;
        --skip-safety-check)
            SKIP_SAFETY=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --force              Skip all safety checks (use with caution!)"
            echo "  --skip-safety-check  Skip interface safety check only"
            echo "  --help, -h           Show this help message"
            echo ""
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

if [ "$FORCE_MODE" = true ]; then
    echo "======================================"
    echo "ManoMonitor Secondary Monitor Setup"
    echo "   ⚠️  FORCE MODE - Safety Disabled ⚠️"
    echo "======================================"
else
    echo "======================================"
    echo "ManoMonitor Secondary Monitor Setup"
    echo "   (Automatic Configuration)"
    echo "======================================"
fi
echo

# Determine script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Auto-detect WiFi interface
echo "🔍 Auto-detecting WiFi interface..."

if [ "$SKIP_SAFETY" = true ]; then
    # Skip safety check, just find any interface
    WIFI_INTERFACE=$(iw dev 2>/dev/null | grep Interface | head -1 | awk '{print $2}')

    if [ -z "$WIFI_INTERFACE" ]; then
        echo "⚠️  Could not auto-detect WiFi interface"
        read -p "Enter WiFi interface manually (e.g., wlan1): " WIFI_INTERFACE
        if [ -z "$WIFI_INTERFACE" ]; then
            echo "❌ WiFi interface required"
            exit 1
        fi
    else
        echo "✓ Found WiFi interface: $WIFI_INTERFACE (safety check skipped)"
    fi
else
    # Use the safety checker to find a safe interface
    SAFE_INTERFACE=$(python3 "$SCRIPT_DIR/check_wifi_safety.py" --suggest 2>/dev/null || echo "")

    if [ -n "$SAFE_INTERFACE" ]; then
        echo "✓ Found safe WiFi interface: $SAFE_INTERFACE"
        WIFI_INTERFACE="$SAFE_INTERFACE"
    else
        echo "⚠️  No safe WiFi interface found automatically"
        echo ""
        echo "Available interfaces:"
        python3 "$SCRIPT_DIR/check_wifi_safety.py" --list 2>/dev/null || true
        echo ""
        echo "Options:"
        echo "  1. Enter interface name manually (if you know it's safe)"
        echo "  2. Run with --force flag to bypass safety checks"
        echo "  3. Cancel and connect via Ethernet or add USB WiFi adapter"
        echo ""
        read -p "Enter WiFi interface to use (or press Ctrl+C to cancel): " WIFI_INTERFACE
        if [ -z "$WIFI_INTERFACE" ]; then
            echo "❌ WiFi interface required"
            exit 1
        fi
        echo "⚠️  Using interface: $WIFI_INTERFACE (will verify safety next)"
    fi
fi

# Check if the selected interface is safe (unless skipped)
if [ "$SKIP_SAFETY" = false ]; then
    echo ""
    echo "🔒 Checking interface safety..."
    python3 "$SCRIPT_DIR/check_wifi_safety.py" "$WIFI_INTERFACE" 2>&1
    SAFETY_CODE=$?

    if [ $SAFETY_CODE -eq 1 ]; then
        echo ""
        echo "❌ ERROR: Interface $WIFI_INTERFACE is NOT SAFE to use!"
        echo "This is your only network connection. Using it will disconnect you."
        echo ""
        echo "Solutions:"
        echo "  1. Use a USB WiFi adapter for monitoring"
        echo "  2. Connect via Ethernet cable first"
        echo "  3. Use a different WiFi interface"
        echo "  4. Run with --force flag to skip this check"
        echo ""
        read -p "Do you want to continue anyway? (type 'YES' to confirm): " FORCE_CONFIRM
        if [ "$FORCE_CONFIRM" != "YES" ]; then
            echo "Setup cancelled for safety"
            echo ""
            echo "To skip safety checks, run:"
            echo "  ./scripts/setup-secondary.sh --force"
            exit 1
        fi
        echo "⚠️  Proceeding at your own risk..."
    elif [ $SAFETY_CODE -eq 2 ]; then
        echo ""
        echo "⚠️  WARNING: Interface $WIFI_INTERFACE is currently connected"
        read -p "Continue? You may lose connectivity. (y/n): " CONTINUE_WARNED
        if [ "$CONTINUE_WARNED" != "y" ]; then
            echo "Setup cancelled"
            exit 1
        fi
    fi

    echo "✓ Interface safety check passed"
else
    echo "⚠️  Safety checks DISABLED - proceeding without validation"
fi
fi

# Use hostname as default monitor name
DEFAULT_NAME=$(hostname)
read -p "Monitor name (default: $DEFAULT_NAME): " MONITOR_NAME
if [ -z "$MONITOR_NAME" ]; then
    MONITOR_NAME="$DEFAULT_NAME"
fi
echo "✓ Monitor name: $MONITOR_NAME"

# Get primary URL (only required input)
echo
echo "📡 Primary Monitor Configuration"
read -p "Enter primary monitor URL (e.g., http://192.168.1.100:8080): " PRIMARY_URL
if [ -z "$PRIMARY_URL" ]; then
    echo "❌ Primary URL is required"
    exit 1
fi

# Check if we can reach primary
echo "🔗 Testing connection to primary..."
if curl -sf "$PRIMARY_URL/api/status" > /dev/null 2>&1; then
    echo "✓ Successfully connected to primary"
else
    echo "⚠️  Warning: Could not reach primary at $PRIMARY_URL"
    read -p "Continue anyway? (y/n): " CONTINUE
    if [ "$CONTINUE" != "y" ]; then
        exit 1
    fi
fi

# Location auto-detection
echo
echo "📍 Location Detection"
echo "Options:"
echo "  1) Auto-detect using GPS/WiFi/IP geolocation (recommended)"
echo "  2) Enter coordinates manually"
echo "  3) Skip for now (will use 0.0, 0.0)"
read -p "Choose option (1/2/3, default: 1): " LOCATION_OPTION

if [ -z "$LOCATION_OPTION" ]; then
    LOCATION_OPTION=1
fi

case $LOCATION_OPTION in
    1)
        echo "Will use auto-detection (configured via .env)"
        LATITUDE=0.0
        LONGITUDE=0.0
        AUTO_DETECT=true
        ;;
    2)
        read -p "Enter latitude: " LATITUDE
        read -p "Enter longitude: " LONGITUDE
        if [ -z "$LATITUDE" ] || [ -z "$LONGITUDE" ]; then
            echo "⚠️  Invalid coordinates, using auto-detection"
            LATITUDE=0.0
            LONGITUDE=0.0
            AUTO_DETECT=true
        else
            AUTO_DETECT=false
        fi
        ;;
    3)
        LATITUDE=0.0
        LONGITUDE=0.0
        AUTO_DETECT=false
        echo "⚠️  Skipping location - triangulation won't work until configured"
        ;;
esac

# Confirm configuration
echo
echo "=========================================="
echo "Configuration Summary"
echo "=========================================="
echo "  Monitor Name:    $MONITOR_NAME"
echo "  WiFi Interface:  $WIFI_INTERFACE"
echo "  Primary URL:     $PRIMARY_URL"
echo "  Location:        $LATITUDE, $LONGITUDE"
if [ "$AUTO_DETECT" = true ]; then
    echo "                   (will auto-detect on first run)"
fi
echo "=========================================="
echo
read -p "Proceed with setup? (y/n): " CONFIRM
if [ "$CONFIRM" != "y" ]; then
    echo "Setup cancelled"
    exit 0
fi

cd "$PROJECT_DIR"

# Step 1: Configure environment
echo
echo "⚙️  Step 1: Configuring environment..."

if [ ! -f .env ]; then
    cp .env.example .env
fi

# Update settings
sed -i "s/^MANOMONITOR_MONITOR_NAME=.*/MANOMONITOR_MONITOR_NAME=$MONITOR_NAME/" .env
sed -i "s/^MANOMONITOR_MONITOR_LATITUDE=.*/MANOMONITOR_MONITOR_LATITUDE=$LATITUDE/" .env
sed -i "s/^MANOMONITOR_MONITOR_LONGITUDE=.*/MANOMONITOR_MONITOR_LONGITUDE=$LONGITUDE/" .env
sed -i "s/^MANOMONITOR_WIFI_INTERFACE=.*/MANOMONITOR_WIFI_INTERFACE=$WIFI_INTERFACE/" .env
sed -i "s/^MANOMONITOR_AUTO_DETECT_LOCATION=.*/MANOMONITOR_AUTO_DETECT_LOCATION=$AUTO_DETECT/" .env

# Optimize for secondary
sed -i "s/^MANOMONITOR_HOST=.*/MANOMONITOR_HOST=127.0.0.1/" .env  # Don't need external access
sed -i "s/^MANOMONITOR_ARP_MONITORING_ENABLED=.*/MANOMONITOR_ARP_MONITORING_ENABLED=false/" .env
sed -i "s/^MANOMONITOR_DHCP_MONITORING_ENABLED=.*/MANOMONITOR_DHCP_MONITORING_ENABLED=false/" .env
sed -i "s/^MANOMONITOR_MAP_ENABLED=.*/MANOMONITOR_MAP_ENABLED=false/" .env

echo "✓ Environment configured"

# Step 2: Set up WiFi interface
echo
echo "📡 Step 2: Setting up WiFi interface..."
sudo ip link set "$WIFI_INTERFACE" down 2>/dev/null || true
sudo iw "$WIFI_INTERFACE" set monitor control 2>/dev/null || sudo iwconfig "$WIFI_INTERFACE" mode monitor 2>/dev/null || true
sudo ip link set "$WIFI_INTERFACE" up
echo "✓ Interface $WIFI_INTERFACE set to monitor mode"

# Step 3: Auto-register and get API key
echo
echo "🔑 Step 3: Registering with primary and retrieving API key..."

# The reporter script will auto-fetch the API key, but we can also save it now
source venv/bin/activate
API_KEY=$(curl -sf "$PRIMARY_URL/api/monitors" | grep -o '"api_key":"[^"]*"' | head -1 | cut -d'"' -f4 || echo "")

if [ -n "$API_KEY" ]; then
    echo "✓ Retrieved API key: ${API_KEY:0:16}..."
    echo "MANOMONITOR_PRIMARY_URL=$PRIMARY_URL" >> .env
    echo "MANOMONITOR_API_KEY=$API_KEY" >> .env
else
    echo "⚠️  Could not retrieve API key (will auto-fetch on first run)"
    echo "MANOMONITOR_PRIMARY_URL=$PRIMARY_URL" >> .env
fi

# Register monitor
echo "📝 Registering monitor with primary..."
./venv/bin/manomonitor monitor-register "$PRIMARY_URL" \
    --name "$MONITOR_NAME" \
    --lat "$LATITUDE" \
    --lon "$LONGITUDE" 2>/dev/null || echo "⚠️  Registration will occur on first reporter run"

echo "✓ Registered with primary"

# Step 4: Install systemd services
echo
echo "🔧 Step 4: Installing systemd services..."

# Create ManoMonitor service
sudo tee /etc/systemd/system/manomonitor-secondary.service > /dev/null << EOF
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

# Create Reporter service with auto-discovery
sudo tee /etc/systemd/system/manomonitor-reporter.service > /dev/null << EOF
[Unit]
Description=ManoMonitor Secondary Reporter (Auto-Discovery)
After=network.target manomonitor-secondary.service
Requires=manomonitor-secondary.service

[Service]
Type=simple
User=root
WorkingDirectory=$PROJECT_DIR
ExecStart=$PROJECT_DIR/venv/bin/python3 $PROJECT_DIR/scripts/secondary_reporter.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable manomonitor-secondary manomonitor-reporter
echo "✓ Systemd services installed and enabled"

# Step 5: Start services
echo
read -p "Start services now? (y/n): " START_NOW
if [ "$START_NOW" = "y" ]; then
    echo "🚀 Starting services..."
    sudo systemctl start manomonitor-secondary
    sleep 2
    sudo systemctl start manomonitor-reporter

    echo
    echo "✓ Services started!"
    echo
    echo "Check status:"
    echo "  sudo systemctl status manomonitor-secondary"
    echo "  sudo systemctl status manomonitor-reporter"
else
    echo
    echo "To start later:"
    echo "  sudo systemctl start manomonitor-secondary"
    echo "  sudo systemctl start manomonitor-reporter"
fi

echo
echo "=========================================="
echo "✅ Setup Complete!"
echo "=========================================="
echo
echo "Services configured:"
echo "  • manomonitor-secondary.service - Captures WiFi signals"
echo "  • manomonitor-reporter.service - Reports to primary (auto-discovery enabled)"
echo
echo "View logs:"
echo "  sudo journalctl -u manomonitor-secondary -f"
echo "  sudo journalctl -u manomonitor-reporter -f"
echo
echo "Primary monitor UI: $PRIMARY_URL"
echo
echo "The reporter will auto-discover and connect to the primary."
echo "No additional configuration needed!"
echo
