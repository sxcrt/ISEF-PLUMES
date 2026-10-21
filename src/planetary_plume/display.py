"""Display-only brightness/contrast adjustment for review images.

The source image array is never modified.  Callers keep the normalized base
array and re-render a new ``uint8`` array for each GUI adjustment.
"""

from __future__ import annotations

import numpy as np


class DisplayAdjustmentError(ValueError):
    """Raised when a display adjustment is invalid."""


def adjust_display(
    base: np.ndarray,
    *,
    brightness: int = 0,
    contrast: float = 1.0,
) -> np.ndarray:
    """Apply a display-only brightness/contrast transform.

    Args:
        base: 2-D ``uint8`` image, normally from
            :func:`planetary_plume.image_readers.normalize_for_display`.
        brightness: integer in ``[-100, 100]``; 0 is unchanged.
        contrast: multiplier in ``[0.05, 10.0]``; 1.0 is unchanged.

    Returns:
        A new ``uint8`` array with the same shape.  ``base`` is not modified.
    """

    values = np.asarray(base)
    if values.ndim != 2:
        raise DisplayAdjustmentError("base must be a two-dimensional array.")
    if values.dtype != np.uint8:
        raise DisplayAdjustmentError("base must have dtype uint8.")
    if isinstance(brightness, bool) or not isinstance(brightness, (int, float)):
        raise DisplayAdjustmentError("brightness must be a number.")
    if not -100 <= float(brightness) <= 100:
        raise DisplayAdjustmentError("brightness must be in [-100, 100].")
    if not isinstance(contrast, (int, float)) or isinstance(contrast, bool):
        raise DisplayAdjustmentError("contrast must be a number.")
    if not 0.05 <= float(contrast) <= 10.0:
        raise DisplayAdjustmentError("contrast must be in [0.05, 10.0].")

    normalized = values.astype(np.float32) / 255.0
    adjusted = (normalized - 0.5) * float(contrast) + 0.5 + float(brightness) / 100.0
    return np.clip(adjusted * 255.0 + 0.5, 0.0, 255.0).astype(np.uint8)
