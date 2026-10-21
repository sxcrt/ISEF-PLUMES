"""Tests for read-only annotation parsing and the Galileo sidecar map."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from planetary_plume.annotations import (
    AnnotationError,
    annotation_record_from_dict,
    build_inventory,
    parse_annotation_text,
    parse_galileo_image_ids,
)


def _write_label(
    path: Path,
    *,
    points: str = "- [10, 20]\n- [30, 20]\n- [20, 40]",
    intervals: str | None = "- [1.0, 1.2]",
    user: str = "tester",
    include_plumes: bool = True,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "comment: Points are in (x, y), i.e. (col, row), order.",
    ]
    if include_plumes:
        lines.extend(
            [
                "plumes:",
                "  comment: Intervals in radians",
                "  intervals:",
            ]
        )
        if intervals is not None:
            lines.extend(f"  {line}" for line in intervals.splitlines())
        lines.append("  user: tester")
    lines.extend(["points:", points, f"user: {user}"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_sidecar(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def _bundle(tmp_path: Path) -> Path:
    root = tmp_path / "bundle"
    _write_label(
        root / "galileo_ssi_io" / "0085r_label.yml",
        intervals="- [2.85, 3.02]\n- [3.22, 3.35]",
        user="mcameron",
    )
    _write_label(
        root / "galileo_ssi_io" / "1300r_label.yml",
        include_plumes=False,
        user="mcameron",
    )
    _write_label(
        root / "new_horizons_lorri_io" / "lor_0034769759_0x630_sci_label.yml",
        intervals="- [5.73, 5.78]",
        user="wkiri",
    )
    _write_label(
        root / "messenger_mdis_mercury" / "EN0108828545M_label.yml",
        include_plumes=False,
        user="gdoran",
    )
    _write_sidecar(
        root / "galileo_image_ids.txt",
        "Labels in galileo_ssi_io/:\n\n"
        "Filename         IMAGE_ID\n"
        "0085r_label.yml  11I0012\n"
        "1300r_label.yml\n"
        "                 G7I0001\n",
    )
    return root


def test_build_inventory_counts_and_mapping(tmp_path: Path) -> None:
    root = _bundle(tmp_path)

    inventory = build_inventory(root)

    assert inventory.summary["total_annotations"] == 4
    assert inventory.summary["plume_positive"] == 2
    assert inventory.summary["plume_negative"] == 2
    assert inventory.summary["total_plume_intervals"] == 3
    assert inventory.summary["by_annotator"] == {
        "gdoran": 1,
        "mcameron": 2,
        "wkiri": 1,
    }

    by_path = {record.annotation_relative_path: record for record in inventory.records}
    io_positive = by_path["galileo_ssi_io/0085r_label.yml"]
    assert io_positive.target_body == "Io"
    assert io_positive.instrument == "Galileo SSI"
    assert io_positive.retrieval_identifier == "11I0012"
    assert io_positive.mapping_status == "sidecar_mapped"
    assert io_positive.plume_interval_count == 2
    assert io_positive.limb_point_count == 3

    # The sidecar entry wraps onto the next line; the parser must still find it.
    io_negative = by_path["galileo_ssi_io/1300r_label.yml"]
    assert io_negative.plume_status is False
    assert io_negative.retrieval_identifier == "G7I0001"

    lorri = by_path["new_horizons_lorri_io/lor_0034769759_0x630_sci_label.yml"]
    assert lorri.mapping_status == "label_stem_candidate"
    assert lorri.retrieval_identifier == "lor_0034769759_0x630_sci"

    mercury = by_path["messenger_mdis_mercury/EN0108828545M_label.yml"]
    assert mercury.mapping_status == "label_stem_candidate"
    assert mercury.plume_status is False


def test_build_inventory_does_not_modify_annotations(tmp_path: Path) -> None:
    root = _bundle(tmp_path)
    target = root / "galileo_ssi_io" / "0085r_label.yml"
    before = target.read_bytes()
    before_hash = hashlib.sha256(before).hexdigest()

    inventory = build_inventory(root)

    after = target.read_bytes()
    assert after == before
    record = next(
        item
        for item in inventory.records
        if item.annotation_relative_path == "galileo_ssi_io/0085r_label.yml"
    )
    assert record.annotation_sha256 == before_hash


def test_missing_galileo_sidecar_entry_is_explicit(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    _write_label(root / "galileo_ssi_europa" / "4852r_label.yml", include_plumes=False)
    _write_sidecar(root / "galileo_image_ids.txt", "0085r_label.yml 11I0012\n")

    inventory = build_inventory(root)

    record = inventory.records[0]
    assert record.mapping_status == "unresolved_sidecar"
    assert record.retrieval_identifier == "4852r"
    assert "missing Galileo image-ID mapping" in record.warnings[0]


def test_duplicate_sidecar_mapping_is_ambiguous(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    _write_label(root / "galileo_ssi_io" / "0085r_label.yml", include_plumes=False)
    _write_sidecar(
        root / "galileo_image_ids.txt",
        "0085r_label.yml 11I0012\n0085r_label.yml G2C0004\n",
    )

    inventory = build_inventory(root)

    record = inventory.records[0]
    assert record.mapping_status == "ambiguous_sidecar"
    assert "ambiguous Galileo image IDs" in record.warnings[0]


def test_unknown_annotation_directory_is_not_silently_labeled(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    _write_label(root / "mystery_target" / "x_label.yml", include_plumes=False)

    inventory = build_inventory(root)

    record = inventory.records[0]
    assert record.target_body is None
    assert record.instrument is None
    assert record.product_family == "unknown"
    assert record.mapping_status == "unknown_layout"
    assert inventory.summary["by_target"] == {"(unresolved)": 1}


@pytest.mark.parametrize(
    "body",
    [
        "points:\n- [1, 2]\n- [3, 4]\nuser: tester\n",
        "points:\n- [1, 2]\n- [3, 4]\n- [5, 6]\n",
        "points:\n- [1, 2]\n- [3, 4]\n- [5, 6]\nuser: tester\nplumes:\n  intervals:\n  - [2.0, 2.0]\n",
        "points:\n- [1, 2]\n- [3, 4]\n- [5, 6]\nuser: tester\nplumes:\n  intervals:\n  - [1.0]\n",
    ],
)
def test_malformed_annotations_raise(tmp_path: Path, body: str) -> None:
    root = tmp_path / "bundle"
    path = root / "galileo_ssi_io" / "bad_label.yml"
    path.parent.mkdir(parents=True)
    path.write_text(body, encoding="utf-8")

    with pytest.raises(AnnotationError):
        build_inventory(root)


def test_galileo_sidecar_reports_duplicate_problems(tmp_path: Path) -> None:
    path = _write_sidecar(
        tmp_path / "galileo_image_ids.txt",
        "0085r_label.yml 11I0012\n0085r_label.yml G2C0004\n",
    )

    mapping = parse_galileo_image_ids(path)

    assert mapping.by_filename["0085r_label.yml"] == ("11I0012", "G2C0004")
    assert mapping.problems


def test_wrapping_intervals_are_opt_in(tmp_path: Path) -> None:
    text = (
        "points:\n- [1, 2]\n- [3, 4]\n- [5, 6]\n"
        "user: tester\n"
        "plumes:\n  intervals:\n  - [6.0, 0.2]\n  user: tester\n"
    )
    path = tmp_path / "wrap_label.yml"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(AnnotationError, match="unless wrapping"):
        parse_annotation_text(
            text,
            source=path,
            root=tmp_path,
            family=None,
            galileo_map=None,
        )

    record = parse_annotation_text(
        text,
        source=path,
        root=tmp_path,
        family=None,
        galileo_map=None,
        allow_wrapping_intervals=True,
    )
    assert record.plume_intervals == ((6.0, 0.2),)


def test_annotation_record_json_round_trip(tmp_path: Path) -> None:
    inventory = build_inventory(_bundle(tmp_path))
    original = inventory.records[0]

    restored = annotation_record_from_dict(original.to_dict())

    assert restored == original
    assert list(restored.plume_intervals) == list(original.plume_intervals)
    assert list(restored.limb_points) == list(original.limb_points)
