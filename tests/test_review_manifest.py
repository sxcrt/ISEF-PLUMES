"""Tests for the sanitized review manifest schema and loader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from planetary_plume.review_manifest import (
    REVIEW_MANIFEST_FORMAT,
    REVIEW_MANIFEST_VERSION,
    ReviewManifestError,
    assert_no_released_label_fields,
    load_review_manifest,
)


def _manifest_payload(**overrides: object) -> dict:
    payload = {
        "format": REVIEW_MANIFEST_FORMAT,
        "format_version": REVIEW_MANIFEST_VERSION,
        "generated_at_utc": "2026-10-20T00:00:00Z",
        "source": {"note": "test"},
        "convention": {
            "description": "test",
            "zero": "up",
            "direction": "clockwise",
            "origin": "fitted_limb_center",
        },
        "images": [
            {
                "image_id": "test:001",
                "display_name": "Test image",
                "product_family": "test",
                "target": "Io",
                "instrument": "Test camera",
                "width": 32,
                "height": 32,
                "image_format": "fits",
                "product_id": "TEST001",
                "product_path": "C:/data/test.fit",
                "pds_label_path": None,
                "image_sha256": "a" * 64,
                "limb": {
                    "center_x": 16.0,
                    "center_y": 16.0,
                    "radius": 10.0,
                    "rms_residual": 0.1,
                },
            }
        ],
    }
    payload.update(overrides)
    return payload


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_manifest_round_trip(tmp_path: Path) -> None:
    manifest = load_review_manifest(_write(tmp_path / "manifest.json", _manifest_payload()))

    assert manifest.images[0].image_id == "test:001"
    assert manifest.images[0].limb.radius == pytest.approx(10.0)
    assert manifest.by_id()["test:001"].width == 32


@pytest.mark.parametrize(
    "forbidden",
    [
        {"plume_status": True},
        {"plume_intervals": [[1.0, 2.0]]},
        {"nested": {"plumes": []}},
        {"positive": True},
        {"negative": False},
        {"ground_truth": "x"},
        {"labels": []},
    ],
)
def test_forbidden_released_label_fields_are_rejected(tmp_path: Path, forbidden: dict) -> None:
    payload = _manifest_payload()
    payload["images"][0].update(forbidden)
    path = _write(tmp_path / "bad.json", payload)

    with pytest.raises(ReviewManifestError, match="Forbidden released-label field"):
        load_review_manifest(path)


def test_assert_no_released_label_fields_scans_nested_lists() -> None:
    with pytest.raises(ReviewManifestError):
        assert_no_released_label_fields({"images": [{"x": {"plume_status": True}}]})


def test_wrong_format_and_version_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ReviewManifestError, match="Unsupported review manifest format"):
        load_review_manifest(_write(tmp_path / "a.json", _manifest_payload(format="other")))
    with pytest.raises(ReviewManifestError, match="Unsupported review manifest version"):
        load_review_manifest(_write(tmp_path / "b.json", _manifest_payload(format_version=99)))


def test_wrong_convention_is_rejected(tmp_path: Path) -> None:
    payload = _manifest_payload()
    payload["convention"]["zero"] = "right"
    with pytest.raises(ReviewManifestError, match="Unsupported review-manifest convention"):
        load_review_manifest(_write(tmp_path / "bad_convention.json", payload))


def test_duplicate_image_ids_are_rejected(tmp_path: Path) -> None:
    payload = _manifest_payload()
    payload["images"].append(dict(payload["images"][0]))

    with pytest.raises(ReviewManifestError, match="duplicate image_id"):
        load_review_manifest(_write(tmp_path / "dupe.json", payload))


def test_invalid_limb_is_rejected(tmp_path: Path) -> None:
    payload = _manifest_payload()
    payload["images"][0]["limb"]["radius"] = 0
    with pytest.raises(ReviewManifestError, match="radius must be positive"):
        load_review_manifest(_write(tmp_path / "bad_limb.json", payload))


def test_missing_fields_are_rejected(tmp_path: Path) -> None:
    payload = _manifest_payload()
    del payload["images"][0]["width"]
    with pytest.raises(ReviewManifestError, match="missing fields"):
        load_review_manifest(_write(tmp_path / "missing.json", payload))


def test_missing_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ReviewManifestError, match="not found"):
        load_review_manifest(tmp_path / "nope.json")
