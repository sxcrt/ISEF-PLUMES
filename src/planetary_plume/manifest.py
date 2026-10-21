"""Manifest export for the Zenodo 2556063 annotation inventory."""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from planetary_plume.annotations import AnnotationInventory, AnnotationRecord

CSV_FIELDS = (
    "annotation_filename",
    "annotation_relative_path",
    "target_body",
    "instrument",
    "label_identifier",
    "retrieval_identifier",
    "retrieval_identifier_kind",
    "mapping_status",
    "mapping_evidence",
    "plume_status",
    "plume_interval_count",
    "plume_intervals",
    "limb_point_count",
    "annotator",
    "annotation_sha256",
    "warnings",
)


class ManifestError(RuntimeError):
    """Raised when a manifest cannot be written safely."""


def _record_row(record: AnnotationRecord) -> dict[str, Any]:
    return {
        "annotation_filename": record.annotation_filename,
        "annotation_relative_path": record.annotation_relative_path,
        "target_body": record.target_body or "",
        "instrument": record.instrument or "",
        "label_identifier": record.label_identifier,
        "retrieval_identifier": record.retrieval_identifier,
        "retrieval_identifier_kind": record.retrieval_identifier_kind,
        "mapping_status": record.mapping_status,
        "mapping_evidence": record.mapping_evidence,
        "plume_status": record.plume_status,
        "plume_interval_count": record.plume_interval_count,
        "plume_intervals": json.dumps(
            [list(interval) for interval in record.plume_intervals],
            separators=(",", ":"),
        ),
        "limb_point_count": record.limb_point_count,
        "annotator": record.annotator,
        "annotation_sha256": record.annotation_sha256,
        "warnings": "; ".join(record.warnings),
    }


def manifest_rows(inventory: AnnotationInventory) -> list[dict[str, Any]]:
    """Return one flat row per annotation, suitable for CSV/JSON export."""

    return [_record_row(record) for record in inventory.records]


def manifest_payload(
    inventory: AnnotationInventory,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build the JSON manifest with explicit provenance and unresolved fields."""

    timestamp = generated_at or datetime.now(timezone.utc).isoformat()
    return {
        "manifest_version": 1,
        "generated_at_utc": timestamp,
        "source": {
            "zenodo_record": "2556063",
            "doi": "10.5281/zenodo.2556063",
            "annotation_root": str(inventory.root),
            "galileo_image_id_map": (
                str(inventory.sidecar_path) if inventory.sidecar_path else None
            ),
        },
        "notes": [
            "This manifest describes annotation files, not image pixels.",
            "plume_status is an annotation status, not a physical confirmation.",
            "retrieval_identifier is evidence-backed only where mapping_status "
            "says so; unresolved identifiers are not PDS product IDs.",
            "Original annotations are read-only and are not modified by this tool.",
        ],
        "summary": inventory.summary,
        "problems": list(inventory.problems),
        "records": [record.to_dict() for record in inventory.records],
    }


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="")
    os.replace(temporary, path)


def write_manifest(
    inventory: AnnotationInventory,
    output_dir: str | Path,
    *,
    stem: str = "zenodo_2556063_manifest",
    generated_at: str | None = None,
) -> dict[str, Path]:
    """Write JSON and CSV manifests.  Source annotations are never touched."""

    destination = Path(output_dir).expanduser().resolve(strict=False)
    json_path = destination / f"{stem}.json"
    csv_path = destination / f"{stem}.csv"

    payload = manifest_payload(inventory, generated_at=generated_at)
    _atomic_write_text(
        json_path,
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    )

    destination.mkdir(parents=True, exist_ok=True)
    temporary_csv = csv_path.with_name(csv_path.name + ".tmp")
    try:
        with temporary_csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerows(manifest_rows(inventory))
        os.replace(temporary_csv, csv_path)
    except OSError as exc:
        raise ManifestError(f"Could not write CSV manifest {csv_path}: {exc}") from exc
    finally:
        if temporary_csv.exists():
            temporary_csv.unlink(missing_ok=True)

    return {"json": json_path, "csv": csv_path}


def format_manifest_summary(inventory: AnnotationInventory) -> str:
    """Human-readable summary for CLI output."""

    summary = inventory.summary
    lines = [
        "Zenodo 2556063 annotation manifest",
        "==================================",
        f"Annotation root: {inventory.root}",
        f"Galileo sidecar: {inventory.sidecar_path or '(not found)'}",
        f"Annotations parsed: {summary['total_annotations']:,}",
        f"Plume-positive annotations: {summary['plume_positive']:,}",
        f"Plume-negative annotations: {summary['plume_negative']:,}",
        f"Plume angular intervals: {summary['total_plume_intervals']:,}",
        "",
        "By directory:",
    ]
    for name, count in summary["by_directory"].items():
        lines.append(f"  {name:<30} {count:,}")
    lines.append("")
    lines.append("By mapping status:")
    for name, count in summary["by_mapping_status"].items():
        lines.append(f"  {name:<30} {count:,}")
    if inventory.problems:
        lines.append("")
        lines.append("Problems:")
        lines.extend(f"  {problem}" for problem in inventory.problems)
    lines.extend(
        [
            "",
            "This manifest does not contain image pixels and does not establish",
            "physical plume truth. Unresolved identifiers must be resolved by an",
            "explicit adapter; they are not PDS product IDs.",
        ]
    )
    return "\n".join(lines)
