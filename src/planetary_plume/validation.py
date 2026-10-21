"""Annotation/image matching, geometry checks, and manual-overlay helpers."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from PIL import Image, ImageDraw

from planetary_plume.acquisition import AcquisitionEntry, sha256_file
from planetary_plume.angle_convention import (
    angle_to_image_point,
    image_point_to_angle,
    interval_polygon,
)
from planetary_plume.annotations import AnnotationRecord
from planetary_plume.image_readers import ImageInfo, ImageReadError, load_image, normalize_for_display


class ValidationError(RuntimeError):
    """Raised when validation cannot proceed safely."""


class GeometryError(ValidationError):
    """Raised when limb geometry or annotation coordinates are unusable."""


@dataclass(frozen=True)
class CircleFit:
    center_x: float
    center_y: float
    radius: float
    rms_residual: float

    def to_dict(self) -> dict[str, float]:
        return {
            "center_x": self.center_x,
            "center_y": self.center_y,
            "radius": self.radius,
            "rms_residual": self.rms_residual,
        }


@dataclass(frozen=True)
class ValidationIssue:
    kind: str
    annotation_relative_path: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "annotation_relative_path": self.annotation_relative_path,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ValidatedImage:
    record: AnnotationRecord
    entry: AcquisitionEntry
    image: ImageInfo
    circle: CircleFit

    def to_dict(self) -> dict[str, Any]:
        return {
            "annotation_relative_path": self.record.annotation_relative_path,
            "product_family": self.record.product_family,
            "plume_status": self.record.plume_status,
            "plume_interval_count": self.record.plume_interval_count,
            "limb_point_count": self.record.limb_point_count,
            "annotator": self.record.annotator,
            "image": self.image.to_dict(),
            "circle": self.circle.to_dict(),
            "resolved_product_id": self.entry.resolved_product_id,
            "image_sha256": self.entry.image_sha256,
        }


@dataclass(frozen=True)
class OverlayReview:
    annotation_relative_path: str
    status: str
    notes: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "annotation_relative_path": self.annotation_relative_path,
            "status": self.status,
            "notes": self.notes,
        }


@dataclass
class ValidationResult:
    records_checked: int = 0
    products_mapped: int = 0
    images_downloaded: int = 0
    images_validated: int = 0
    subset_positive: int = 0
    subset_negative: int = 0
    issues: list[ValidationIssue] = field(default_factory=list)
    validated: list[ValidatedImage] = field(default_factory=list)
    overlay_reviews: list[OverlayReview] = field(default_factory=list)

    def add_issue(self, kind: str, annotation_relative_path: str, detail: str) -> None:
        self.issues.append(ValidationIssue(kind, annotation_relative_path, detail))

    def summary(self) -> dict[str, Any]:
        issue_counts: dict[str, int] = {}
        for issue in self.issues:
            issue_counts[issue.kind] = issue_counts.get(issue.kind, 0) + 1
        review_counts: dict[str, int] = {}
        for review in self.overlay_reviews:
            review_counts[review.status] = review_counts.get(review.status, 0) + 1
        return {
            "records_checked": self.records_checked,
            "products_mapped": self.products_mapped,
            "images_downloaded": self.images_downloaded,
            "images_validated": self.images_validated,
            "subset_positive": self.subset_positive,
            "subset_negative": self.subset_negative,
            "issue_counts": dict(sorted(issue_counts.items())),
            "overlay_review_counts": dict(sorted(review_counts.items())),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary(),
            "issues": [issue.to_dict() for issue in self.issues],
            "images": [item.to_dict() for item in self.validated],
            "overlay_reviews": [review.to_dict() for review in self.overlay_reviews],
        }


def fit_circle(points: Iterable[tuple[float, float]]) -> CircleFit:
    """Algebraic least-squares circle fit to limb points."""

    array = np.asarray(list(points), dtype=float)
    if array.ndim != 2 or array.shape[1] != 2 or array.shape[0] < 3:
        raise GeometryError("At least three two-dimensional limb points are required.")
    if not np.isfinite(array).all():
        raise GeometryError("Limb points must be finite.")

    x = array[:, 0]
    y = array[:, 1]
    design = np.column_stack([x, y, np.ones(len(x))])
    rhs = -(x * x + y * y)
    solution, residuals, rank, _singular = np.linalg.lstsq(design, rhs, rcond=None)
    if rank < 3:
        raise GeometryError("Limb points are collinear; circle fit is unstable.")
    d, e, f = solution
    center_x = -d / 2.0
    center_y = -e / 2.0
    radius_squared = center_x * center_x + center_y * center_y - f
    if radius_squared <= 0 or not np.isfinite(radius_squared):
        raise GeometryError("Circle fit produced an invalid radius.")
    radius = math.sqrt(radius_squared)
    distances = np.hypot(x - center_x, y - center_y)
    rms = float(np.sqrt(np.mean((distances - radius) ** 2)))
    return CircleFit(center_x, center_y, radius, rms)


def angle_up_clockwise(center: tuple[float, float], point: tuple[float, float]) -> float:
    """Compatibility wrapper around the explicit angle-convention module."""

    return image_point_to_angle(point, center)


def point_on_circle(
    center: tuple[float, float], radius: float, angle: float
) -> tuple[float, float]:
    """Compatibility wrapper around the explicit angle-convention module."""

    point = angle_to_image_point(center, radius, angle)
    return point.x, point.y


def sector_polygon(
    center: tuple[float, float],
    radius: float,
    start: float,
    end: float,
    *,
    outer_factor: float = 1.6,
    steps: int = 48,
) -> list[tuple[float, float]]:
    """Compatibility wrapper around the explicit angle-convention module."""

    try:
        return interval_polygon(
            center,
            radius,
            radius * outer_factor,
            start,
            end,
            steps=steps,
        )
    except ValueError as exc:
        raise GeometryError(str(exc)) from exc


def _check_points_inside_image(record: AnnotationRecord, image: ImageInfo) -> None:
    for index, (x, y) in enumerate(record.limb_points):
        if not (0 <= x < image.width and 0 <= y < image.height):
            raise GeometryError(
                f"Limb point {index} ({x}, {y}) lies outside "
                f"{image.width}x{image.height} image {image.path}."
            )


def render_overlay(
    image: ImageInfo,
    record: AnnotationRecord,
    output_path: str | Path,
    *,
    convention: str = "up_clockwise",
    status: str = "UNVERIFIED - inspect before scientific use",
) -> Path:
    """Render limb points, fitted circle, and plume sectors for manual review."""

    if convention != "up_clockwise":
        raise ValidationError(f"Unsupported convention: {convention}")
    _check_points_inside_image(record, image)
    circle = fit_circle(record.limb_points)

    display = normalize_for_display(image.array)
    base = Image.fromarray(display, mode="L").convert("RGB")
    draw = ImageDraw.Draw(base)

    draw.ellipse(
        [
            circle.center_x - circle.radius,
            circle.center_y - circle.radius,
            circle.center_x + circle.radius,
            circle.center_y + circle.radius,
        ],
        outline=(255, 60, 60),
        width=2,
    )
    for x, y in record.limb_points:
        draw.ellipse([x - 3, y - 3, x + 3, y + 3], fill=(255, 60, 60))

    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    sector_draw = ImageDraw.Draw(overlay)
    for start, end in record.plume_intervals:
        polygon = sector_polygon(
            (circle.center_x, circle.center_y),
            circle.radius,
            start,
            end,
        )
        sector_draw.polygon(polygon, fill=(0, 170, 255, 55), outline=(0, 170, 255, 220))
        for angle in (start, end):
            inner = point_on_circle((circle.center_x, circle.center_y), circle.radius, angle)
            outer = point_on_circle(
                (circle.center_x, circle.center_y),
                circle.radius * 1.6,
                angle,
            )
            sector_draw.line([inner, outer], fill=(0, 170, 255, 255), width=2)
    base = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(base)

    banner = (
        f"{record.annotation_relative_path} | {record.target_body or '?'} / "
        f"{record.instrument or '?'} | 0 rad = up, clockwise | {status}"
    )
    text_width = min(base.width, 1200)
    draw.rectangle([0, 0, text_width, 34], fill=(0, 0, 0))
    draw.text((6, 8), banner, fill=(255, 255, 255))
    draw.text(
        (6, base.height - 20),
        f"circle r={circle.radius:.1f}px, rms={circle.rms_residual:.2f}px",
        fill=(255, 255, 255),
    )

    destination = Path(output_path).expanduser().resolve(strict=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    base.save(destination)
    return destination


def validate_acquisition(
    records: Iterable[AnnotationRecord],
    entries: Iterable[AcquisitionEntry],
    *,
    subset_paths: set[str] | None = None,
) -> ValidationResult:
    """Match records to downloaded images and check integrity/dimensions."""

    record_list = [
        record for record in records
        if subset_paths is None or record.annotation_relative_path in subset_paths
    ]
    entry_list = list(entries)
    entries_by_path: dict[str, list[AcquisitionEntry]] = {}
    for entry in entry_list:
        entries_by_path.setdefault(entry.annotation_relative_path, []).append(entry)

    result = ValidationResult(records_checked=len(record_list))
    result.subset_positive = sum(record.plume_status for record in record_list)
    result.subset_negative = len(record_list) - result.subset_positive

    seen_hashes: dict[str, str] = {}
    seen_products: dict[str, str] = {}
    for record in record_list:
        path = record.annotation_relative_path
        matches = entries_by_path.get(path, [])
        if not matches:
            result.add_issue("missing_entry", path, "No acquisition entry for annotation.")
            continue
        if len(matches) > 1:
            result.add_issue(
                "duplicate_entry",
                path,
                f"{len(matches)} acquisition entries refer to this annotation.",
            )
            continue
        entry = matches[0]
        if entry.annotation_sha256 != record.annotation_sha256:
            result.add_issue(
                "annotation_changed",
                path,
                "Annotation SHA256 no longer matches the manifest record.",
            )
        if entry.mapping_status != "resolved":
            result.add_issue(
                "mapping_not_resolved",
                path,
                f"Mapping status is {entry.mapping_status!r}: {entry.error or ''}",
            )
            continue
        result.products_mapped += 1
        if entry.download_status in {"downloaded", "resumed", "skipped_existing"}:
            result.images_downloaded += 1
        else:
            result.add_issue(
                "download_failed",
                path,
                entry.error or f"download status {entry.download_status!r}",
            )
            continue
        if not entry.image_path:
            result.add_issue("missing_image_path", path, "Acquisition entry has no image path.")
            continue
        image_path = Path(entry.image_path)
        if not image_path.is_file():
            result.add_issue("missing_image_file", path, f"Image not found: {image_path}")
            continue
        actual_size = image_path.stat().st_size
        if entry.image_size_bytes is not None and actual_size != entry.image_size_bytes:
            result.add_issue(
                "image_size_mismatch",
                path,
                f"Recorded {entry.image_size_bytes} bytes; found {actual_size}.",
            )
        if entry.image_sha256:
            actual_sha = sha256_file(image_path)
            if actual_sha != entry.image_sha256:
                result.add_issue(
                    "image_checksum_mismatch",
                    path,
                    "Image SHA256 no longer matches the acquisition log.",
                )
        if entry.label_url:
            if entry.label_download_status not in {"downloaded", "resumed", "skipped_existing"}:
                result.add_issue(
                    "label_download_failed",
                    path,
                    f"Label download status is {entry.label_download_status!r}.",
                )
            elif entry.label_path and not Path(entry.label_path).is_file():
                result.add_issue(
                    "missing_label_file",
                    path,
                    f"Label not found: {entry.label_path}",
                )
        try:
            image = load_image(image_path, entry.label_path)
        except (ImageReadError, OSError, ValueError) as exc:
            result.add_issue("unreadable_image", path, f"{type(exc).__name__}: {exc}")
            continue
        try:
            _check_points_inside_image(record, image)
            circle = fit_circle(record.limb_points)
        except GeometryError as exc:
            result.add_issue("geometry_error", path, str(exc))
            continue

        if entry.image_sha256:
            seen_hashes.setdefault(entry.image_sha256, path)
            if seen_hashes[entry.image_sha256] != path:
                result.add_issue(
                    "duplicate_image",
                    path,
                    f"Same image SHA256 used by {seen_hashes[entry.image_sha256]}.",
                )
        if entry.resolved_product_id:
            seen_products.setdefault(entry.resolved_product_id, path)
            if seen_products[entry.resolved_product_id] != path:
                result.add_issue(
                    "duplicate_product",
                    path,
                    f"Same product ID used by {seen_products[entry.resolved_product_id]}.",
                )

        result.images_validated += 1
        result.validated.append(ValidatedImage(record, entry, image, circle))

    return result


def load_overlay_reviews(path: str | Path) -> list[OverlayReview]:
    source = Path(path).expanduser().resolve(strict=False)
    if not source.is_file():
        raise ValidationError(f"Overlay review file not found: {source}")
    payload = json.loads(source.read_text(encoding="utf-8"))
    reviews = payload.get("reviews", [])
    if not isinstance(reviews, list):
        raise ValidationError("Overlay review file must contain a 'reviews' list.")
    parsed: list[OverlayReview] = []
    for index, item in enumerate(reviews):
        if not isinstance(item, dict):
            raise ValidationError(f"reviews[{index}] must be an object.")
        path_value = item.get("annotation_relative_path")
        status = item.get("status")
        if not isinstance(path_value, str) or not isinstance(status, str):
            raise ValidationError(
                f"reviews[{index}] requires string annotation_relative_path and status."
            )
        if status not in {"aligned", "ambiguous", "misaligned", "not_inspected"}:
            raise ValidationError(f"reviews[{index}] has unknown status {status!r}.")
        parsed.append(OverlayReview(path_value, status, str(item.get("notes", ""))))
    return parsed


def format_validation_report(result: ValidationResult) -> str:
    summary = result.summary()
    lines = [
        "Dataset validation report",
        "========================",
        f"Annotations checked: {summary['records_checked']}",
        f"Products mapped: {summary['products_mapped']}",
        f"Images downloaded: {summary['images_downloaded']}",
        f"Images validated: {summary['images_validated']}",
        f"Subset labels: {summary['subset_positive']} positive, "
        f"{summary['subset_negative']} negative",
        "",
        "Issues:",
    ]
    if result.issues:
        for issue in result.issues:
            lines.append(
                f"  [{issue.kind}] {issue.annotation_relative_path}: {issue.detail}"
            )
    else:
        lines.append("  (none)")
    lines.extend(["", "Overlay review:"])
    if result.overlay_reviews:
        for review in result.overlay_reviews:
            lines.append(
                f"  [{review.status}] {review.annotation_relative_path}: {review.notes}"
            )
    else:
        lines.append("  (not reviewed; do not claim visual alignment)")
    lines.extend(
        [
            "",
            "Visual alignment is a manual judgment. It is not established by this",
            "text report alone, and it does not establish physical plume truth.",
        ]
    )
    return "\n".join(lines)


def write_validation_report(result: ValidationResult, path: str | Path) -> Path:
    destination = Path(path).expanduser().resolve(strict=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(
        json.dumps(result.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)
    return destination
