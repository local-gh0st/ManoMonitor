"""Positioning utilities for multi-monitor bilateration.

This module calculates device positions based on signal strength readings
from multiple monitoring stations.
"""

import math
from dataclasses import dataclass
from typing import Optional


@dataclass
class GeoPoint:
    """A geographic point with latitude and longitude."""
    latitude: float
    longitude: float

    def distance_to(self, other: "GeoPoint") -> float:
        """Calculate distance to another point in meters using Haversine formula."""
        R = 6371000  # Earth's radius in meters

        lat1 = math.radians(self.latitude)
        lat2 = math.radians(other.latitude)
        delta_lat = math.radians(other.latitude - self.latitude)
        delta_lon = math.radians(other.longitude - self.longitude)

        a = (math.sin(delta_lat / 2) ** 2 +
             math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return R * c

    def point_at_distance_and_bearing(self, distance: float, bearing: float) -> "GeoPoint":
        """
        Calculate a point at a given distance and bearing from this point.

        Args:
            distance: Distance in meters
            bearing: Bearing in radians (0 = North, π/2 = East)

        Returns:
            New GeoPoint at the specified distance and bearing
        """
        R = 6371000  # Earth's radius in meters

        lat1 = math.radians(self.latitude)
        lon1 = math.radians(self.longitude)

        lat2 = math.asin(
            math.sin(lat1) * math.cos(distance / R) +
            math.cos(lat1) * math.sin(distance / R) * math.cos(bearing)
        )
        lon2 = lon1 + math.atan2(
            math.sin(bearing) * math.sin(distance / R) * math.cos(lat1),
            math.cos(distance / R) - math.sin(lat1) * math.sin(lat2)
        )

        return GeoPoint(
            latitude=math.degrees(lat2),
            longitude=math.degrees(lon2)
        )

    def bearing_to(self, other: "GeoPoint") -> float:
        """Calculate bearing to another point in radians."""
        lat1 = math.radians(self.latitude)
        lat2 = math.radians(other.latitude)
        delta_lon = math.radians(other.longitude - self.longitude)

        x = math.sin(delta_lon) * math.cos(lat2)
        y = (math.cos(lat1) * math.sin(lat2) -
             math.sin(lat1) * math.cos(lat2) * math.cos(delta_lon))

        return math.atan2(x, y)


@dataclass
class MonitorReading:
    """A signal reading from a monitor."""
    monitor_location: GeoPoint
    signal_strength: int  # dBm
    estimated_distance: Optional[float] = None  # meters


@dataclass
class PositionEstimate:
    """An estimated device position."""
    location: GeoPoint
    accuracy: float  # estimated accuracy in meters
    confidence: float  # 0-1 confidence score


def signal_to_distance(
    signal_dbm: int,
    tx_power: int = -59,  # Typical transmit power at 1m
    path_loss_exponent: float = 3.0,  # Indoor environment (2.7-4.3 typical)
) -> float:
    """
    Estimate distance from signal strength using log-distance path loss model.

    RSSI = TxPower - 10 * n * log10(distance)
    distance = 10 ^ ((TxPower - RSSI) / (10 * n))

    Args:
        signal_dbm: Received signal strength in dBm
        tx_power: Reference signal strength at 1 meter (calibrate for your devices)
        path_loss_exponent: Environment factor (2=free space, 2.7-3.5=indoor, 4-6=obstructed)

    Returns:
        Estimated distance in meters
    """
    if signal_dbm >= tx_power:
        return 0.5  # Very close, minimum distance

    exponent = (tx_power - signal_dbm) / (10 * path_loss_exponent)
    distance = math.pow(10, exponent)

    # Clamp to reasonable indoor range
    return min(max(distance, 0.5), 100.0)


def bilaterate(
    reading1: MonitorReading,
    reading2: MonitorReading,
    prefer_inside: Optional[GeoPoint] = None,
) -> Optional[PositionEstimate]:
    """
    Calculate device position from two monitor readings using bilateration.

    With two monitors, we get two circles (one around each monitor).
    These circles intersect at 0, 1, or 2 points.

    Args:
        reading1: Signal reading from first monitor
        reading2: Signal reading from second monitor
        prefer_inside: If provided, prefer the intersection point closer to this location

    Returns:
        PositionEstimate or None if circles don't intersect
    """
    # Calculate distances from signal strength if not provided
    d1 = reading1.estimated_distance or signal_to_distance(reading1.signal_strength)
    d2 = reading2.estimated_distance or signal_to_distance(reading2.signal_strength)

    p1 = reading1.monitor_location
    p2 = reading2.monitor_location

    # Distance between monitors
    monitor_distance = p1.distance_to(p2)

    if monitor_distance == 0:
        return None  # Monitors at same location

    # Check if circles intersect
    if monitor_distance > d1 + d2:
        # Circles don't intersect - use midpoint weighted by distances
        # This happens when device is outside both ranges
        total = d1 + d2
        weight1 = 1 - (d1 / total) if total > 0 else 0.5

        bearing = p1.bearing_to(p2)
        midpoint_dist = monitor_distance * weight1
        location = p1.point_at_distance_and_bearing(midpoint_dist, bearing)

        return PositionEstimate(
            location=location,
            accuracy=max(d1, d2),  # High uncertainty
            confidence=0.3,
        )

    if monitor_distance < abs(d1 - d2):
        # One circle is inside the other
        # Place at the edge of the smaller circle
        if d1 < d2:
            bearing = p1.bearing_to(p2)
            location = p1.point_at_distance_and_bearing(d1, bearing)
        else:
            bearing = p2.bearing_to(p1)
            location = p2.point_at_distance_and_bearing(d2, bearing)

        return PositionEstimate(
            location=location,
            accuracy=min(d1, d2),
            confidence=0.4,
        )

    # Calculate intersection points using circle-circle intersection
    # Convert to local coordinate system for calculation
    # p1 at origin, p2 on x-axis
    d = monitor_distance

    # a = distance from p1 to the line connecting intersection points
    a = (d1 * d1 - d2 * d2 + d * d) / (2 * d)

    # h = distance from that line to intersection points
    h_squared = d1 * d1 - a * a
    if h_squared < 0:
        h_squared = 0  # Numerical precision fix
    h = math.sqrt(h_squared)

    # Calculate intersection points
    bearing_p1_p2 = p1.bearing_to(p2)

    # Point on line between p1 and p2
    mid_point = p1.point_at_distance_and_bearing(a, bearing_p1_p2)

    # Two intersection points (perpendicular to p1-p2 line)
    perp_bearing1 = bearing_p1_p2 + math.pi / 2
    perp_bearing2 = bearing_p1_p2 - math.pi / 2

    intersection1 = mid_point.point_at_distance_and_bearing(h, perp_bearing1)
    intersection2 = mid_point.point_at_distance_and_bearing(h, perp_bearing2)

    # Choose the better intersection point
    if prefer_inside:
        # Prefer point closer to the reference location
        dist1 = prefer_inside.distance_to(intersection1)
        dist2 = prefer_inside.distance_to(intersection2)
        chosen = intersection1 if dist1 < dist2 else intersection2
    else:
        # Default: choose the midpoint of the two intersections
        # This is a reasonable default for home setups
        chosen = GeoPoint(
            latitude=(intersection1.latitude + intersection2.latitude) / 2,
            longitude=(intersection1.longitude + intersection2.longitude) / 2,
        )

    # Accuracy is roughly the distance between intersection points
    accuracy = intersection1.distance_to(intersection2) / 2

    return PositionEstimate(
        location=chosen,
        accuracy=max(accuracy, 1.0),  # Minimum 1m accuracy
        confidence=0.7 if h > 0.5 else 0.5,
    )


def calculate_position(
    readings: list[MonitorReading],
    home_center: Optional[GeoPoint] = None,
) -> Optional[PositionEstimate]:
    """
    Calculate device position from multiple monitor readings.

    Args:
        readings: List of signal readings from different monitors
        home_center: Optional center point of the home (to prefer inside positions)

    Returns:
        Best position estimate or None
    """
    if len(readings) < 1:
        return None

    if len(readings) == 1:
        # Single monitor: can only give a rough distance
        reading = readings[0]
        distance = reading.estimated_distance or signal_to_distance(reading.signal_strength)

        # Place at a default bearing (North) since we don't know direction
        location = reading.monitor_location.point_at_distance_and_bearing(distance, 0)

        return PositionEstimate(
            location=location,
            accuracy=distance * 2,  # Very uncertain without direction
            confidence=0.2,
        )

    if len(readings) == 2:
        # Bilateration
        return bilaterate(readings[0], readings[1], prefer_inside=home_center)

    # 3+ monitors: use weighted average of pairwise bilaterations
    # (Full trilateration is more complex and this works well enough)
    estimates: list[PositionEstimate] = []

    for i in range(len(readings)):
        for j in range(i + 1, len(readings)):
            estimate = bilaterate(readings[i], readings[j], prefer_inside=home_center)
            if estimate:
                estimates.append(estimate)

    if not estimates:
        return None

    # Weighted average by confidence
    total_weight = sum(e.confidence for e in estimates)
    if total_weight == 0:
        return None

    avg_lat = sum(e.location.latitude * e.confidence for e in estimates) / total_weight
    avg_lon = sum(e.location.longitude * e.confidence for e in estimates) / total_weight
    avg_accuracy = sum(e.accuracy * e.confidence for e in estimates) / total_weight

    return PositionEstimate(
        location=GeoPoint(latitude=avg_lat, longitude=avg_lon),
        accuracy=avg_accuracy,
        confidence=min(1.0, total_weight / len(estimates)),
    )


def meters_to_degrees_lat(meters: float) -> float:
    """Convert meters to approximate degrees of latitude."""
    return meters / 111320  # ~111.32 km per degree


def meters_to_degrees_lon(meters: float, latitude: float) -> float:
    """Convert meters to approximate degrees of longitude at a given latitude."""
    return meters / (111320 * math.cos(math.radians(latitude)))
