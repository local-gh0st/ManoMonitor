#!/bin/bash
#
# WhosHere Installation Script
# WiFi-based presence detection and proximity alert system
#
# Usage: sudo ./install.sh
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
INSTALL_DIR="/opt/whoshere"
SERVICE_USER="whoshere"
PYTHON_MIN_VERSION="3.11"

print_banner() {
    echo -e "${BLUE}"
    echo "╔═══════════════════════════════════════════╗"
    echo "║         WhosHere Installation             ║"
    echo "║   WiFi Presence Detection System v2.0     ║"
    echo "╚═══════════════════════════════════════════╝"
    echo -e "${NC}"
}

print_step() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

print_error() {
    echo -e "${RED}[✗]${NC} $1"
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        print_error "This script must be run as root (use sudo)"
        exit 1
    fi
}

check_os() {
    if [[ ! -f /etc/os-release ]]; then
        print_error "Cannot detect OS. This script requires Ubuntu/Debian."
        exit 1
    fi

    . /etc/os-release
    if [[ "$ID" != "ubuntu" && "$ID" != "debian" && "$ID_LIKE" != *"debian"* ]]; then
        print_warning "This script is designed for Ubuntu/Debian. Continuing anyway..."
    fi

    print_step "Detected OS: $PRETTY_NAME"
}

check_python() {
    if command -v python3 &> /dev/null; then
        PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        if python3 -c "import sys; exit(0 if sys.version_info >= (3, 11) else 1)" 2>/dev/null; then
            print_step "Python $PYTHON_VERSION found"
            return 0
        fi
    fi

    print_warning "Python 3.11+ not found. Installing..."
    apt-get update
    apt-get install -y python3.11 python3.11-venv python3.11-dev python3-pip
    print_step "Python 3.11 installed"
}

install_dependencies() {
    print_step "Installing system dependencies..."

    apt-get update
    apt-get install -y \
        tshark \
        wireless-tools \
        iw \
        net-tools \
        git \
        curl \
        build-essential \
        libffi-dev \
        libssl-dev

    # Allow non-root users to capture packets (needed for tshark)
    print_step "Configuring packet capture permissions..."
    setcap cap_net_raw,cap_net_admin=eip /usr/bin/dumpcap 2>/dev/null || true

    print_step "System dependencies installed"
}

create_user() {
    if id "$SERVICE_USER" &>/dev/null; then
        print_step "User $SERVICE_USER already exists"
    else
        useradd -r -s /bin/false -d "$INSTALL_DIR" "$SERVICE_USER"
        print_step "Created system user: $SERVICE_USER"
    fi

    # Add user to wireshark group for packet capture
    usermod -aG wireshark "$SERVICE_USER" 2>/dev/null || true
}

