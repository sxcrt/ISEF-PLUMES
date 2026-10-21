"""Tests for the exploratory angular-convention diagnostic."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from planetary_plume.convention import angular_profile, contrast_scores
from planetary_plume.image_readers import ImageInfo
from planetary_plume.validation import CircleFit


def test_contrast_scores_favors_documented_convention_on_synthetic_profile() -> None:
    bins = 360
    profile = np.full(bins, 0.1, dtype=np.float64)
    start = int(0.20 / (2 * math.pi) * bins)
    end = int(0.40 / (2 * math.pi) * bins)
    profile[start:end] = 1.0

    scores = contrast_scores(profile, ((0.20, 0.40),))

    assert scores["up_cw"] == max(scores.values())
    assert scores["up_cw"] > 0


def test_contrast_scores_rejects_invalid_interval() -> None:
    with pytest.raises(ValueError, match="Invalid interval"):
        contrast_scores(np.ones(360), ((0.4, 0.2),))


def test_angular_profile_peaks_in_bright_sector() -> None:
    size = 120
    center = 60.0
    array = np.zeros((size, size), dtype=np.uint8)
    yy, xx = np.mgrid[0:size, 0:size]
    dx = xx - center
    dy = yy - center
    radius = np.hypot(dx, dy)
    angle = np.arctan2(dx, -dy) % (2 * math.pi)
    wedge = (radius >= 12) & (radius <= 20) & (angle >= 0.0) & (angle <= 0.5)
    array[wedge] = 255
    info = ImageInfo(
        path=Path("synthetic.png"),
        format="test",
        width=size,
        height=size,
        bit_depth=8,
        dtype="uint8",
        array=array,
        metadata={},
        warnings=(),
    )
    circle = CircleFit(center, center, 10.0, 0.0)

    profile = angular_profile(info, circle, bins=360, inner_factor=1.2, outer_factor=2.0)

    peak = int(np.nanargmax(profile))
    peak_angle = peak / 360 * 2 * math.pi
    assert 0.0 <= peak_angle <= 0.5
