#!/usr/bin/env python3
"""
Enhanced Secondary Monitor Reporter with Auto-Discovery

This script automatically discovers the primary monitor on the network
and configures itself with minimal user input.

Usage:
    python3 scripts/secondary_reporter.py  # Auto-discovers everything

Or with manual config:
    python3 scripts/secondary_reporter.py --primary-url http://192.168.1.100:8080
"""

import argparse
import asyncio
import json
import logging
import os
import socket
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from manomonitor.config import settings
from manomonitor.database.models import ProbeLog, Asset

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def discover_primary_monitor(timeout: float = 5.0) -> Optional[str]:
    """
    Auto-discover primary monitor on local network.

    Scans common ports (8080, 8000, 5000) on local subnet for ManoMonitor.
    """
    logger.info("🔍 Auto-discovering primary monitor on network...")

    # Get local IP and subnet
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()

        # Parse subnet (assume /24)
        ip_parts = local_ip.split('.')
        subnet = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}"

        logger.info(f"Local subnet: {subnet}.0/24")

        # Common ManoMonitor ports
        ports = [8080, 8000, 5000]

        # Scan broadcast and common IPs first (faster)
        priority_ips = [
            f"{subnet}.1",    # Router/gateway
            f"{subnet}.100",  # Common static
            f"{subnet}.10",
            f"{subnet}.50",
        ]

        for ip in priority_ips:
            if ip == local_ip:
                continue
            for port in ports:
                url = f"http://{ip}:{port}"
                if check_manomonitor_endpoint(url, timeout=1.0):
                    logger.info(f"✓ Found primary monitor at {url}")
                    return url

        # If not found, scan full subnet (slower)
        logger.info("Scanning full subnet... (this may take a minute)")
        for i in range(2, 255):
            ip = f"{subnet}.{i}"
            if ip == local_ip:
                continue
            for port in ports:
                url = f"http://{ip}:{port}"
                if check_manomonitor_endpoint(url, timeout=0.5):
                    logger.info(f"✓ Found primary monitor at {url}")
                    return url
    except Exception as e:
        logger.debug(f"Discovery error: {e}")

    logger.warning("✗ Could not auto-discover primary monitor")
    return None


def check_manomonitor_endpoint(url: str, timeout: float = 2.0) -> bool:
    """Check if URL is a ManoMonitor instance."""
    try:
        import requests
        response = requests.get(f"{url}/api/status", timeout=timeout)
        if response.status_code == 200:
            data = response.json()
            # Check for ManoMonitor-specific fields
            if "app_name" in data or "version" in data:
                return True
    except Exception:
        pass
    return False


