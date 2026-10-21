"""Read-only parsing of the Zenodo 2556063 limb/plume annotation bundle.

The bundle contains YAML annotations, not images.  This module deliberately
preserves the original YAML values and never rewrites the annotation files.
Directory names are mapped to target/instrument only through the explicit table
below, which mirrors the bundle's README and directory layout.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ZENODO_RECORD_ID = "2556063"
ZENODO_DOI = "10.5281/zenodo.2556063"
ZENODO_CONCEPT_DOI = "10.5281/zenodo.2556062"
ZENODO_ZIP_NAME = "plume_annotations.zip"
ZENODO_ZIP_SIZE = 151_704
ZENODO_ZIP_MD5 = "f2c479e5f5cd10720c99ad820f14bceb"
ZENODO_ZIP_URL = (
    "https://zenodo.org/api/records/2556063/files/plume_annotations.zip/content"
)
EXPECTED_ANNOTATION_COUNT = 308


class AnnotationError(ValueError):
    """Raised when annotation data is missing, malformed, or inconsistent."""


@dataclass(frozen=True)
class FamilySpec:
    """Directory-level identity asserted by the bundle documentation."""

    target_body: str
    instrument: str
    product_family: str
    identifier_kind: str
    default_mapping_status: str
    mapping_evidence: str


# These mappings are copied from the Zenodo README's directory descriptions.
# They are not inferred from filenames.
FAMILY_SPECS: dict[str, FamilySpec] = {
    "cassini_iss_enceladus": FamilySpec(
        target_body="Enceladus",
        instrument="Cassini ISS",
        product_family="cassini_iss",
        identifier_kind="cassini_label_stem",
        default_mapping_status="unresolved_adapter",
        mapping_evidence=(
            "Cassini PDS PRODUCT_ID differs from the label filename stem; "
            "no Cassini adapter is implemented in this milestone."
        ),
    ),
    "galileo_ssi_callisto": FamilySpec(
        target_body="Callisto",
        instrument="Galileo SSI",
        product_family="galileo_ssi",
        identifier_kind="galileo_image_id",
        default_mapping_status="unresolved_sidecar",
        mapping_evidence="Requires an entry in galileo_image_ids.txt.",
    ),
    "galileo_ssi_europa": FamilySpec(
        target_body="Europa",
        instrument="Galileo SSI",
        product_family="galileo_ssi",
        identifier_kind="galileo_image_id",
        default_mapping_status="unresolved_sidecar",
        mapping_evidence="Requires an entry in galileo_image_ids.txt.",
    ),
    "galileo_ssi_ganymede": FamilySpec(
        target_body="Ganymede",
        instrument="Galileo SSI",
        product_family="galileo_ssi",
        identifier_kind="galileo_image_id",
        default_mapping_status="unresolved_sidecar",
        mapping_evidence="Requires an entry in galileo_image_ids.txt.",
    ),
    "galileo_ssi_io": FamilySpec(
        target_body="Io",
        instrument="Galileo SSI",
        product_family="galileo_ssi",
        identifier_kind="galileo_image_id",
        default_mapping_status="unresolved_sidecar",
        mapping_evidence="Requires an entry in galileo_image_ids.txt.",
    ),
    "messenger_mdis_mercury": FamilySpec(
        target_body="Mercury",
        instrument="MESSENGER MDIS",
        product_family="messenger_mdis",
        identifier_kind="messenger_label_stem",
        default_mapping_status="label_stem_candidate",
        mapping_evidence=(
            "Sample raw EDR PRODUCT_ID matched the label stem; not verified "
            "for every MESSENGER annotation."
        ),
    ),
    "new_horizons_lorri_io": FamilySpec(
        target_body="Io",
        instrument="New Horizons LORRI",
        product_family="new_horizons_lorri",
        identifier_kind="lorri_label_stem",
        default_mapping_status="label_stem_candidate",
        mapping_evidence=(
            "Label filename stem is the LORRI product identifier candidate; "
            "PDS resolution is required before retrieval."
        ),
    ),
}


@dataclass(frozen=True)
class AnnotationRecord:
    """One parsed annotation file, with provenance and label fields intact."""

    annotation_filename: str
    annotation_relative_path: str
    annotation_sha256: str
    directory: str
    target_body: str | None
    instrument: str | None
    product_family: str
    label_identifier: str
    retrieval_identifier: str
    retrieval_identifier_kind: str
    mapping_status: str
    mapping_evidence: str
    plume_status: bool
    plume_interval_count: int
    plume_intervals: tuple[tuple[float, float], ...]
    limb_point_count: int
    limb_points: tuple[tuple[float, float], ...]
    annotator: str
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "annotation_filename": self.annotation_filename,
            "annotation_relative_path": self.annotation_relative_path,
            "annotation_sha256": self.annotation_sha256,
            "directory": self.directory,
            "target_body": self.target_body,
            "instrument": self.instrument,
            "product_family": self.product_family,
            "label_identifier": self.label_identifier,
            "retrieval_identifier": self.retrieval_identifier,
            "retrieval_identifier_kind": self.retrieval_identifier_kind,
            "mapping_status": self.mapping_status,
            "mapping_evidence": self.mapping_evidence,
            "plume_status": self.plume_status,
            "plume_interval_count": self.plume_interval_count,
            "plume_intervals": [list(interval) for interval in self.plume_intervals],
            "limb_point_count": self.limb_point_count,
            "limb_points": [list(point) for point in self.limb_points],
            "annotator": self.annotator,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class GalileoImageMap:
    """The sidecar mapping Galileo label filenames to image IDs."""

    source_path: Path | None
    by_filename: dict[str, tuple[str, ...]]
    problems: tuple[str, ...]

    def lookup(self, filename: str) -> tuple[str, ...]:
        return self.by_filename.get(filename, ())


@dataclass(frozen=True)
class AnnotationInventory:
    """All parsed annotations plus deterministic summary counts."""

    root: Path
    sidecar_path: Path | None
    records: tuple[AnnotationRecord, ...]
    summary: dict[str, Any]
    problems: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "sidecar_path": str(self.sidecar_path) if self.sidecar_path else None,
            "summary": self.summary,
            "problems": list(self.problems),
            "records": [record.to_dict() for record in self.records],
        }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AnnotationError(f"{label} must be a number, got {type(value).__name__}.")
    converted = float(value)
    if not math.isfinite(converted):
        raise AnnotationError(f"{label} must be finite.")
    return converted


def _parse_points(raw: Any) -> tuple[tuple[float, float], ...]:
    if not isinstance(raw, list) or len(raw) < 3:
        raise AnnotationError("'points' must be a list with at least three points.")
    points: list[tuple[float, float]] = []
    for index, point in enumerate(raw):
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise AnnotationError(f"points[{index}] must be a two-item [x, y] pair.")
        points.append(
            (
                _number(point[0], f"points[{index}][0]"),
                _number(point[1], f"points[{index}][1]"),
            )
        )
    return tuple(points)


def _parse_intervals(
    raw: Any, *, allow_wrapping: bool = False
) -> tuple[tuple[float, float], ...]:
    if not isinstance(raw, list):
        raise AnnotationError("'plumes.intervals' must be a list when present.")
    intervals: list[tuple[float, float]] = []
    for index, interval in enumerate(raw):
        if not isinstance(interval, (list, tuple)) or len(interval) != 2:
            raise AnnotationError(
                f"plumes.intervals[{index}] must be a two-item [start, end] pair."
            )
        start = _number(interval[0], f"plumes.intervals[{index}][0]")
        end = _number(interval[1], f"plumes.intervals[{index}][1]")
        if start == end:
            raise AnnotationError(
                f"plumes.intervals[{index}] must have a non-zero width, got "
                f"{start!r} == {end!r}."
            )
        if start > end and not allow_wrapping:
            raise AnnotationError(
                f"plumes.intervals[{index}] must have start < end unless wrapping "
                f"is explicitly allowed, got {start!r} > {end!r}."
            )
        intervals.append((start, end))
    return tuple(intervals)


def parse_annotation_text(
    text: str,
    *,
    source: Path,
    root: Path,
    family: FamilySpec | None,
    galileo_map: GalileoImageMap | None,
    allow_wrapping_intervals: bool = False,
) -> AnnotationRecord:
    """Parse one YAML annotation without modifying it.

    ``allow_wrapping_intervals`` is used only by the independent-comparison
    stage, which must handle an interval that crosses 0/360 degrees.  The
    default preserves the released-bundle validation behavior.
    """

    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise AnnotationError(f"{source}: invalid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise AnnotationError(f"{source}: annotation root must be a mapping.")

    points = _parse_points(raw.get("points"))
    annotator = raw.get("user")
    if not isinstance(annotator, str) or not annotator.strip():
        raise AnnotationError(f"{source}: 'user' must be a non-empty string.")

    warnings: list[str] = []
    plume_present = "plumes" in raw
    intervals: tuple[tuple[float, float], ...] = ()
    if plume_present:
        plumes = raw.get("plumes")
        if not isinstance(plumes, dict):
            raise AnnotationError(f"{source}: 'plumes' must be a mapping.")
        intervals = _parse_intervals(
            plumes.get("intervals", []),
            allow_wrapping=allow_wrapping_intervals,
        )
        if not intervals:
            warnings.append("'plumes' key is present but has no intervals.")
        for index, (start, end) in enumerate(intervals):
            if start < 0 or end > 2 * math.pi:
                warnings.append(
                    f"interval {index} falls outside [0, 2*pi): "
                    f"[{start}, {end}]."
                )

    label_identifier = source.name
    if label_identifier.endswith("_label.yml"):
        label_identifier = label_identifier[: -len("_label.yml")]
    else:
        label_identifier = source.stem

    if family is None:
        target_body = None
        instrument = None
        product_family = "unknown"
        retrieval_identifier = label_identifier
        identifier_kind = "unknown"
        mapping_status = "unknown_layout"
        mapping_evidence = "Directory is not described by the bundle README."
        warnings.append(f"unknown annotation directory: {source.parent.name}")
    else:
        target_body = family.target_body
        instrument = family.instrument
        product_family = family.product_family
        retrieval_identifier = label_identifier
        identifier_kind = family.identifier_kind
        mapping_status = family.default_mapping_status
        mapping_evidence = family.mapping_evidence

        if family.product_family == "galileo_ssi":
            mapped = galileo_map.lookup(source.name) if galileo_map else ()
            if len(mapped) == 1:
                retrieval_identifier = mapped[0]
                mapping_status = "sidecar_mapped"
                mapping_evidence = "galileo_image_ids.txt"
            elif len(mapped) > 1:
                mapping_status = "ambiguous_sidecar"
                mapping_evidence = (
                    "galileo_image_ids.txt contains multiple image IDs for this "
                    "label filename."
                )
                warnings.append(
                    "ambiguous Galileo image IDs: " + ", ".join(mapped)
                )
            else:
                mapping_status = "unresolved_sidecar"
                mapping_evidence = "No entry in galileo_image_ids.txt."
                warnings.append("missing Galileo image-ID mapping.")

    relative = source.relative_to(root).as_posix()
    return AnnotationRecord(
        annotation_filename=source.name,
        annotation_relative_path=relative,
        annotation_sha256=_sha256_file(source),
        directory=source.parent.name,
        target_body=target_body,
        instrument=instrument,
        product_family=product_family,
        label_identifier=label_identifier,
        retrieval_identifier=retrieval_identifier,
        retrieval_identifier_kind=identifier_kind,
        mapping_status=mapping_status,
        mapping_evidence=mapping_evidence,
        plume_status=plume_present,
        plume_interval_count=len(intervals),
        plume_intervals=intervals,
        limb_point_count=len(points),
        limb_points=points,
        annotator=annotator.strip(),
        warnings=tuple(warnings),
    )


def parse_galileo_image_ids(path: str | Path) -> GalileoImageMap:
    """Parse the bundle's Galileo filename -> image-ID sidecar."""

    source = Path(path).expanduser().resolve(strict=False)
    if not source.is_file():
        return GalileoImageMap(
            source_path=source,
            by_filename={},
            problems=(f"Galileo image-ID map not found: {source}",),
        )

    text = source.read_text(encoding="utf-8", errors="replace")
    pattern = re.compile(r"([A-Za-z0-9]+_label\.yml)\s+([A-Za-z0-9]+)")
    found: dict[str, list[str]] = {}
    for match in pattern.finditer(text):
        filename, image_id = match.group(1), match.group(2).upper()
        found.setdefault(filename, []).append(image_id)

    by_filename: dict[str, tuple[str, ...]] = {}
    problems: list[str] = []
    for filename, image_ids in sorted(found.items()):
        unique = tuple(sorted(set(image_ids)))
        by_filename[filename] = unique
        if len(unique) > 1:
            problems.append(
                f"{filename} maps to multiple image IDs: {', '.join(unique)}"
            )

    return GalileoImageMap(
        source_path=source,
        by_filename=by_filename,
        problems=tuple(problems),
    )


