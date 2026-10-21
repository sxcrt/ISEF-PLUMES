"""Build the sanitized review manifest and the comparison-only label map.

This is a build-time module.  It reads the existing released annotation manifest
to obtain limb points (the required limb-circle reference) and the acquisition
log to obtain verified image identities.  It writes:

* ``review_manifest.json`` - image identity, dimensions, product paths, and limb
  geometry only; consumed by the GUI.
* ``release_label_map.json`` - verified image-ID to released-YAML mapping only;
  consumed by the comparison script and never by the GUI.

Released plume intervals and positive/negative status are never copied into
either output.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from planetary_plume.acquisition import sha256_file
from planetary_plume.annotations import annotation_record_from_dict
from planetary_plume.image_readers import ImageReadError, load_image
from planetary_plume.review_manifest import (
    LimbCircle,
    ReviewImage,
    ReviewManifestError,
    assert_no_released_label_fields,
    review_manifest_payload,
)
from planetary_plume.validation import GeometryError, fit_circle

RELEASE_LABEL_MAP_FORMAT = "planetary-plume-release-label-map"
RELEASE_LABEL_MAP_VERSION = 1
DOWNLOAD_OK = {"downloaded", "resumed", "skipped_existing"}


class ReviewManifestBuildError(RuntimeError):
    """Raised when a review manifest cannot be built safely."""


@dataclass(frozen=True)
class BuildProblem:
    annotation_relative_path: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {
            "annotation_relative_path": self.annotation_relative_path,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class BuildResult:
    review_manifest_path: Path
    label_map_path: Path
    image_count: int
    problems: tuple[BuildProblem, ...]

    def summary(self) -> dict[str, Any]:
        return {
            "review_manifest": str(self.review_manifest_path),
            "release_label_map": str(self.label_map_path),
            "image_count": self.image_count,
            "skipped_or_problem_count": len(self.problems),
            "problems": [problem.to_dict() for problem in self.problems],
        }


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ReviewManifestBuildError(f"Required JSON file not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReviewManifestBuildError(f"Could not read {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReviewManifestBuildError(f"{path} must contain a JSON object.")
    return payload


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="",
    )
    os.replace(temporary, path)


def _backup_existing(path: Path) -> Path | None:
    if not path.is_file():
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"{path.name}.{stamp}.bak")
    counter = 1
    while backup.exists():
        backup = path.with_name(f"{path.name}.{stamp}.{counter}.bak")
        counter += 1
    os.replace(path, backup)
    return backup


def _image_id_for(entry: dict[str, Any]) -> tuple[str, str, str]:
    family = str(entry.get("product_family") or "")
    resolved_image_id = entry.get("resolved_image_id")
    resolved_product_id = entry.get("resolved_product_id")
    if not family:
        raise ReviewManifestBuildError("Acquisition entry has no product_family.")
    if family == "galileo_ssi":
        if not resolved_image_id:
            raise ReviewManifestBuildError(
                "Galileo entry has no verified resolved_image_id; refusing a filename guess."
            )
        return f"{family}:{resolved_image_id}", str(resolved_image_id), str(resolved_product_id or "")
    if family == "new_horizons_lorri":
        if not resolved_product_id:
            raise ReviewManifestBuildError(
                "LORRI entry has no verified resolved_product_id; refusing a filename guess."
            )
        return f"{family}:{resolved_product_id}", str(resolved_product_id), str(resolved_product_id)
    key = resolved_image_id or resolved_product_id
    if not key:
        raise ReviewManifestBuildError(
            f"Acquisition entry for {family} has no verified image or product identifier."
        )
    return f"{family}:{key}", str(key), str(resolved_product_id or key)


def _display_name(family: str, image_key: str, product_id: str) -> str:
    if family == "galileo_ssi":
        suffix = f" ({product_id})" if product_id else ""
        return f"Galileo SSI {image_key}{suffix}"
    if family == "new_horizons_lorri":
        return f"New Horizons LORRI {product_id or image_key}"
    return f"{family} {image_key}"


def build_review_manifest(
    annotation_manifest_path: str | Path,
    acquisition_log_path: str | Path,
    review_manifest_path: str | Path,
    label_map_path: str | Path,
    *,
    force: bool = False,
    generated_at_utc: str | None = None,
) -> BuildResult:
    """Join the existing manifest to the acquisition log and write both outputs."""

    manifest_source = Path(annotation_manifest_path).expanduser().resolve(strict=False)
    acquisition_source = Path(acquisition_log_path).expanduser().resolve(strict=False)
    output_manifest = Path(review_manifest_path).expanduser().resolve(strict=False)
    output_label_map = Path(label_map_path).expanduser().resolve(strict=False)

    for destination in (output_manifest, output_label_map):
        if destination.exists() and not force:
            raise ReviewManifestBuildError(
                f"Refusing to overwrite existing file: {destination}. "
                "Move it aside or pass --force to create a timestamped backup."
            )

    annotation_payload = _load_json(manifest_source)
    records = annotation_payload.get("records")
    if not isinstance(records, list) or not records:
        raise ReviewManifestBuildError(f"{manifest_source} contains no 'records' list.")

    records_by_path: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise ReviewManifestBuildError("Annotation manifest records must be objects.")
        relative = record.get("annotation_relative_path")
        if not isinstance(relative, str) or not relative:
            raise ReviewManifestBuildError("Annotation record has no annotation_relative_path.")
        records_by_path.setdefault(relative, []).append(record)

    acquisition_payload = _load_json(acquisition_source)
    entries = acquisition_payload.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ReviewManifestBuildError(f"{acquisition_source} contains no 'entries' list.")

    problems: list[BuildProblem] = []
    images: list[ReviewImage] = []
    mappings: list[dict[str, Any]] = []

    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            problems.append(BuildProblem(f"entries[{index}]", "Entry is not an object."))
            continue
        relative = str(entry.get("annotation_relative_path") or "")
        if not relative:
            problems.append(BuildProblem(f"entries[{index}]", "Entry has no annotation path."))
            continue
        if entry.get("mapping_status") != "resolved":
            problems.append(
                BuildProblem(relative, f"Mapping status is {entry.get('mapping_status')!r}, not resolved.")
            )
            continue
        if entry.get("download_status") not in DOWNLOAD_OK:
            problems.append(
                BuildProblem(
                    relative,
                    f"Image download status is {entry.get('download_status')!r}, not usable.",
                )
            )
            continue

        candidates = records_by_path.get(relative, [])
        if not candidates:
            problems.append(BuildProblem(relative, "No annotation record matches this entry."))
            continue
        if len(candidates) > 1:
            problems.append(
                BuildProblem(relative, "Multiple annotation records share this relative path.")
            )
            continue
        record_payload = candidates[0]
        entry_sha = str(entry.get("annotation_sha256") or "")
        record_sha = str(record_payload.get("annotation_sha256") or "")
        if not entry_sha or entry_sha != record_sha:
            problems.append(
                BuildProblem(relative, "Annotation SHA256 differs between manifest and acquisition log.")
            )
            continue

        image_path_value = entry.get("image_path")
        if not image_path_value:
            problems.append(BuildProblem(relative, "Acquisition entry has no image_path."))
            continue
        image_path = Path(str(image_path_value)).expanduser().resolve(strict=False)
        if not image_path.is_file():
            problems.append(BuildProblem(relative, f"Image not found: {image_path}"))
            continue

        label_path_value = entry.get("label_path")
        label_path = (
            Path(str(label_path_value)).expanduser().resolve(strict=False)
            if label_path_value
            else None
        )
        if image_path.suffix.lower() == ".img" and (label_path is None or not label_path.is_file()):
            problems.append(BuildProblem(relative, f"PDS label not found: {label_path}"))
            continue

        try:
            record = annotation_record_from_dict(record_payload)
        except (KeyError, TypeError, ValueError) as exc:
            problems.append(BuildProblem(relative, f"Invalid annotation record: {exc}"))
            continue

        try:
            image = load_image(image_path, label_path)
        except (ImageReadError, OSError, ValueError) as exc:
            problems.append(BuildProblem(relative, f"Image could not be loaded: {exc}"))
            continue

        if entry.get("image_sha256"):
            actual_sha = sha256_file(image_path)
            if actual_sha != str(entry["image_sha256"]):
                problems.append(
                    BuildProblem(relative, "Image SHA256 no longer matches the acquisition log.")
                )
                continue

        try:
            circle = fit_circle(record.limb_points)
        except GeometryError as exc:
            problems.append(BuildProblem(relative, f"Limb circle could not be fitted: {exc}"))
            continue

        try:
            image_id, image_key, product_id = _image_id_for(entry)
        except ReviewManifestBuildError as exc:
            problems.append(BuildProblem(relative, str(exc)))
            continue

        family = str(entry.get("product_family") or "")
        target = record.target_body or entry.get("target") or "Unknown"
        instrument = record.instrument or entry.get("instrument") or "Unknown"
        display_name = _display_name(family, image_key, product_id or image_path.name)

        try:
            review_image = ReviewImage(
                image_id=image_id,
                display_name=display_name,
                product_family=family,
                target=str(target),
                instrument=str(instrument),
                width=image.width,
                height=image.height,
                image_format=image.format,
                product_id=product_id or image_path.name,
                product_path=str(image_path),
                pds_label_path=str(label_path) if label_path else None,
                image_sha256=str(entry.get("image_sha256") or sha256_file(image_path)),
                limb=LimbCircle(
                    center_x=circle.center_x,
                    center_y=circle.center_y,
                    radius=circle.radius,
                    rms_residual=circle.rms_residual,
                ),
            )
        except (ReviewManifestError, TypeError, ValueError) as exc:
            problems.append(BuildProblem(relative, f"Invalid review image: {exc}"))
            continue

        images.append(review_image)
        mappings.append(
            {
                "image_id": image_id,
                "annotation_relative_path": relative,
                "annotation_sha256": entry_sha,
                "annotation_filename": Path(relative).name,
                "release_directory": Path(relative).parent.name,
                "product_family": family,
            }
        )

    if not images:
        raise ReviewManifestBuildError(
            "No usable images were found. Problems: "
            + ("; ".join(problem.detail for problem in problems) or "none")
        )

    image_ids = [image.image_id for image in images]
    duplicates = sorted({value for value in image_ids if image_ids.count(value) > 1})
    if duplicates:
        raise ReviewManifestBuildError(
            "Verified image_id collision: " + ", ".join(duplicates)
            + ". Refusing to guess which image is meant."
        )

    # Neutral ordering: never group or order by released class.
    images.sort(key=lambda image: (image.product_family, image.image_id))
    mappings.sort(key=lambda item: (str(item["product_family"]), str(item["image_id"])))

    path_counts = Counter(str(item["annotation_relative_path"]) for item in mappings)
    duplicate_paths = sorted(path for path, count in path_counts.items() if count > 1)
    if duplicate_paths:
        raise ReviewManifestBuildError(
            "The same released annotation path would map to multiple images: "
            + ", ".join(duplicate_paths)
            + ". Refusing to create an ambiguous mapping."
        )

    generated_at = generated_at_utc or _utc_now()
    source = {
        "annotation_manifest": str(manifest_source),
        "annotation_manifest_sha256": sha256_file(manifest_source),
        "acquisition_log": str(acquisition_source),
        "acquisition_log_sha256": sha256_file(acquisition_source),
        "note": (
            "Review manifest contains image identity, dimensions, product paths, "
            "and fitted limb geometry only. Released plume sectors and class "
            "status are deliberately excluded."
        ),
    }
    manifest_payload = review_manifest_payload(
        generated_at_utc=generated_at,
        source=source,
        images=images,
    )
    label_map_payload = {
        "format": RELEASE_LABEL_MAP_FORMAT,
        "format_version": RELEASE_LABEL_MAP_VERSION,
        "generated_at_utc": generated_at,
        "source": {
            "annotation_manifest": str(manifest_source),
            "annotation_manifest_sha256": source["annotation_manifest_sha256"],
            "acquisition_log": str(acquisition_source),
            "acquisition_log_sha256": source["acquisition_log_sha256"],
            "note": (
                "Comparison-only mapping. The GUI must not read this file. "
                "Released intervals and class status are not stored here."
            ),
        },
        "mappings": mappings,
    }
    assert_no_released_label_fields(manifest_payload)

    if force:
        _backup_existing(output_manifest)
        _backup_existing(output_label_map)

    try:
        _atomic_write_json(output_manifest, manifest_payload)
        _atomic_write_json(output_label_map, label_map_payload)
    except OSError as exc:
        raise ReviewManifestBuildError(
            f"Could not write review manifest outputs: {exc}"
        ) from exc

    return BuildResult(
        review_manifest_path=output_manifest,
        label_map_path=output_label_map,
        image_count=len(images),
        problems=tuple(problems),
    )


def load_release_label_map(path: str | Path) -> dict[str, Any]:
    """Load and validate the comparison-only label map."""

    source = Path(path).expanduser().resolve(strict=False)
    payload = _load_json(source)
    assert_no_released_label_fields(payload)
    if payload.get("format") != RELEASE_LABEL_MAP_FORMAT:
        raise ReviewManifestBuildError(
            f"Unsupported release label map format: {payload.get('format')!r}."
        )
    if payload.get("format_version") != RELEASE_LABEL_MAP_VERSION:
        raise ReviewManifestBuildError(
            f"Unsupported release label map version: {payload.get('format_version')!r}."
        )
    mappings = payload.get("mappings")
    if not isinstance(mappings, list) or not mappings:
        raise ReviewManifestBuildError("Release label map contains no mappings.")
    return payload
