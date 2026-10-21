"""Tests for the minimal PDS3 and FITS readers."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from planetary_plume.image_readers import (
    ImageReadError,
    load_image,
    normalize_for_display,
    parse_pds3_label_text,
    read_fits_image,
    read_pds3_image,
)


def _fits_card(key: str, value: object, comment: str = "") -> str:
    if isinstance(value, str):
        rendered = f"'{value}'"
    elif isinstance(value, bool):
        rendered = "T" if value else "F"
    else:
        rendered = str(value)
    card = f"{key:<8}= {rendered:>20}"
    if comment:
        card += f" / {comment}"
    return f"{card:<80}"


def _write_fits(path: Path, array: np.ndarray, extra: dict[str, object] | None = None) -> Path:
    cards = [
        _fits_card("SIMPLE", True),
        _fits_card("BITPIX", -32 if array.dtype == np.float32 else 16),
        _fits_card("NAXIS", 2),
        _fits_card("NAXIS1", array.shape[1]),
        _fits_card("NAXIS2", array.shape[0]),
    ]
    for key, value in (extra or {}).items():
        cards.append(_fits_card(key, value))
    cards.append(f"{'END':<80}")
    header = "".join(cards).encode("ascii")
    header += b" " * ((2880 - len(header) % 2880) % 2880)
    data = array.astype(">f4" if array.dtype == np.float32 else ">i2").tobytes()
    data += b"\0" * ((2880 - len(data) % 2880) % 2880)
    path.write_bytes(header + data)
    return path


def test_fits_values_ignore_comments_after_numeric_fields() -> None:
    from planetary_plume.image_readers import parse_fits_header

    header = (
        f"{'SIMPLE':<8}= {'T':>20}".ljust(80)
        + f"{'BITPIX':<8}= {'-32':>20} / IEEE single precision floating point".ljust(80)
        + f"{'NAXIS':<8}= {'2':>20}".ljust(80)
        + f"{'NAXIS1':<8}= {'2':>20}".ljust(80)
        + f"{'NAXIS2':<8}= {'2':>20}".ljust(80)
        + "END".ljust(80)
    ).encode("ascii")
    header += b" " * ((2880 - len(header) % 2880) % 2880)

    cards, offset = parse_fits_header(header)

    assert cards["BITPIX"] == -32
    assert offset == 2880


def test_read_fits_primary_hdu(tmp_path: Path) -> None:
    array = np.arange(12, dtype=np.float32).reshape(3, 4)
    path = _write_fits(
        tmp_path / "sample.fit",
        array,
        {"TARGET": "IO", "EXPTIME": 0.003, "INSTRU": "LORRI"},
    )

    info = read_fits_image(path)

    assert info.format == "fits"
    assert (info.width, info.height) == (4, 3)
    assert info.bit_depth == 32
    assert info.array.shape == (3, 4)
    np.testing.assert_allclose(info.array, array)
    # Row 0 is the first FITS row as displayed at the top of the image.
    assert info.array[0].tolist() == [0.0, 1.0, 2.0, 3.0]
    assert info.array[-1].tolist() == [8.0, 9.0, 10.0, 11.0]
    assert info.metadata["target"] == "IO"
    assert info.metadata["exptime"] == pytest.approx(0.003)


def test_read_pds3_with_line_prefix(tmp_path: Path) -> None:
    path = tmp_path / "sample.img"
    label = tmp_path / "sample.lbl"
    label.write_text(
        "\n".join(
            [
                "PDS_VERSION_ID = PDS3",
                "RECORD_BYTES = 16",
                '^IMAGE = ("sample.img", 2)',
                "OBJECT = IMAGE",
                "  LINES = 3",
                "  LINE_SAMPLES = 4",
                "  SAMPLE_BITS = 8",
                "  SAMPLE_TYPE = UNSIGNED_INTEGER",
                "  LINE_PREFIX_BYTES = 4",
                "END_OBJECT = IMAGE",
                "END",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    header = b"HEADER" + b" " * 10
    rows = b""
    expected = []
    for row_index in range(3):
        prefix = bytes([row_index]) * 4
        values = bytes([row_index * 10 + column for column in range(4)])
        rows += prefix + values
        expected.append(list(values))
    path.write_bytes(header + rows)

    info = read_pds3_image(path, label)

    assert info.format == "pds3"
    assert (info.width, info.height) == (4, 3)
    assert info.bit_depth == 8
    assert info.array.tolist() == expected
    assert info.array[0].tolist() == [0, 1, 2, 3]
    assert info.array[-1].tolist() == [20, 21, 22, 23]
    assert "line-prefix" in info.warnings[0]


def test_parse_pds3_label_separates_image_object() -> None:
    global_values, image_values = parse_pds3_label_text(
        "\n".join(
            [
                "RECORD_BYTES = 100",
                "OBJECT = IMAGE",
                "  LINES = 3",
                "  LINE_SAMPLES = 4",
                "END_OBJECT = IMAGE",
            ]
        )
    )
    assert global_values["RECORD_BYTES"] == "100"
    assert image_values["LINES"] == "3"
    assert "RECORD_BYTES" not in image_values


def test_truncated_pds3_image_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad.img"
    label = tmp_path / "bad.lbl"
    label.write_text(
        "\n".join(
            [
                "RECORD_BYTES = 16",
                '^IMAGE = ("bad.img", 2)',
                "OBJECT = IMAGE",
                "  LINES = 10",
                "  LINE_SAMPLES = 10",
                "  SAMPLE_BITS = 8",
                "END_OBJECT = IMAGE",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    path.write_bytes(b"short")

    with pytest.raises(ImageReadError, match="truncated"):
        read_pds3_image(path, label)


def test_load_image_dispatches_by_extension(tmp_path: Path) -> None:
    array = np.ones((2, 3), dtype=np.float32)
    fits_path = _write_fits(tmp_path / "x.fit", array)
    assert load_image(fits_path).format == "fits"

    with pytest.raises(ImageReadError, match="Unsupported"):
        load_image(tmp_path / "x.png")


def test_normalize_for_display_handles_constant_and_nan() -> None:
    constant = np.ones((2, 2), dtype=np.float32)
    np.testing.assert_array_equal(normalize_for_display(constant), np.zeros((2, 2), dtype=np.uint8))

    values = np.array([[0.0, 1.0], [np.nan, 2.0]], dtype=np.float32)
    normalized = normalize_for_display(values)
    assert normalized.dtype == np.uint8
    assert normalized[1, 0] == 0
    assert normalized.max() == 255