async def get_primary_api_key(primary_url: str) -> Optional[str]:
    """Fetch API key from primary monitor."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{primary_url}/api/monitors")
            response.raise_for_status()
            monitors = response.json()

            # Find local/primary monitor
            primary = next((m for m in monitors if m.get("is_local")), None)
            if primary and primary.get("api_key"):
                return primary["api_key"]
    except Exception as e:
        logger.debug(f"Failed to get API key: {e}")
    return None


def get_local_hostname() -> str:
    """Get local hostname for default monitor name."""
    try:
        return socket.gethostname()
    except Exception:
        return "Secondary"


class SecondaryReporter:
    """Reports signal readings from secondary monitor to primary."""

    def __init__(
        self,
        primary_url: str,
        api_key: str,
        report_interval: int = 30,
        batch_size: int = 100,
    ):
        self.primary_url = primary_url.rstrip("/")
        self.api_key = api_key
        self.report_interval = report_interval
        self.batch_size = batch_size

        # Database setup
        db_url = settings.get_database_url()
        self.engine = create_async_engine(db_url, echo=False)
        self.async_session = sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

        # HTTP client
        self.http_client: Optional[httpx.AsyncClient] = None

        # Tracking
        self.last_report_time: Optional[datetime] = None
        self.total_readings_sent = 0
        self.consecutive_errors = 0

    async def start(self):
        """Start the reporter."""
        logger.info(f"🚀 Starting secondary reporter")
        logger.info(f"📡 Primary URL: {self.primary_url}")
        logger.info(f"⏱️  Report interval: {self.report_interval} seconds")

        self.http_client = httpx.AsyncClient(timeout=30.0)

        # Test connection to primary
        try:
            await self._test_connection()
            logger.info("✓ Successfully connected to primary monitor")
        except Exception as e:
            logger.error(f"✗ Failed to connect to primary: {e}")
            logger.error("Please check PRIMARY_URL and network connectivity")
            return

        # Main reporting loop
        try:
            while True:
                try:
                    await self._report_readings()
                    self.consecutive_errors = 0
                except Exception as e:
                    self.consecutive_errors += 1
                    logger.error(f"Error reporting readings: {e}")

                    if self.consecutive_errors >= 5:
                        logger.error(
                            "Too many consecutive errors. Check primary monitor."
                        )
                        await asyncio.sleep(self.report_interval * 2)
                    else:
                        await asyncio.sleep(self.report_interval)
                else:
                    await asyncio.sleep(self.report_interval)

        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            if self.http_client:
                await self.http_client.aclose()

    async def _test_connection(self):
        """Test connection to primary monitor."""
        response = await self.http_client.get(f"{self.primary_url}/api/status")
        response.raise_for_status()

    async def _report_readings(self):
        """Collect and report recent signal readings to primary."""
        # Get readings since last report (or last 60 seconds)
        cutoff_time = datetime.utcnow() - timedelta(seconds=self.report_interval * 2)
        if self.last_report_time:
            cutoff_time = max(cutoff_time, self.last_report_time)

        # Query database for recent readings
        async with self.async_session() as session:
            # Get distinct MAC addresses with their latest readings
            stmt = select(ProbeLog).where(ProbeLog.timestamp >= cutoff_time)
            result = await session.execute(stmt)
            probe_logs = result.scalars().all()

            if not probe_logs:
                logger.debug("No new readings to report")
                self.last_report_time = datetime.utcnow()
                return

            # Group by MAC and average signal strength
            readings_map: dict[str, list[int]] = {}
            for log in probe_logs:
                if log.signal_strength is None:
                    continue

                # Get MAC from asset
                asset_stmt = select(Asset).where(Asset.id == log.asset_id)
                asset_result = await session.execute(asset_stmt)
                asset = asset_result.scalar_one_or_none()

                if asset:
                    mac = asset.mac_address
                    if mac not in readings_map:
                        readings_map[mac] = []
                    readings_map[mac].append(log.signal_strength)

            # Average signals per MAC
            readings = []
            for mac, signals in readings_map.items():
                avg_signal = sum(signals) // len(signals)
                readings.append({"mac_address": mac, "signal_strength": avg_signal})

            if not readings:
                logger.debug("No valid readings with signal strength")
                self.last_report_time = datetime.utcnow()
                return

            # Batch readings if too many
            if len(readings) > self.batch_size:
                readings = readings[: self.batch_size]
                logger.debug(f"Batching to {self.batch_size} readings")

        # Send to primary
        payload = {"api_key": self.api_key, "readings": readings}

        try:
            response = await self.http_client.post(
                f"{self.primary_url}/api/monitors/report",
                json=payload,
                timeout=30.0,
            )
            response.raise_for_status()
            result = response.json()

            self.total_readings_sent += len(readings)
            self.last_report_time = datetime.utcnow()

            logger.info(
                f"✓ Reported {len(readings)} readings to primary "
                f"(total: {self.total_readings_sent})"
            )

            if result.get("readings_added"):
                logger.debug(f"Primary added {result['readings_added']} readings")

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error {e.response.status_code}: {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Failed to report readings: {e}")
            raise


async def main_async(args):
    """Async main function."""
    # Try to get config from environment first
    primary_url = args.primary_url or os.getenv("MANOMONITOR_PRIMARY_URL")
    api_key = args.api_key or os.getenv("MANOMONITOR_API_KEY")

    # Auto-discovery if not configured
    if not primary_url:
        primary_url = discover_primary_monitor()
        if not primary_url:
            logger.error("❌ Could not discover primary monitor")
            logger.error("Please specify --primary-url or set MANOMONITOR_PRIMARY_URL")
            return 1

    if not api_key:
        logger.info("🔑 Fetching API key from primary...")
        api_key = await get_primary_api_key(primary_url)
        if not api_key:
            logger.error("❌ Could not retrieve API key from primary")
            logger.error("Please specify --api-key or set MANOMONITOR_API_KEY")
            logger.error(f"Or run on primary: manomonitor monitor-info")
            return 1

    logger.info(f"✓ Configuration complete")
    logger.info(f"  Primary: {primary_url}")
    logger.info(f"  API Key: {api_key[:16]}...")

    # Create and start reporter
    reporter = SecondaryReporter(
        primary_url=primary_url,
        api_key=api_key,
        report_interval=args.interval,
        batch_size=args.batch_size,
    )

    try:
        await reporter.start()
        return 0
    except KeyboardInterrupt:
        logger.info("Stopped by user")
        return 0


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Report signal readings from secondary monitor to primary (with auto-discovery)"
    )
    parser.add_argument(
        "--primary-url",
        default=None,
        help="Primary monitor URL (auto-discovers if not specified)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="API key for authentication (auto-retrieves if not specified)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=30,
        help="Report interval in seconds (default: 30)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Maximum readings per report (default: 100)",
    )
    parser.add_argument(
        "--debug", action="store_true", help="Enable debug logging"
    )

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        exit_code = asyncio.run(main_async(args))
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("Stopped by user")
        sys.exit(0)


if __name__ == "__main__":
    main()
