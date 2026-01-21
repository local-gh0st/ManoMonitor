#!/usr/bin/env python3
"""
Secondary Monitor Reporter for ManoMonitor

This script runs on secondary monitors and reports signal readings
to the primary monitor for triangulation.

Usage:
    python3 secondary_reporter.py --primary-url http://192.168.1.100:8080 --api-key YOUR_API_KEY

Or set environment variables:
    export MANOMONITOR_PRIMARY_URL=http://192.168.1.100:8080
    export MANOMONITOR_API_KEY=your_api_key
    python3 secondary_reporter.py
"""

import argparse
import asyncio
import logging
import os
import sys
import time
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
        logger.info(f"Starting secondary reporter")
        logger.info(f"Primary URL: {self.primary_url}")
        logger.info(f"Report interval: {self.report_interval} seconds")

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


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Report signal readings from secondary monitor to primary"
    )
    parser.add_argument(
        "--primary-url",
        default=os.getenv("MANOMONITOR_PRIMARY_URL"),
        help="Primary monitor URL (e.g., http://192.168.1.100:8080)",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("MANOMONITOR_API_KEY"),
        help="API key for authentication with primary",
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

    if not args.primary_url:
        logger.error("--primary-url or MANOMONITOR_PRIMARY_URL is required")
        parser.print_help()
        sys.exit(1)

    if not args.api_key:
        logger.error("--api-key or MANOMONITOR_API_KEY is required")
        parser.print_help()
        sys.exit(1)

    # Create and start reporter
    reporter = SecondaryReporter(
        primary_url=args.primary_url,
        api_key=args.api_key,
        report_interval=args.interval,
        batch_size=args.batch_size,
    )

    try:
        asyncio.run(reporter.start())
    except KeyboardInterrupt:
        logger.info("Stopped by user")


if __name__ == "__main__":
    main()
