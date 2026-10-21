"""Resumable, checksum-aware acquisition for labels and a small Io sample.

The acquisition layer never overwrites an existing final file and never
substitutes a product based on filename similarity.  Partial downloads use a
``.part`` file and HTTP Range requests so interrupted runs can resume.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from planetary_plume.annotations import (
    ZENODO_ZIP_MD5,
    ZENODO_ZIP_NAME,
    ZENODO_ZIP_SIZE,
    ZENODO_ZIP_URL,
    AnnotationRecord,
)
from planetary_plume.pds import (
    DEFAULT_USER_AGENT,
    PdsError,
    PdsSolrClient,
    ProductMapping,
    resolve_record,
)

DEFAULT_DELAY_SECONDS = 0.5
DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_RETRIES = 3


class AcquisitionError(RuntimeError):
    """Raised when acquisition cannot proceed safely."""


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def md5_file(path: str | Path) -> str:
    digest = hashlib.md5()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class DownloadResult:
    url: str
    destination: Path
    status: str
    http_status: int | None
    bytes_written: int
    expected_size: int | None
    computed_sha256: str | None
    computed_md5: str | None
    expected_md5: str | None
    resumed_from: int
    attempts: int
    error: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "destination": str(self.destination),
            "status": self.status,
            "http_status": self.http_status,
            "bytes_written": self.bytes_written,
            "expected_size": self.expected_size,
            "computed_sha256": self.computed_sha256,
            "computed_md5": self.computed_md5,
            "expected_md5": self.expected_md5,
            "resumed_from": self.resumed_from,
            "attempts": self.attempts,
            "error": self.error,
        }


def _existing_result(
    url: str,
    destination: Path,
    *,
    expected_size: int | None,
    expected_md5: str | None,
) -> DownloadResult:
    size = destination.stat().st_size
    computed_md5 = md5_file(destination) if expected_md5 else None
    computed_sha256 = sha256_file(destination)
    error = None
    if expected_size is not None and size != expected_size:
        error = (
            f"Existing file size {size} does not match expected {expected_size}; "
            "refusing to overwrite."
        )
    if expected_md5 is not None and computed_md5 != expected_md5:
        error = (
            "Existing file MD5 does not match the expected value; refusing to "
            "overwrite."
        )
    status = "existing_mismatch" if error else "skipped_existing"
    return DownloadResult(
        url=url,
        destination=destination,
        status=status,
        http_status=None,
        bytes_written=size,
        expected_size=expected_size,
        computed_sha256=computed_sha256,
        computed_md5=computed_md5,
        expected_md5=expected_md5,
        resumed_from=0,
        attempts=0,
        error=error,
    )


def download_with_resume(
    url: str,
    destination: str | Path,
    *,
    expected_size: int | None = None,
    expected_md5: str | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    retries: int = DEFAULT_RETRIES,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    user_agent: str = DEFAULT_USER_AGENT,
    overwrite: bool = False,
) -> DownloadResult:
    """Download a URL, resuming ``.part`` files and verifying optional integrity."""

    if timeout_seconds <= 0:
        raise AcquisitionError("timeout_seconds must be positive.")
    if retries < 0:
        raise AcquisitionError("retries must be non-negative.")
    if delay_seconds < 0:
        raise AcquisitionError("delay_seconds must be non-negative.")

    target = Path(destination).expanduser().resolve(strict=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not overwrite:
        return _existing_result(
            url,
            target,
            expected_size=expected_size,
            expected_md5=expected_md5,
        )

    part = target.with_name(target.name + ".part")
    last_http_status: int | None = None
    last_error: str | None = None
    resumed_from = 0
    attempts_used = 0

    for attempt in range(1, retries + 2):
        attempts_used = attempt
        if delay_seconds:
            time.sleep(delay_seconds * (attempt - 1))
        if part.exists() and expected_size is not None and part.stat().st_size > expected_size:
            part.unlink(missing_ok=True)
        resume_from = part.stat().st_size if part.exists() else 0
        resumed_from = max(resumed_from, resume_from)

        headers = {"User-Agent": user_agent}
        if resume_from:
            headers["Range"] = f"bytes={resume_from}-"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                last_http_status = getattr(response, "status", None)
                content_length = response.headers.get("Content-Length")
                remaining = int(content_length) if content_length is not None else None
                if last_http_status == 206 and resume_from:
                    mode = "ab"
                else:
                    mode = "wb"
                    if resume_from:
                        resume_from = 0
                with part.open(mode) as handle:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
                final_size = part.stat().st_size
                if expected_size is not None and final_size != expected_size:
                    raise AcquisitionError(
                        f"Downloaded size {final_size} != expected {expected_size}."
                    )
                computed_md5 = md5_file(part) if expected_md5 else None
                if expected_md5 is not None and computed_md5 != expected_md5:
                    # Do not promote a corrupt partial file.  Keep a copy for
                    # diagnosis, but restart from zero on the next attempt.
                    corrupt = part.with_name(part.name + ".corrupt")
                    if corrupt.exists():
                        corrupt.unlink()
                    part.replace(corrupt)
                    raise AcquisitionError(
                        f"MD5 mismatch: expected {expected_md5}, got {computed_md5}. "
                        f"Corrupt partial kept at {corrupt}."
                    )
                if target.exists() and not overwrite:
                    raise AcquisitionError(
                        f"Destination appeared during download and will not be "
                        f"overwritten: {target}"
                    )
                os.replace(part, target)
                return DownloadResult(
                    url=url,
                    destination=target,
                    status="downloaded" if resume_from == 0 else "resumed",
                    http_status=last_http_status,
                    bytes_written=final_size,
                    expected_size=expected_size,
                    computed_sha256=sha256_file(target),
                    computed_md5=computed_md5,
                    expected_md5=expected_md5,
                    resumed_from=resume_from,
                    attempts=attempt,
                    error=None,
                )
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, AcquisitionError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if isinstance(exc, urllib.error.HTTPError) and exc.code == 416:
                # A Range request can be unsatisfiable if the partial is already
                # complete.  Let the next attempt start from zero.
                part.unlink(missing_ok=True)
            if attempt > retries:
                break

    return DownloadResult(
        url=url,
        destination=target,
        status="failed",
        http_status=last_http_status,
        bytes_written=part.stat().st_size if part.exists() else 0,
        expected_size=expected_size,
        computed_sha256=sha256_file(part) if part.exists() else None,
        computed_md5=md5_file(part) if part.exists() and expected_md5 else None,
        expected_md5=expected_md5,
        resumed_from=resumed_from,
        attempts=attempts_used,
        error=last_error,
    )


def _safe_zip_member(name: str) -> str:
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or normalized.startswith("../") or "/../" in normalized:
        raise AcquisitionError(f"Unsafe ZIP member path: {name!r}")
    if len(normalized) >= 2 and normalized[1] == ":":
        raise AcquisitionError(f"Unsafe drive-letter ZIP member: {name!r}")
    if not normalized or normalized in {".", ".."}:
        raise AcquisitionError(f"Unsafe ZIP member name: {name!r}")
    return normalized


@dataclass(frozen=True)
class ExtractionResult:
    zip_path: Path
    destination: Path
    status: str
    annotation_files: int
    error: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "zip_path": str(self.zip_path),
            "destination": str(self.destination),
            "status": self.status,
            "annotation_files": self.annotation_files,
            "error": self.error,
        }


def extract_zip_safely(
    zip_path: str | Path,
    destination: str | Path,
) -> ExtractionResult:
    """Extract a ZIP atomically, refusing path traversal and symlinks."""

    archive = Path(zip_path).expanduser().resolve(strict=False)
    target = Path(destination).expanduser().resolve(strict=False)
    if not archive.is_file():
        raise AcquisitionError(f"ZIP file not found: {archive}")
    if target.exists():
        count = len(list(target.rglob("*_label.yml")))
        if count:
            return ExtractionResult(archive, target, "skipped_existing", count, None)
        if any(target.iterdir()):
            raise AcquisitionError(
                f"Extraction destination exists and is not an annotation bundle: {target}"
            )
        target.rmdir()

    temporary = target.with_name(target.name + ".extracting")
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(archive) as bundle:
            bad = bundle.testzip()
            if bad is not None:
                raise AcquisitionError(f"Corrupt ZIP member: {bad}")
            for info in bundle.infolist():
                name = _safe_zip_member(info.filename)
                mode = (info.external_attr >> 16) & 0o170000
                if mode == 0o120000:
                    raise AcquisitionError(f"Symlink ZIP member is not allowed: {name!r}")
                if info.is_dir():
                    (temporary / name).mkdir(parents=True, exist_ok=True)
                    continue
                output = temporary / name
                output.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(info) as source, output.open("wb") as sink:
                    shutil.copyfileobj(source, sink)

        count = len(list(temporary.rglob("*_label.yml")))
        if count == 0:
            raise AcquisitionError("ZIP extracted but contains no *_label.yml files.")
        if target.exists():
            shutil.rmtree(temporary)
            return ExtractionResult(
                archive,
                target,
                "skipped_existing",
                len(list(target.rglob("*_label.yml"))),
                None,
            )
        os.replace(temporary, target)
        return ExtractionResult(archive, target, "extracted", count, None)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
        raise


@dataclass(frozen=True)
class AnnotationAcquisition:
    download: DownloadResult
    extraction: ExtractionResult
    annotation_root: Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "download": self.download.to_dict(),
            "extraction": self.extraction.to_dict(),
            "annotation_root": str(self.annotation_root),
        }


def acquire_annotations(
    data_dir: str | Path,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    retries: int = DEFAULT_RETRIES,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
) -> AnnotationAcquisition:
    """Download and extract the Zenodo annotation bundle without overwriting."""

    root = Path(data_dir).expanduser().resolve(strict=False) / "raw" / "zenodo_2556063"
    archive = root / ZENODO_ZIP_NAME
    download = download_with_resume(
        ZENODO_ZIP_URL,
        archive,
        expected_size=ZENODO_ZIP_SIZE,
        expected_md5=ZENODO_ZIP_MD5,
        timeout_seconds=timeout_seconds,
        retries=retries,
        delay_seconds=delay_seconds,
    )
    if download.status not in {"downloaded", "resumed", "skipped_existing"}:
        raise AcquisitionError(
            f"Annotation bundle download failed: {download.error or download.status}"
        )
    extraction = extract_zip_safely(archive, root / "annotations")
    annotation_root = extraction.destination / "plume_annotations"
    if not annotation_root.is_dir():
        # The current bundle uses this directory; if a future bundle does not,
        # locate it rather than assuming.
        candidates = sorted(extraction.destination.rglob("galileo_image_ids.txt"))
        if not candidates:
            raise AcquisitionError(
                "Extracted bundle has no plume_annotations directory or sidecar."
            )
        annotation_root = candidates[0].parent
    return AnnotationAcquisition(download, extraction, annotation_root)


@dataclass(frozen=True)
class SamplePlan:
    records: tuple[AnnotationRecord, ...]
    strata: dict[str, int]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "records": [record.to_dict() for record in self.records],
            "strata": dict(sorted(self.strata.items())),
            "warnings": list(self.warnings),
            "total": len(self.records),
        }


def plan_io_sample(
    records: list[AnnotationRecord] | tuple[AnnotationRecord, ...],
    *,
    per_stratum: int = 3,
    target_body: str = "Io",
    families: tuple[str, ...] = ("galileo_ssi", "new_horizons_lorri"),
) -> SamplePlan:
    """Deterministically select a stratified Io sample with both classes."""

    if per_stratum <= 0:
        raise AcquisitionError("per_stratum must be positive.")

    grouped: dict[tuple[str, bool], list[AnnotationRecord]] = {}
    for record in records:
        if record.target_body != target_body:
            continue
        if record.product_family not in families:
            continue
        if record.product_family == "galileo_ssi" and record.mapping_status != "sidecar_mapped":
            continue
        grouped.setdefault((record.product_family, record.plume_status), []).append(record)

    selected: list[AnnotationRecord] = []
    strata: dict[str, int] = {}
    warnings: list[str] = []
    for (family, plume_status), group in sorted(grouped.items()):
        ordered = sorted(group, key=lambda item: item.annotation_relative_path)
        chosen = ordered[:per_stratum]
        selected.extend(chosen)
        key = f"{family}:{'positive' if plume_status else 'negative'}"
        strata[key] = len(chosen)
        if len(chosen) < per_stratum:
            warnings.append(
                f"{key} has only {len(chosen)} available record(s); "
                f"requested {per_stratum}."
            )

    for family in families:
        has_positive = any(
            record.product_family == family and record.plume_status
            for record in selected
        )
        has_negative = any(
            record.product_family == family and not record.plume_status
            for record in selected
        )
        if not has_positive:
            warnings.append(f"{family}: no positive annotation selected.")
        if not has_negative:
            warnings.append(f"{family}: no negative annotation selected.")

    selected.sort(
        key=lambda item: (
            item.product_family,
            not item.plume_status,
            item.annotation_relative_path,
        )
    )
    return SamplePlan(tuple(selected), strata, tuple(warnings))


def _url_filename(url: str | None) -> str | None:
    if not url:
        return None
    path = urllib.parse.urlsplit(url).path
    name = Path(path).name
    if name and name.lower() not in {"prod", "download"} and "." in name:
        return name
    return None


def _sanitize_filename(name: str) -> str:
    cleaned = "".join(
        character if character.isalnum() or character in "._-" else "_"
        for character in name
    ).strip("._")
    if not cleaned:
        raise AcquisitionError(f"Could not derive a safe filename from {name!r}.")
    return cleaned


def _data_filename(mapping: ProductMapping) -> str:
    assert mapping.product is not None
    from_url = _url_filename(mapping.product.data_url)
    if from_url:
        return _sanitize_filename(from_url)
    product_id = mapping.product.product_id
    if Path(product_id).suffix.lower() in {".fit", ".fits", ".img"}:
        return _sanitize_filename(product_id)
    return _sanitize_filename(product_id + ".img")


def _label_filename(mapping: ProductMapping, data_filename: str) -> str:
    from_url = _url_filename(mapping.product.label_url if mapping.product else None)
    if from_url:
        return _sanitize_filename(from_url)
    stem = Path(data_filename).stem
    return _sanitize_filename(stem + ".lbl")


@dataclass(frozen=True)
class AcquisitionEntry:
    annotation_relative_path: str
    annotation_sha256: str
    product_family: str
    retrieval_identifier: str
    mapping_status: str
    resolved_product_id: str | None
    resolved_image_id: str | None
    target: str | None
    instrument: str | None
    data_url: str | None
    label_url: str | None
    image_path: str | None
    label_path: str | None
    image_size_bytes: int | None
    image_sha256: str | None
    label_sha256: str | None
    download_status: str
    label_download_status: str | None
    http_status: int | None
    error: str | None
    mapping_evidence: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "annotation_relative_path": self.annotation_relative_path,
            "annotation_sha256": self.annotation_sha256,
            "product_family": self.product_family,
            "retrieval_identifier": self.retrieval_identifier,
            "mapping_status": self.mapping_status,
            "resolved_product_id": self.resolved_product_id,
            "resolved_image_id": self.resolved_image_id,
            "target": self.target,
            "instrument": self.instrument,
            "data_url": self.data_url,
            "label_url": self.label_url,
            "image_path": self.image_path,
            "label_path": self.label_path,
            "image_size_bytes": self.image_size_bytes,
            "image_sha256": self.image_sha256,
            "label_sha256": self.label_sha256,
            "download_status": self.download_status,
            "label_download_status": self.label_download_status,
            "http_status": self.http_status,
            "error": self.error,
            "mapping_evidence": self.mapping_evidence,
        }


def acquire_sample(
    plan: SamplePlan,
    client: PdsSolrClient,
    images_dir: str | Path,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    retries: int = DEFAULT_RETRIES,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    overwrite: bool = False,
    log_path: str | Path | None = None,
) -> list[AcquisitionEntry]:
    """Resolve and download the selected sample, preserving originals."""

    destination = Path(images_dir).expanduser().resolve(strict=False)
    destination.mkdir(parents=True, exist_ok=True)
    entries: list[AcquisitionEntry] = []

    for record in plan.records:
        mapping = resolve_record(record, client)
        if mapping.mapping_status != "resolved" or mapping.product is None:
            entry = AcquisitionEntry(
                annotation_relative_path=record.annotation_relative_path,
                annotation_sha256=record.annotation_sha256,
                product_family=record.product_family,
                retrieval_identifier=record.retrieval_identifier,
                mapping_status=mapping.mapping_status,
                resolved_product_id=None,
                resolved_image_id=None,
                target=record.target_body,
                instrument=record.instrument,
                data_url=None,
                label_url=None,
                image_path=None,
                label_path=None,
                image_size_bytes=None,
                image_sha256=None,
                label_sha256=None,
                download_status="mapping_failed",
                label_download_status=None,
                http_status=None,
                error=mapping.error,
                mapping_evidence=mapping.evidence,
            )
            entries.append(entry)
            _write_log(entries, log_path)
            continue

        product = mapping.product
        family_dir = destination / record.product_family
        product_dir = family_dir / _sanitize_filename(record.label_identifier)
        product_dir.mkdir(parents=True, exist_ok=True)
        data_name = _data_filename(mapping)
        label_name = _label_filename(mapping, data_name)
        image_path = product_dir / data_name
        label_path = product_dir / label_name

        data_result = download_with_resume(
            product.data_url,
            image_path,
            timeout_seconds=timeout_seconds,
            retries=retries,
            delay_seconds=delay_seconds,
            overwrite=overwrite,
        )
        label_result: DownloadResult | None = None
        label_status: str | None = None
        if product.label_url:
            label_result = download_with_resume(
                product.label_url,
                label_path,
                timeout_seconds=timeout_seconds,
                retries=retries,
                delay_seconds=delay_seconds,
                overwrite=overwrite,
            )
            label_status = label_result.status

        download_ok = data_result.status in {"downloaded", "resumed", "skipped_existing"}
        error = data_result.error
        if not download_ok:
            error = data_result.error or data_result.status
        elif label_result is not None and label_result.status not in {
            "downloaded",
            "resumed",
            "skipped_existing",
        }:
            error = f"label download: {label_result.error or label_result.status}"

        label_ok = bool(
            label_result
            and label_result.status in {"downloaded", "resumed", "skipped_existing"}
        )
        entry = AcquisitionEntry(
            annotation_relative_path=record.annotation_relative_path,
            annotation_sha256=record.annotation_sha256,
            product_family=record.product_family,
            retrieval_identifier=record.retrieval_identifier,
            mapping_status=mapping.mapping_status,
            resolved_product_id=product.product_id,
            resolved_image_id=product.image_id,
            target=product.target,
            instrument=product.instrument,
            data_url=product.data_url,
            label_url=product.label_url,
            image_path=str(image_path) if download_ok else None,
            label_path=str(label_path) if label_ok else None,
            image_size_bytes=data_result.bytes_written if download_ok else None,
            image_sha256=data_result.computed_sha256 if download_ok else None,
            label_sha256=(
                label_result.computed_sha256 if label_result and label_ok else None
            ),
            download_status=data_result.status,
            label_download_status=label_status,
            http_status=data_result.http_status,
            error=error,
            mapping_evidence=mapping.evidence,
        )
        entries.append(entry)
        _write_log(entries, log_path)

    return entries


def acquisition_entry_from_dict(payload: dict[str, Any]) -> AcquisitionEntry:
    """Reconstruct an acquisition entry from an acquisition-log JSON object."""

    required = (
        "annotation_relative_path",
        "annotation_sha256",
        "product_family",
        "retrieval_identifier",
        "mapping_status",
        "download_status",
    )
    missing = [key for key in required if key not in payload]
    if missing:
        raise AcquisitionError(
            f"Acquisition entry is missing fields: {', '.join(missing)}"
        )
    return AcquisitionEntry(
        annotation_relative_path=str(payload["annotation_relative_path"]),
        annotation_sha256=str(payload["annotation_sha256"]),
        product_family=str(payload["product_family"]),
        retrieval_identifier=str(payload["retrieval_identifier"]),
        mapping_status=str(payload["mapping_status"]),
        resolved_product_id=payload.get("resolved_product_id"),
        resolved_image_id=payload.get("resolved_image_id"),
        target=payload.get("target"),
        instrument=payload.get("instrument"),
        data_url=payload.get("data_url"),
        label_url=payload.get("label_url"),
        image_path=payload.get("image_path"),
        label_path=payload.get("label_path"),
        image_size_bytes=payload.get("image_size_bytes"),
        image_sha256=payload.get("image_sha256"),
        label_sha256=payload.get("label_sha256"),
        download_status=str(payload["download_status"]),
        label_download_status=payload.get("label_download_status"),
        http_status=payload.get("http_status"),
        error=payload.get("error"),
        mapping_evidence=str(payload.get("mapping_evidence", "")),
    )


def acquisition_summary(entries: list[AcquisitionEntry] | tuple[AcquisitionEntry, ...]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    by_family: dict[str, int] = {}
    total_bytes = 0
    for entry in entries:
        counts[entry.download_status] = counts.get(entry.download_status, 0) + 1
        by_family[entry.product_family] = by_family.get(entry.product_family, 0) + 1
        if entry.image_size_bytes:
            total_bytes += entry.image_size_bytes
    return {
        "total_planned": len(entries),
        "by_download_status": dict(sorted(counts.items())),
        "by_family": dict(sorted(by_family.items())),
        "total_image_bytes": total_bytes,
    }


def _write_log(entries: list[AcquisitionEntry], log_path: str | Path | None) -> None:
    if log_path is None:
        return
    destination = Path(log_path).expanduser().resolve(strict=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "summary": acquisition_summary(entries),
        "entries": [entry.to_dict() for entry in entries],
    }
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)
