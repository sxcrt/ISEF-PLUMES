"""Tests for display-only brightness/contrast and viewport errors."""

from __future__ import annotations

import numpy as np
import pytest

from planetary_plume.display import DisplayAdjustmentError, adjust_display
from planetary_plume.viewport import ViewTransform, ViewportError


def test_display_identity_keeps_pixels() -> None:
    base = np.arange(256, dtype=np.uint8).reshape(16, 16)

    adjusted = adjust_display(base, brightness=0, contrast=1.0)

    assert np.array_equal(adjusted, base)
    assert adjusted is not base


def test_display_brightness_and_contrast_do_not_modify_source() -> None:
    base = np.linspace(0, 255, 32 * 32, dtype=np.uint8).reshape(32, 32)
    before = base.copy()

    brighter = adjust_display(base, brightness=25, contrast=1.0)
    higher_contrast = adjust_display(base, brightness=0, contrast=2.0)

    assert np.array_equal(base, before)
    assert brighter.mean() > base.mean()
    assert higher_contrast.std() > base.std()


@pytest.mark.parametrize(
    ("brightness", "contrast"),
    [(-101, 1.0), (101, 1.0), (0, 0.01), (0, 11.0)],
)
def test_invalid_display_values_raise(brightness: int, contrast: float) -> None:
    with pytest.raises(DisplayAdjustmentError):
        adjust_display(np.zeros((4, 4), dtype=np.uint8), brightness=brightness, contrast=contrast)


def test_display_rejects_wrong_shape_or_dtype() -> None:
    with pytest.raises(DisplayAdjustmentError):
        adjust_display(np.zeros((4, 4, 3), dtype=np.uint8))
    with pytest.raises(DisplayAdjustmentError):
        adjust_display(np.zeros((4, 4), dtype=np.float32))


def test_viewport_pan_and_invalid_values() -> None:
    transform = ViewTransform(scale=2.0, offset_x=10.0, offset_y=20.0)
    panned = transform.pan(5.0, -3.0)

    assert panned.image_to_screen(0.0, 0.0) == (15.0, 17.0)
    with pytest.raises(ViewportError):
        transform.zoom_at(0.0, 0.0, 0.0)
    with pytest.raises(ViewportError):
        ViewTransform(float("inf"), 0.0, 0.0)
