#!/usr/bin/env python
"""Run a local environment and configuration diagnostic.

Exit status is 0 when core dependencies and configuration are usable. Missing
PyTorch or development tools produce warnings during the foundation phase.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from planetary_plume.config import ConfigError, load_config  # noqa: E402
from planetary_plume.environment import (  # noqa: E402
    collect_environment,
    format_environment_report,
)


def _describe_directory(label: str, path: Path, warnings: list[str]) -> None:
    if path.exists() and path.is_dir():
        if os.access(path, os.W_OK):
            print(f"  [OK]      {label}: {path}")
        else:
            message = f"{label} is not writable: {path}"
            warnings.append(message)
            print(f"  [WARN]    {label}: {path} (not writable)")
    else:
        message = f"{label} does not exist: {path}"
        warnings.append(message)
        print(f"  [WARN]    {label}: {path} (missing)")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Report Python, package, PyTorch/CUDA, and config status."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="YAML configuration file (default: PLUME_CONFIG or config/default.yaml).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings, including missing optional tools, as failures.",
    )
    args = parser.parse_args(argv)

    failures: list[str] = []
    warnings: list[str] = []

    report = collect_environment()
    print(format_environment_report(report))
    print()

    if sys.version_info < (3, 11):
        failures.append(
            f"Python 3.11 or newer is required; found {report.python_version}."
        )

    print("Configuration")
    print("-------------")
    config = None
    try:
        config = load_config(args.config)
        print(f"  [OK]      Loaded: {config.source_path}")
        print(f"  [OK]      Project: {config.project.name}")
        print(f"  [OK]      Random seed: {config.project.random_seed}")
        _describe_directory("Data directory", config.paths.data_dir, warnings)
        _describe_directory("Output directory", config.paths.outputs_dir, warnings)

        if config.dataset.root is not None:
            _describe_directory("Dataset root", config.dataset.root, warnings)
        else:
            print(
                "  [INFO]    Dataset root: not set; audit defaults to the data "
                "directory."
            )
    except ConfigError as exc:
        message = f"Configuration error: {exc}"
        failures.append(message)
        print(f"  [FAIL]    {message}")
        print("            Fix config/default.yaml or pass --config <path>.")

    print()
    print("Dependency summary")
    print("------------------")

    missing_core = report.missing("core")
    if missing_core:
        names = ", ".join(package.distribution for package in missing_core)
        message = f"Missing core dependency(ies): {names}"
        failures.append(message)
        print(f"  [FAIL]    {message}")
        print("            Install with: python -m pip install -r requirements.txt")
    else:
        print("  [OK]      All core dependencies are installed.")

    if report.torch.installed:
        print(f"  [OK]      PyTorch is installed ({report.torch.version}).")
    else:
        message = "PyTorch is not installed (expected during the foundation phase)."
        warnings.append(message)
        print(f"  [WARN]    {message}")
        print("            Install it only when model work begins; see README.md.")

    missing_dev = report.missing("dev")
    if missing_dev:
        names = ", ".join(package.distribution for package in missing_dev)
        message = f"Missing development dependency(ies): {names}"
        warnings.append(message)
        print(f"  [WARN]    {message}")
        print(
            "            Install with: python -m pip install -r requirements-dev.txt"
        )
    else:
        print("  [OK]      Test dependencies are installed.")

    if args.strict and warnings:
        failures.extend(f"Strict mode: {warning}" for warning in warnings)

    print()
    print("Summary")
    print("-------")
    if failures:
        for failure in failures:
            print(f"  [FAIL] {failure}")
        print("Environment check FAILED. Fix the items above and run it again.")
        return 1

    print("  [OK] Foundation environment check passed.")
    if warnings:
        print(f"  {len(warnings)} warning(s) reported above.")
    print(
        "  Next: audit the candidate dataset with scripts/audit_dataset.py before "
        "any model work."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