install_application() {
    print_step "Installing WhosHere to $INSTALL_DIR..."

    # Create installation directory
    mkdir -p "$INSTALL_DIR"

    # Copy application files
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    cp -r "$SCRIPT_DIR"/* "$INSTALL_DIR/"

    # Create data directory
    mkdir -p "$INSTALL_DIR/data"

    # Create virtual environment
    print_step "Creating Python virtual environment..."
    python3 -m venv "$INSTALL_DIR/venv"

    # Install Python dependencies
    print_step "Installing Python dependencies..."
    "$INSTALL_DIR/venv/bin/pip" install --upgrade pip
    "$INSTALL_DIR/venv/bin/pip" install -e "$INSTALL_DIR"

    # Set permissions
    chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
    chmod -R 755 "$INSTALL_DIR"

    print_step "Application installed"
}

create_config() {
    CONFIG_FILE="$INSTALL_DIR/.env"

    if [[ -f "$CONFIG_FILE" ]]; then
        print_warning "Configuration file already exists. Skipping..."
        return
    fi

    # Detect WiFi interface
    WIFI_INTERFACE=$(iw dev | grep Interface | head -1 | awk '{print $2}')
    if [[ -z "$WIFI_INTERFACE" ]]; then
        WIFI_INTERFACE="wlan0"
        print_warning "Could not detect WiFi interface. Using default: wlan0"
    else
        print_step "Detected WiFi interface: $WIFI_INTERFACE"
    fi

    # Generate secret key
    SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")

    cat > "$CONFIG_FILE" << EOF
# WhosHere Configuration
# Edit this file to customize your installation

# Application settings
WHOSHERE_HOST=0.0.0.0
WHOSHERE_PORT=8080
WHOSHERE_DEBUG=false
WHOSHERE_SECRET_KEY=$SECRET_KEY

# WiFi capture settings
WHOSHERE_WIFI_INTERFACE=$WIFI_INTERFACE
WHOSHERE_CAPTURE_ENABLED=true

# Detection settings
WHOSHERE_DEFAULT_SIGNAL_THRESHOLD=-65
WHOSHERE_PRESENCE_TIMEOUT_MINUTES=5
WHOSHERE_NOTIFICATION_COOLDOWN_MINUTES=60
WHOSHERE_NOTIFY_NEW_DEVICES=false

# IFTTT notifications (optional)
WHOSHERE_IFTTT_ENABLED=false
WHOSHERE_IFTTT_WEBHOOK_KEY=
WHOSHERE_IFTTT_EVENT_NAME=whoshere_detected

# Home Assistant notifications (optional)
WHOSHERE_HOMEASSISTANT_ENABLED=false
WHOSHERE_HOMEASSISTANT_URL=http://homeassistant.local:8123
WHOSHERE_HOMEASSISTANT_TOKEN=
WHOSHERE_HOMEASSISTANT_NOTIFY_SERVICE=notify.notify

# Data retention
WHOSHERE_LOG_RETENTION_DAYS=30
EOF

    chown "$SERVICE_USER:$SERVICE_USER" "$CONFIG_FILE"
    chmod 600 "$CONFIG_FILE"

    print_step "Configuration file created: $CONFIG_FILE"
}

install_systemd_service() {
    print_step "Installing systemd service..."

    cat > /etc/systemd/system/whoshere.service << EOF
[Unit]
Description=WhosHere - WiFi Presence Detection System
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$INSTALL_DIR
Environment="PATH=$INSTALL_DIR/venv/bin"
EnvironmentFile=$INSTALL_DIR/.env
ExecStart=$INSTALL_DIR/venv/bin/python -m whoshere.main
Restart=always
RestartSec=10

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$INSTALL_DIR/data
PrivateTmp=true

# Allow network capture
AmbientCapabilities=CAP_NET_RAW CAP_NET_ADMIN
CapabilityBoundingSet=CAP_NET_RAW CAP_NET_ADMIN

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable whoshere

    print_step "Systemd service installed and enabled"
}

initialize_database() {
    print_step "Initializing database..."

    cd "$INSTALL_DIR"
    sudo -u "$SERVICE_USER" "$INSTALL_DIR/venv/bin/python" -c "
import asyncio
from whoshere.database.connection import init_db
asyncio.run(init_db())
print('Database initialized successfully')
"

    print_step "Database initialized"
}

print_summary() {
    echo ""
    echo -e "${GREEN}════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  WhosHere Installation Complete!${NC}"
    echo -e "${GREEN}════════════════════════════════════════════${NC}"
    echo ""
    echo "Installation directory: $INSTALL_DIR"
    echo "Configuration file:     $INSTALL_DIR/.env"
    echo ""
    echo "Commands:"
    echo "  Start service:    sudo systemctl start whoshere"
    echo "  Stop service:     sudo systemctl stop whoshere"
    echo "  View logs:        sudo journalctl -u whoshere -f"
    echo "  Check status:     sudo systemctl status whoshere"
    echo ""
    echo "Web interface: http://$(hostname -I | awk '{print $1}'):8080"
    echo ""
    echo -e "${YELLOW}Important:${NC}"
    echo "  1. Edit $INSTALL_DIR/.env to configure notifications"
    echo "  2. Your WiFi adapter must support monitor mode"
    echo "  3. Start the service: sudo systemctl start whoshere"
    echo ""
}

# Main installation flow
main() {
    print_banner
    check_root
    check_os
    check_python
    install_dependencies
    create_user
    install_application
    create_config
    install_systemd_service
    initialize_database
    print_summary
}

# Run main
main "$@"
