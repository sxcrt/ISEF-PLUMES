#!/usr/bin/env python
"""Run the exploratory angular-convention diagnostic on acquired positives."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from planetary_plume.acquisition import acquisition_entry_from_dict  # noqa: E402
from planetary_plume.annotations import (  # noqa: E402
    AnnotationError,
    annotation_record_from_dict,
)
from planetary_plume.config import ConfigError, load_config  # noqa: E402
from planetary_plume.convention import diagnose_record  # noqa: E402
from planetary_plume.image_readers import load_image  # noqa: E402
from planetary_plume.validation import fit_circle  # noqa: E402


def _resolve(value: Path | None, default: Path) -> Path:
    if value is None:
        return default
    candidate = value.expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    return candidate.resolve(strict=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare documented and alternative plume-angle conventions."
    )
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--acquisition-log", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
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
    output_path = _resolve(
        args.output,
        config.paths.outputs_dir / "validation" / "io_sample" / "angle_convention_diagnostic.json",
    )

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        records = {
            item["annotation_relative_path"]: annotation_record_from_dict(item)
            for item in manifest.get("records", [])
        }
        acquisition = json.loads(acquisition_path.read_text(encoding="utf-8"))
        entries = [
            acquisition_entry_from_dict(item)
            for item in acquisition.get("entries", [])
        ]
    except (OSError, json.JSONDecodeError, AnnotationError, KeyError) as exc:
        print(f"Could not read inputs: {exc}", file=sys.stderr)
        return 2

    results = []
    for entry in entries:
        record = records.get(entry.annotation_relative_path)
        if record is None or not record.plume_status or not entry.image_path:
            continue
        try:
            image = load_image(entry.image_path, entry.label_path)
            circle = fit_circle(record.limb_points)
            results.append(diagnose_record(image, record, circle))
        except (OSError, ValueError) as exc:
            results.append(
                {
                    "annotation_relative_path": entry.annotation_relative_path,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    payload = {
        "convention_note": (
            "Scores are exploratory brightness contrasts, not proof of the "
            "annotation convention. Inconsistent scores mean the angular "
            "reference/orientation is unresolved."
        ),
        "results": results,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(output_path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output_path)

    for result in results:
        print(result["annotation_relative_path"])
        if "error" in result:
            print(f"  ERROR: {result['error']}")
            continue
        scores = {
            key: round(value, 2) if value is not None else None
            for key, value in result["scores"].items()
        }
        print(f"  highest={result['highest']} scores={scores}")
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
