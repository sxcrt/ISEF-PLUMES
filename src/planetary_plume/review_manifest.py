"""Sanitized review manifest for independent plume-candidate annotation.

This module is deliberately separated from the released-label parser.  The
review manifest contains image identity, dimensions, source paths, and the
fitted limb circle only.  It must never contain released plume sectors or
positive/negative labels.  The GUI imports this module and nothing from
:mod:`planetary_plume.annotations`.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REVIEW_MANIFEST_FORMAT = "planetary-plume-review-manifest"
REVIEW_MANIFEST_VERSION = 1
CONVENTION_DESCRIPTION = (
    "0 rad = up; increasing clockwise; origin = fitted limb-circle center; "
    "x = column (right), y = row (down)"
)

# Exact key names that would indicate released-label content.  The scan is
# recursive because a future manifest format could nest these fields.
FORBIDDEN_LABEL_KEYS = frozenset(
    {
        "plume",
        "plumes",
        "plume_status",
        "plume_intervals",
        "plume_interval_count",
        "positive",
        "negative",
        "ground_truth",
        "ground_truth_label",
        "labels",
    }
)


class ReviewManifestError(ValueError):
    """Raised when a review manifest is missing, malformed, or unsafe."""


@dataclass(frozen=True)
class LimbCircle:
    center_x: float
    center_y: float
    radius: float
    rms_residual: float

    def __post_init__(self) -> None:
        values = (self.center_x, self.center_y, self.radius, self.rms_residual)
        if not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
            raise ReviewManifestError("Limb-circle values must be numbers.")
        if not all(math.isfinite(float(value)) for value in values):
            raise ReviewManifestError("Limb-circle values must be finite.")
        if self.radius <= 0:
            raise ReviewManifestError("Limb-circle radius must be positive.")
        if self.rms_residual < 0:
            raise ReviewManifestError("Limb-circle RMS residual must be non-negative.")

    def to_dict(self) -> dict[str, float]:
        return {
            "center_x": float(self.center_x),
            "center_y": float(self.center_y),
            "radius": float(self.radius),
            "rms_residual": float(self.rms_residual),
        }

    @classmethod
    def from_dict(cls, payload: Any, *, label: str = "limb") -> "LimbCircle":
        if not isinstance(payload, dict):
            raise ReviewManifestError(f"{label} must be an object.")
        required = ("center_x", "center_y", "radius", "rms_residual")
        missing = [key for key in required if key not in payload]
        if missing:
            raise ReviewManifestError(f"{label} is missing fields: {', '.join(missing)}")
        return cls(
            center_x=float(payload["center_x"]),
            center_y=float(payload["center_y"]),
            radius=float(payload["radius"]),
            rms_residual=float(payload["rms_residual"]),
        )


@dataclass(frozen=True)
class ReviewImage:
    """One image that can be independently reviewed.  No label fields."""

    image_id: str
    display_name: str
    product_family: str
    target: str
    instrument: str
    width: int
    height: int
    image_format: str
    product_id: str
    product_path: str
    pds_label_path: str | None
    image_sha256: str
    limb: LimbCircle

    def __post_init__(self) -> None:
        if not isinstance(self.image_id, str) or not self.image_id.strip():
            raise ReviewManifestError("image_id must be a non-empty string.")
        for field_name in (
            "display_name",
            "product_family",
            "target",
            "instrument",
            "image_format",
            "product_id",
            "product_path",
            "image_sha256",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ReviewManifestError(f"{field_name} must be a non-empty string.")
        if not isinstance(self.width, int) or isinstance(self.width, bool) or self.width <= 0:
            raise ReviewManifestError("width must be a positive integer.")
        if not isinstance(self.height, int) or isinstance(self.height, bool) or self.height <= 0:
            raise ReviewManifestError("height must be a positive integer.")
        if self.pds_label_path is not None and not isinstance(self.pds_label_path, str):
            raise ReviewManifestError("pds_label_path must be a string or null.")
        if not isinstance(self.limb, LimbCircle):
            raise ReviewManifestError("limb must be a LimbCircle.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "image_id": self.image_id,
            "display_name": self.display_name,
            "product_family": self.product_family,
            "target": self.target,
            "instrument": self.instrument,
            "width": self.width,
            "height": self.height,
            "image_format": self.image_format,
            "product_id": self.product_id,
            "product_path": self.product_path,
            "pds_label_path": self.pds_label_path,
            "image_sha256": self.image_sha256,
            "limb": self.limb.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Any, *, label: str = "image") -> "ReviewImage":
        if not isinstance(payload, dict):
            raise ReviewManifestError(f"{label} must be an object.")
        required = (
            "image_id",
            "display_name",
            "product_family",
            "target",
            "instrument",
            "width",
            "height",
            "image_format",
            "product_id",
            "product_path",
            "image_sha256",
            "limb",
        )
        missing = [key for key in required if key not in payload]
        if missing:
            raise ReviewManifestError(f"{label} is missing fields: {', '.join(missing)}")
        try:
            return cls(
                image_id=str(payload["image_id"]),
                display_name=str(payload["display_name"]),
                product_family=str(payload["product_family"]),
                target=str(payload["target"]),
                instrument=str(payload["instrument"]),
                width=int(payload["width"]),
                height=int(payload["height"]),
                image_format=str(payload["image_format"]),
                product_id=str(payload["product_id"]),
                product_path=str(payload["product_path"]),
                pds_label_path=(
                    None if payload.get("pds_label_path") is None else str(payload["pds_label_path"])
                ),
                image_sha256=str(payload["image_sha256"]),
                limb=LimbCircle.from_dict(payload["limb"], label=f"{label}.limb"),
            )
        except (TypeError, ValueError) as exc:
            if isinstance(exc, ReviewManifestError):
                raise
            raise ReviewManifestError(f"{label} has invalid values: {exc}") from exc


@dataclass(frozen=True)
class ReviewManifest:
    generated_at_utc: str
    source: dict[str, Any]
    images: tuple[ReviewImage, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.generated_at_utc, str) or not self.generated_at_utc.strip():
            raise ReviewManifestError("generated_at_utc must be a non-empty string.")
        if not isinstance(self.source, dict):
            raise ReviewManifestError("source must be an object.")
        if not self.images:
            raise ReviewManifestError("Review manifest contains no images.")
        image_ids = [image.image_id for image in self.images]
        duplicates = sorted({item for item in image_ids if image_ids.count(item) > 1})
        if duplicates:
            raise ReviewManifestError(
                "Review manifest contains duplicate image_id values: " + ", ".join(duplicates)
            )

    def by_id(self) -> dict[str, ReviewImage]:
        return {image.image_id: image for image in self.images}

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": REVIEW_MANIFEST_FORMAT,
            "format_version": REVIEW_MANIFEST_VERSION,
            "generated_at_utc": self.generated_at_utc,
            "source": self.source,
            "convention": {
                "description": CONVENTION_DESCRIPTION,
                "zero": "up",
                "direction": "clockwise",
                "origin": "fitted_limb_center",
            },
            "images": [image.to_dict() for image in self.images],
        }


def assert_no_released_label_fields(payload: Any, *, path: str = "$") -> None:
    """Reject any exact key that would expose released plume labels."""

    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(key, str) and key.lower() in FORBIDDEN_LABEL_KEYS:
                raise ReviewManifestError(
                    f"Forbidden released-label field {key!r} at {path}. "
                    "The review manifest must not contain plume labels."
                )
            assert_no_released_label_fields(value, path=f"{path}.{key}")
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            assert_no_released_label_fields(value, path=f"{path}[{index}]")


def review_manifest_payload(
    *,
    generated_at_utc: str,
    source: dict[str, Any],
    images: list[ReviewImage],
) -> dict[str, Any]:
    manifest = ReviewManifest(generated_at_utc, source, tuple(images))
    payload = manifest.to_dict()
    assert_no_released_label_fields(payload)
    return payload


def load_review_manifest(path: str | Path) -> ReviewManifest:
    source_path = Path(path).expanduser().resolve(strict=False)
    if not source_path.is_file():
        raise ReviewManifestError(f"Review manifest not found: {source_path}")
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReviewManifestError(f"Could not read review manifest {source_path}: {exc}") from exc

    assert_no_released_label_fields(payload)
    if not isinstance(payload, dict):
        raise ReviewManifestError("Review manifest root must be an object.")
    if payload.get("format") != REVIEW_MANIFEST_FORMAT:
        raise ReviewManifestError(
            f"Unsupported review manifest format: {payload.get('format')!r}. "
            f"Expected {REVIEW_MANIFEST_FORMAT!r}."
        )
    if payload.get("format_version") != REVIEW_MANIFEST_VERSION:
        raise ReviewManifestError(
            f"Unsupported review manifest version: {payload.get('format_version')!r}."
        )
    convention = payload.get("convention")
    if not isinstance(convention, dict):
        raise ReviewManifestError("Review manifest is missing the 'convention' object.")
    expected_convention = {
        "zero": "up",
        "direction": "clockwise",
        "origin": "fitted_limb_center",
    }
    for key, expected in expected_convention.items():
        if convention.get(key) != expected:
            raise ReviewManifestError(
                f"Unsupported review-manifest convention.{key}: "
                f"{convention.get(key)!r}; expected {expected!r}."
            )
    images = payload.get("images")
    if not isinstance(images, list) or not images:
        raise ReviewManifestError("Review manifest must contain a non-empty 'images' list.")
    parsed_images = tuple(
        ReviewImage.from_dict(item, label=f"images[{index}]")
        for index, item in enumerate(images)
    )
    source = payload.get("source")
    if not isinstance(source, dict):
        raise ReviewManifestError("Review manifest 'source' must be an object.")
    generated_at = payload.get("generated_at_utc")
    if not isinstance(generated_at, str) or not generated_at.strip():
        raise ReviewManifestError("Review manifest 'generated_at_utc' must be a non-empty string.")
    return ReviewManifest(generated_at, source, parsed_images)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
