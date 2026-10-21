"""Exploratory angular-convention diagnostic.

The documented convention is ``0 rad = up, clockwise``, but the annotation
README does not define the angular origin.  This module measures whether the
annotated sectors coincide with bright structure outside the fitted limb under
that convention and five alternatives.  A consistent result would support a
convention; inconsistent results mean the convention is unresolved.
"""

from __future__ import annotations

import math
from typing import Callable

import numpy as np

from planetary_plume.annotations import AnnotationRecord
from planetary_plume.image_readers import ImageInfo, normalize_for_display
from planetary_plume.validation import CircleFit

TAU = 2.0 * math.pi


def _up_cw(angle: float) -> float:
    return angle % TAU


def _up_ccw(angle: float) -> float:
    return (-angle) % TAU


def _right_ccw_math(angle: float) -> float:
    return (math.pi / 2.0 - angle) % TAU


def _right_cw_screen(angle: float) -> float:
    return (math.pi / 2.0 + angle) % TAU


def _down_cw(angle: float) -> float:
    return (math.pi + angle) % TAU


def _down_ccw(angle: float) -> float:
    return (math.pi - angle) % TAU


CONVENTIONS: dict[str, Callable[[float], float]] = {
    "up_cw": _up_cw,
    "up_ccw": _up_ccw,
    "right_ccw_math": _right_ccw_math,
    "right_cw_screen": _right_cw_screen,
    "down_cw": _down_cw,
    "down_ccw": _down_ccw,
}


def angular_profile(
    image: ImageInfo,
    circle: CircleFit,
    *,
    bins: int = 720,
    inner_factor: float = 1.02,
    outer_factor: float = 1.8,
    percentile: float = 90.0,
) -> np.ndarray:
    """Brightness profile in documented-angle bins for an annulus outside the limb."""

    if bins < 12:
        raise ValueError("bins must be at least 12.")
    if not (1.0 <= inner_factor < outer_factor):
        raise ValueError("Require 1 <= inner_factor < outer_factor.")
    if not 0 <= percentile <= 100:
        raise ValueError("percentile must be in [0, 100].")

    display = normalize_for_display(image.array).astype(np.float64) / 255.0
    yy, xx = np.mgrid[0 : display.shape[0], 0 : display.shape[1]]
    dx = xx - circle.center_x
    dy = yy - circle.center_y
    radius = np.hypot(dx, dy)
    angle = np.arctan2(dx, -dy) % TAU
    mask = (radius >= circle.radius * inner_factor) & (radius <= circle.radius * outer_factor)
    if mask.sum() < bins:
        raise ValueError("Too few annulus pixels for an angular profile.")

    indices = np.minimum((angle[mask] / TAU * bins).astype(int), bins - 1)
    values = display[mask]
    profile = np.full(bins, np.nan, dtype=np.float64)
    for index in range(bins):
        bin_values = values[indices == index]
        if bin_values.size:
            profile[index] = float(np.percentile(bin_values, percentile))
    return profile


def _profile_value(profile: np.ndarray, documented_angle: float) -> float:
    bins = len(profile)
    index = min(int((documented_angle % TAU) / TAU * bins), bins - 1)
    return float(profile[index])


def contrast_scores(
    profile: np.ndarray,
    intervals: tuple[tuple[float, float], ...],
    *,
    samples_per_interval: int = 24,
) -> dict[str, float]:
    """Mean-in-sector minus mean-outside, in profile standard deviations."""

    finite = np.isfinite(profile)
    if finite.sum() < 10:
        raise ValueError("Profile has too few finite bins.")
    base = float(np.nanmean(profile))
    spread = float(np.nanstd(profile)) or 1.0

    scores: dict[str, float] = {}
    for name, mapper in CONVENTIONS.items():
        sampled: list[float] = []
        for start, end in intervals:
            if not (0 <= start < end <= TAU):
                raise ValueError(f"Invalid interval: [{start}, {end}]")
            for angle in np.linspace(start, end, max(2, samples_per_interval)):
                value = _profile_value(profile, mapper(float(angle)))
                if math.isfinite(value):
                    sampled.append(value)
        scores[name] = (float(np.mean(sampled)) - base) / spread if sampled else float("nan")
    return scores


def diagnose_record(image: ImageInfo, record: AnnotationRecord, circle: CircleFit) -> dict[str, object]:
    """Return the diagnostic scores for one positive annotation."""

    if not record.plume_status or not record.plume_intervals:
        raise ValueError("Convention diagnostic requires a positive annotation.")
    profile = angular_profile(image, circle)
    scores = contrast_scores(profile, record.plume_intervals)
    return {
        "annotation_relative_path": record.annotation_relative_path,
        "plume_intervals": [list(interval) for interval in record.plume_intervals],
        "scores": {key: (None if math.isnan(value) else value) for key, value in scores.items()},
        "highest": max(
            (key for key, value in scores.items() if math.isfinite(value)),
            key=lambda key: scores[key],
            default=None,
        ),
    }
