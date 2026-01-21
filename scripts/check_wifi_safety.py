#!/usr/bin/env python3
"""
WiFi Interface Safety Checker for ManoMonitor

Checks if a WiFi interface is safe to put into monitor mode without
disconnecting the user from the network.
"""

import subprocess
import sys
from typing import Optional, Tuple


def get_interface_status(interface: str) -> dict:
    """Get detailed status of a WiFi interface."""
    status = {
        "exists": False,
        "is_up": False,
        "is_connected": False,
        "has_ip": False,
        "ssid": None,
        "ip_address": None,
        "is_only_interface": False,
    }

    # Check if interface exists
    try:
        result = subprocess.run(
            ["ip", "link", "show", interface],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            status["exists"] = True
            status["is_up"] = "UP" in result.stdout
    except Exception:
        return status

    # Check if connected to a network
    try:
        result = subprocess.run(
            ["iw", interface, "info"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if 'ssid' in line.lower():
                    ssid = line.split()[-1]
                    if ssid and ssid != "not":
                        status["ssid"] = ssid
                        status["is_connected"] = True
    except Exception:
        pass

    # Check if interface has IP address
    try:
        result = subprocess.run(
            ["ip", "addr", "show", interface],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if 'inet ' in line:
                    ip = line.strip().split()[1].split('/')[0]
                    status["has_ip"] = True
                    status["ip_address"] = ip
    except Exception:
        pass

    # Check if this is the only network interface with connectivity
    try:
        result = subprocess.run(
            ["ip", "route", "show", "default"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            # Count how many interfaces have default routes
            interfaces_with_routes = set()
            for line in result.stdout.split('\n'):
                if 'dev' in line:
                    parts = line.split()
                    if 'dev' in parts:
                        idx = parts.index('dev') + 1
                        if idx < len(parts):
                            interfaces_with_routes.add(parts[idx])

            if interface in interfaces_with_routes and len(interfaces_with_routes) == 1:
                status["is_only_interface"] = True
    except Exception:
        pass

    return status


def check_interface_safety(interface: str) -> Tuple[bool, str, str]:
    """
    Check if it's safe to put an interface into monitor mode.

    Returns:
        (is_safe, risk_level, message)
        risk_level: "safe", "warning", "danger"
    """
    status = get_interface_status(interface)

    if not status["exists"]:
        return False, "danger", f"Interface {interface} does not exist"

    # Danger: Only active network connection
    if status["is_only_interface"] and status["is_connected"]:
        return False, "danger", (
            f"⛔ DANGER: {interface} is your ONLY active network connection!\n"
            f"   Connected to: {status['ssid']}\n"
            f"   IP Address: {status['ip_address']}\n"
            f"   Switching to monitor mode will DISCONNECT you from the network.\n"
            f"   You may lose SSH access or network connectivity."
        )

    # Warning: Connected but not only interface
    if status["is_connected"] and not status["is_only_interface"]:
        return True, "warning", (
            f"⚠️  WARNING: {interface} is currently connected\n"
            f"   Connected to: {status['ssid']}\n"
            f"   IP Address: {status['ip_address']}\n"
            f"   You have other network interfaces available.\n"
            f"   Switching to monitor mode will disconnect this interface."
        )

    # Safe: Not connected or down
    if not status["is_connected"]:
        return True, "safe", f"✓ Safe: {interface} is not connected to any network"

    return True, "safe", f"✓ Safe to use {interface}"


def list_wifi_interfaces() -> list:
    """List all WiFi interfaces on the system."""
    interfaces = []
    try:
        result = subprocess.run(
            ["iw", "dev"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if 'Interface' in line:
                    interface = line.split()[-1]
                    interfaces.append(interface)
    except Exception:
        pass
    return interfaces


def suggest_safe_interface() -> Optional[str]:
    """Suggest a safe interface to use for monitoring."""
    interfaces = list_wifi_interfaces()

    # Check each interface
    safe_interfaces = []
    for iface in interfaces:
        is_safe, risk, msg = check_interface_safety(iface)
        if is_safe and risk == "safe":
            safe_interfaces.append(iface)

    return safe_interfaces[0] if safe_interfaces else None


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Check if a WiFi interface is safe to use for monitor mode"
    )
    parser.add_argument(
        "interface",
        nargs="?",
        help="WiFi interface to check (e.g., wlan0, wlan1). If not provided, lists all interfaces.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all WiFi interfaces and their status",
    )
    parser.add_argument(
        "--suggest",
        action="store_true",
        help="Suggest a safe interface to use",
    )

    args = parser.parse_args()

    if args.list or not args.interface:
        print("Available WiFi Interfaces:")
        print("=" * 60)
        interfaces = list_wifi_interfaces()
        if not interfaces:
            print("No WiFi interfaces found")
            return 1

        for iface in interfaces:
            is_safe, risk, msg = check_interface_safety(iface)
            status = get_interface_status(iface)

            # Print interface name with color coding
            if risk == "danger":
                print(f"\n❌ {iface} - DANGEROUS TO USE")
            elif risk == "warning":
                print(f"\n⚠️  {iface} - USE WITH CAUTION")
            else:
                print(f"\n✅ {iface} - SAFE TO USE")

            # Print details
            if status["is_connected"]:
                print(f"   Status: Connected to '{status['ssid']}'")
                if status["ip_address"]:
                    print(f"   IP: {status['ip_address']}")
            else:
                print(f"   Status: Not connected")

            if status["is_only_interface"]:
                print(f"   ⚠️  This is your ONLY network connection!")

        print("\n" + "=" * 60)

        # Suggest safe interface
        safe = suggest_safe_interface()
        if safe:
            print(f"\n💡 Recommended: Use {safe} for monitor mode")
        else:
            print("\n⚠️  No safe interfaces found!")
            print("   Consider using a USB WiFi adapter for monitoring.")

        return 0

    # Check specific interface
    if args.suggest:
        safe = suggest_safe_interface()
        if safe:
            print(safe)
            return 0
        else:
            print("No safe interface found", file=sys.stderr)
            return 1

    # Check specific interface
    is_safe, risk, msg = check_interface_safety(args.interface)
    print(msg)

    if not is_safe:
        print("\n❌ NOT SAFE to put this interface into monitor mode!")
        print("\nRecommendations:")
        print("  1. Use a second WiFi adapter (USB) for monitoring")
        print("  2. Connect via Ethernet cable instead")
        print("  3. Use a different WiFi interface")

        safe = suggest_safe_interface()
        if safe:
            print(f"\n💡 Try using: {safe}")

        return 1
    elif risk == "warning":
        print("\n⚠️  Proceed with caution!")
        return 2
    else:
        print("\n✅ Safe to proceed")
        return 0


if __name__ == "__main__":
    sys.exit(main())