def locate_annotation_root(path: str | Path) -> Path:
    """Find the directory that directly contains the instrument subdirectories."""

    root = Path(path).expanduser().resolve(strict=False)
    if not root.exists():
        raise AnnotationError(f"Annotation path does not exist: {root}")
    if not root.is_dir():
        raise AnnotationError(f"Annotation path is not a directory: {root}")

    nested = root / "plume_annotations"
    if nested.is_dir() and any(nested.rglob("*_label.yml")):
        return nested
    if any(root.rglob("*_label.yml")):
        return root
    raise AnnotationError(f"No *_label.yml files found under: {root}")


def _find_sidecar(root: Path) -> Path | None:
    for candidate in (root / "galileo_image_ids.txt", root.parent / "galileo_image_ids.txt"):
        if candidate.is_file():
            return candidate
    return None


def build_inventory(
    annotation_root: str | Path,
    *,
    galileo_map_path: str | Path | None = None,
) -> AnnotationInventory:
    """Parse every annotation file under the bundle root."""

    root = locate_annotation_root(annotation_root)
    sidecar_path = (
        Path(galileo_map_path).expanduser().resolve(strict=False)
        if galileo_map_path is not None
        else _find_sidecar(root)
    )
    galileo_map = (
        parse_galileo_image_ids(sidecar_path)
        if sidecar_path is not None
        else GalileoImageMap(source_path=None, by_filename={}, problems=())
    )

    files = sorted(root.rglob("*_label.yml"), key=lambda item: item.as_posix().lower())
    if not files:
        raise AnnotationError(f"No annotation files found under: {root}")

    records: list[AnnotationRecord] = []
    problems: list[str] = list(galileo_map.problems)
    for path in files:
        family = FAMILY_SPECS.get(path.parent.name)
        try:
            record = parse_annotation_text(
                path.read_text(encoding="utf-8"),
                source=path,
                root=root,
                family=family,
                galileo_map=galileo_map,
            )
        except (OSError, UnicodeError, AnnotationError) as exc:
            raise AnnotationError(f"Could not parse {path}: {exc}") from exc
        records.append(record)

    records.sort(key=lambda item: item.annotation_relative_path)
    summary = summarize_records(records)
    return AnnotationInventory(
        root=root,
        sidecar_path=sidecar_path if sidecar_path and sidecar_path.is_file() else None,
        records=tuple(records),
        summary=summary,
        problems=tuple(problems),
    )


