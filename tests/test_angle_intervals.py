"""Tests for wrap-aware intervals and screen-to-image coordinate transforms."""

from __future__ import annotations

import math

import pytest

from planetary_plume.angle_convention import image_point_to_angle
from planetary_plume.angle_intervals import (
    AngularInterval,
    AngularIntervalError,
    angular_distance,
    direction_line,
    format_interval_deg,
    minimum_distance_rad,
    overlap_width_rad,
    wrapped_interval_polygon,
)
from planetary_plume.viewport import ViewTransform, ViewportError


def test_cardinal_angles_up_right_down_left() -> None:
    center = (100.0, 100.0)

    assert image_point_to_angle((100.0, 90.0), center) == pytest.approx(0.0)
    assert image_point_to_angle((110.0, 100.0), center) == pytest.approx(math.pi / 2)
    assert image_point_to_angle((100.0, 110.0), center) == pytest.approx(math.pi)
    assert image_point_to_angle((90.0, 100.0), center) == pytest.approx(3 * math.pi / 2)


def test_interval_crosses_zero() -> None:
    interval = AngularInterval.from_degrees(350.0, 10.0)

    assert interval.crosses_zero is True
    assert interval.width_deg == pytest.approx(20.0)
    assert interval.contains(math.radians(0.0))
    assert interval.contains(math.radians(355.0))
    assert interval.contains(math.radians(5.0))
    assert not interval.contains(math.radians(20.0))
    assert interval.start_deg == pytest.approx(350.0)
    assert interval.end_deg == pytest.approx(10.0)


def test_interval_does_not_cross_zero() -> None:
    interval = AngularInterval.from_degrees(10.0, 30.0)

    assert interval.crosses_zero is False
    assert interval.width_deg == pytest.approx(20.0)
    assert interval.contains(math.radians(20.0))
    assert not interval.contains(math.radians(5.0))


def test_overlap_across_zero() -> None:
    first = AngularInterval.from_degrees(350.0, 10.0)

    assert overlap_width_rad(first, AngularInterval.from_degrees(355.0, 5.0)) == pytest.approx(
        math.radians(10.0)
    )
    assert overlap_width_rad(first, AngularInterval.from_degrees(5.0, 15.0)) == pytest.approx(
        math.radians(5.0)
    )
    assert overlap_width_rad(first, AngularInterval.from_degrees(15.0, 25.0)) == 0.0


def test_minimum_distance_across_zero() -> None:
    first = AngularInterval.from_degrees(350.0, 10.0)

    assert minimum_distance_rad(first, AngularInterval.from_degrees(355.0, 5.0)) == 0.0
    assert minimum_distance_rad(first, AngularInterval.from_degrees(20.0, 30.0)) == pytest.approx(
        math.radians(10.0)
    )
    assert minimum_distance_rad(first, AngularInterval.from_degrees(340.0, 345.0)) == pytest.approx(
        math.radians(5.0)
    )


def test_direction_contains_and_distance() -> None:
    direction = AngularInterval.direction_from_degrees(0.0)
    interval = AngularInterval.from_degrees(350.0, 10.0)

    assert direction.is_direction
    assert direction.contains(math.radians(0.0))
    assert direction.contains(
        math.radians(359.9), tolerance_rad=math.radians(0.2)
    )
    assert interval.contains(direction.start_rad)
    assert minimum_distance_rad(direction, interval) == 0.0
    assert minimum_distance_rad(
        AngularInterval.direction_from_degrees(90.0),
        interval,
    ) == pytest.approx(math.radians(80.0))
    assert angular_distance(0.0, 2 * math.pi - 0.1) == pytest.approx(0.1)


def test_wrapped_interval_polygon_spans_zero() -> None:
    interval = AngularInterval.from_degrees(350.0, 10.0)
    polygon = wrapped_interval_polygon((100.0, 100.0), 20.0, 30.0, interval, steps=12)

    assert len(polygon) == 24
    radii = [math.hypot(x - 100.0, y - 100.0) for x, y in polygon]
    assert min(radii) == pytest.approx(20.0)
    assert max(radii) == pytest.approx(30.0)
    # The polygon must include points on both sides of the 0/360 boundary.
    angles = [image_point_to_angle(point, (100.0, 100.0)) for point in polygon]
    assert any(angle > math.radians(340.0) for angle in angles)
    assert any(angle < math.radians(20.0) for angle in angles)


def test_direction_line_and_format() -> None:
    direction = AngularInterval.direction_from_degrees(90.0)
    inner, outer = direction_line((0.0, 0.0), 10.0, 20.0, direction)

    assert inner == pytest.approx((10.0, 0.0))
    assert outer == pytest.approx((20.0, 0.0))
    assert "direction 90.0°" in format_interval_deg(direction)
    assert "crosses 0°" in format_interval_deg(AngularInterval.from_degrees(350.0, 10.0))


def test_screen_to_image_cardinal_directions() -> None:
    # A 2x scale with an offset; image (100, 100) is the limb center.
    transform = ViewTransform(scale=2.0, offset_x=100.0, offset_y=100.0)
    center = (100.0, 100.0)

    screen_points = {
        0.0: transform.image_to_screen(100.0, 50.0),  # up
        math.pi / 2: transform.image_to_screen(150.0, 100.0),  # right
        math.pi: transform.image_to_screen(100.0, 150.0),  # down
        3 * math.pi / 2: transform.image_to_screen(50.0, 100.0),  # left
    }
    for expected, screen_point in screen_points.items():
        image_point = transform.screen_to_image(*screen_point)
        angle = image_point_to_angle(image_point, center)
        assert angle == pytest.approx(expected)


def test_viewport_round_trip_and_fit() -> None:
    transform = ViewTransform.fit(800, 600, 1000, 800, margin=0.05)

    for point in ((0.0, 0.0), (800.0, 600.0), (123.4, 456.7)):
        screen = transform.image_to_screen(*point)
        recovered = transform.screen_to_image(*screen)
        assert recovered == pytest.approx(point)

    top_left = transform.image_to_screen(0.0, 0.0)
    bottom_right = transform.image_to_screen(800.0, 600.0)
    assert (top_left[0] + bottom_right[0]) / 2 == pytest.approx(500.0)
    assert (top_left[1] + bottom_right[1]) / 2 == pytest.approx(400.0)


def test_zoom_at_keeps_anchor_image_point() -> None:
    transform = ViewTransform(scale=1.5, offset_x=20.0, offset_y=30.0)
    anchor_screen = (400.0, 300.0)
    anchor_image = transform.screen_to_image(*anchor_screen)

    zoomed = transform.zoom_at(2.0, *anchor_screen)

    assert zoomed.screen_to_image(*anchor_screen) == pytest.approx(anchor_image)
    assert zoomed.scale == pytest.approx(3.0)


def test_invalid_interval_and_viewport_values() -> None:
    with pytest.raises(AngularIntervalError):
        wrapped_interval_polygon((0, 0), 10, 10, AngularInterval.from_degrees(0, 10))
    with pytest.raises(AngularIntervalError):
        direction_line((0, 0), 10, 5, AngularInterval.direction_from_degrees(0))
    with pytest.raises(AngularIntervalError):
        AngularInterval.from_radians(float("nan"), 0.0)
    with pytest.raises(ViewportError):
        ViewTransform(0.0, 0.0, 0.0)
    with pytest.raises(ViewportError):
        ViewTransform.fit(0, 10, 100, 100)
