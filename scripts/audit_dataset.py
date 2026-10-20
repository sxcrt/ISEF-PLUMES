#!/usr/bin/env python
"""Describe a dataset directory without assuming its format or labels.

The audit is descriptive. It cannot establish provenance, licensing, annotation
quality, or scientific suitability.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from planetary_plume.config import ConfigError, load_config  # noqa: E402
from planetary_plume.dataset_audit import (  # noqa: E402
    DatasetAuditError,
    audit_dataset,
    audit_to_dict,
    format_audit,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Inventory a dataset directory and sample image dimensions. "
            "No dataset format or labels are assumed."
        )
    )
    parser.add_argument(
        "dataset_dir",
        nargs="?",
        type=Path,
        default=None,
        help=(
            "Directory to audit. Defaults to dataset.root, or paths.data_dir "
            "when dataset.root is null."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="YAML configuration file (default: PLUME_CONFIG or config/default.yaml).",
    )
    parser.add_argument(
        "--max-images",
        type=int,
        default=None,
        help=(
            "Number of image files to inspect; 0 means all. Defaults to "
            "dataset.dimension_sample_size in the configuration."
        ),
    )
    parser.add_argument(
        "--json",
        dest="json_path",
        type=Path,
        default=None,
        metavar="PATH",
        help="Write a JSON version of the report to PATH.",
    )
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    if args.dataset_dir is not None:
        dataset_dir = args.dataset_dir
        source = "command line"
    elif config.dataset.root is not None:
        dataset_dir = config.dataset.root
        source = "dataset.root"
    else:
        dataset_dir = config.paths.data_dir
        source = "paths.data_dir"

    sample_size = (
        args.max_images
        if args.max_images is not None
        else config.dataset.dimension_sample_size
    )
    if sample_size < 0:
        print("--max-images must be zero or a positive integer.", file=sys.stderr)
        return 2

    print(f"Auditing: {dataset_dir}")
    print(f"Source: {source}")
    print()

    try:
        report = audit_dataset(
            dataset_dir,
            image_extensions=config.dataset.image_extensions,
            dimension_sample_size=sample_size,
        )
    except DatasetAuditError as exc:
        print(f"Dataset audit failed: {exc}", file=sys.stderr)
        return 2

    print(format_audit(report))

    if args.json_path is not None:
        json_path = args.json_path.expanduser()
        if not json_path.is_absolute():
            json_path = Path.cwd() / json_path
        try:
            json_path.parent.mkdir(parents=True, exist_ok=True)
            json_path.write_text(
                json.dumps(audit_to_dict(report), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            print(f"Could not write JSON report: {exc}", file=sys.stderr)
            return 2
        print(f"\nJSON report written to: {json_path}")

    if report.total_files == 0 or report.total_bytes == 0:
        print(
            "\n[WARN] The directory contains no non-empty files (only "
            "placeholders or empty files). Point the audit at the actual "
            "dataset directory before drawing conclusions."
        )
        return 2

    print(
        "\nAudit complete. This establishes file inventory only, not dataset "
        "suitability; complete the gate in docs/research_plan.md."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
