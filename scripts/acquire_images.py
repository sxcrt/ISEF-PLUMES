#!/usr/bin/env python
"""Resolve and acquire a small, stratified Io image sample.

The default run is deliberately small.  Use ``--dry-run`` to inspect mappings
without downloading pixels.
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

from planetary_plume.acquisition import (  # noqa: E402
    AcquisitionError,
    acquire_sample,
    acquisition_summary,
    plan_io_sample,
)
from planetary_plume.annotations import (  # noqa: E402
    AnnotationError,
    annotation_record_from_dict,
)
from planetary_plume.config import ConfigError, load_config  # noqa: E402
from planetary_plume.pds import (  # noqa: E402
    PdsError,
    PdsSolrClient,
    mapping_report,
    mapping_summary,
    write_mapping_report,
)


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
        description="Resolve and download a small stratified Io sample."
    )
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Defaults to outputs/manifests/zenodo_2556063_manifest.json.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Defaults to outputs/acquisition/io_sample.",
    )
    parser.add_argument("--per-stratum", type=int, default=3)
    parser.add_argument(
        "--families",
        default="galileo_ssi,new_horizons_lorri",
        help="Comma-separated product families.",
    )
    parser.add_argument("--target", default="Io")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow replacing final downloaded files (off by default).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve mappings only; do not download images.",
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
    output_dir = _resolve(
        args.output_dir,
        config.paths.outputs_dir / "acquisition" / "io_sample",
    )
    families = tuple(item.strip() for item in args.families.split(",") if item.strip())

    if not manifest_path.is_file():
        print(
            f"Manifest not found: {manifest_path}. Run scripts/build_manifest.py first.",
            file=sys.stderr,
        )
        return 2
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        records = [
            annotation_record_from_dict(item) for item in payload.get("records", [])
        ]
    except (OSError, json.JSONDecodeError, AnnotationError) as exc:
        print(f"Could not read manifest: {exc}", file=sys.stderr)
        return 2

    try:
        plan = plan_io_sample(
            records,
            per_stratum=args.per_stratum,
            target_body=args.target,
            families=families,
        )
    except AcquisitionError as exc:
        print(f"Sample planning failed: {exc}", file=sys.stderr)
        return 2

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        output_dir / "sample_plan.json",
        {
            "manifest": str(manifest_path),
            "target": args.target,
            "families": list(families),
            "per_stratum": args.per_stratum,
            "plan": plan.to_dict(),
            "warnings": list(plan.warnings),
        },
    )
    print(f"Manifest: {manifest_path}")
    print(f"Selected {len(plan.records)} annotation(s) for target {args.target}.")
    for stratum, count in plan.strata.items():
        print(f"  {stratum}: {count}")
    for warning in plan.warnings:
        print(f"  [WARN] {warning}")

    client = PdsSolrClient(timeout_seconds=args.timeout)
    try:
        mappings = mapping_report(
            plan.records,
            client,
            target_body=args.target,
            families=families,
        )
    except PdsError as exc:
        print(f"PDS mapping failed: {exc}", file=sys.stderr)
        return 2

    mapping_path = write_mapping_report(mappings, output_dir / "mapping_report.json")
    summary = mapping_summary(mappings)
    print(f"Mapping report: {mapping_path}")
    print(f"Mapping status: {summary['by_status']}")
    for mapping in mappings:
        product = mapping.product.product_id if mapping.product else "(none)"
        print(
            f"  {mapping.mapping_status:<10} {mapping.annotation_relative_path} "
            f"-> {mapping.retrieval_identifier} / {product}"
        )
        if mapping.error:
            print(f"             {mapping.error}")

    if args.dry_run:
        failed = [
            mapping
            for mapping in mappings
            if mapping.mapping_status not in {"resolved", "unsupported"}
        ]
        print("Dry run complete; no images downloaded.")
        return 1 if failed else 0

    try:
        entries = acquire_sample(
            plan,
            client,
            output_dir / "images",
            timeout_seconds=args.timeout,
            retries=args.retries,
            delay_seconds=args.delay,
            overwrite=args.overwrite,
            log_path=output_dir / "acquisition_log.json",
        )
    except (AcquisitionError, PdsError, OSError) as exc:
        print(f"Image acquisition failed: {exc}", file=sys.stderr)
        return 2

    acq_summary = acquisition_summary(entries)
    print(f"Acquisition log: {output_dir / 'acquisition_log.json'}")
    print(f"Acquisition status: {acq_summary['by_download_status']}")
    print(f"Image bytes: {acq_summary['total_image_bytes']:,}")
    failures = [
        entry
        for entry in entries
        if entry.download_status not in {"downloaded", "resumed", "skipped_existing"}
        or entry.mapping_status != "resolved"
    ]
    if failures:
        print(f"[WARN] {len(failures)} acquisition failure(s); see the log.", file=sys.stderr)
        return 1
    print("Sample acquired without falling back to similar filenames.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
