"""Explicit image-coordinate to plume-angle conversion.

Convention established from the bundle README and the KDD 2019 paper's
Figure 6 axis label:

* image ``x`` is the column index, increasing right;
* image ``y`` is the row index, increasing down;
* the angular origin is the fitted limb-circle center;
* 0 rad points up (negative row direction);
* angles increase clockwise in the displayed image.

The inverse transform is included so tests can check cardinal directions and
round trips independently of image readers and overlay rendering.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

TAU = 2.0 * math.pi
CONVENTION_DESCRIPTION = (
    "0 rad = up; increasing clockwise; origin = fitted limb-circle center; "
    "x = column (right), y = row (down)"
)


class AngleConventionError(ValueError):
    """Raised when an angle or coordinate is invalid."""


def normalize_angle(angle: float) -> float:
    """Normalize radians into ``[0, 2*pi)``."""

    if not math.isfinite(angle):
        raise AngleConventionError("angle must be finite.")
    return angle % TAU


def degrees_to_radians(degrees: float) -> float:
    if not math.isfinite(degrees):
        raise AngleConventionError("degrees must be finite.")
    return math.radians(degrees) % TAU


def radians_to_degrees(radians: float) -> float:
    return math.degrees(normalize_angle(radians))


@dataclass(frozen=True)
class ImagePoint:
    x: float
    y: float


def image_point_to_angle(
    point: ImagePoint | tuple[float, float],
    center: ImagePoint | tuple[float, float],
) -> float:
    """Return the documented angle for a native-image point.

    ``theta = atan2(x - cx, -(y - cy)) mod 2*pi``
    """

    px, py = (point.x, point.y) if isinstance(point, ImagePoint) else point
    cx, cy = (center.x, center.y) if isinstance(center, ImagePoint) else center
    values = (px, py, cx, cy)
    if not all(math.isfinite(value) for value in values):
        raise AngleConventionError("point and center coordinates must be finite.")
    return math.atan2(px - cx, -(py - cy)) % TAU


def angle_to_image_point(
    center: ImagePoint | tuple[float, float],
    radius: float,
    angle: float,
) -> ImagePoint:
    """Inverse conversion: place a point on a circle at the documented angle."""

    cx, cy = (center.x, center.y) if isinstance(center, ImagePoint) else center
    if not all(math.isfinite(value) for value in (cx, cy, radius, angle)):
        raise AngleConventionError("center, radius, and angle must be finite.")
    if radius < 0:
        raise AngleConventionError("radius must be non-negative.")
    theta = normalize_angle(angle)
    return ImagePoint(
        x=cx + radius * math.sin(theta),
        y=cy - radius * math.cos(theta),
    )


def point_radius_angle(
    point: ImagePoint | tuple[float, float],
    center: ImagePoint | tuple[float, float],
) -> tuple[float, float]:
    """Return ``(radius, angle)`` for a native-image point."""

    px, py = (point.x, point.y) if isinstance(point, ImagePoint) else point
    cx, cy = (center.x, center.y) if isinstance(center, ImagePoint) else center
    radius = math.hypot(px - cx, py - cy)
    return radius, image_point_to_angle((px, py), (cx, cy))


def interval_polygon(
    center: ImagePoint | tuple[float, float],
    inner_radius: float,
    outer_radius: float,
    start: float,
    end: float,
    *,
    steps: int = 48,
) -> list[tuple[float, float]]:
    """Polygon for an angular interval between two radii."""

    if not (0 <= start < end <= TAU):
        raise AngleConventionError(
            f"interval must satisfy 0 <= start < end <= 2*pi: [{start}, {end}]"
        )
    if inner_radius < 0 or outer_radius <= inner_radius:
        raise AngleConventionError("require 0 <= inner_radius < outer_radius.")
    if steps < 2:
        raise AngleConventionError("steps must be at least 2.")
    angles = [
        start + (end - start) * index / (steps - 1)
        for index in range(steps)
    ]
    outer = [angle_to_image_point(center, outer_radius, angle) for angle in angles]
    inner = [angle_to_image_point(center, inner_radius, angle) for angle in reversed(angles)]
    return [(point.x, point.y) for point in outer + inner]
