"""Minimal, dependency-free readers for the two Io image formats.

The pilot uses PDS3 Galileo SSI images (with detached PDS labels) and FITS
New Horizons LORRI images.  These readers intentionally support only the
formats needed by the sample; they do not claim general PDS/FITS coverage.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


class ImageReadError(ValueError):
    """Raised when an image cannot be read unambiguously."""


@dataclass
class ImageInfo:
    path: Path
    format: str
    width: int
    height: int
    bit_depth: int
    dtype: str
    array: np.ndarray
    metadata: dict[str, Any]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "format": self.format,
            "width": self.width,
            "height": self.height,
            "bit_depth": self.bit_depth,
            "dtype": self.dtype,
            "metadata": dict(sorted(self.metadata.items())),
            "warnings": list(self.warnings),
        }


def _clean_pds_line(line: str) -> str:
    return line.split("/*", 1)[0].rstrip()


def _parse_pds_assignments(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        cleaned = _clean_pds_line(line)
        if not cleaned.strip() or cleaned.lstrip().startswith("/*"):
            continue
        match = re.match(r"^\s*([A-Z0-9_^]+)\s*=\s*(.*)$", cleaned)
        if match:
            values[match.group(1)] = match.group(2).strip()
    return values


def _extract_image_object(text: str) -> str:
    match = re.search(
        r"OBJECT\s*=\s*IMAGE\b(.*?)(?:END_OBJECT\s*=\s*IMAGE|^\s*END\s*$)",
        text,
        flags=re.DOTALL | re.MULTILINE | re.IGNORECASE,
    )
    return match.group(1) if match else text


def parse_pds3_label_text(text: str) -> tuple[dict[str, str], dict[str, str]]:
    """Return global and IMAGE-object assignments from a PDS3 label."""

    global_values = _parse_pds_assignments(text)
    image_values = _parse_pds_assignments(_extract_image_object(text))
    return global_values, image_values


def _int_value(values: dict[str, str], key: str, *, required: bool = True) -> int | None:
    raw = values.get(key)
    if raw is None:
        if required:
            raise ImageReadError(f"Missing required PDS label key {key!r}.")
        return None
    match = re.match(r"^[+-]?\d+", raw)
    if not match:
        raise ImageReadError(f"PDS label key {key!r} is not an integer: {raw!r}")
    return int(match.group(0))


def _pds_dtype(sample_bits: int, sample_type: str, byte_order: str) -> np.dtype:
    endian = "<" if "LSB" in byte_order.upper() else ">"
    sample = sample_type.upper()
    if sample_bits == 8:
        return np.dtype("u1")
    if sample_bits == 16:
        return np.dtype(endian + ("i2" if "SIGNED" in sample and "UNSIGNED" not in sample else "u2"))
    if sample_bits == 32:
        if "FLOAT" in sample or "REAL" in sample:
            return np.dtype(endian + "f4")
        return np.dtype(endian + ("i4" if "SIGNED" in sample and "UNSIGNED" not in sample else "u4"))
    raise ImageReadError(f"Unsupported PDS sample_bits: {sample_bits}")


def read_pds3_image(image_path: str | Path, label_path: str | Path | None = None) -> ImageInfo:
    """Read a 2-D PDS3 image using its detached label."""

    path = Path(image_path).expanduser().resolve(strict=False)
    if not path.is_file():
        raise ImageReadError(f"Image not found: {path}")
    if label_path is None:
        candidates = [path.with_suffix(".lbl"), path.with_suffix(".LBL")]
        label = next((candidate for candidate in candidates if candidate.is_file()), None)
        if label is None:
            raise ImageReadError(f"No PDS label found for {path}")
    else:
        label = Path(label_path).expanduser().resolve(strict=False)
    if not label.is_file():
        raise ImageReadError(f"PDS label not found: {label}")

    text = label.read_text(encoding="latin-1", errors="replace")
    global_values, image_values = parse_pds3_label_text(text)
    merged = {**global_values, **image_values}

    record_bytes = _int_value(merged, "RECORD_BYTES")
    lines = _int_value(image_values, "LINES") or _int_value(merged, "LINES")
    samples = _int_value(image_values, "LINE_SAMPLES") or _int_value(merged, "LINE_SAMPLES")
    sample_bits = _int_value(image_values, "SAMPLE_BITS") or _int_value(merged, "SAMPLE_BITS")
    prefix = _int_value(image_values, "LINE_PREFIX_BYTES", required=False) or 0
    sample_type = image_values.get("SAMPLE_TYPE", merged.get("SAMPLE_TYPE", "UNSIGNED_INTEGER"))
    byte_order = image_values.get("BYTE_ORDER", merged.get("BYTE_ORDER", "MSB"))

    pointer = re.search(
        r'\^IMAGE\s*=\s*\(\s*"[^"]+"\s*,\s*(\d+)\s*\)',
        text,
        flags=re.IGNORECASE,
    )
    if not pointer:
        pointer = re.search(r"\^IMAGE\s*=\s*(\d+)", text, flags=re.IGNORECASE)
    if not pointer:
        raise ImageReadError(f"Could not find ^IMAGE pointer in {label}")
    start_record = int(pointer.group(1))

    dtype = _pds_dtype(sample_bits, sample_type, byte_order)
    bytes_per_sample = dtype.itemsize
    row_stride = prefix + samples * bytes_per_sample
    start_offset = (start_record - 1) * record_bytes
    raw = path.read_bytes()
    required_end = start_offset + (lines - 1) * row_stride + prefix + samples * bytes_per_sample
    if required_end > len(raw):
        raise ImageReadError(
            f"Image is truncated: need {required_end} bytes, found {len(raw)}."
        )

    if prefix == 0:
        array = np.frombuffer(
            raw,
            dtype=dtype,
            count=lines * samples,
            offset=start_offset,
        ).reshape(lines, samples).copy()
    else:
        array = np.empty((lines, samples), dtype=dtype)
        for row in range(lines):
            offset = start_offset + row * row_stride + prefix
            array[row] = np.frombuffer(
                raw,
                dtype=dtype,
                count=samples,
                offset=offset,
            )

    warnings: list[str] = []
    if prefix:
        warnings.append(f"Skipped {prefix} line-prefix bytes per row.")
    if sample_bits not in {8, 16, 32}:
        warnings.append(f"Unusual sample_bits: {sample_bits}.")

    metadata = {
        "label_path": str(label),
        "record_bytes": record_bytes,
        "start_record": start_record,
        "lines": lines,
        "line_samples": samples,
        "sample_bits": sample_bits,
        "sample_type": sample_type,
        "line_prefix_bytes": prefix,
        "byte_order": byte_order,
        "target_name": merged.get("TARGET_NAME"),
        "image_id": merged.get("IMAGE_ID"),
        "data_set_id": merged.get("DATA_SET_ID"),
        "filter_name": merged.get("FILTER_NAME"),
        "exposure_duration": merged.get("EXPOSURE_DURATION"),
        "image_time": merged.get("IMAGE_TIME"),
    }
    return ImageInfo(
        path=path,
        format="pds3",
        width=samples,
        height=lines,
        bit_depth=sample_bits,
        dtype=str(array.dtype),
        array=array,
        metadata=metadata,
        warnings=tuple(warnings),
    )


def _fits_value(raw: str) -> Any:
    value = raw.strip()
    if value.startswith("'"):
        match = re.match(r"^'((?:[^']|'')*)'", value)
        if match:
            return match.group(1).replace("''", "'").strip()
    # FITS comments begin with '/' outside a quoted string.
    value = value.split("/", 1)[0].strip()
    upper = value.upper()
    if upper == "T":
        return True
    if upper == "F":
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def parse_fits_header(data: bytes) -> tuple[dict[str, Any], int]:
    """Parse the primary FITS header and return cards plus data offset."""

    cards: dict[str, Any] = {}
    offset = 0
    while True:
        block = data[offset : offset + 2880]
        if len(block) < 2880:
            raise ImageReadError("Truncated FITS header block.")
        end_found = False
        for index in range(0, 2880, 80):
            card = block[index : index + 80].decode("ascii", errors="replace")
            key = card[:8].strip()
            if not key:
                continue
            if key == "END":
                end_found = True
                break
            if card[8:10] == "= ":
                cards[key] = _fits_value(card[10:])
        offset += 2880
        if end_found:
            return cards, offset


def read_fits_image(image_path: str | Path) -> ImageInfo:
    """Read the primary 2-D image HDU from a FITS file."""

    path = Path(image_path).expanduser().resolve(strict=False)
    if not path.is_file():
        raise ImageReadError(f"Image not found: {path}")
    raw = path.read_bytes()
    cards, data_offset = parse_fits_header(raw)

    bitpix = int(cards.get("BITPIX", 0))
    naxis = int(cards.get("NAXIS", 0))
    if naxis != 2:
        raise ImageReadError(f"Only 2-D FITS images are supported; NAXIS={naxis}.")
    width = int(cards.get("NAXIS1", 0))
    height = int(cards.get("NAXIS2", 0))
    if width <= 0 or height <= 0:
        raise ImageReadError("FITS NAXIS1/NAXIS2 must be positive.")

    dtype_map = {
        8: "u1",
        16: ">i2",
        32: ">i4",
        -32: ">f4",
        -64: ">f8",
    }
    if bitpix not in dtype_map:
        raise ImageReadError(f"Unsupported FITS BITPIX: {bitpix}")
    dtype = np.dtype(dtype_map[bitpix])
    required = width * height * dtype.itemsize
    if data_offset + required > len(raw):
        raise ImageReadError(
            f"FITS data is truncated: need {required} bytes at offset "
            f"{data_offset}, found {len(raw) - data_offset}."
        )
    array = np.frombuffer(raw, dtype=dtype, count=width * height, offset=data_offset)
    array = array.reshape(height, width).copy()

    bscale = float(cards.get("BSCALE", 1.0))
    bzero = float(cards.get("BZERO", 0.0))
    if bscale != 1.0 or bzero != 0.0:
        array = array.astype(np.float64) * bscale + bzero

    metadata = {
        "bitpix": bitpix,
        "naxis": naxis,
        "naxis1": width,
        "naxis2": height,
        "bscale": bscale,
        "bzero": bzero,
        "exptime": cards.get("EXPTIME"),
        "target": cards.get("TARGET"),
        "instrument": cards.get("INSTRUME") or cards.get("INSTRU"),
        "telescope": cards.get("TELESCOP"),
        "date_obs": cards.get("DATE-OBS"),
        "met": cards.get("MET"),
        "request_description": cards.get("REQDESC"),
        "compression": cards.get("HSCOMPR"),
        "observation_complete": cards.get("OBSCOMPL"),
        "soc_version": cards.get("SOCVER"),
        "utc": cards.get("SPCUTCAL"),
    }
    warnings: list[str] = []
    if bscale != 1.0 or bzero != 0.0:
        warnings.append(f"Applied FITS BSCALE={bscale}, BZERO={bzero}.")
    return ImageInfo(
        path=path,
        format="fits",
        width=width,
        height=height,
        bit_depth=abs(bitpix),
        dtype=str(array.dtype),
        array=array,
        metadata={key: value for key, value in metadata.items() if value is not None},
        warnings=tuple(warnings),
    )


def load_image(image_path: str | Path, label_path: str | Path | None = None) -> ImageInfo:
    """Load a supported image by extension."""

    path = Path(image_path).expanduser().resolve(strict=False)
    suffix = path.suffix.lower()
    if suffix in {".fit", ".fits"}:
        return read_fits_image(path)
    if suffix == ".img":
        return read_pds3_image(path, label_path)
    if suffix == ".lbl":
        return read_pds3_image(path.with_suffix(".img"), path)
    raise ImageReadError(f"Unsupported image extension: {path.suffix!r}")


def normalize_for_display(
    array: np.ndarray,
    *,
    lower_percentile: float = 0.5,
    upper_percentile: float = 99.8,
) -> np.ndarray:
    """Robust percentile stretch to uint8 for overlay inspection only."""

    if not 0 <= lower_percentile < upper_percentile <= 100:
        raise ImageReadError("Percentiles must satisfy 0 <= lower < upper <= 100.")
    values = np.asarray(array, dtype=np.float64)
    finite = np.isfinite(values)
    if not finite.any():
        return np.zeros(values.shape, dtype=np.uint8)
    clean = values[finite]
    lower, upper = np.percentile(clean, [lower_percentile, upper_percentile])
    if not np.isfinite(lower) or not np.isfinite(upper) or upper <= lower:
        return np.zeros(values.shape, dtype=np.uint8)
    scaled = np.clip((values - lower) / (upper - lower), 0.0, 1.0)
    scaled[~finite] = 0.0
    return (scaled * 255.0 + 0.5).astype(np.uint8)
