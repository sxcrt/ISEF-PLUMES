"""Tests for the descriptive dataset audit."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from planetary_plume.dataset_audit import (
    DatasetAuditError,
    audit_dataset,
    audit_to_dict,
    format_audit,
)


def _make_image(
    path: Path,
    size: tuple[int, int] = (8, 6),
    mode: str = "RGB",
    color: str | int = "white",
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new(mode, size, color).save(path)
    return path


def test_audit_counts_structure_and_dimensions(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    _make_image(root / "observed" / "a.png", size=(8, 6))
    _make_image(root / "observed" / "nested" / "b.png", size=(8, 6))
    _make_image(root / "negatives" / "c.jpg", size=(4, 4))
    (root / "labels").mkdir()
    (root / "labels" / "notes.txt").write_text("not a label", encoding="utf-8")
    (root / "root_notes.txt").write_text("root file", encoding="utf-8")

    report = audit_dataset(root, dimension_sample_size=0)

    assert report.root == root.resolve()
    assert report.total_files == 5
    assert report.total_directories == 4  # observed, observed/nested, negatives, labels
    assert report.root_files == 1
    assert report.max_depth == 2
    assert report.extension_counts[".png"] == 2
    assert report.extension_counts[".jpg"] == 1
    assert report.extension_counts[".txt"] == 2

    assert report.image_files == 3
    assert report.images_inspected == 3
    assert report.sampled is False
    assert report.dimension_counts == {"8x6": 2, "4x4": 1}
    assert report.mode_counts == {"RGB": 3}
    assert report.unreadable_images == ()

    top_level = {entry.name: entry for entry in report.top_level}
    assert set(top_level) == {"observed", "negatives", "labels"}
    assert top_level["observed"].files == 2
    assert top_level["negatives"].files == 1
    assert top_level["labels"].files == 1


def test_audit_samples_deterministically(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    for index in range(10):
        _make_image(root / f"image_{index}.png", size=(index + 1, 4))

    report = audit_dataset(root, dimension_sample_size=3)

    assert report.image_files == 10
    assert report.images_inspected == 3
    assert report.sampled is True
    assert sum(report.dimension_counts.values()) == 3

    second_report = audit_dataset(root, dimension_sample_size=3)
    assert second_report.dimension_counts == report.dimension_counts


def test_audit_reports_unreadable_images(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    _make_image(root / "good.png")
    (root / "bad.png").write_text("this is not an image", encoding="utf-8")

    report = audit_dataset(root, dimension_sample_size=0)

    assert report.image_files == 2
    assert report.images_inspected == 2
    assert len(report.unreadable_images) == 1
    assert "bad.png" in report.unreadable_images[0]


def test_audit_rejects_missing_or_non_directory_paths(tmp_path: Path) -> None:
    with pytest.raises(DatasetAuditError, match="does not exist"):
        audit_dataset(tmp_path / "missing")

    file_path = tmp_path / "file.txt"
    file_path.write_text("text", encoding="utf-8")
    with pytest.raises(DatasetAuditError, match="not a directory"):
        audit_dataset(file_path)


def test_audit_rejects_invalid_sample_size(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    root.mkdir()

    with pytest.raises(DatasetAuditError, match="non-negative"):
        audit_dataset(root, dimension_sample_size=-1)

    with pytest.raises(DatasetAuditError, match="non-negative"):
        audit_dataset(root, dimension_sample_size=1.5)


def test_format_and_json_output(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    _make_image(root / "a.png", size=(1024, 1024))

    report = audit_dataset(root, dimension_sample_size=0)
    text = format_audit(report)

    assert "Dataset audit" in text
    assert "1024x1024" in text
    assert "does not verify labels" in text

    payload = audit_to_dict(report)
    serialized = json.dumps(payload)
    restored = json.loads(serialized)
    assert isinstance(restored["root"], str)
    assert restored["total_files"] == 1
    assert restored["dimension_counts"] == {"1024x1024": 1}
