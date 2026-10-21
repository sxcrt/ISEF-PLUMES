"""Pure screen/image coordinate transforms for the review canvas.

The GUI uses this object for every mouse-to-image conversion.  Keeping the
transform separate from Qt makes the cardinal-direction and round-trip tests
deterministic.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


class ViewportError(ValueError):
    """Raised when a view transform is invalid."""


@dataclass(frozen=True)
class ViewTransform:
    scale: float
    offset_x: float
    offset_y: float

    def __post_init__(self) -> None:
        values = (self.scale, self.offset_x, self.offset_y)
        if not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
            raise ViewportError("View transform values must be numbers.")
        if not all(math.isfinite(float(value)) for value in values):
            raise ViewportError("View transform values must be finite.")
        if self.scale <= 0:
            raise ViewportError("scale must be positive.")

    def image_to_screen(self, x: float, y: float) -> tuple[float, float]:
        return (x * self.scale + self.offset_x, y * self.scale + self.offset_y)

    def screen_to_image(self, x: float, y: float) -> tuple[float, float]:
        return ((x - self.offset_x) / self.scale, (y - self.offset_y) / self.scale)

    def pan(self, dx: float, dy: float) -> "ViewTransform":
        return ViewTransform(self.scale, self.offset_x + dx, self.offset_y + dy)

    def zoom_at(
        self,
        factor: float,
        screen_x: float,
        screen_y: float,
        *,
        min_scale: float = 0.02,
        max_scale: float = 40.0,
    ) -> "ViewTransform":
        if not math.isfinite(factor) or factor <= 0:
            raise ViewportError("zoom factor must be finite and positive.")
        if min_scale <= 0 or max_scale <= min_scale:
            raise ViewportError("require 0 < min_scale < max_scale.")
        new_scale = min(max(self.scale * factor, min_scale), max_scale)
        image_x, image_y = self.screen_to_image(screen_x, screen_y)
        return ViewTransform(
            scale=new_scale,
            offset_x=screen_x - image_x * new_scale,
            offset_y=screen_y - image_y * new_scale,
        )

    @classmethod
    def fit(
        cls,
        image_width: int,
        image_height: int,
        view_width: int,
        view_height: int,
        *,
        margin: float = 0.04,
    ) -> "ViewTransform":
        if image_width <= 0 or image_height <= 0:
            raise ViewportError("image dimensions must be positive.")
        if view_width <= 0 or view_height <= 0:
            raise ViewportError("view dimensions must be positive.")
        if not 0 <= margin < 0.5:
            raise ViewportError("margin must be in [0, 0.5).")
        usable_width = view_width * (1.0 - 2.0 * margin)
        usable_height = view_height * (1.0 - 2.0 * margin)
        scale = min(usable_width / image_width, usable_height / image_height)
        return cls(
            scale=scale,
            offset_x=(view_width - image_width * scale) / 2.0,
            offset_y=(view_height - image_height * scale) / 2.0,
        )