def annotation_record_from_dict(payload: dict[str, Any]) -> AnnotationRecord:
    """Reconstruct a record from a manifest JSON object without changing values."""

    required = (
        "annotation_filename",
        "annotation_relative_path",
        "annotation_sha256",
        "directory",
        "product_family",
        "label_identifier",
        "retrieval_identifier",
        "retrieval_identifier_kind",
        "mapping_status",
        "mapping_evidence",
        "plume_status",
        "plume_interval_count",
        "plume_intervals",
        "limb_point_count",
        "limb_points",
        "annotator",
        "warnings",
    )
    missing = [key for key in required if key not in payload]
    if missing:
        raise AnnotationError(f"Manifest record is missing fields: {', '.join(missing)}")

    intervals = tuple(
        (float(interval[0]), float(interval[1]))
        for interval in payload["plume_intervals"]
    )
    points = tuple((float(point[0]), float(point[1])) for point in payload["limb_points"])
    return AnnotationRecord(
        annotation_filename=str(payload["annotation_filename"]),
        annotation_relative_path=str(payload["annotation_relative_path"]),
        annotation_sha256=str(payload["annotation_sha256"]),
        directory=str(payload["directory"]),
        target_body=payload.get("target_body"),
        instrument=payload.get("instrument"),
        product_family=str(payload["product_family"]),
        label_identifier=str(payload["label_identifier"]),
        retrieval_identifier=str(payload["retrieval_identifier"]),
        retrieval_identifier_kind=str(payload["retrieval_identifier_kind"]),
        mapping_status=str(payload["mapping_status"]),
        mapping_evidence=str(payload["mapping_evidence"]),
        plume_status=bool(payload["plume_status"]),
        plume_interval_count=int(payload["plume_interval_count"]),
        plume_intervals=intervals,
        limb_point_count=int(payload["limb_point_count"]),
        limb_points=points,
        annotator=str(payload["annotator"]),
        warnings=tuple(str(warning) for warning in payload["warnings"]),
    )


def summarize_records(records: tuple[AnnotationRecord, ...] | list[AnnotationRecord]) -> dict[str, Any]:
    """Deterministic counts used by manifest and validation reports."""

    total = len(records)
    positives = sum(record.plume_status for record in records)
    intervals = sum(record.plume_interval_count for record in records)
    limb_histogram = Counter(record.limb_point_count for record in records)
    return {
        "total_annotations": total,
        "plume_positive": positives,
        "plume_negative": total - positives,
        "total_plume_intervals": intervals,
        "by_directory": dict(sorted(Counter(record.directory for record in records).items())),
        "by_target": dict(
            sorted(Counter(record.target_body or "(unresolved)" for record in records).items())
        ),
        "by_instrument": dict(
            sorted(Counter(record.instrument or "(unresolved)" for record in records).items())
        ),
        "by_annotator": dict(sorted(Counter(record.annotator for record in records).items())),
        "by_mapping_status": dict(
            sorted(Counter(record.mapping_status for record in records).items())
        ),
        "limb_point_count_histogram": {
            str(key): limb_histogram[key] for key in sorted(limb_histogram)
        },
        "annotations_with_warnings": sum(bool(record.warnings) for record in records),
    }
