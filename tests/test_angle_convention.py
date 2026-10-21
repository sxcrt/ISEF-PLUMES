"""Tests for the explicit image-coordinate / plume-angle convention."""

from __future__ import annotations

import math

import pytest

from planetary_plume.angle_convention import (
    AngleConventionError,
    angle_to_image_point,
    degrees_to_radians,
    image_point_to_angle,
    interval_polygon,
    normalize_angle,
    point_radius_angle,
    radians_to_degrees,
)


def test_cardinal_angles_in_image_coordinates() -> None:
    center = (100.0, 100.0)

    assert image_point_to_angle((100.0, 90.0), center) == pytest.approx(0.0)
    assert image_point_to_angle((110.0, 100.0), center) == pytest.approx(math.pi / 2)
    assert image_point_to_angle((100.0, 110.0), center) == pytest.approx(math.pi)
    assert image_point_to_angle((90.0, 100.0), center) == pytest.approx(3 * math.pi / 2)


def test_inverse_conversion_places_cardinal_points() -> None:
    center = (100.0, 100.0)

    top = angle_to_image_point(center, 10.0, 0.0)
    right = angle_to_image_point(center, 10.0, math.pi / 2)
    bottom = angle_to_image_point(center, 10.0, math.pi)
    left = angle_to_image_point(center, 10.0, 3 * math.pi / 2)

    assert (top.x, top.y) == pytest.approx((100.0, 90.0))
    assert (right.x, right.y) == pytest.approx((110.0, 100.0))
    assert (bottom.x, bottom.y) == pytest.approx((100.0, 110.0))
    assert (left.x, left.y) == pytest.approx((90.0, 100.0))


def test_round_trip_point_radius_angle() -> None:
    center = (20.0, 30.0)
    for angle in (0.0, 0.3, 1.2, math.pi, 4.5, 6.1):
        point = angle_to_image_point(center, 7.5, angle)
        radius, recovered = point_radius_angle((point.x, point.y), center)
        assert radius == pytest.approx(7.5)
        assert recovered == pytest.approx(normalize_angle(angle))


def test_degrees_radians_conversion() -> None:
    assert degrees_to_radians(0) == 0
    assert degrees_to_radians(90) == pytest.approx(math.pi / 2)
    assert radians_to_degrees(math.pi) == pytest.approx(180)
    assert radians_to_degrees(-math.pi / 2) == pytest.approx(270)


def test_interval_polygon_is_outside_inner_radius() -> None:
    polygon = interval_polygon((0.0, 0.0), 10.0, 15.0, 0.1, 0.4, steps=8)
    assert len(polygon) == 16
    radii = [math.hypot(x, y) for x, y in polygon]
    assert min(radii) == pytest.approx(10.0)
    assert max(radii) == pytest.approx(15.0)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_invalid_values_raise(value: float) -> None:
    with pytest.raises(AngleConventionError):
        normalize_angle(value)
    with pytest.raises(AngleConventionError):
        angle_to_image_point((0.0, 0.0), 1.0, value)


def test_invalid_interval_raises() -> None:
    with pytest.raises(AngleConventionError):
        interval_polygon((0.0, 0.0), 10.0, 15.0, 0.4, 0.1)
