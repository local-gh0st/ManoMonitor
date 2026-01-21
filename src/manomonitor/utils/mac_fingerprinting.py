"""
MAC Address Randomization Detection and Device Fingerprinting.

This module provides functionality to:
1. Detect randomized MAC addresses
2. Fingerprint devices based on signal patterns and behavior
3. Group randomized MACs that likely belong to the same device

Note: We cannot reverse MAC randomization to get the true hardware address.
This is by design for privacy. Instead, we use behavioral fingerprinting to
group related MACs with probability scoring.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from manomonitor.database.models import Asset, DeviceGroup, ProbeLog

logger = logging.getLogger(__name__)


@dataclass
class DeviceFingerprint:
    """Fingerprint characteristics for device identification."""

    # Signal strength characteristics
    avg_signal_strength: Optional[float] = None
    signal_variance: Optional[float] = None

    # Timing patterns
    avg_probe_interval: Optional[float] = None  # seconds between probes
    probe_time_variance: Optional[float] = None

    # Vendor/capabilities indicators
    vendor_prefix: Optional[str] = None  # First 3 bytes of MAC (may be consistent)
    device_capabilities: Optional[str] = None  # WiFi capabilities if available

    # SSIDs probed for (can indicate same device)
    common_ssids: list[str] = None

    def __post_init__(self):
        if self.common_ssids is None:
            self.common_ssids = []

    def to_json(self) -> str:
        """Serialize fingerprint to JSON."""
        return json.dumps({
            "avg_signal": self.avg_signal_strength,
            "signal_var": self.signal_variance,
            "avg_interval": self.avg_probe_interval,
            "interval_var": self.probe_time_variance,
            "vendor_prefix": self.vendor_prefix,
            "capabilities": self.device_capabilities,
            "ssids": self.common_ssids,
        })

    @classmethod
    def from_json(cls, data: str) -> "DeviceFingerprint":
        """Deserialize fingerprint from JSON."""
        parsed = json.loads(data)
        return cls(
            avg_signal_strength=parsed.get("avg_signal"),
            signal_variance=parsed.get("signal_var"),
            avg_probe_interval=parsed.get("avg_interval"),
            probe_time_variance=parsed.get("interval_var"),
            vendor_prefix=parsed.get("vendor_prefix"),
            device_capabilities=parsed.get("capabilities"),
            common_ssids=parsed.get("ssids", []),
        )


def is_randomized_mac(mac_address: str) -> bool:
    """
    Detect if a MAC address is locally-administered (randomized).

    Randomized MACs have the "locally administered" bit set:
    - Bit 1 of the first octet is 1
    - First byte will be: X2, X6, XA, XE (where X is any hex digit)

    Examples:
    - 02:XX:XX:XX:XX:XX - randomized
    - 06:XX:XX:XX:XX:XX - randomized
    - 0A:XX:XX:XX:XX:XX - randomized
    - 00:XX:XX:XX:XX:XX - NOT randomized (globally unique)
    - A4:XX:XX:XX:XX:XX - NOT randomized (globally unique)

    Args:
        mac_address: MAC address in format "AA:BB:CC:DD:EE:FF"

    Returns:
        True if MAC is locally-administered (randomized), False otherwise
    """
    try:
        # Get first byte
        first_byte = int(mac_address.split(":")[0], 16)

        # Check if bit 1 is set (locally administered)
        # Bit 0 = multicast/unicast
        # Bit 1 = locally administered (1) vs globally unique (0)
        is_local = bool(first_byte & 0b00000010)

        return is_local
    except (ValueError, IndexError):
        logger.warning(f"Invalid MAC address format: {mac_address}")
        return False


async def calculate_device_fingerprint(
    db: AsyncSession,
    asset_id: int,
    lookback_hours: int = 24
) -> DeviceFingerprint:
    """
    Calculate device fingerprint based on recent probe activity.

    Args:
        db: Database session
        asset_id: Asset ID to fingerprint
        lookback_hours: Hours of history to analyze

    Returns:
        DeviceFingerprint with behavioral characteristics
    """
    cutoff = datetime.utcnow() - timedelta(hours=lookback_hours)

    # Get recent probe logs
    stmt = (
        select(ProbeLog)
        .where(ProbeLog.asset_id == asset_id)
        .where(ProbeLog.timestamp >= cutoff)
        .order_by(ProbeLog.timestamp)
    )
    result = await db.execute(stmt)
    logs = result.scalars().all()

    if not logs:
        return DeviceFingerprint()

    # Calculate signal strength stats
    signals = [log.signal_strength for log in logs if log.signal_strength is not None]
    avg_signal = sum(signals) / len(signals) if signals else None
    signal_var = None
    if signals and len(signals) > 1:
        variance = sum((s - avg_signal) ** 2 for s in signals) / len(signals)
        signal_var = variance ** 0.5  # Standard deviation

    # Calculate timing patterns
    timestamps = [log.timestamp for log in logs]
    intervals = []
    for i in range(1, len(timestamps)):
        interval = (timestamps[i] - timestamps[i-1]).total_seconds()
        # Filter out very long gaps (device was away)
        if interval < 3600:  # Less than 1 hour
            intervals.append(interval)

    avg_interval = sum(intervals) / len(intervals) if intervals else None
    interval_var = None
    if intervals and len(intervals) > 1:
        variance = sum((i - avg_interval) ** 2 for i in intervals) / len(intervals)
        interval_var = variance ** 0.5

    # Collect SSIDs
    ssids = list(set(log.ssid for log in logs if log.ssid))

    # Get MAC prefix (vendor might be consistent even with randomization)
    asset = await db.get(Asset, asset_id)
    vendor_prefix = ":".join(asset.mac_address.split(":")[:3]) if asset else None

    return DeviceFingerprint(
        avg_signal_strength=avg_signal,
        signal_variance=signal_var,
        avg_probe_interval=avg_interval,
        probe_time_variance=interval_var,
        vendor_prefix=vendor_prefix,
        common_ssids=ssids,
    )


def calculate_similarity_score(fp1: DeviceFingerprint, fp2: DeviceFingerprint) -> float:
    """
    Calculate similarity between two device fingerprints.

    Returns a score from 0.0 (completely different) to 1.0 (very similar).

    Factors considered:
    - Signal strength similarity (devices in same location)
    - Probe timing similarity (same scanning behavior)
    - SSID overlap (probing for same networks)
    - Vendor prefix match (some randomization keeps OUI)
    """
    score = 0.0
    factors = 0

    # Signal strength similarity (weighted heavily - same location = same device)
    if fp1.avg_signal_strength is not None and fp2.avg_signal_strength is not None:
        signal_diff = abs(fp1.avg_signal_strength - fp2.avg_signal_strength)
        # Devices in same location should have signal within 10 dBm
        if signal_diff <= 10:
            signal_score = 1.0 - (signal_diff / 10.0)
            score += signal_score * 0.4  # 40% weight
            factors += 0.4
        else:
            factors += 0.4  # Count it but add 0 to score

    # Probe interval similarity
    if fp1.avg_probe_interval is not None and fp2.avg_probe_interval is not None:
        # Similar probe intervals suggest same OS/device
        if fp1.avg_probe_interval > 0 and fp2.avg_probe_interval > 0:
            ratio = min(fp1.avg_probe_interval, fp2.avg_probe_interval) / \
                    max(fp1.avg_probe_interval, fp2.avg_probe_interval)
            score += ratio * 0.2  # 20% weight
            factors += 0.2

    # SSID overlap (same networks probed = likely same device)
    if fp1.common_ssids and fp2.common_ssids:
        ssid_set1 = set(fp1.common_ssids)
        ssid_set2 = set(fp2.common_ssids)
        intersection = ssid_set1 & ssid_set2
        union = ssid_set1 | ssid_set2

        if union:
            jaccard = len(intersection) / len(union)
            score += jaccard * 0.3  # 30% weight
            factors += 0.3

    # Vendor prefix match (some devices keep OUI even when randomizing)
    if fp1.vendor_prefix and fp2.vendor_prefix:
        if fp1.vendor_prefix == fp2.vendor_prefix:
            score += 0.1  # 10% weight
        factors += 0.1

    # Normalize score by factors actually compared
    if factors > 0:
        return score / factors
    return 0.0


async def find_matching_device_group(
    db: AsyncSession,
    asset_id: int,
    min_confidence: float = 0.6
) -> Optional[DeviceGroup]:
    """
    Find existing device group that matches this asset's fingerprint.

    Args:
        db: Database session
        asset_id: Asset to find match for
        min_confidence: Minimum similarity score to consider a match

    Returns:
        Matching DeviceGroup if found, None otherwise
    """
    # Calculate fingerprint for this asset
    fp_candidate = await calculate_device_fingerprint(db, asset_id)

    # Get all device groups
    stmt = select(DeviceGroup)
    result = await db.execute(stmt)
    groups = result.scalars().all()

    best_match = None
    best_score = 0.0

    for group in groups:
        if not group.fingerprint_data:
            continue

        try:
            fp_group = DeviceFingerprint.from_json(group.fingerprint_data)
            similarity = calculate_similarity_score(fp_candidate, fp_group)

            if similarity >= min_confidence and similarity > best_score:
                best_score = similarity
                best_match = group
        except Exception as e:
            logger.warning(f"Error comparing fingerprints for group {group.id}: {e}")

    if best_match:
        logger.info(
            f"Found matching device group {best_match.id} for asset {asset_id} "
            f"(confidence: {best_score:.2%})"
        )
        # Update confidence score
        best_match.confidence_score = best_score

    return best_match


async def group_randomized_macs(
    db: AsyncSession,
    asset: Asset,
    auto_create_group: bool = True
) -> Optional[DeviceGroup]:
    """
    Analyze and group a MAC address with others if it's randomized.

    Args:
        db: Database session
        asset: Asset to analyze
        auto_create_group: Create new group if no match found

    Returns:
        DeviceGroup the asset was assigned to, or None
    """
    # Check if MAC is randomized
    if not is_randomized_mac(asset.mac_address):
        asset.is_randomized_mac = False
        return None

    asset.is_randomized_mac = True

    # Try to find matching group
    matching_group = await find_matching_device_group(db, asset.id)

    if matching_group:
        # Add to existing group
        asset.device_group_id = matching_group.id
        matching_group.last_seen = datetime.utcnow()
        matching_group.times_seen += 1

        # Update primary MAC if this one is more recent
        if not matching_group.primary_mac or asset.last_seen > matching_group.last_seen:
            matching_group.primary_mac = asset.mac_address

        logger.info(f"Added {asset.mac_address} to device group {matching_group.id}")
        return matching_group

    elif auto_create_group:
        # Create new group for this device
        fingerprint = await calculate_device_fingerprint(db, asset.id)

        new_group = DeviceGroup(
            primary_mac=asset.mac_address,
            fingerprint_data=fingerprint.to_json(),
            confidence_score=1.0,  # 100% confident with first MAC
            first_seen=asset.first_seen,
            last_seen=asset.last_seen,
            times_seen=asset.times_seen,
        )
        db.add(new_group)
        await db.flush()

        asset.device_group_id = new_group.id
        logger.info(f"Created new device group {new_group.id} for {asset.mac_address}")
        return new_group

    return None
