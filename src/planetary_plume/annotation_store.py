"""Versioned storage for independent human plume-candidate annotations.

The stored file is separate from the released labels and from generated
reports.  It records only reviewer-provided candidates, classifications,
confidence, notes, image flags, and review state.  No field asserts that a
feature is a confirmed physical plume.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import shutil
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from planetary_plume.angle_intervals import AngularInterval, format_interval_deg
from planetary_plume.review_manifest import LimbCircle, ReviewImage, ReviewManifest

ANNOTATION_FORMAT = "planetary-plume-independent-annotations"
ANNOTATION_FORMAT_VERSION = 1
PROTOCOL_VERSION = "independent-annotation-v1"
CONVENTION = {
    "zero": "up",
    "direction": "clockwise",
    "origin": "fitted_limb_center",
    "canonical_units": "radians",
    "display_units": "degrees",
}

CLASSIFICATIONS = ("PLAUSIBLE", "UNCERTAIN", "NO_CANDIDATE_IDENTIFIED")
CONFIDENCES = ("LOW", "MEDIUM", "HIGH")
IMAGE_FLAGS = ("AMBIGUOUS", "NEEDS_REVIEW")
_IMAGE_FLAG_ORDER = {value: index for index, value in enumerate(IMAGE_FLAGS)}
_GEOMETRY_KINDS = ("direction", "interval")


class AnnotationStoreError(ValueError):
    """Raised when annotation data is malformed or inconsistent."""


class ConcurrentModificationError(AnnotationStoreError):
    """Raised when the annotation file changed on disk unexpectedly."""


@dataclass(frozen=True)
class SaveResult:
    path: Path
    sha256: str
    backup_path: Path | None
    session: "ReviewSession"


def utc_now_iso(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _validate_timestamp(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AnnotationStoreError(f"{label} must be a non-empty ISO-8601 timestamp.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AnnotationStoreError(f"{label} is not a valid ISO-8601 timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise AnnotationStoreError(f"{label} must include a timezone: {value!r}")
    return value


def _require_string(value: Any, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise AnnotationStoreError(f"{label} must be a string.")
    if not allow_empty and not value.strip():
        raise AnnotationStoreError(f"{label} must be non-empty.")
    return value


@dataclass(frozen=True)
class CandidateGeometry:
    """A direction or a clockwise angular interval on the fitted limb."""

    kind: str
    interval: AngularInterval

    def __post_init__(self) -> None:
        if self.kind not in _GEOMETRY_KINDS:
            raise AnnotationStoreError(f"Unknown geometry kind: {self.kind!r}.")
        if not isinstance(self.interval, AngularInterval):
            raise AnnotationStoreError("geometry.interval must be an AngularInterval.")
        if self.kind == "direction" and not self.interval.is_direction:
            raise AnnotationStoreError("A direction geometry must have zero width.")
        if self.kind == "interval" and self.interval.is_direction:
            raise AnnotationStoreError("An interval geometry must have non-zero width.")

    @classmethod
    def direction_from_radians(cls, angle: float) -> "CandidateGeometry":
        return cls("direction", AngularInterval.direction_from_radians(angle))

    @classmethod
    def direction_from_degrees(cls, angle_deg: float) -> "CandidateGeometry":
        return cls("direction", AngularInterval.direction_from_degrees(angle_deg))

    @classmethod
    def interval_from_radians(cls, start: float, end: float) -> "CandidateGeometry":
        return cls("interval", AngularInterval.from_radians(start, end))

    @classmethod
    def interval_from_degrees(cls, start_deg: float, end_deg: float) -> "CandidateGeometry":
        return cls("interval", AngularInterval.from_degrees(start_deg, end_deg))

    @property
    def start_rad(self) -> float:
        return self.interval.start_rad

    @property
    def end_rad(self) -> float:
        return self.interval.end_rad

    @property
    def width_rad(self) -> float:
        return self.interval.width_rad

    @property
    def start_deg(self) -> float:
        return self.interval.start_deg

    @property
    def end_deg(self) -> float:
        return self.interval.end_deg

    @property
    def width_deg(self) -> float:
        return self.interval.width_deg

    @property
    def crosses_zero(self) -> bool:
        return self.interval.crosses_zero

    def format(self) -> str:
        return format_interval_deg(self.interval)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "start_rad": float(self.start_rad),
            "end_rad": float(self.end_rad),
            "start_deg": float(self.start_deg),
            "end_deg": float(self.end_deg),
            "width_rad": float(self.width_rad),
            "width_deg": float(self.width_deg),
            "crosses_zero": self.crosses_zero,
        }

    @classmethod
    def from_dict(cls, payload: Any, *, label: str = "geometry") -> "CandidateGeometry":
        if not isinstance(payload, dict):
            raise AnnotationStoreError(f"{label} must be an object.")
        for key in ("kind", "start_rad", "end_rad"):
            if key not in payload:
                raise AnnotationStoreError(f"{label} is missing {key!r}.")
        kind = payload["kind"]
        if kind not in _GEOMETRY_KINDS:
            raise AnnotationStoreError(f"{label}.kind is unknown: {kind!r}.")
        try:
            interval = AngularInterval.from_radians(
                float(payload["start_rad"]), float(payload["end_rad"])
            )
        except (TypeError, ValueError) as exc:
            raise AnnotationStoreError(f"{label} has invalid angles: {exc}") from exc
        geometry = cls(kind, interval)

        checks = (
            ("start_deg", geometry.start_deg, 1e-6),
            ("end_deg", geometry.end_deg, 1e-6),
            ("width_rad", geometry.width_rad, 1e-9),
            ("width_deg", geometry.width_deg, 1e-6),
        )
        for key, computed, tolerance in checks:
            if key in payload:
                try:
                    stored = float(payload[key])
                except (TypeError, ValueError) as exc:
                    raise AnnotationStoreError(f"{label}.{key} must be a number.") from exc
                if not math.isclose(stored, computed, abs_tol=tolerance):
                    raise AnnotationStoreError(
                        f"{label}.{key} ({stored}) is inconsistent with the canonical "
                        f"radians ({computed})."
                    )
        if "crosses_zero" in payload and bool(payload["crosses_zero"]) != geometry.crosses_zero:
            raise AnnotationStoreError(f"{label}.crosses_zero is inconsistent with the angles.")
        return geometry


@dataclass(frozen=True)
class CandidateAnnotation:
    candidate_id: str
    classification: str
    confidence: str
    geometry: CandidateGeometry | None
    notes: str
    created_at_utc: str
    updated_at_utc: str

    def __post_init__(self) -> None:
        _require_string(self.candidate_id, "candidate_id")
        if self.classification not in CLASSIFICATIONS:
            raise AnnotationStoreError(
                f"classification must be one of {CLASSIFICATIONS}, got {self.classification!r}."
            )
        if self.confidence not in CONFIDENCES:
            raise AnnotationStoreError(
                f"confidence must be one of {CONFIDENCES}, got {self.confidence!r}."
            )
        if not isinstance(self.notes, str):
            raise AnnotationStoreError("candidate notes must be a string.")
        _validate_timestamp(self.created_at_utc, "created_at_utc")
        _validate_timestamp(self.updated_at_utc, "updated_at_utc")
        if self.classification == "NO_CANDIDATE_IDENTIFIED":
            if self.geometry is not None:
                raise AnnotationStoreError(
                    "NO_CANDIDATE_IDENTIFIED cannot carry candidate geometry."
                )
        elif self.geometry is None:
            raise AnnotationStoreError(
                f"{self.classification} requires a direction or interval geometry."
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "classification": self.classification,
            "confidence": self.confidence,
            "geometry": None if self.geometry is None else self.geometry.to_dict(),
            "notes": self.notes,
            "created_at_utc": self.created_at_utc,
            "updated_at_utc": self.updated_at_utc,
        }

    @classmethod
    def from_dict(cls, payload: Any, *, label: str = "candidate") -> "CandidateAnnotation":
        if not isinstance(payload, dict):
            raise AnnotationStoreError(f"{label} must be an object.")
        required = (
            "candidate_id",
            "classification",
            "confidence",
            "geometry",
            "notes",
            "created_at_utc",
            "updated_at_utc",
        )
        missing = [key for key in required if key not in payload]
        if missing:
            raise AnnotationStoreError(f"{label} is missing fields: {', '.join(missing)}")
        geometry = (
            None
            if payload["geometry"] is None
            else CandidateGeometry.from_dict(payload["geometry"], label=f"{label}.geometry")
        )
        return cls(
            candidate_id=str(payload["candidate_id"]),
            classification=str(payload["classification"]),
            confidence=str(payload["confidence"]),
            geometry=geometry,
            notes=str(payload["notes"]),
            created_at_utc=str(payload["created_at_utc"]),
            updated_at_utc=str(payload["updated_at_utc"]),
        )

    def with_updates(
        self,
        *,
        classification: str | None = None,
        confidence: str | None = None,
        geometry: CandidateGeometry | None = None,
        notes: str | None = None,
        now: datetime | None = None,
    ) -> "CandidateAnnotation":
        return replace(
            self,
            classification=self.classification if classification is None else classification,
            confidence=self.confidence if confidence is None else confidence,
            geometry=self.geometry if geometry is None else geometry,
            notes=self.notes if notes is None else notes,
            updated_at_utc=utc_now_iso(now),
        )


def new_candidate(
    *,
    classification: str,
    confidence: str,
    geometry: CandidateGeometry | None,
    notes: str = "",
    candidate_id: str | None = None,
    now: datetime | None = None,
) -> CandidateAnnotation:
    """Create one candidate with creation/update timestamps."""

    if candidate_id is None:
        import uuid

        candidate_id = str(uuid.uuid4())
    timestamp = utc_now_iso(now)
    return CandidateAnnotation(
        candidate_id=candidate_id,
        classification=classification,
        confidence=confidence,
        geometry=geometry,
        notes=notes,
        created_at_utc=timestamp,
        updated_at_utc=timestamp,
    )


@dataclass(frozen=True)
class ImageReview:
    image_id: str
    display_name: str
    product_family: str
    source_product_path: str
    source_product_sha256: str
    target: str
    instrument: str
    width: int
    height: int
    limb: LimbCircle
    candidates: tuple[CandidateAnnotation, ...]
    no_candidate_identified: bool
    image_flags: tuple[str, ...]
    notes: str
    is_complete: bool
    created_at_utc: str
    updated_at_utc: str
    completed_at_utc: str | None

    def __post_init__(self) -> None:
        _require_string(self.image_id, "image_id")
        _require_string(self.display_name, "display_name")
        _require_string(self.product_family, "product_family")
        _require_string(self.source_product_path, "source_product_path")
        _require_string(self.source_product_sha256, "source_product_sha256")
        _require_string(self.target, "target")
        _require_string(self.instrument, "instrument")
        if not isinstance(self.width, int) or isinstance(self.width, bool) or self.width <= 0:
            raise AnnotationStoreError("width must be a positive integer.")
        if not isinstance(self.height, int) or isinstance(self.height, bool) or self.height <= 0:
            raise AnnotationStoreError("height must be a positive integer.")
        if not isinstance(self.limb, LimbCircle):
            raise AnnotationStoreError("limb must be a LimbCircle.")
        if not isinstance(self.candidates, tuple):
            raise AnnotationStoreError("candidates must be a tuple.")
        for candidate in self.candidates:
            if not isinstance(candidate, CandidateAnnotation):
                raise AnnotationStoreError("candidates must contain CandidateAnnotation objects.")
        ids = [candidate.candidate_id for candidate in self.candidates]
        duplicates = sorted({value for value in ids if ids.count(value) > 1})
        if duplicates:
            raise AnnotationStoreError("Duplicate candidate_id values: " + ", ".join(duplicates))
        if any(flag not in IMAGE_FLAGS for flag in self.image_flags):
            raise AnnotationStoreError(
                f"image_flags must be a subset of {IMAGE_FLAGS}, got {self.image_flags!r}."
            )
        if not isinstance(self.notes, str):
            raise AnnotationStoreError("image notes must be a string.")
        _validate_timestamp(self.created_at_utc, "created_at_utc")
        _validate_timestamp(self.updated_at_utc, "updated_at_utc")

        no_candidate_records = [
            candidate
            for candidate in self.candidates
            if candidate.classification == "NO_CANDIDATE_IDENTIFIED"
        ]
        if self.no_candidate_identified:
            if self.candidates and not (
                len(self.candidates) == 1 and len(no_candidate_records) == 1
            ):
                raise AnnotationStoreError(
                    "no_candidate_identified cannot coexist with candidate geometries."
                )
        else:
            if no_candidate_records:
                raise AnnotationStoreError(
                    "A NO_CANDIDATE_IDENTIFIED record requires "
                    "no_candidate_identified=true."
                )
        if self.is_complete:
            if not self.no_candidate_identified and not self.candidates:
                raise AnnotationStoreError(
                    "A complete review must mark no_candidate_identified or contain "
                    "at least one candidate."
                )
            if self.completed_at_utc is None:
                raise AnnotationStoreError("A complete review requires completed_at_utc.")
            _validate_timestamp(self.completed_at_utc, "completed_at_utc")
        elif self.completed_at_utc is not None:
            raise AnnotationStoreError(
                "completed_at_utc must be null while the review is incomplete."
            )

    @classmethod
    def from_review_image(
        cls, image: ReviewImage, *, now: datetime | None = None
    ) -> "ImageReview":
        timestamp = utc_now_iso(now)
        return cls(
            image_id=image.image_id,
            display_name=image.display_name,
            product_family=image.product_family,
            source_product_path=image.product_path,
            source_product_sha256=image.image_sha256,
            target=image.target,
            instrument=image.instrument,
            width=image.width,
            height=image.height,
            limb=image.limb,
            candidates=(),
            no_candidate_identified=False,
            image_flags=(),
            notes="",
            is_complete=False,
            created_at_utc=timestamp,
            updated_at_utc=timestamp,
            completed_at_utc=None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "image_id": self.image_id,
            "display_name": self.display_name,
            "product_family": self.product_family,
            "source_product_path": self.source_product_path,
            "source_product_sha256": self.source_product_sha256,
            "target": self.target,
            "instrument": self.instrument,
            "width": self.width,
            "height": self.height,
            "limb": self.limb.to_dict(),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "no_candidate_identified": self.no_candidate_identified,
            "image_flags": list(self.image_flags),
            "notes": self.notes,
            "is_complete": self.is_complete,
            "created_at_utc": self.created_at_utc,
            "updated_at_utc": self.updated_at_utc,
            "completed_at_utc": self.completed_at_utc,
        }

    @classmethod
    def from_dict(cls, payload: Any, *, label: str = "image") -> "ImageReview":
        if not isinstance(payload, dict):
            raise AnnotationStoreError(f"{label} must be an object.")
        required = (
            "image_id",
            "display_name",
            "product_family",
            "source_product_path",
            "source_product_sha256",
            "target",
            "instrument",
            "width",
            "height",
            "limb",
            "candidates",
            "no_candidate_identified",
            "image_flags",
            "notes",
            "is_complete",
            "created_at_utc",
            "updated_at_utc",
            "completed_at_utc",
        )
        missing = [key for key in required if key not in payload]
        if missing:
            raise AnnotationStoreError(f"{label} is missing fields: {', '.join(missing)}")
        candidates_payload = payload["candidates"]
        if not isinstance(candidates_payload, list):
            raise AnnotationStoreError(f"{label}.candidates must be a list.")
        flags_payload = payload["image_flags"]
        if not isinstance(flags_payload, list):
            raise AnnotationStoreError(f"{label}.image_flags must be a list.")
        try:
            return cls(
                image_id=str(payload["image_id"]),
                display_name=str(payload["display_name"]),
                product_family=str(payload["product_family"]),
                source_product_path=str(payload["source_product_path"]),
                source_product_sha256=str(payload["source_product_sha256"]),
                target=str(payload["target"]),
                instrument=str(payload["instrument"]),
                width=int(payload["width"]),
                height=int(payload["height"]),
                limb=LimbCircle.from_dict(payload["limb"], label=f"{label}.limb"),
                candidates=tuple(
                    CandidateAnnotation.from_dict(item, label=f"{label}.candidates[{index}]")
                    for index, item in enumerate(candidates_payload)
                ),
                no_candidate_identified=bool(payload["no_candidate_identified"]),
                image_flags=tuple(str(flag) for flag in flags_payload),
                notes=str(payload["notes"]),
                is_complete=bool(payload["is_complete"]),
                created_at_utc=str(payload["created_at_utc"]),
                updated_at_utc=str(payload["updated_at_utc"]),
                completed_at_utc=(
                    None if payload["completed_at_utc"] is None else str(payload["completed_at_utc"])
                ),
            )
        except (TypeError, ValueError) as exc:
            if isinstance(exc, AnnotationStoreError):
                raise
            raise AnnotationStoreError(f"{label} has invalid values: {exc}") from exc

    def candidate(self, candidate_id: str) -> CandidateAnnotation:
        for candidate in self.candidates:
            if candidate.candidate_id == candidate_id:
                return candidate
        raise AnnotationStoreError(f"Candidate not found: {candidate_id}")

    def _with_candidates(
        self,
        candidates: tuple[CandidateAnnotation, ...],
        *,
        no_candidate_identified: bool | None = None,
        now: datetime | None = None,
        touch: bool = True,
    ) -> "ImageReview":
        flag = (
            self.no_candidate_identified
            if no_candidate_identified is None
            else no_candidate_identified
        )
        # Any change to candidate geometry or to the negative assessment reopens
        # a completed review. The reviewer must explicitly complete it again.
        reopen = self.is_complete
        return replace(
            self,
            candidates=candidates,
            no_candidate_identified=flag,
            is_complete=False if reopen else self.is_complete,
            completed_at_utc=None if reopen else self.completed_at_utc,
            updated_at_utc=utc_now_iso(now) if touch else self.updated_at_utc,
        )

    def with_candidate(
        self, candidate: CandidateAnnotation, *, now: datetime | None = None
    ) -> "ImageReview":
        if self.no_candidate_identified:
            raise AnnotationStoreError(
                "Uncheck no_candidate_identified before adding a candidate."
            )
        if any(item.candidate_id == candidate.candidate_id for item in self.candidates):
            raise AnnotationStoreError(f"Duplicate candidate_id: {candidate.candidate_id}")
        if candidate.classification == "NO_CANDIDATE_IDENTIFIED" and self.candidates:
            raise AnnotationStoreError(
                "NO_CANDIDATE_IDENTIFIED cannot be added alongside other candidates."
            )
        no_candidate = candidate.classification == "NO_CANDIDATE_IDENTIFIED"
        return self._with_candidates(
            self.candidates + (candidate,),
            no_candidate_identified=no_candidate or None,
            now=now,
        )

    def replace_candidate(
        self, candidate: CandidateAnnotation, *, now: datetime | None = None
    ) -> "ImageReview":
        existing = self.candidate(candidate.candidate_id)
        if (
            candidate.classification == "NO_CANDIDATE_IDENTIFIED"
            and len(self.candidates) > 1
        ):
            raise AnnotationStoreError(
                "NO_CANDIDATE_IDENTIFIED cannot coexist with other candidates."
            )
        updated = tuple(
            candidate if item.candidate_id == candidate.candidate_id else item
            for item in self.candidates
        )
        no_candidate = self.no_candidate_identified
        if candidate.classification == "NO_CANDIDATE_IDENTIFIED":
            no_candidate = True
        elif existing.classification == "NO_CANDIDATE_IDENTIFIED":
            no_candidate = False
        return self._with_candidates(
            updated,
            no_candidate_identified=no_candidate,
            now=now,
        )

    def delete_candidate(
        self, candidate_id: str, *, now: datetime | None = None
    ) -> "ImageReview":
        existing = self.candidate(candidate_id)
        remaining = tuple(
            item for item in self.candidates if item.candidate_id != candidate_id
        )
        no_candidate = self.no_candidate_identified
        if existing.classification == "NO_CANDIDATE_IDENTIFIED" and not remaining:
            no_candidate = False
        return self._with_candidates(
            remaining,
            no_candidate_identified=no_candidate,
            now=now,
        )

    def with_no_candidate(
        self, enabled: bool, *, now: datetime | None = None
    ) -> "ImageReview":
        candidates = () if enabled else self.candidates
        reopen = self.is_complete
        return replace(
            self,
            candidates=candidates,
            no_candidate_identified=bool(enabled),
            is_complete=False if reopen else self.is_complete,
            completed_at_utc=None if reopen else self.completed_at_utc,
            updated_at_utc=utc_now_iso(now),
        )

    def with_flags(
        self, flags: tuple[str, ...] | list[str], *, now: datetime | None = None
    ) -> "ImageReview":
        unique = sorted(set(flags), key=lambda value: _IMAGE_FLAG_ORDER.get(value, 99))
        return replace(
            self,
            image_flags=tuple(unique),
            updated_at_utc=utc_now_iso(now),
        )

    def with_notes(self, notes: str, *, now: datetime | None = None) -> "ImageReview":
        if not isinstance(notes, str):
            raise AnnotationStoreError("Image notes must be a string.")
        return replace(self, notes=notes, updated_at_utc=utc_now_iso(now))

    def mark_complete(
        self, complete: bool, *, now: datetime | None = None
    ) -> "ImageReview":
        timestamp = utc_now_iso(now)
        if complete:
            if not self.no_candidate_identified and not self.candidates:
                raise AnnotationStoreError(
                    "Cannot complete: mark no_candidate_identified or add at least "
                    "one candidate."
                )
            return replace(
                self,
                is_complete=True,
                completed_at_utc=timestamp,
                updated_at_utc=timestamp,
            )
        return replace(
            self,
            is_complete=False,
            completed_at_utc=None,
            updated_at_utc=timestamp,
        )

    def summary(self) -> str:
        if self.is_complete:
            state = "complete"
        elif self.candidates or self.no_candidate_identified or self.image_flags or self.notes:
            state = "in progress"
        else:
            state = "not started"
        if self.no_candidate_identified:
            outcome = "no candidate identified"
        else:
            outcome = f"{len(self.candidates)} candidate(s)"
        return f"{state} · {outcome}"


@dataclass(frozen=True)
class ReviewSession:
    format_version: int
    protocol_version: str
    reviewer: str
    created_at_utc: str
    updated_at_utc: str
    reviews: tuple[ImageReview, ...]

    def __post_init__(self) -> None:
        if self.format_version != ANNOTATION_FORMAT_VERSION:
            raise AnnotationStoreError(
                f"Unsupported annotation format version: {self.format_version!r}."
            )
        if self.protocol_version != PROTOCOL_VERSION:
            raise AnnotationStoreError(
                f"Unsupported protocol version: {self.protocol_version!r}."
            )
        _require_string(self.reviewer, "reviewer")
        _validate_timestamp(self.created_at_utc, "created_at_utc")
        _validate_timestamp(self.updated_at_utc, "updated_at_utc")
        if not isinstance(self.reviews, tuple):
            raise AnnotationStoreError("reviews must be a tuple.")
        ids = [review.image_id for review in self.reviews]
        duplicates = sorted({value for value in ids if ids.count(value) > 1})
        if duplicates:
            raise AnnotationStoreError("Duplicate image_id reviews: " + ", ".join(duplicates))

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": ANNOTATION_FORMAT,
            "format_version": self.format_version,
            "protocol_version": self.protocol_version,
            "convention": dict(CONVENTION),
            "reviewer": self.reviewer,
            "created_at_utc": self.created_at_utc,
            "updated_at_utc": self.updated_at_utc,
            "images": [review.to_dict() for review in self.reviews],
        }

    @classmethod
    def from_dict(cls, payload: Any) -> "ReviewSession":
        if not isinstance(payload, dict):
            raise AnnotationStoreError("Annotation file root must be an object.")
        if payload.get("format") != ANNOTATION_FORMAT:
            raise AnnotationStoreError(
                f"Unsupported annotation format: {payload.get('format')!r}. "
                f"Expected {ANNOTATION_FORMAT!r}."
            )
        convention = payload.get("convention")
        if not isinstance(convention, dict):
            raise AnnotationStoreError("Annotation file is missing the 'convention' object.")
        for key, expected in CONVENTION.items():
            if convention.get(key) != expected:
                raise AnnotationStoreError(
                    f"Unsupported convention.{key}: {convention.get(key)!r}; "
                    f"expected {expected!r}. The angle convention cannot be changed silently."
                )
        images = payload.get("images")
        if not isinstance(images, list):
            raise AnnotationStoreError("Annotation file must contain an 'images' list.")
        try:
            return cls(
                format_version=int(payload.get("format_version")),
                protocol_version=str(payload.get("protocol_version")),
                reviewer=str(payload.get("reviewer")),
                created_at_utc=str(payload.get("created_at_utc")),
                updated_at_utc=str(payload.get("updated_at_utc")),
                reviews=tuple(
                    ImageReview.from_dict(item, label=f"images[{index}]")
                    for index, item in enumerate(images)
                ),
            )
        except (TypeError, ValueError) as exc:
            if isinstance(exc, AnnotationStoreError):
                raise
            raise AnnotationStoreError(f"Annotation file has invalid values: {exc}") from exc

    def review(self, image_id: str) -> ImageReview:
        for review in self.reviews:
            if review.image_id == image_id:
                return review
        raise AnnotationStoreError(f"Image review not found: {image_id}")

    def replace_review(
        self, review: ImageReview, *, now: datetime | None = None
    ) -> "ReviewSession":
        found = False
        reviews: list[ImageReview] = []
        for existing in self.reviews:
            if existing.image_id == review.image_id:
                reviews.append(review)
                found = True
            else:
                reviews.append(existing)
        if not found:
            reviews.append(review)
        return replace(
            self,
            reviews=tuple(reviews),
            updated_at_utc=utc_now_iso(now),
        )

    def with_timestamp(self, now: datetime | None = None) -> "ReviewSession":
        return replace(self, updated_at_utc=utc_now_iso(now))

    def validate_against_manifest(self, manifest: ReviewManifest) -> None:
        images = manifest.by_id()
        extra = sorted(review.image_id for review in self.reviews if review.image_id not in images)
        if extra:
            raise AnnotationStoreError(
                "Annotation file contains image IDs that are not in the review manifest: "
                + ", ".join(extra)
            )
        for review in self.reviews:
            image = images[review.image_id]
            if review.source_product_sha256 != image.image_sha256:
                raise AnnotationStoreError(
                    f"{review.image_id}: source image SHA256 differs from the manifest. "
                    "Do not merge annotations across different image products."
                )
            if (review.width, review.height) != (image.width, image.height):
                raise AnnotationStoreError(
                    f"{review.image_id}: image dimensions differ from the manifest."
                )
            if not (
                math.isclose(review.limb.center_x, image.limb.center_x, abs_tol=1e-6)
                and math.isclose(review.limb.center_y, image.limb.center_y, abs_tol=1e-6)
                and math.isclose(review.limb.radius, image.limb.radius, abs_tol=1e-6)
            ):
                raise AnnotationStoreError(
                    f"{review.image_id}: fitted limb geometry differs from the manifest. "
                    "Angles would not be comparable."
                )

    def add_missing_from_manifest(
        self, manifest: ReviewManifest, *, now: datetime | None = None
    ) -> "ReviewSession":
        self.validate_against_manifest(manifest)
        existing = {review.image_id for review in self.reviews}
        additions = tuple(
            ImageReview.from_review_image(image, now=now)
            for image in manifest.images
            if image.image_id not in existing
        )
        if not additions:
            return self
        return replace(self, reviews=self.reviews + additions)


def new_session(
    manifest: ReviewManifest,
    reviewer: str,
    *,
    now: datetime | None = None,
) -> ReviewSession:
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise AnnotationStoreError("reviewer must be a non-empty string.")
    timestamp = utc_now_iso(now)
    return ReviewSession(
        format_version=ANNOTATION_FORMAT_VERSION,
        protocol_version=PROTOCOL_VERSION,
        reviewer=reviewer.strip(),
        created_at_utc=timestamp,
        updated_at_utc=timestamp,
        reviews=tuple(
            ImageReview.from_review_image(image, now=now) for image in manifest.images
        ),
    )


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_session(path: str | Path) -> ReviewSession:
    source = Path(path).expanduser().resolve(strict=False)
    if not source.is_file():
        raise AnnotationStoreError(f"Annotation file not found: {source}")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AnnotationStoreError(f"Could not read annotation file {source}: {exc}") from exc
    return ReviewSession.from_dict(payload)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="")
    os.replace(temporary, path)


def save_session(
    session: ReviewSession,
    path: str | Path,
    *,
    expected_sha256: str | None = None,
    backup: bool = True,
    now: datetime | None = None,
) -> SaveResult:
    """Atomically write an annotation session.

    ``expected_sha256`` is the hash observed when the session was loaded.  If the
    file exists and the hash differs, the save is refused instead of silently
    overwriting another process's edits.  A one-generation ``.bak`` copy is kept
    by default.
    """

    destination = Path(path).expanduser().resolve(strict=False)
    exists = destination.is_file()
    if exists:
        if expected_sha256 is None:
            raise ConcurrentModificationError(
                f"Annotation file already exists but no prior hash was supplied: {destination}. "
                "Refusing to overwrite it."
            )
        try:
            actual = file_sha256(destination)
        except OSError as exc:
            raise AnnotationStoreError(
                f"Could not read annotation file {destination}: {exc}"
            ) from exc
        if actual != expected_sha256:
            raise ConcurrentModificationError(
                f"Annotation file changed on disk: {destination}. Reload before saving."
            )
    elif expected_sha256 is not None:
        raise ConcurrentModificationError(
            f"Annotation file disappeared while editing: {destination}."
        )

    session_to_write = session.with_timestamp(now)
    payload = session_to_write.to_dict()
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    backup_path: Path | None = None
    if exists and backup:
        backup_path = destination.with_name(destination.name + ".bak")
        try:
            shutil.copy2(destination, backup_path)
        except OSError as exc:
            raise AnnotationStoreError(
                f"Could not create annotation backup {backup_path}: {exc}"
            ) from exc

    try:
        _atomic_write_text(destination, text)
        written_sha = file_sha256(destination)
    except OSError as exc:
        raise AnnotationStoreError(
            f"Could not write annotation file {destination}: {exc}"
        ) from exc
    return SaveResult(
        path=destination,
        sha256=written_sha,
        backup_path=backup_path,
        session=session_to_write,
    )


def clone_session(session: ReviewSession) -> ReviewSession:
    """Deep copy for an in-memory saved-state snapshot."""

    return copy.deepcopy(session)
