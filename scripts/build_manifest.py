#!/usr/bin/env python
"""Build the reproducible annotation manifest from the extracted bundle."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from planetary_plume.annotations import (  # noqa: E402
    EXPECTED_ANNOTATION_COUNT,
    AnnotationError,
    build_inventory,
)
from planetary_plume.config import ConfigError, load_config  # noqa: E402
from planetary_plume.manifest import (  # noqa: E402
    ManifestError,
    format_manifest_summary,
    write_manifest,
)


def _resolve(value: Path | None, default: Path) -> Path:
    if value is None:
        return default
    candidate = value.expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    return candidate.resolve(strict=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the Zenodo 2556063 annotation manifest (read-only)."
    )
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument(
        "--annotations-dir",
        type=Path,
        default=None,
        help="Defaults to data/raw/zenodo_2556063/annotations.",
    )
    parser.add_argument(
        "--galileo-map",
        type=Path,
        default=None,
        help="Optional explicit path to galileo_image_ids.txt.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Defaults to outputs/manifests.",
    )
    parser.add_argument("--stem", default="zenodo_2556063_manifest")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    annotations_dir = _resolve(
        args.annotations_dir,
        config.paths.data_dir / "raw" / "zenodo_2556063" / "annotations",
    )
    output_dir = _resolve(args.output_dir, config.paths.outputs_dir / "manifests")
    galileo_map = _resolve(args.galileo_map, Path()) if args.galileo_map else None

    try:
        inventory = build_inventory(annotations_dir, galileo_map_path=galileo_map)
        paths = write_manifest(inventory, output_dir, stem=args.stem)
    except (AnnotationError, ManifestError, OSError) as exc:
        print(f"Manifest generation failed: {exc}", file=sys.stderr)
        return 2

    print(format_manifest_summary(inventory))
    print()
    print(f"JSON manifest: {paths['json']}")
    print(f"CSV manifest:  {paths['csv']}")

    if inventory.summary["total_annotations"] != EXPECTED_ANNOTATION_COUNT:
        print(
            f"[WARN] Expected {EXPECTED_ANNOTATION_COUNT} annotations, found "
            f"{inventory.summary['total_annotations']}. This is not the reviewed bundle.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
