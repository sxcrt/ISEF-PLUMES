#!/usr/bin/env python
"""Validate the acquired Io sample and render annotation overlays."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from planetary_plume.acquisition import (  # noqa: E402
    AcquisitionError,
    acquisition_entry_from_dict,
    acquisition_summary,
)
from planetary_plume.annotations import (  # noqa: E402
    AnnotationError,
    annotation_record_from_dict,
)
from planetary_plume.config import ConfigError, load_config  # noqa: E402
from planetary_plume.validation import (  # noqa: E402
    ValidationError,
    format_validation_report,
    load_overlay_reviews,
    render_overlay,
    validate_acquisition,
    write_validation_report,
)


def _resolve(value: Path | None, default: Path) -> Path:
    if value is None:
        return default
    candidate = value.expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    return candidate.resolve(strict=False)


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "__", value).strip("._") or "overlay"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate the acquired Io sample and render overlays for inspection."
    )
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Defaults to outputs/manifests/zenodo_2556063_manifest.json.",
    )
    parser.add_argument(
        "--acquisition-log",
        type=Path,
        default=None,
        help="Defaults to outputs/acquisition/io_sample/acquisition_log.json.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Defaults to outputs/validation/io_sample.",
    )
    parser.add_argument(
        "--overlay-review",
        type=Path,
        default=None,
        help="Optional JSON file with manually assigned overlay statuses.",
    )
    parser.add_argument(
        "--overlay-status",
        default="UNVERIFIED - inspect before scientific use",
        help="Banner status written into each overlay.",
    )
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    manifest_path = _resolve(
        args.manifest,
        config.paths.outputs_dir / "manifests" / "zenodo_2556063_manifest.json",
    )
    acquisition_path = _resolve(
        args.acquisition_log,
        config.paths.outputs_dir / "acquisition" / "io_sample" / "acquisition_log.json",
    )
    output_dir = _resolve(
        args.output_dir,
        config.paths.outputs_dir / "validation" / "io_sample",
    )

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        records = [
            annotation_record_from_dict(item)
            for item in manifest.get("records", [])
        ]
        acquisition = json.loads(acquisition_path.read_text(encoding="utf-8"))
        entries = [
            acquisition_entry_from_dict(item)
            for item in acquisition.get("entries", [])
        ]
    except (OSError, json.JSONDecodeError, AnnotationError, AcquisitionError) as exc:
        print(f"Could not read manifest or acquisition log: {exc}", file=sys.stderr)
        return 2

    subset_paths = {entry.annotation_relative_path for entry in entries}
    result = validate_acquisition(records, entries, subset_paths=subset_paths)

    overlay_dir = output_dir / "overlays"
    overlay_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[Path] = []
    for item in result.validated:
        filename = _safe_name(item.record.annotation_relative_path) + ".png"
        try:
            rendered.append(
                render_overlay(
                    item.image,
                    item.record,
                    overlay_dir / filename,
                    status=args.overlay_status,
                )
            )
        except (ValidationError, OSError) as exc:
            result.add_issue(
                "overlay_failed",
                item.record.annotation_relative_path,
                f"{type(exc).__name__}: {exc}",
            )

    if args.overlay_review:
        try:
            result.overlay_reviews = load_overlay_reviews(args.overlay_review)
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            print(f"Could not load overlay review: {exc}", file=sys.stderr)
            return 2

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = write_validation_report(result, output_dir / "validation_report.json")
    markdown_path = output_dir / "validation_report.md"
    markdown_path.write_text(format_validation_report(result) + "\n", encoding="utf-8")

    print(format_validation_report(result))
    print()
    print(f"Validation JSON: {json_path}")
    print(f"Validation report: {markdown_path}")
    print(f"Overlays rendered: {len(rendered)} in {overlay_dir}")
    print(f"Acquisition summary: {acquisition_summary(entries)}")
    if not result.overlay_reviews:
        print(
            "[WARN] No manual overlay review supplied. Do not claim visual "
            "alignment until the images have been inspected.",
            file=sys.stderr,
        )
    return 1 if result.issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
