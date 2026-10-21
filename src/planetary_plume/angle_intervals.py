"""Wrap-aware angular intervals built on the project convention.

The established conversion lives in :mod:`planetary_plume.angle_convention`:
``0`` radians points up and angles increase clockwise.  This module adds only
interval bookkeeping (containment, overlap, distance, and polygon points).  It
does not define a second angle convention.

An interval is stored as ``(start, end)`` in ``[0, 2*pi)`` and is traversed
clockwise from ``start`` to ``end``.  When ``end < start`` the interval crosses
``0``/``2*pi``.  A zero-width interval represents a single direction.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from planetary_plume.angle_convention import (
    TAU,
    ImagePoint,
    angle_to_image_point,
    degrees_to_radians,
    normalize_angle,
    radians_to_degrees,
)

_EPSILON = 1e-12


class AngularIntervalError(ValueError):
    """Raised when an angular interval is malformed."""


@dataclass(frozen=True)
class AngularInterval:
    """A clockwise angular interval or a single direction.

    ``start_rad`` and ``end_rad`` are normalized to ``[0, 2*pi)``.  The width is
    always the clockwise sweep from start to end, so it lies in
    ``[0, 2*pi)``.  Width zero means a direction, not a full circle.
    """

    start_rad: float
    end_rad: float

    def __post_init__(self) -> None:
        for label, value in (("start_rad", self.start_rad), ("end_rad", self.end_rad)):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise AngularIntervalError(f"{label} must be a number.")
            if not math.isfinite(float(value)):
                raise AngularIntervalError(f"{label} must be finite.")

    @classmethod
    def from_radians(cls, start: float, end: float) -> "AngularInterval":
        try:
            return cls(normalize_angle(float(start)), normalize_angle(float(end)))
        except (TypeError, ValueError) as exc:
            raise AngularIntervalError(f"Invalid interval angles: {exc}") from exc

    @classmethod
    def from_degrees(cls, start_deg: float, end_deg: float) -> "AngularInterval":
        return cls.from_radians(
            degrees_to_radians(float(start_deg)),
            degrees_to_radians(float(end_deg)),
        )

    @classmethod
    def direction_from_radians(cls, angle: float) -> "AngularInterval":
        value = normalize_angle(float(angle))
        return cls(value, value)

    @classmethod
    def direction_from_degrees(cls, angle_deg: float) -> "AngularInterval":
        return cls.direction_from_radians(degrees_to_radians(float(angle_deg)))

    @property
    def width_rad(self) -> float:
        return (self.end_rad - self.start_rad) % TAU

    @property
    def width_deg(self) -> float:
        return radians_to_degrees(self.width_rad)

    @property
    def start_deg(self) -> float:
        return radians_to_degrees(self.start_rad)

    @property
    def end_deg(self) -> float:
        return radians_to_degrees(self.end_rad)

    @property
    def is_direction(self) -> bool:
        return self.width_rad <= _EPSILON

    @property
    def crosses_zero(self) -> bool:
        return (not self.is_direction) and self.end_rad < self.start_rad

    def contains(self, angle: float, *, tolerance_rad: float = 0.0) -> bool:
        """Return whether ``angle`` lies on the clockwise sweep."""

        if tolerance_rad < 0 or not math.isfinite(tolerance_rad):
            raise AngularIntervalError("tolerance_rad must be finite and non-negative.")
        target = normalize_angle(float(angle))
        if tolerance_rad >= TAU:
            return True
        if self.is_direction:
            return angular_distance(target, self.start_rad) <= tolerance_rad + _EPSILON
        delta = (target - self.start_rad) % TAU
        return delta <= self.width_rad + tolerance_rad + _EPSILON

    def segments(self) -> tuple[tuple[float, float], ...]:
        """Split into non-wrapping ``[start, end]`` segments in radians."""

        if self.is_direction:
            return ()
        if self.end_rad > self.start_rad:
            return ((self.start_rad, self.end_rad),)
        return ((self.start_rad, TAU), (0.0, self.end_rad))

    def to_degrees(self) -> tuple[float, float]:
        return self.start_deg, self.end_deg


def angular_distance(first: float, second: float) -> float:
    """Shortest absolute angular distance in radians."""

    delta = abs((normalize_angle(first) - normalize_angle(second) + math.pi) % TAU - math.pi)
    return min(delta, TAU)


def overlap_width_rad(first: AngularInterval, second: AngularInterval) -> float:
    """Width of the intersection of two intervals (zero for directions)."""

    total = 0.0
    for first_start, first_end in first.segments():
        for second_start, second_end in second.segments():
            start = max(first_start, second_start)
            end = min(first_end, second_end)
            if end > start:
                total += end - start
    return min(total, TAU)


def minimum_distance_rad(first: AngularInterval, second: AngularInterval) -> float:
    """Minimum angular distance between two intervals.

    Zero means the intervals overlap or touch.  For a direction, the distance is
    zero when the direction lies inside the other interval.
    """

    if first.is_direction and second.is_direction:
        return angular_distance(first.start_rad, second.start_rad)
    if first.is_direction:
        return 0.0 if second.contains(first.start_rad) else min(
            angular_distance(first.start_rad, second.start_rad),
            angular_distance(first.start_rad, second.end_rad),
        )
    if second.is_direction:
        return 0.0 if first.contains(second.start_rad) else min(
            angular_distance(first.start_rad, second.start_rad),
            angular_distance(first.end_rad, second.start_rad),
        )
    if overlap_width_rad(first, second) > 0:
        return 0.0
    if first.contains(second.start_rad) or second.contains(first.start_rad):
        return 0.0
    candidates = (
        angular_distance(first.start_rad, second.start_rad),
        angular_distance(first.start_rad, second.end_rad),
        angular_distance(first.end_rad, second.start_rad),
        angular_distance(first.end_rad, second.end_rad),
    )
    return min(candidates)


def wrapped_interval_polygon(
    center: ImagePoint | tuple[float, float],
    inner_radius: float,
    outer_radius: float,
    interval: AngularInterval,
    *,
    steps: int = 64,
) -> list[tuple[float, float]]:
    """Polygon for a clockwise interval, including intervals crossing zero.

    Points are returned in native image coordinates.  A direction returns an
    empty list because it has no area.
    """

    if inner_radius < 0 or outer_radius <= inner_radius:
        raise AngularIntervalError("require 0 <= inner_radius < outer_radius.")
    if steps < 2:
        raise AngularIntervalError("steps must be at least 2.")
    if interval.is_direction:
        return []

    angles = [
        interval.start_rad + interval.width_rad * index / (steps - 1)
        for index in range(steps)
    ]
    outer = [angle_to_image_point(center, outer_radius, angle) for angle in angles]
    inner = [angle_to_image_point(center, inner_radius, angle) for angle in reversed(angles)]
    return [(point.x, point.y) for point in outer + inner]


def direction_line(
    center: ImagePoint | tuple[float, float],
    inner_radius: float,
    outer_radius: float,
    interval: AngularInterval,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Endpoints of a radial line for a direction interval."""

    if not interval.is_direction:
        raise AngularIntervalError("direction_line requires a zero-width interval.")
    if inner_radius < 0 or outer_radius <= inner_radius:
        raise AngularIntervalError("require 0 <= inner_radius < outer_radius.")
    inner = angle_to_image_point(center, inner_radius, interval.start_rad)
    outer = angle_to_image_point(center, outer_radius, interval.start_rad)
    return (inner.x, inner.y), (outer.x, outer.y)


def format_interval_deg(interval: AngularInterval, *, digits: int = 1) -> str:
    """Human-readable interval in the documented clockwise direction."""

    if interval.is_direction:
        return f"direction {interval.start_deg:.{digits}f}°"
    suffix = ", crosses 0°" if interval.crosses_zero else ""
    return (
        f"{interval.start_deg:.{digits}f}°–{interval.end_deg:.{digits}f}° "
        f"({interval.width_deg:.{digits}f}° clockwise{suffix})"
    )
