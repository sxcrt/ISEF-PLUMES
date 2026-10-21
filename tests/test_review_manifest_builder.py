"""Tests for the sanitized manifest builder and comparison-only label map."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from planetary_plume.acquisition import sha256_file
from planetary_plume.review_manifest import (
    assert_no_released_label_fields,
    load_review_manifest,
)
from planetary_plume.review_manifest_builder import (
    ReviewManifestBuildError,
    _image_id_for,
    build_review_manifest,
    load_release_label_map,
)


def _fits_card(key: str, value: object) -> str:
    if isinstance(value, str):
        rendered = f"'{value}'"
    else:
        rendered = str(value)
    return f"{key:<8}= {rendered:>20}".ljust(80)


def _write_fits(path: Path, shape: tuple[int, int] = (32, 32)) -> Path:
    array = np.linspace(0, 1, shape[0] * shape[1], dtype=np.float32).reshape(shape)
    cards = [
        _fits_card("SIMPLE", "T"),
        _fits_card("BITPIX", -32),
        _fits_card("NAXIS", 2),
        _fits_card("NAXIS1", shape[1]),
        _fits_card("NAXIS2", shape[0]),
        "END".ljust(80),
    ]
    header = "".join(cards).encode("ascii")
    header += b" " * ((2880 - len(header) % 2880) % 2880)
    data = array.astype(">f4").tobytes()
    data += b"\0" * ((2880 - len(data) % 2880) % 2880)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + data)
    return path


def _record(relative: str, sha: str, product_family: str = "new_horizons_lorri") -> dict:
    return {
        "annotation_filename": Path(relative).name,
        "annotation_relative_path": relative,
        "annotation_sha256": sha,
        "directory": Path(relative).parent.name,
        "target_body": "Io",
        "instrument": "New Horizons LORRI" if product_family == "new_horizons_lorri" else "Galileo SSI",
        "product_family": product_family,
        "label_identifier": Path(relative).name.replace("_label.yml", ""),
        "retrieval_identifier": "TEST",
        "retrieval_identifier_kind": "test",
        "mapping_status": "resolved",
        "mapping_evidence": "test",
        "plume_status": True,
        "plume_interval_count": 1,
        "plume_intervals": [[1.0, 1.2]],
        "limb_point_count": 4,
        "limb_points": [[10.0, 5.0], [15.0, 10.0], [10.0, 15.0], [5.0, 10.0]],
        "annotator": "tester",
        "warnings": [],
    }


def _entry(
    relative: str,
    sha: str,
    image_path: Path,
    *,
    image_id: str,
    product_id: str,
    product_family: str = "new_horizons_lorri",
) -> dict:
    return {
        "annotation_relative_path": relative,
        "annotation_sha256": sha,
        "product_family": product_family,
        "retrieval_identifier": "TEST",
        "mapping_status": "resolved",
        "resolved_product_id": product_id,
        "resolved_image_id": image_id,
        "target": "IO",
        "instrument": "LORRI" if product_family == "new_horizons_lorri" else "SSI",
        "image_path": str(image_path),
        "label_path": None,
        "image_sha256": sha256_file(image_path) if image_path.is_file() else "0" * 64,
        "download_status": "skipped_existing",
    }


def _write_inputs(
    root: Path,
    entries: list[dict],
    records: list[dict],
) -> tuple[Path, Path]:
    manifest = root / "manifest.json"
    acquisition = root / "acquisition.json"
    manifest.write_text(
        json.dumps({"manifest_version": 1, "records": records}), encoding="utf-8"
    )
    acquisition.write_text(json.dumps({"entries": entries}), encoding="utf-8")
    return manifest, acquisition


def test_build_review_manifest_is_sanitized_and_neutral(tmp_path: Path) -> None:
    image_b = _write_fits(tmp_path / "images" / "b.fit")
    image_a = _write_fits(tmp_path / "images" / "a.fit")
    sha = "b" * 64
    record_b = _record("new_horizons_lorri_io/b_label.yml", sha)
    record_a = _record("new_horizons_lorri_io/a_label.yml", sha)
    entries = [
        _entry(
            "new_horizons_lorri_io/b_label.yml",
            sha,
            image_b,
            image_id="LOR_B",
            product_id="LOR_B",
        ),
        _entry(
            "new_horizons_lorri_io/a_label.yml",
            sha,
            image_a,
            image_id="LOR_A",
            product_id="LOR_A",
        ),
    ]
    manifest_path, acquisition_path = _write_inputs(tmp_path, entries, [record_b, record_a])
    before = manifest_path.read_bytes()

    result = build_review_manifest(
        manifest_path,
        acquisition_path,
        tmp_path / "out" / "review_manifest.json",
        tmp_path / "out" / "label_map.json",
        generated_at_utc="2026-10-20T00:00:00Z",
    )

    payload = json.loads(result.review_manifest_path.read_text(encoding="utf-8"))
    assert result.image_count == 2
    assert [image["image_id"] for image in payload["images"]] == [
        "new_horizons_lorri:LOR_A",
        "new_horizons_lorri:LOR_B",
    ]
    assert_no_released_label_fields(payload)
    serialized = json.dumps(payload).lower()
    for forbidden in ("plume_status", "plume_intervals", "plume_interval_count"):
        assert forbidden not in serialized
    assert manifest_path.read_bytes() == before
    assert load_review_manifest(result.review_manifest_path).images[0].width == 32

    label_map = load_release_label_map(result.label_map_path)
    assert label_map["mappings"][0]["image_id"] == "new_horizons_lorri:LOR_A"
    assert label_map["mappings"][0]["annotation_relative_path"] == (
        "new_horizons_lorri_io/a_label.yml"
    )
    serialized_map = json.dumps(label_map).lower()
    for forbidden in ("plume_status", "plume_intervals", "plume_interval_count"):
        assert forbidden not in serialized_map


def test_verified_identifiers_are_required() -> None:
    assert _image_id_for(
        {
            "product_family": "galileo_ssi",
            "resolved_image_id": "11I0012",
            "resolved_product_id": "0085r.img",
        }
    ) == ("galileo_ssi:11I0012", "11I0012", "0085r.img")
    assert _image_id_for(
        {
            "product_family": "new_horizons_lorri",
            "resolved_product_id": "LOR_0034769759_0X630_SCI",
        }
    )[0] == "new_horizons_lorri:LOR_0034769759_0X630_SCI"

    with pytest.raises(ReviewManifestBuildError, match="filename guess"):
        _image_id_for({"product_family": "galileo_ssi", "resolved_product_id": "0085r.img"})
    with pytest.raises(ReviewManifestBuildError, match="filename guess"):
        _image_id_for({"product_family": "new_horizons_lorri", "resolved_image_id": "X"})


def test_unresolved_mapping_is_skipped_with_problem(tmp_path: Path) -> None:
    image_a = _write_fits(tmp_path / "a.fit")
    image_b = _write_fits(tmp_path / "b.fit")
    sha = "a1" * 32
    valid = _entry(
        "new_horizons_lorri_io/a_label.yml", sha, image_a, image_id="A", product_id="A"
    )
    unresolved = _entry(
        "new_horizons_lorri_io/b_label.yml", sha, image_b, image_id="B", product_id="B"
    )
    unresolved["mapping_status"] = "unresolved_adapter"
    manifest_path, acquisition_path = _write_inputs(
        tmp_path,
        [valid, unresolved],
        [
            _record("new_horizons_lorri_io/a_label.yml", sha),
            _record("new_horizons_lorri_io/b_label.yml", sha),
        ],
    )

    result = build_review_manifest(
        manifest_path,
        acquisition_path,
        tmp_path / "review_manifest.json",
        tmp_path / "label_map.json",
    )

    assert result.image_count == 1
    assert len(result.problems) == 1
    assert "not resolved" in result.problems[0].detail


def test_build_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    image = _write_fits(tmp_path / "a.fit")
    sha = "c" * 64
    manifest_path, acquisition_path = _write_inputs(
        tmp_path,
        [_entry("new_horizons_lorri_io/a_label.yml", sha, image, image_id="A", product_id="A")],
        [_record("new_horizons_lorri_io/a_label.yml", sha)],
    )
    output = tmp_path / "review_manifest.json"
    label_map = tmp_path / "label_map.json"
    build_review_manifest(manifest_path, acquisition_path, output, label_map)

    with pytest.raises(ReviewManifestBuildError, match="Refusing to overwrite"):
        build_review_manifest(manifest_path, acquisition_path, output, label_map)

    build_review_manifest(manifest_path, acquisition_path, output, label_map, force=True)
    backups = list(tmp_path.glob("review_manifest.json.*.bak"))
    assert backups


def test_missing_image_is_reported_not_guessed(tmp_path: Path) -> None:
    sha = "d" * 64
    manifest_path, acquisition_path = _write_inputs(
        tmp_path,
        [
            _entry(
                "new_horizons_lorri_io/a_label.yml",
                sha,
                tmp_path / "missing.fit",
                image_id="A",
                product_id="A",
            )
        ],
        [_record("new_horizons_lorri_io/a_label.yml", sha)],
    )

    with pytest.raises(ReviewManifestBuildError, match="No usable images"):
        build_review_manifest(
            manifest_path,
            acquisition_path,
            tmp_path / "review_manifest.json",
            tmp_path / "label_map.json",
        )


def test_duplicate_verified_image_id_is_rejected(tmp_path: Path) -> None:
    image_a = _write_fits(tmp_path / "a.fit")
    image_b = _write_fits(tmp_path / "b.fit")
    sha = "e" * 64
    manifest_path, acquisition_path = _write_inputs(
        tmp_path,
        [
            _entry("new_horizons_lorri_io/a_label.yml", sha, image_a, image_id="A", product_id="SAME"),
            _entry("new_horizons_lorri_io/b_label.yml", sha, image_b, image_id="B", product_id="SAME"),
        ],
        [
            _record("new_horizons_lorri_io/a_label.yml", sha),
            _record("new_horizons_lorri_io/b_label.yml", sha),
        ],
    )

    with pytest.raises(ReviewManifestBuildError, match="collision"):
        build_review_manifest(
            manifest_path,
            acquisition_path,
            tmp_path / "review_manifest.json",
            tmp_path / "label_map.json",
        )


def test_same_released_path_for_two_images_is_rejected(tmp_path: Path) -> None:
    image_a = _write_fits(tmp_path / "a.fit")
    image_b = _write_fits(tmp_path / "b.fit")
    sha = "a2" * 32
    relative = "new_horizons_lorri_io/a_label.yml"
    manifest_path, acquisition_path = _write_inputs(
        tmp_path,
        [
            _entry(relative, sha, image_a, image_id="A", product_id="A"),
            _entry(relative, sha, image_b, image_id="B", product_id="B"),
        ],
        [_record(relative, sha)],
    )

    with pytest.raises(ReviewManifestBuildError, match="same released annotation path"):
        build_review_manifest(
            manifest_path,
            acquisition_path,
            tmp_path / "review_manifest.json",
            tmp_path / "label_map.json",
        )


def test_sha_mismatch_and_unresolved_mapping_are_skipped(tmp_path: Path) -> None:
    image = _write_fits(tmp_path / "a.fit")
    sha = "f" * 64
    entry = _entry(
        "new_horizons_lorri_io/a_label.yml", sha, image, image_id="A", product_id="A"
    )
    entry["image_sha256"] = "0" * 64
    manifest_path, acquisition_path = _write_inputs(
        tmp_path,
        [entry],
        [_record("new_horizons_lorri_io/a_label.yml", sha)],
    )

    with pytest.raises(ReviewManifestBuildError, match="No usable images"):
        build_review_manifest(
            manifest_path,
            acquisition_path,
            tmp_path / "review_manifest.json",
            tmp_path / "label_map.json",
        )
