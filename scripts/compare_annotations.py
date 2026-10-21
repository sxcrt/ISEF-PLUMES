#!/usr/bin/env python
"""Compare saved independent annotations with released labels.

Run this only after independently reviewing and saving the images.  The GUI
never performs this comparison and never reads the released labels.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from planetary_plume.annotation_store import (  # noqa: E402
    AnnotationStoreError,
    file_sha256,
    load_session,
)
from planetary_plume.config import ConfigError, load_config  # noqa: E402
from planetary_plume.review_compare import (  # noqa: E402
    ComparisonError,
    DISCLAIMER,
    compare_session,
    load_label_map,
    write_report,
)
from planetary_plume.review_manifest import (  # noqa: E402
    ReviewManifestError,
    load_review_manifest,
)


def _resolve(value: Path | None, default: Path) -> Path:
    if value is None:
        return default
    path = value.expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve(strict=False)


def _default_annotation_root() -> Path:
    try:
        config = load_config()
        return (
            config.paths.data_dir
            / "raw"
            / "zenodo_2556063"
            / "annotations"
            / "plume_annotations"
        ).resolve(strict=False)
    except ConfigError:
        return PROJECT_ROOT / "data" / "raw" / "zenodo_2556063" / "annotations" / "plume_annotations"


def _unique_stem(directory: Path, stem: str, suffix: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = directory / f"{stem}_{stamp}{suffix}"
    counter = 1
    while candidate.exists():
        candidate = directory / f"{stem}_{stamp}_{counter}{suffix}"
        counter += 1
    return candidate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare saved independent annotations with released plume labels. "
            "This is a separate, explicit stage; the annotation GUI never runs it."
        )
    )
    parser.add_argument(
        "--session",
        type=Path,
        default=None,
        help="Saved independent annotation JSON (default: annotations/independent/independent_review.json).",
    )
    parser.add_argument(
        "--review-manifest",
        type=Path,
        default=None,
        help="Sanitized review manifest (default: annotations/independent/review_manifest.json).",
    )
    parser.add_argument(
        "--label-map",
        type=Path,
        default=None,
        help="Verified image-ID mapping (default: annotations/independent/release_label_map.json).",
    )
    parser.add_argument(
        "--annotations-root",
        type=Path,
        default=None,
        help="Released annotation bundle root (default: data/raw/zenodo_2556063/annotations/plume_annotations).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output JSON path. Must not already exist. Defaults to a timestamped file under outputs/comparisons/.",
    )
    parser.add_argument(
        "--markdown",
        type=Path,
        default=None,
        help="Output Markdown path. Must not already exist. Defaults to the JSON stem with .md.",
    )
    parser.add_argument(
        "--tolerance-deg",
        type=float,
        default=10.0,
        help="Reporting tolerance for near-miss classification (default: 10 degrees).",
    )
    parser.add_argument(
        "--include-incomplete",
        action="store_true",
        help=(
            "Also compare saved reviews that are not marked complete. They are "
            "reported as INCONCLUSIVE. By default only completed reviews are compared."
        ),
    )
    args = parser.parse_args(argv)

    session_path = _resolve(
        args.session,
        PROJECT_ROOT / "annotations" / "independent" / "independent_review.json",
    )
    manifest_path = _resolve(
        args.review_manifest,
        PROJECT_ROOT / "annotations" / "independent" / "review_manifest.json",
    )
    label_map_path = _resolve(
        args.label_map,
        PROJECT_ROOT / "annotations" / "independent" / "release_label_map.json",
    )
    annotation_root = _resolve(args.annotations_root, _default_annotation_root())

    if not session_path.is_file():
        print(
            f"ERROR: saved independent annotations not found: {session_path}\n"
            "Complete and save at least one independent review first.",
            file=sys.stderr,
        )
        return 2

    try:
        session = load_session(session_path)
        manifest = load_review_manifest(manifest_path)
        label_map = load_label_map(label_map_path)
    except (AnnotationStoreError, ReviewManifestError, ComparisonError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    session_sha = file_sha256(session_path)
    manifest_sha = file_sha256(manifest_path)
    try:
        report = compare_session(
            session,
            manifest,
            label_map,
            annotation_root,
            tolerance_deg=args.tolerance_deg,
            complete_only=not args.include_incomplete,
            session_path=session_path,
            session_sha256=session_sha,
            review_manifest_path=manifest_path,
            review_manifest_sha256=manifest_sha,
        )
    except ComparisonError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    output_dir = PROJECT_ROOT / "outputs" / "comparisons"
    json_path = _resolve(args.output, _unique_stem(output_dir, "independent_vs_released", ".json"))
    if args.markdown is not None:
        markdown_path = _resolve(args.markdown, json_path.with_suffix(".md"))
    else:
        markdown_path = json_path.with_suffix(".md")

    try:
        written_json, written_markdown = write_report(report, json_path, markdown_path)
    except ComparisonError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    summary = report.summary()
    print("Independent vs released annotation comparison")
    print("==============================================")
    print(f"Compared: {summary['total_compared']}")
    print(f"  excluded incomplete: {summary['excluded_incomplete']}")
    print(f"  agreement: {summary['agreement']}")
    print(f"  disagreement: {summary['disagreement']}")
    print(f"  inconclusive: {summary['inconclusive']}")
    print(f"  missing mapping: {summary['missing_mapping']}")
    print(f"  ambiguous mapping: {summary['ambiguous_mapping']}")
    print(f"  missing released annotation: {summary['missing_released_annotation']}")
    print(f"  stale released annotation: {summary['stale_released_annotation']}")
    print(f"  unreviewed manifest images: {summary['unreviewed_images']}")
    print("")
    print(f"JSON: {written_json}")
    if written_markdown is not None:
        print(f"Markdown: {written_markdown}")
    print("")
    print(DISCLAIMER)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
