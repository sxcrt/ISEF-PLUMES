"""Smoke tests for the documented command-line entry points."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=str(cwd or PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_annotate_candidates_help() -> None:
    pytest.importorskip("PySide6")
    result = _run(str(PROJECT_ROOT / "scripts" / "annotate_candidates.py"), "--help")
    assert result.returncode == 0
    assert "released labels are not loaded or shown" in " ".join(result.stdout.split()).lower()


def test_build_review_manifest_help() -> None:
    result = _run(str(PROJECT_ROOT / "scripts" / "build_review_manifest.py"), "--help")
    assert result.returncode == 0
    assert "sanitized review manifest" in result.stdout.lower()


def test_compare_annotations_requires_saved_annotations(tmp_path: Path) -> None:
    result = _run(
        str(PROJECT_ROOT / "scripts" / "compare_annotations.py"),
        "--session",
        str(tmp_path / "missing_session.json"),
    )
    assert result.returncode == 2
    assert "saved independent annotations not found" in result.stderr


def test_compare_annotations_help() -> None:
    result = _run(str(PROJECT_ROOT / "scripts" / "compare_annotations.py"), "--help")
    assert result.returncode == 0
    assert "separate" in result.stdout.lower()
