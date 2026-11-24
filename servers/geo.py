"""Small, dependency-free geometry helpers shared by the MCP servers.

Coordinates are always (latitude, longitude) in decimal degrees.
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence

EARTH_RADIUS_M = 6_371_000.0

LatLon = Sequence[float]


def haversine_m(a: LatLon, b: LatLon) -> float:
    """Great-circle distance between two points, in metres."""
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def path_length_m(points: Sequence[LatLon]) -> float:
    """Total length of a polyline, in metres."""
    return sum(haversine_m(points[i], points[i + 1]) for i in range(len(points) - 1))


def sample_path(points: Sequence[LatLon], step_m: float = 50.0) -> list[tuple[float, float]]:
    """Return points spaced roughly every ``step_m`` metres along a polyline.

    The first and last points of the polyline are always included.
    """
    if not points:
        return []
    if len(points) == 1:
        return [(float(points[0][0]), float(points[0][1]))]
    samples: list[tuple[float, float]] = [(float(points[0][0]), float(points[0][1]))]
    carry = 0.0  # distance travelled since the last sample
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        seg = haversine_m(a, b)
        if seg == 0:
            continue
        pos = step_m - carry  # distance into this segment of the next sample
        while pos <= seg:
            t = pos / seg
            samples.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
            pos += step_m
        carry = seg - (pos - step_m)
    last = (float(points[-1][0]), float(points[-1][1]))
    if samples[-1] != last:
        samples.append(last)
    return samples


def min_distance_to_samples_m(point: LatLon, samples: Iterable[LatLon]) -> float:
    """Distance from ``point`` to the closest of ``samples`` (metres)."""
    return min((haversine_m(point, s) for s in samples), default=float("inf"))


def offset_point(origin: LatLon, dest: LatLon, fraction: float, perpendicular: float) -> tuple[float, float]:
    """A point ``fraction`` of the way from origin to dest, pushed sideways.

    ``perpendicular`` is the sideways offset as a fraction of the origin→dest
    distance (positive = left of travel direction).
    """
    lat = origin[0] + (dest[0] - origin[0]) * fraction
    lon = origin[1] + (dest[1] - origin[1]) * fraction
    # Work in a locally-flat frame where 1 deg lon is shrunk by cos(lat).
    k = math.cos(math.radians(lat))
    dx = (dest[1] - origin[1]) * k
    dy = dest[0] - origin[0]
    # Left-perpendicular of (dx, dy) is (-dy, dx).
    return (lat + dx * perpendicular, lon + (-dy * perpendicular) / k)
