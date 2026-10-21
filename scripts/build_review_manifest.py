#!/usr/bin/env python
"""Build the sanitized independent-review manifest and comparison label map."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from planetary_plume.review_manifest_builder import (  # noqa: E402
    ReviewManifestBuildError,
    build_review_manifest,
)


def _resolve(value: Path | None, default: Path) -> Path:
    if value is None:
        return default
    path = value.expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve(strict=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build the sanitized review manifest used by the independent annotation "
            "GUI. Released plume intervals and class status are never copied."
        )
    )
    parser.add_argument(
        "--annotation-manifest",
        type=Path,
        default=None,
        help="Existing Zenodo/manifest JSON (default: outputs/manifests/zenodo_2556063_manifest.json).",
    )
    parser.add_argument(
        "--acquisition-log",
        type=Path,
        default=None,
        help="Existing acquisition log (default: outputs/acquisition/io_sample/acquisition_log.json).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Sanitized review manifest (default: annotations/independent/review_manifest.json).",
    )
    parser.add_argument(
        "--label-map",
        type=Path,
        default=None,
        help="Comparison-only label map (default: annotations/independent/release_label_map.json).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Move existing outputs to timestamped .bak files before writing.",
    )
    args = parser.parse_args(argv)

    manifest_path = _resolve(
        args.annotation_manifest,
        PROJECT_ROOT / "outputs" / "manifests" / "zenodo_2556063_manifest.json",
    )
    acquisition_path = _resolve(
        args.acquisition_log,
        PROJECT_ROOT / "outputs" / "acquisition" / "io_sample" / "acquisition_log.json",
    )
    output_path = _resolve(
        args.output,
        PROJECT_ROOT / "annotations" / "independent" / "review_manifest.json",
    )
    label_map_path = _resolve(
        args.label_map,
        PROJECT_ROOT / "annotations" / "independent" / "release_label_map.json",
    )

    try:
        result = build_review_manifest(
            manifest_path,
            acquisition_path,
            output_path,
            label_map_path,
            force=args.force,
        )
    except ReviewManifestBuildError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print("Sanitized review manifest built")
    print("===============================")
    print(f"Images: {result.image_count}")
    print(f"Review manifest: {result.review_manifest_path}")
    print(f"Comparison-only label map: {result.label_map_path}")
    if result.problems:
        print("")
        print("Skipped or problematic entries:")
        for problem in result.problems:
            print(f"  - {problem.annotation_relative_path}: {problem.detail}")
    print("")
    print(
        "The review manifest contains image identity, dimensions, product paths, and "
        "fitted limb geometry only. It contains no released plume sectors or class "
        "status. Source annotations and images were read, not modified."
    )
    print("")
    print("Next: python scripts\\annotate_candidates.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
