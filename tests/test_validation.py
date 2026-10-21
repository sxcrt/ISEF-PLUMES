"""Tests for geometry, overlay rendering, and acquisition validation."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from planetary_plume.acquisition import AcquisitionEntry
from planetary_plume.annotations import AnnotationRecord
from planetary_plume.image_readers import read_fits_image
from planetary_plume.validation import (
    GeometryError,
    ValidationResult,
    angle_up_clockwise,
    fit_circle,
    format_validation_report,
    load_overlay_reviews,
    render_overlay,
    sector_polygon,
    validate_acquisition,
)


def _fits_card(key: str, value: object) -> str:
    if isinstance(value, str):
        rendered = f"'{value}'"
    else:
        rendered = str(value)
    return f"{key:<8}= {rendered:>20}".ljust(80)


def _write_fits(path: Path, array: np.ndarray) -> Path:
    cards = [
        _fits_card("SIMPLE", "T"),
        _fits_card("BITPIX", -32),
        _fits_card("NAXIS", 2),
        _fits_card("NAXIS1", array.shape[1]),
        _fits_card("NAXIS2", array.shape[0]),
        "END".ljust(80),
    ]
    header = "".join(cards).encode("ascii")
    header += b" " * ((2880 - len(header) % 2880) % 2880)
    data = array.astype(">f4").tobytes()
    data += b"\0" * ((2880 - len(data) % 2880) % 2880)
    path.write_bytes(header + data)
    return path


def _record(
    path: str = "new_horizons_lorri_io/x_label.yml",
    *,
    points: tuple[tuple[float, float], ...] = ((8.0, 8.0), (12.0, 8.0), (10.0, 12.0)),
    intervals: tuple[tuple[float, float], ...] = ((0.2, 0.4),),
    plume: bool = True,
) -> AnnotationRecord:
    return AnnotationRecord(
        annotation_filename=Path(path).name,
        annotation_relative_path=path,
        annotation_sha256="a" * 64,
        directory=Path(path).parent.name,
        target_body="Io",
        instrument="New Horizons LORRI",
        product_family="new_horizons_lorri",
        label_identifier="x",
        retrieval_identifier="x",
        retrieval_identifier_kind="lorri_label_stem",
        mapping_status="label_stem_candidate",
        mapping_evidence="test",
        plume_status=plume,
        plume_interval_count=len(intervals),
        plume_intervals=intervals,
        limb_point_count=len(points),
        limb_points=points,
        annotator="tester",
        warnings=(),
    )


def _entry(
    *,
    path: str = "new_horizons_lorri_io/x_label.yml",
    image_path: Path,
    label_path: Path | None = None,
    product_id: str = "LOR_X",
    image_sha: str | None = None,
    download_status: str = "downloaded",
) -> AcquisitionEntry:
    return AcquisitionEntry(
        annotation_relative_path=path,
        annotation_sha256="a" * 64,
        product_family="new_horizons_lorri",
        retrieval_identifier="x",
        mapping_status="resolved",
        resolved_product_id=product_id,
        resolved_image_id=None,
        target="J1 IO",
        instrument="LORRI",
        data_url="https://example/x.fit",
        label_url="https://example/x.lbl",
        image_path=str(image_path),
        label_path=str(label_path) if label_path else None,
        image_size_bytes=image_path.stat().st_size,
        image_sha256=image_sha,
        label_sha256=None,
        download_status=download_status,
        label_download_status="downloaded",
        http_status=200,
        error=None,
        mapping_evidence="test",
    )


def test_fit_circle_and_angle_convention() -> None:
    circle = fit_circle(((0, -1), (1, 0), (0, 1), (-1, 0)))
    assert circle.center_x == pytest.approx(0, abs=1e-9)
    assert circle.center_y == pytest.approx(0, abs=1e-9)
    assert circle.radius == pytest.approx(1, abs=1e-9)
    assert circle.rms_residual == pytest.approx(0, abs=1e-9)

    assert angle_up_clockwise((0, 0), (0, -1)) == pytest.approx(0)
    assert angle_up_clockwise((0, 0), (1, 0)) == pytest.approx(math.pi / 2)
    assert angle_up_clockwise((0, 0), (0, 1)) == pytest.approx(math.pi)
    assert angle_up_clockwise((0, 0), (-1, 0)) == pytest.approx(3 * math.pi / 2)


def test_fit_circle_rejects_collinear_points() -> None:
    with pytest.raises(GeometryError, match="collinear"):
        fit_circle(((0, 0), (1, 1), (2, 2)))


def test_sector_polygon_is_outside_limb() -> None:
    polygon = sector_polygon((0, 0), 10, 0.1, 0.4, outer_factor=1.5, steps=8)
    assert len(polygon) == 16
    radii = [math.hypot(x, y) for x, y in polygon]
    assert min(radii) == pytest.approx(10)
    assert max(radii) == pytest.approx(15)


def test_render_overlay_writes_image_and_does_not_mutate_input(tmp_path: Path) -> None:
    array = np.arange(20 * 20, dtype=np.float32).reshape(20, 20)
    image_path = _write_fits(tmp_path / "image.fit", array)
    record = _record()
    output = tmp_path / "overlay.png"

    render_overlay(
        read_fits_image(image_path),
        record,
        output,
        status="TEST ONLY",
    )

    assert output.is_file()
    with Image.open(output) as rendered:
        assert rendered.size == (20, 20)
    assert np.array_equal(array, np.arange(20 * 20, dtype=np.float32).reshape(20, 20))


def test_render_overlay_rejects_points_outside_image(tmp_path: Path) -> None:
    image_path = _write_fits(tmp_path / "image.fit", np.ones((10, 10), dtype=np.float32))
    record = _record(points=((8.0, 8.0), (12.0, 8.0), (10.0, 12.0)))

    with pytest.raises(GeometryError, match="outside"):
        render_overlay(read_fits_image(image_path), record, tmp_path / "out.png")


def test_validate_acquisition_matches_and_detects_missing(tmp_path: Path) -> None:
    image_path = _write_fits(tmp_path / "image.fit", np.ones((20, 20), dtype=np.float32))
    record = _record()
    entry = _entry(image_path=image_path)

    result = validate_acquisition([record], [entry])

    assert result.images_validated == 1
    assert result.products_mapped == 1
    assert not result.issues
    assert result.validated[0].record.annotation_relative_path == record.annotation_relative_path

    missing = validate_acquisition([record], [])
    assert missing.images_validated == 0
    assert any(issue.kind == "missing_entry" for issue in missing.issues)


def test_validate_acquisition_detects_checksum_mismatch(tmp_path: Path) -> None:
    image_path = _write_fits(tmp_path / "image.fit", np.ones((20, 20), dtype=np.float32))
    record = _record()
    entry = _entry(image_path=image_path, image_sha="not-the-real-hash")

    result = validate_acquisition([record], [entry])

    assert any(issue.kind == "image_checksum_mismatch" for issue in result.issues)


def test_validate_acquisition_detects_duplicate_product_and_hash(tmp_path: Path) -> None:
    image_path = _write_fits(tmp_path / "image.fit", np.ones((20, 20), dtype=np.float32))
    record_a = _record("new_horizons_lorri_io/a_label.yml")
    record_b = _record("new_horizons_lorri_io/b_label.yml")
    entry_a = _entry(
        path=record_a.annotation_relative_path,
        image_path=image_path,
        image_sha="same-hash",
    )
    entry_b = _entry(
        path=record_b.annotation_relative_path,
        image_path=image_path,
        image_sha="same-hash",
    )

    result = validate_acquisition([record_a, record_b], [entry_a, entry_b])

    kinds = {issue.kind for issue in result.issues}
    assert "duplicate_product" in kinds
    assert "duplicate_image" in kinds


def test_overlay_review_loader_and_report(tmp_path: Path) -> None:
    review_path = tmp_path / "review.json"
    review_path.write_text(
        json.dumps(
            {
                "reviews": [
                    {
                        "annotation_relative_path": "new_horizons_lorri_io/x_label.yml",
                        "status": "aligned",
                        "notes": "Sector follows the visible jet.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    reviews = load_overlay_reviews(review_path)
    result = ValidationResult(records_checked=1, images_validated=1)
    result.overlay_reviews = reviews

    text = format_validation_report(result)

    assert "aligned" in text
    assert "manual judgment" in text
