#!/usr/bin/env python
"""Download and extract the Zenodo 2556063 annotation bundle.

The bundle is small (~152 KB) and contains annotations, not images.  Existing
archives and extracted annotations are never overwritten.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from planetary_plume.acquisition import AcquisitionError, acquire_annotations  # noqa: E402
from planetary_plume.annotations import (  # noqa: E402
    EXPECTED_ANNOTATION_COUNT,
    AnnotationError,
    build_inventory,
)
from planetary_plume.config import ConfigError, load_config  # noqa: E402


def _resolve(value: Path | None, default: Path) -> Path:
    if value is None:
        return default
    candidate = value.expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    return candidate.resolve(strict=False)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Acquire the Zenodo 2556063 annotation bundle without overwriting."
    )
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Defaults to paths.data_dir from the configuration.",
    )
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="Acquisition summary path; defaults to outputs/acquisition/annotation_acquisition.json.",
    )
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    data_dir = _resolve(args.data_dir, config.paths.data_dir)
    summary_path = _resolve(
        args.json,
        config.paths.outputs_dir / "acquisition" / "annotation_acquisition.json",
    )

    print(f"Data directory: {data_dir}")
    print(f"Acquisition summary: {summary_path}")
    try:
        acquisition = acquire_annotations(
            data_dir,
            timeout_seconds=args.timeout,
            retries=args.retries,
            delay_seconds=args.delay,
        )
        inventory = build_inventory(acquisition.annotation_root)
    except (AcquisitionError, AnnotationError) as exc:
        print(f"Annotation acquisition failed: {exc}", file=sys.stderr)
        return 2

    count = inventory.summary["total_annotations"]
    payload = {
        "acquisition": acquisition.to_dict(),
        "inventory_summary": inventory.summary,
        "inventory_problems": list(inventory.problems),
        "expected_annotation_count": EXPECTED_ANNOTATION_COUNT,
        "annotation_count_matches_expected": count == EXPECTED_ANNOTATION_COUNT,
    }
    _write_json(summary_path, payload)

    print(f"Download status: {acquisition.download.status}")
    print(f"Extraction status: {acquisition.extraction.status}")
    print(f"Annotation root: {acquisition.annotation_root}")
    print(f"Annotations parsed: {count:,}")
    print(
        f"Plume-positive / negative: {inventory.summary['plume_positive']:,} / "
        f"{inventory.summary['plume_negative']:,}"
    )
    if count != EXPECTED_ANNOTATION_COUNT:
        print(
            f"[WARN] Expected {EXPECTED_ANNOTATION_COUNT} annotations, found {count}. "
            "Do not assume this is the reviewed bundle version.",
            file=sys.stderr,
        )
        return 1
    print("Annotation bundle acquired and parsed; source annotations were not modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
