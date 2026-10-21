"""Separate comparison of independent annotations with released labels.

This module is intentionally not imported by the GUI.  It is run only after the
reviewer has saved independent annotations.  Matching uses verified ``image_id``
values from the acquisition pipeline, never filename similarity.

An agreement is an annotation-similarity result.  It is not evidence that a
feature is a confirmed physical plume.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from planetary_plume.angle_intervals import (
    AngularInterval,
    format_interval_deg,
    minimum_distance_rad,
    overlap_width_rad,
)
from planetary_plume.annotation_store import (
    ImageReview,
    ReviewSession,
    file_sha256,
)
from planetary_plume.annotations import (
    FAMILY_SPECS,
    AnnotationError,
    parse_annotation_text,
)
from planetary_plume.review_manifest import ReviewImage, ReviewManifest

COMPARISON_FORMAT = "planetary-plume-independent-comparison"
COMPARISON_FORMAT_VERSION = 1
DISCLAIMER = (
    "Agreement between an independent annotation and a released label is a "
    "statement about annotation similarity only. It does not prove that a "
    "feature is a physical plume, and neither annotation set is validated "
    "physical truth."
)

STATUS_AGREEMENT = "AGREEMENT"
STATUS_DISAGREEMENT = "DISAGREEMENT"
STATUS_INCONCLUSIVE = "INCONCLUSIVE"
STATUS_MISSING_MAPPING = "MISSING_MAPPING"
STATUS_AMBIGUOUS_MAPPING = "AMBIGUOUS_MAPPING"
STATUS_MISSING_RELEASED_ANNOTATION = "MISSING_RELEASED_ANNOTATION"
STATUS_STALE_RELEASED_ANNOTATION = "STALE_RELEASED_ANNOTATION"
STATUS_INVALID_RELEASED_ANNOTATION = "INVALID_RELEASED_ANNOTATION"
STATUS_MISSING_REVIEW_MANIFEST_IMAGE = "MISSING_REVIEW_MANIFEST_IMAGE"

STATUSES = (
    STATUS_AGREEMENT,
    STATUS_DISAGREEMENT,
    STATUS_INCONCLUSIVE,
    STATUS_MISSING_MAPPING,
    STATUS_AMBIGUOUS_MAPPING,
    STATUS_MISSING_RELEASED_ANNOTATION,
    STATUS_STALE_RELEASED_ANNOTATION,
    STATUS_INVALID_RELEASED_ANNOTATION,
    STATUS_MISSING_REVIEW_MANIFEST_IMAGE,
)

POSITIVE_CLASSIFICATIONS = ("PLAUSIBLE", "UNCERTAIN")
_EXACT_EPSILON_RAD = 1e-9


class ComparisonError(RuntimeError):
    """Raised when comparison inputs or outputs cannot be used safely."""


class ReleasedAnnotationMissing(ComparisonError):
    """The released annotation file is absent."""


class ReleasedAnnotationStale(ComparisonError):
    """The released annotation no longer matches its verified checksum."""


class ReleasedAnnotationInvalid(ComparisonError):
    """The released annotation cannot be parsed safely."""


@dataclass(frozen=True)
class LabelMapEntry:
    image_id: str
    annotation_relative_path: str
    annotation_sha256: str
    annotation_filename: str
    release_directory: str
    product_family: str

    def to_dict(self) -> dict[str, str]:
        return {
            "image_id": self.image_id,
            "annotation_relative_path": self.annotation_relative_path,
            "annotation_sha256": self.annotation_sha256,
            "annotation_filename": self.annotation_filename,
            "release_directory": self.release_directory,
            "product_family": self.product_family,
        }


@dataclass(frozen=True)
class LabelMap:
    path: Path
    entries_by_image: dict[str, tuple[LabelMapEntry, ...]]
    problems: tuple[str, ...]
    ambiguous_image_ids: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ReleasedAnnotation:
    image_id: str
    annotation_relative_path: str
    annotation_sha256: str
    plume_status: bool
    intervals: tuple[AngularInterval, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class CandidateComparison:
    candidate_id: str
    classification: str
    confidence: str
    kind: str
    start_deg: float
    end_deg: float
    width_deg: float
    crosses_zero: bool
    notes: str
    best_overlap_deg: float | None
    nearest_distance_deg: float | None
    nearest_release_interval_deg: tuple[float, float] | None
    exact_match: bool
    matched_release_indices: tuple[int, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "classification": self.classification,
            "confidence": self.confidence,
            "kind": self.kind,
            "start_deg": _round(self.start_deg),
            "end_deg": _round(self.end_deg),
            "width_deg": _round(self.width_deg),
            "crosses_zero": self.crosses_zero,
            "notes": self.notes,
            "best_overlap_deg": _round_or_none(self.best_overlap_deg),
            "nearest_distance_deg": _round_or_none(self.nearest_distance_deg),
            "nearest_release_interval_deg": (
                None
                if self.nearest_release_interval_deg is None
                else [_round(self.nearest_release_interval_deg[0]), _round(self.nearest_release_interval_deg[1])]
            ),
            "exact_match": self.exact_match,
            "matched_release_indices": list(self.matched_release_indices),
        }


@dataclass(frozen=True)
class ImageComparison:
    image_id: str
    annotation_relative_path: str | None
    status: str
    comparison_kind: str
    reasons: tuple[str, ...]
    review_complete: bool
    image_flags: tuple[str, ...]
    no_candidate_identified: bool
    reviewed_positive: bool
    released_positive: bool | None
    released_intervals_deg: tuple[tuple[float, float], ...]
    candidates: tuple[CandidateComparison, ...]
    max_overlap_deg: float | None
    min_distance_deg: float | None
    released_intervals_total: int
    released_intervals_matched: int
    reviewed_candidates_total: int
    reviewed_candidates_matched: int
    partial_coverage: bool
    review_notes: str
    released_annotation_sha256: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "image_id": self.image_id,
            "annotation_relative_path": self.annotation_relative_path,
            "status": self.status,
            "comparison_kind": self.comparison_kind,
            "reasons": list(self.reasons),
            "review": {
                "is_complete": self.review_complete,
                "image_flags": list(self.image_flags),
                "no_candidate_identified": self.no_candidate_identified,
                "reviewed_positive": self.reviewed_positive,
                "notes": self.review_notes,
            },
            "released": {
                "plume_status": self.released_positive,
                "intervals_deg": [
                    [_round(start), _round(end)] for start, end in self.released_intervals_deg
                ],
                "annotation_sha256": self.released_annotation_sha256,
            },
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "metrics": {
                "max_overlap_deg": _round_or_none(self.max_overlap_deg),
                "min_distance_deg": _round_or_none(self.min_distance_deg),
                "released_intervals_total": self.released_intervals_total,
                "released_intervals_matched": self.released_intervals_matched,
                "reviewed_candidates_total": self.reviewed_candidates_total,
                "reviewed_candidates_matched": self.reviewed_candidates_matched,
                "partial_coverage": self.partial_coverage,
            },
        }


@dataclass(frozen=True)
class ComparisonReport:
    generated_at_utc: str
    session_path: Path
    session_sha256: str
    review_manifest_path: Path
    review_manifest_sha256: str
    label_map_path: Path
    label_map_sha256: str
    annotation_root: Path
    tolerance_deg: float
    complete_only: bool
    excluded_incomplete: int
    images: tuple[ImageComparison, ...]
    unreviewed_image_ids: tuple[str, ...]
    problems: tuple[str, ...]

    def summary(self) -> dict[str, Any]:
        counts = {status: 0 for status in STATUSES}
        for image in self.images:
            counts[image.status] = counts.get(image.status, 0) + 1
        return {
            "total_compared": len(self.images),
            "excluded_incomplete": self.excluded_incomplete,
            "agreement": counts[STATUS_AGREEMENT],
            "disagreement": counts[STATUS_DISAGREEMENT],
            "inconclusive": counts[STATUS_INCONCLUSIVE],
            "missing_mapping": counts[STATUS_MISSING_MAPPING],
            "ambiguous_mapping": counts[STATUS_AMBIGUOUS_MAPPING],
            "missing_released_annotation": counts[STATUS_MISSING_RELEASED_ANNOTATION],
            "stale_released_annotation": counts[STATUS_STALE_RELEASED_ANNOTATION],
            "invalid_released_annotation": counts[STATUS_INVALID_RELEASED_ANNOTATION],
            "missing_review_manifest_image": counts[STATUS_MISSING_REVIEW_MANIFEST_IMAGE],
            "reviewed_positive": sum(1 for image in self.images if image.reviewed_positive),
            "released_positive": sum(1 for image in self.images if image.released_positive),
            "both_positive": sum(
                1
                for image in self.images
                if image.reviewed_positive and image.released_positive
            ),
            "partial_coverage": sum(1 for image in self.images if image.partial_coverage),
            "unreviewed_images": len(self.unreviewed_image_ids),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": COMPARISON_FORMAT,
            "format_version": COMPARISON_FORMAT_VERSION,
            "generated_at_utc": self.generated_at_utc,
            "disclaimer": DISCLAIMER,
            "parameters": {
                "tolerance_deg": self.tolerance_deg,
                "complete_only": self.complete_only,
            },
            "inputs": {
                "session": {
                    "path": str(self.session_path),
                    "sha256": self.session_sha256,
                },
                "review_manifest": {
                    "path": str(self.review_manifest_path),
                    "sha256": self.review_manifest_sha256,
                },
                "release_label_map": {
                    "path": str(self.label_map_path),
                    "sha256": self.label_map_sha256,
                },
                "annotation_root": str(self.annotation_root),
            },
            "summary": self.summary(),
            "images": [image.to_dict() for image in self.images],
            "unreviewed_image_ids": list(self.unreviewed_image_ids),
            "problems": list(self.problems),
        }


def _round(value: float, digits: int = 3) -> float:
    return round(float(value), digits)


def _round_or_none(value: float | None) -> float | None:
    return None if value is None else _round(value)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def load_label_map(path: str | Path) -> LabelMap:
    """Load the comparison-only verified image-ID mapping."""

    source = Path(path).expanduser().resolve(strict=False)
    if not source.is_file():
        raise ComparisonError(f"Release label map not found: {source}")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ComparisonError(f"Could not read release label map {source}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ComparisonError("Release label map root must be an object.")
    if payload.get("format") != "planetary-plume-release-label-map":
        raise ComparisonError(
            f"Unsupported release label map format: {payload.get('format')!r}."
        )
    if payload.get("format_version") != 1:
        raise ComparisonError(
            f"Unsupported release label map version: {payload.get('format_version')!r}."
        )
    mappings = payload.get("mappings")
    if not isinstance(mappings, list) or not mappings:
        raise ComparisonError("Release label map contains no mappings.")

    entries: dict[str, list[LabelMapEntry]] = {}
    problems: list[str] = []
    for index, item in enumerate(mappings):
        if not isinstance(item, dict):
            problems.append(f"mappings[{index}] is not an object.")
            continue
        required = ("image_id", "annotation_relative_path", "annotation_sha256")
        missing = [key for key in required if not item.get(key)]
        if missing:
            problems.append(f"mappings[{index}] missing fields: {', '.join(missing)}")
            continue
        relative = str(item["annotation_relative_path"])
        if Path(relative).is_absolute() or ".." in Path(relative).parts:
            problems.append(
                f"mappings[{index}] has an unsafe annotation path: {relative!r}."
            )
            continue
        entry = LabelMapEntry(
            image_id=str(item["image_id"]),
            annotation_relative_path=relative,
            annotation_sha256=str(item["annotation_sha256"]),
            annotation_filename=str(item.get("annotation_filename") or Path(relative).name),
            release_directory=str(item.get("release_directory") or Path(relative).parent.name),
            product_family=str(item.get("product_family") or ""),
        )
        entries.setdefault(entry.image_id, []).append(entry)
    path_to_images: dict[str, set[str]] = {}
    for entry in (item for values in entries.values() for item in values):
        path_to_images.setdefault(entry.annotation_relative_path, set()).add(entry.image_id)
    ambiguous_image_ids: set[str] = set()
    for relative, image_ids in sorted(path_to_images.items()):
        if len(image_ids) > 1:
            ambiguous_image_ids.update(image_ids)
            problems.append(
                f"Released annotation path {relative!r} maps to multiple image IDs: "
                + ", ".join(sorted(image_ids))
            )
    return LabelMap(
        path=source,
        entries_by_image={key: tuple(value) for key, value in entries.items()},
        problems=tuple(problems),
        ambiguous_image_ids=frozenset(ambiguous_image_ids),
    )


def _load_released_annotation(
    entry: LabelMapEntry,
    annotation_root: Path,
) -> ReleasedAnnotation:
    root = annotation_root.expanduser().resolve(strict=False)
    path = (root / entry.annotation_relative_path).resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ComparisonError(
            f"Released annotation path escapes the annotation root: {entry.annotation_relative_path}"
        ) from exc
    if not path.is_file():
        raise ReleasedAnnotationMissing(f"Released annotation not found: {path}")
    actual_sha = file_sha256(path)
    if actual_sha != entry.annotation_sha256:
        raise ReleasedAnnotationStale(
            f"Released annotation SHA256 does not match the verified mapping: {path}"
        )
    try:
        text = path.read_text(encoding="utf-8")
        record = parse_annotation_text(
            text,
            source=path,
            root=root,
            family=FAMILY_SPECS.get(path.parent.name),
            galileo_map=None,
            allow_wrapping_intervals=True,
        )
    except (OSError, UnicodeError, AnnotationError) as exc:
        raise ReleasedAnnotationInvalid(
            f"Could not parse released annotation {path}: {exc}"
        ) from exc
    if record.annotation_sha256 != entry.annotation_sha256:
        raise ReleasedAnnotationStale(f"Released annotation changed while reading: {path}")
    intervals = tuple(
        AngularInterval.from_radians(start, end) for start, end in record.plume_intervals
    )
    return ReleasedAnnotation(
        image_id=entry.image_id,
        annotation_relative_path=entry.annotation_relative_path,
        annotation_sha256=entry.annotation_sha256,
        plume_status=record.plume_status,
        intervals=intervals,
        warnings=record.warnings,
    )


def _candidate_comparisons(
    review: ImageReview,
    released: ReleasedAnnotation,
) -> tuple[tuple[CandidateComparison, ...], float | None, float | None, int, int, int, bool]:
    positive = [
        candidate
        for candidate in review.candidates
        if candidate.classification in POSITIVE_CLASSIFICATIONS and candidate.geometry is not None
    ]
    comparisons: list[CandidateComparison] = []
    matched_release: set[int] = set()
    matched_candidates = 0
    best_overlaps: list[float] = []
    best_distances: list[float] = []

    for candidate in positive:
        assert candidate.geometry is not None
        interval = candidate.geometry.interval
        overlaps = [
            overlap_width_rad(interval, released_interval)
            for released_interval in released.intervals
        ]
        distances = [
            minimum_distance_rad(interval, released_interval)
            for released_interval in released.intervals
        ]
        matched_indices = tuple(
            index
            for index, (overlap, distance) in enumerate(zip(overlaps, distances))
            if overlap > 0 or distance <= _EXACT_EPSILON_RAD
        )
        if matched_indices:
            matched_candidates += 1
            matched_release.update(matched_indices)

        if released.intervals:
            best_overlap = max(overlaps) if overlaps else 0.0
            if overlaps:
                best_distance = min(distances)
                best_distance_index = min(range(len(distances)), key=lambda index: distances[index])
            else:
                best_distance = None
                best_distance_index = None
            nearest_interval = (
                (
                    released.intervals[best_distance_index].start_deg,
                    released.intervals[best_distance_index].end_deg,
                )
                if best_distance_index is not None
                else None
            )
            best_overlaps.append(best_overlap)
            if best_distance is not None:
                best_distances.append(best_distance)
        else:
            best_overlap = None
            best_distance = None
            nearest_interval = None

        comparisons.append(
            CandidateComparison(
                candidate_id=candidate.candidate_id,
                classification=candidate.classification,
                confidence=candidate.confidence,
                kind=candidate.geometry.kind,
                start_deg=candidate.geometry.start_deg,
                end_deg=candidate.geometry.end_deg,
                width_deg=candidate.geometry.width_deg,
                crosses_zero=candidate.geometry.crosses_zero,
                notes=candidate.notes,
                best_overlap_deg=(
                    None if best_overlap is None else math.degrees(best_overlap)
                ),
                nearest_distance_deg=(
                    None if best_distance is None else math.degrees(best_distance)
                ),
                nearest_release_interval_deg=nearest_interval,
                exact_match=bool(matched_indices),
                matched_release_indices=matched_indices,
            )
        )

    max_overlap = max(best_overlaps) if best_overlaps else None
    min_distance = min(best_distances) if best_distances else None
    partial = (
        bool(positive)
        and bool(released.intervals)
        and (len(matched_release) < len(released.intervals) or matched_candidates < len(positive))
    )
    return (
        tuple(comparisons),
        max_overlap,
        min_distance,
        len(released.intervals),
        len(matched_release),
        len(positive),
        partial,
    )


def compare_image(
    review: ImageReview,
    manifest_image: ReviewImage | None,
    released: ReleasedAnnotation | None,
    *,
    tolerance_deg: float,
) -> ImageComparison:
    """Compare one saved independent review with one released annotation."""

    if not math.isfinite(tolerance_deg) or tolerance_deg < 0:
        raise ComparisonError("tolerance_deg must be finite and non-negative.")
    if manifest_image is None:
        return ImageComparison(
            image_id=review.image_id,
            annotation_relative_path=None,
            status=STATUS_MISSING_REVIEW_MANIFEST_IMAGE,
            comparison_kind="MISSING_REVIEW_MANIFEST_IMAGE",
            reasons=("Image ID is not present in the review manifest.",),
            review_complete=review.is_complete,
            image_flags=review.image_flags,
            no_candidate_identified=review.no_candidate_identified,
            reviewed_positive=any(
                candidate.classification in POSITIVE_CLASSIFICATIONS
                for candidate in review.candidates
            ),
            released_positive=None,
            released_intervals_deg=(),
            candidates=(),
            max_overlap_deg=None,
            min_distance_deg=None,
            released_intervals_total=0,
            released_intervals_matched=0,
            reviewed_candidates_total=0,
            reviewed_candidates_matched=0,
            partial_coverage=False,
            review_notes=review.notes,
            released_annotation_sha256=None,
        )

    reasons: list[str] = []
    if not review.is_complete:
        reasons.append("Independent review is not marked complete.")
    if review.image_flags:
        reasons.append("Image is flagged: " + ", ".join(review.image_flags) + ".")
    if review.source_product_sha256 != manifest_image.image_sha256:
        reasons.append("Independent review refers to a different source image SHA256.")
    if released is None:
        return ImageComparison(
            image_id=review.image_id,
            annotation_relative_path=None,
            status=STATUS_MISSING_MAPPING,
            comparison_kind="MISSING_MAPPING",
            reasons=tuple(reasons + ["No verified released-label mapping for this image_id."]),
            review_complete=review.is_complete,
            image_flags=review.image_flags,
            no_candidate_identified=review.no_candidate_identified,
            reviewed_positive=any(
                candidate.classification in POSITIVE_CLASSIFICATIONS
                for candidate in review.candidates
            ),
            released_positive=None,
            released_intervals_deg=(),
            candidates=(),
            max_overlap_deg=None,
            min_distance_deg=None,
            released_intervals_total=0,
            released_intervals_matched=0,
            reviewed_candidates_total=0,
            reviewed_candidates_matched=0,
            partial_coverage=False,
            review_notes=review.notes,
            released_annotation_sha256=None,
        )

    positive_candidates = [
        candidate
        for candidate in review.candidates
        if candidate.classification in POSITIVE_CLASSIFICATIONS
    ]
    negative_statement = review.no_candidate_identified or any(
        candidate.classification == "NO_CANDIDATE_IDENTIFIED"
        for candidate in review.candidates
    )
    (
        candidates,
        max_overlap,
        min_distance,
        released_total,
        released_matched,
        reviewed_total,
        partial,
    ) = _candidate_comparisons(review, released)

    released_intervals_deg = tuple(
        (interval.start_deg, interval.end_deg) for interval in released.intervals
    )

    status = STATUS_INCONCLUSIVE
    kind = "REVIEW_INCOMPLETE"
    if review.source_product_sha256 != manifest_image.image_sha256:
        status = STATUS_INCONCLUSIVE
        kind = "SOURCE_IMAGE_CHANGED"
    elif not review.is_complete:
        status = STATUS_INCONCLUSIVE
        kind = "REVIEW_INCOMPLETE"
    elif review.image_flags:
        status = STATUS_INCONCLUSIVE
        kind = "IMAGE_FLAGGED"
    elif positive_candidates and negative_statement:
        status = STATUS_INCONCLUSIVE
        kind = "CONTRADICTORY_REVIEW"
    elif not positive_candidates and not negative_statement:
        status = STATUS_INCONCLUSIVE
        kind = "NO_ASSESSMENT"
    elif released.plume_status and not released.intervals:
        status = STATUS_INCONCLUSIVE
        kind = "RELEASED_POSITIVE_WITHOUT_INTERVALS"
    elif (not released.plume_status) and released.intervals:
        status = STATUS_INCONCLUSIVE
        kind = "RELEASED_NEGATIVE_WITH_INTERVALS"
    elif not positive_candidates and not released.plume_status:
        status = STATUS_AGREEMENT
        kind = "BOTH_NEGATIVE"
    elif not positive_candidates and released.plume_status:
        status = STATUS_DISAGREEMENT
        kind = "MISSED_RELEASED_POSITIVE"
    elif positive_candidates and not released.plume_status:
        status = STATUS_DISAGREEMENT
        kind = "CANDIDATE_WITHOUT_RELEASED_POSITIVE"
    else:
        all_released_matched = released_matched == released_total
        all_candidates_matched = reviewed_total > 0 and all(
            candidate.exact_match for candidate in candidates
        )
        if all_released_matched and all_candidates_matched:
            status = STATUS_AGREEMENT
            kind = "POSITIVE_OVERLAP"
        elif max_overlap is not None and max_overlap > 0:
            status = STATUS_INCONCLUSIVE
            kind = "PARTIAL_OVERLAP"
            reasons.append(
                "At least one sector overlaps, but coverage is partial."
            )
        elif min_distance is not None and math.degrees(min_distance) <= tolerance_deg:
            status = STATUS_INCONCLUSIVE
            kind = "POSITIVE_NEAR_MISS"
            reasons.append(
                f"No overlap; nearest sector is within the {tolerance_deg:g}° reporting tolerance."
            )
        else:
            status = STATUS_DISAGREEMENT
            kind = "POSITIVE_NO_OVERLAP"
            reasons.append("No reviewed candidate overlaps or lies near a released sector.")

    if positive_candidates and not released.plume_status:
        reasons.append("The reviewer marked at least one candidate; the released label has none.")
    if (not positive_candidates) and released.plume_status:
        reasons.append("The reviewer marked no candidate; the released label has a sector.")

    return ImageComparison(
        image_id=review.image_id,
        annotation_relative_path=released.annotation_relative_path,
        status=status,
        comparison_kind=kind,
        reasons=tuple(reasons),
        review_complete=review.is_complete,
        image_flags=review.image_flags,
        no_candidate_identified=review.no_candidate_identified,
        reviewed_positive=bool(positive_candidates),
        released_positive=released.plume_status,
        released_intervals_deg=released_intervals_deg,
        candidates=candidates,
        max_overlap_deg=None if max_overlap is None else math.degrees(max_overlap),
        min_distance_deg=None if min_distance is None else math.degrees(min_distance),
        released_intervals_total=released_total,
        released_intervals_matched=released_matched,
        reviewed_candidates_total=reviewed_total,
        reviewed_candidates_matched=sum(1 for candidate in candidates if candidate.exact_match),
        partial_coverage=partial,
        review_notes=review.notes,
        released_annotation_sha256=released.annotation_sha256,
    )


def compare_session(
    session: ReviewSession,
    manifest: ReviewManifest,
    label_map: LabelMap,
    annotation_root: str | Path,
    *,
    tolerance_deg: float = 10.0,
    complete_only: bool = False,
    generated_at_utc: str | None = None,
    session_path: str | Path | None = None,
    session_sha256: str | None = None,
    review_manifest_path: str | Path | None = None,
    review_manifest_sha256: str | None = None,
) -> ComparisonReport:
    """Compare every saved review, or only complete reviews, against released labels."""

    if not session.reviews:
        raise ComparisonError("The independent annotation session contains no image reviews.")
    if not math.isfinite(tolerance_deg) or tolerance_deg < 0:
        raise ComparisonError("tolerance_deg must be finite and non-negative.")

    manifest_by_id = manifest.by_id()
    root = Path(annotation_root).expanduser().resolve(strict=False)
    if not root.is_dir():
        raise ComparisonError(f"Released annotation root not found: {root}")

    all_reviews = sorted(session.reviews, key=lambda review: review.image_id)
    reviews = all_reviews
    if complete_only:
        reviews = [review for review in reviews if review.is_complete]
    excluded_incomplete = len(all_reviews) - len(reviews)
    if not reviews:
        raise ComparisonError(
            "No reviews are eligible for comparison. Complete and save at least one review."
        )

    images: list[ImageComparison] = []
    problems: list[str] = list(label_map.problems)
    for review in reviews:
        manifest_image = manifest_by_id.get(review.image_id)
        if manifest_image is None:
            images.append(
                compare_image(review, None, None, tolerance_deg=tolerance_deg)
            )
            continue
        entries = label_map.entries_by_image.get(review.image_id, ())
        if not entries:
            images.append(
                compare_image(review, manifest_image, None, tolerance_deg=tolerance_deg)
            )
            continue
        if len(entries) > 1 or review.image_id in label_map.ambiguous_image_ids:
            base = compare_image(review, manifest_image, None, tolerance_deg=tolerance_deg)
            reason = (
                f"{len(entries)} released annotations map to this image_id; refusing "
                "to choose one."
                if len(entries) > 1
                else "The released annotation path also maps to another image_id; "
                "refusing to choose one."
            )
            images.append(
                ImageComparison(
                    **{
                        **base.__dict__,
                        "status": STATUS_AMBIGUOUS_MAPPING,
                        "comparison_kind": "AMBIGUOUS_MAPPING",
                        "reasons": tuple(list(base.reasons) + [reason]),
                    }
                )
            )
            if len(entries) > 1:
                problems.append(
                    f"{review.image_id}: {len(entries)} released annotations map to "
                    "this image_id."
                )
            continue
        entry = entries[0]
        try:
            released = _load_released_annotation(entry, root)
        except ReleasedAnnotationMissing as exc:
            message = str(exc)
            status = STATUS_MISSING_RELEASED_ANNOTATION
            kind = "MISSING_RELEASED_ANNOTATION"
        except ReleasedAnnotationStale as exc:
            message = str(exc)
            status = STATUS_STALE_RELEASED_ANNOTATION
            kind = "STALE_RELEASED_ANNOTATION"
        except ComparisonError as exc:
            message = str(exc)
            status = STATUS_INVALID_RELEASED_ANNOTATION
            kind = "INVALID_RELEASED_ANNOTATION"
        else:
            images.append(
                compare_image(
                    review,
                    manifest_image,
                    released,
                    tolerance_deg=tolerance_deg,
                )
            )
            continue

        base = compare_image(review, manifest_image, None, tolerance_deg=tolerance_deg)
        images.append(
            ImageComparison(
                **{
                    **base.__dict__,
                    "annotation_relative_path": entry.annotation_relative_path,
                    "status": status,
                    "comparison_kind": kind,
                    "reasons": tuple(list(base.reasons) + [message]),
                }
            )
        )
        problems.append(f"{review.image_id}: {message}")

    reviewed_ids = {review.image_id for review in session.reviews}
    unreviewed = tuple(
        sorted(
            image.image_id for image in manifest.images if image.image_id not in reviewed_ids
        )
    )
    mapped_not_in_manifest = sorted(
        set(label_map.entries_by_image) - set(manifest_by_id)
    )
    if mapped_not_in_manifest:
        problems.append(
            "Release label map contains image IDs absent from the review manifest: "
            + ", ".join(mapped_not_in_manifest)
        )

    return ComparisonReport(
        generated_at_utc=generated_at_utc or _utc_now(),
        session_path=(
            Path(session_path).expanduser().resolve(strict=False)
            if session_path is not None
            else Path("(in-memory)")
        ),
        session_sha256=session_sha256 or "(not written)",
        review_manifest_path=(
            Path(review_manifest_path).expanduser().resolve(strict=False)
            if review_manifest_path is not None
            else Path("(in-memory)")
        ),
        review_manifest_sha256=review_manifest_sha256 or "(not written)",
        label_map_path=label_map.path,
        label_map_sha256=file_sha256(label_map.path),
        annotation_root=root,
        tolerance_deg=float(tolerance_deg),
        complete_only=complete_only,
        excluded_incomplete=excluded_incomplete,
        images=tuple(images),
        unreviewed_image_ids=unreviewed,
        problems=tuple(problems),
    )


def format_markdown(report: ComparisonReport) -> str:
    summary = report.summary()
    lines = [
        "# Independent vs released annotation comparison",
        "",
        f"**Generated:** {report.generated_at_utc}  ",
        "**Protocol:** `independent-annotation-v1`  ",
        f"**Tolerance:** {report.tolerance_deg:g}°  ",
        f"**Complete-only:** {report.complete_only}",
        "",
        f"> **{DISCLAIMER}**",
        "",
        "## Inputs",
        "",
        f"- Independent annotations: `{report.session_path}` (SHA256 `{report.session_sha256}`)",
        f"- Review manifest: `{report.review_manifest_path}` (SHA256 `{report.review_manifest_sha256}`)",
        f"- Release label map: `{report.label_map_path}` (SHA256 `{report.label_map_sha256}`)",
        f"- Released annotation root: `{report.annotation_root}`",
        "",
        "## Summary",
        "",
        "| Result | Count |",
        "| --- | ---: |",
        f"| Compared | {summary['total_compared']} |",
        f"| Excluded incomplete (complete-only mode) | {summary['excluded_incomplete']} |",
        f"| Agreement | {summary['agreement']} |",
        f"| Disagreement | {summary['disagreement']} |",
        f"| Inconclusive | {summary['inconclusive']} |",
        f"| Missing mapping | {summary['missing_mapping']} |",
        f"| Ambiguous mapping | {summary['ambiguous_mapping']} |",
        f"| Missing released annotation | {summary['missing_released_annotation']} |",
        f"| Stale released annotation | {summary['stale_released_annotation']} |",
        f"| Invalid released annotation | {summary['invalid_released_annotation']} |",
        f"| Missing review-manifest image | {summary['missing_review_manifest_image']} |",
        f"| Partial coverage | {summary['partial_coverage']} |",
        f"| Unreviewed images | {summary['unreviewed_images']} |",
        "",
        "## Image results",
        "",
    ]
    for image in report.images:
        lines.extend(
            [
                f"### `{image.image_id}` — {image.status} ({image.comparison_kind})",
                "",
                f"- Released annotation: "
                f"`{image.annotation_relative_path or '(no verified mapping)'}`",
                f"- Review complete: {image.review_complete}; "
                f"flags: {', '.join(image.image_flags) or '(none)'}",
                f"- Reviewed candidate(s): {image.reviewed_candidates_total}; "
                f"released positive: {image.released_positive}",
                f"- Released interval(s) in degrees: "
                f"{_format_intervals(image.released_intervals_deg) or '(none)'}",
                f"- Max overlap: {_format_metric(image.max_overlap_deg)}; "
                f"nearest distance: {_format_metric(image.min_distance_deg)}",
                f"- Released intervals matched: {image.released_intervals_matched}/"
                f"{image.released_intervals_total}; partial coverage: {image.partial_coverage}",
            ]
        )
        if image.candidates:
            lines.append("- Candidate details:")
            for index, candidate in enumerate(image.candidates):
                lines.append(
                    f"  - [{index}] {candidate.classification}/{candidate.confidence} "
                    f"{format_interval_deg(AngularInterval.from_degrees(candidate.start_deg, candidate.end_deg))}"
                    f" (kind={candidate.kind}); overlap="
                    f"{_format_metric(candidate.best_overlap_deg)}; nearest="
                    f"{_format_metric(candidate.nearest_distance_deg)}; "
                    f"exact={candidate.exact_match}"
                )
                if candidate.notes:
                    lines.append(f"    - Note: {candidate.notes}")
        if image.reasons:
            lines.append("- Reasons:")
            for reason in image.reasons:
                lines.append(f"  - {reason}")
        if image.review_notes:
            lines.append(f"- Reviewer image note: {image.review_notes}")
        lines.append("")
    if report.unreviewed_image_ids:
        lines.extend(
            [
                "## Unreviewed manifest images",
                "",
                "These images are in the manifest but have no saved independent review; "
                "they were not compared.",
                "",
            ]
        )
        lines.extend(f"- `{image_id}`" for image_id in report.unreviewed_image_ids)
        lines.append("")
    if report.problems:
        lines.extend(["## Mapping and input problems", ""])
        lines.extend(f"- {problem}" for problem in report.problems)
        lines.append("")
    lines.extend(
        [
            "## Interpretation limit",
            "",
            DISCLAIMER,
            "",
            "A status of AGREEMENT does not establish that the released label is correct, "
            "that the reviewer saw the same physical feature, or that the feature is a "
            "confirmed plume. DISAGREEMENT and INCONCLUSIVE likewise do not establish "
            "that either annotation is wrong.",
            "",
        ]
    )
    return "\n".join(lines)


def _format_metric(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}°"


def _format_intervals(intervals: tuple[tuple[float, float], ...]) -> str:
    return "; ".join(f"{start:.3f}°–{end:.3f}°" for start, end in intervals)


def write_report(
    report: ComparisonReport,
    json_path: str | Path,
    markdown_path: str | Path | None = None,
) -> tuple[Path, Path | None]:
    """Write comparison outputs without overwriting any existing file."""

    destination_json = Path(json_path).expanduser().resolve(strict=False)
    destination_markdown = (
        Path(markdown_path).expanduser().resolve(strict=False)
        if markdown_path is not None
        else None
    )
    for destination in (destination_json, destination_markdown):
        if destination is not None and destination.exists():
            raise ComparisonError(
                f"Refusing to overwrite existing comparison output: {destination}"
            )
    try:
        destination_json.parent.mkdir(parents=True, exist_ok=True)
        json_text = (
            json.dumps(report.to_dict(), indent=2, sort_keys=True, ensure_ascii=False)
            + "\n"
        )
        _atomic_write(destination_json, json_text)
        if destination_markdown is not None:
            destination_markdown.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(destination_markdown, format_markdown(report))
    except OSError as exc:
        raise ComparisonError(f"Could not write comparison output: {exc}") from exc
    return destination_json, destination_markdown


def _atomic_write(path: Path, text: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="")
    os.replace(temporary, path)
