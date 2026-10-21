"""Tests for resumable acquisition, extraction, and sample planning."""

from __future__ import annotations

import hashlib
import threading
import zipfile
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from planetary_plume.acquisition import (
    AcquisitionError,
    SamplePlan,
    acquire_sample,
    acquisition_entry_from_dict,
    acquisition_summary,
    download_with_resume,
    extract_zip_safely,
    plan_io_sample,
)
from planetary_plume.annotations import AnnotationRecord
from planetary_plume.pds import PdsProduct


class _RangeHandler(BaseHTTPRequestHandler):
    payload = b"0123456789abcdef"
    requests = 0

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        type(self).requests += 1
        range_header = self.headers.get("Range")
        data = type(self).payload
        if range_header:
            start = int(range_header.split("=")[1].split("-")[0])
            body = data[start:]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(data)-1}/{len(data)}")
        else:
            body = data
            self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        return


@contextmanager
def _server(payload: bytes):
    handler = type("Handler", (_RangeHandler,), {"payload": payload, "requests": 0})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/file.bin", handler
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_download_fresh_and_skip_existing(tmp_path: Path) -> None:
    payload = b"abc123" * 100
    with _server(payload) as (url, handler):
        destination = tmp_path / "file.bin"
        first = download_with_resume(
            url,
            destination,
            expected_size=len(payload),
            expected_md5=hashlib.md5(payload).hexdigest(),
            delay_seconds=0,
        )
        assert first.status == "downloaded"
        assert destination.read_bytes() == payload
        assert first.computed_sha256 == hashlib.sha256(payload).hexdigest()

        second = download_with_resume(url, destination, delay_seconds=0)
        assert second.status == "skipped_existing"
        assert handler.requests == 1


def test_existing_bad_checksum_is_not_overwritten(tmp_path: Path) -> None:
    destination = tmp_path / "file.bin"
    destination.write_bytes(b"do not replace")
    with _server(b"expected") as (url, _handler):
        result = download_with_resume(
            url,
            destination,
            expected_md5=hashlib.md5(b"expected").hexdigest(),
            delay_seconds=0,
        )
    assert result.status == "existing_mismatch"
    assert destination.read_bytes() == b"do not replace"


def test_partial_download_resumes_with_range(tmp_path: Path) -> None:
    payload = b"0123456789abcdef" * 100
    destination = tmp_path / "file.bin"
    part = destination.with_name(destination.name + ".part")
    part.write_bytes(payload[:123])
    with _server(payload) as (url, handler):
        result = download_with_resume(
            url,
            destination,
            expected_size=len(payload),
            delay_seconds=0,
        )
    assert result.status == "resumed"
    assert result.resumed_from == 123
    assert destination.read_bytes() == payload
    assert handler.requests == 1


def test_extract_zip_refuses_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../escape_label.yml", "points: []\n")
    with pytest.raises(AcquisitionError, match="Unsafe ZIP member"):
        extract_zip_safely(archive, tmp_path / "out")


def test_extract_zip_is_atomic_and_preserves_existing(tmp_path: Path) -> None:
    archive = tmp_path / "bundle.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("plume_annotations/galileo_ssi_io/x_label.yml", "user: test\n")
        bundle.writestr("plume_annotations/galileo_image_ids.txt", "x_label.yml 11I0012\n")

    first = extract_zip_safely(archive, tmp_path / "out")
    assert first.status == "extracted"
    assert first.annotation_files == 1
    target = tmp_path / "out" / "plume_annotations" / "galileo_ssi_io" / "x_label.yml"
    before = target.read_bytes()

    second = extract_zip_safely(archive, tmp_path / "out")
    assert second.status == "skipped_existing"
    assert target.read_bytes() == before


def _record(
    path: str,
    *,
    family: str,
    plume: bool,
    mapping_status: str = "sidecar_mapped",
    target: str = "Io",
) -> AnnotationRecord:
    return AnnotationRecord(
        annotation_filename=Path(path).name,
        annotation_relative_path=path,
        annotation_sha256="0" * 64,
        directory=Path(path).parent.name,
        target_body=target,
        instrument="Galileo SSI" if family == "galileo_ssi" else "New Horizons LORRI",
        product_family=family,
        label_identifier=Path(path).stem.replace("_label", ""),
        retrieval_identifier=Path(path).stem.replace("_label", ""),
        retrieval_identifier_kind="galileo_image_id",
        mapping_status=mapping_status,
        mapping_evidence="test",
        plume_status=plume,
        plume_interval_count=1 if plume else 0,
        plume_intervals=((1.0, 1.1),) if plume else (),
        limb_point_count=3,
        limb_points=((1.0, 2.0), (3.0, 4.0), (5.0, 6.0)),
        annotator="tester",
        warnings=(),
    )


def test_plan_io_sample_is_stratified_and_deterministic() -> None:
    records = [
        _record("galileo_ssi_io/a_label.yml", family="galileo_ssi", plume=True),
        _record("galileo_ssi_io/b_label.yml", family="galileo_ssi", plume=True),
        _record("galileo_ssi_io/c_label.yml", family="galileo_ssi", plume=False),
        _record(
            "new_horizons_lorri_io/d_label.yml",
            family="new_horizons_lorri",
            plume=True,
            mapping_status="label_stem_candidate",
        ),
        _record(
            "new_horizons_lorri_io/e_label.yml",
            family="new_horizons_lorri",
            plume=False,
            mapping_status="label_stem_candidate",
        ),
        _record("galileo_ssi_europa/f_label.yml", family="galileo_ssi", plume=True, target="Europa"),
    ]

    plan = plan_io_sample(records, per_stratum=1)

    assert len(plan.records) == 4
    assert plan.strata == {
        "galileo_ssi:negative": 1,
        "galileo_ssi:positive": 1,
        "new_horizons_lorri:negative": 1,
        "new_horizons_lorri:positive": 1,
    }
    assert all(record.target_body == "Io" for record in plan.records)

    second = plan_io_sample(records, per_stratum=1)
    assert [record.annotation_relative_path for record in second.records] == [
        record.annotation_relative_path for record in plan.records
    ]


@pytest.mark.parametrize("per_stratum", [0, -1])
def test_plan_rejects_invalid_stratum(per_stratum: int) -> None:
    with pytest.raises(AcquisitionError, match="positive"):
        plan_io_sample([], per_stratum=per_stratum)


def test_acquisition_summary_counts_statuses() -> None:
    # A lightweight check of the summary helper without network access.
    from planetary_plume.acquisition import AcquisitionEntry

    entries = [
        AcquisitionEntry(
            annotation_relative_path="a",
            annotation_sha256="0",
            product_family="galileo_ssi",
            retrieval_identifier="11I0012",
            mapping_status="resolved",
            resolved_product_id="0085r.img",
            resolved_image_id="11I0012",
            target="IO",
            instrument="SSI",
            data_url="https://example/a.img",
            label_url="https://example/a.lbl",
            image_path="a.img",
            label_path="a.lbl",
            image_size_bytes=100,
            image_sha256="abc",
            label_sha256="def",
            download_status="downloaded",
            label_download_status="downloaded",
            http_status=200,
            error=None,
            mapping_evidence="test",
        )
    ]
    summary = acquisition_summary(entries)
    assert summary["total_planned"] == 1
    assert summary["by_download_status"] == {"downloaded": 1}
    assert summary["total_image_bytes"] == 100


class _FileClient:
    def __init__(self, data_url: str, label_url: str) -> None:
        self.data_url = data_url
        self.label_url = label_url

    def resolve_lorri(self, product_id: str, target: str) -> PdsProduct:
        return PdsProduct(
            product_id="LOR_TEST",
            image_id=None,
            target="J1 IO",
            instrument="LORRI",
            data_url=self.data_url,
            label_url=self.label_url,
            data_set_id="NH-J-LORRI-3-JUPITER-V3.0",
            volume_id="test",
            product_type="RDR",
            lines=2,
            line_samples=2,
            sample_bits=32,
            source_query=f"identifier:{product_id}",
        )


def test_acquire_sample_downloads_and_then_skips(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    image_source = source / "image.fit"
    label_source = source / "image.lbl"
    image_source.write_bytes(b"fake-fits-bytes")
    label_source.write_text("PDS_VERSION_ID = PDS3\n", encoding="utf-8")

    record = _record(
        "new_horizons_lorri_io/lor_test_label.yml",
        family="new_horizons_lorri",
        plume=True,
        mapping_status="label_stem_candidate",
    )
    record = AnnotationRecord(
        **{**record.__dict__, "retrieval_identifier": "lor_test"}
    )
    plan = SamplePlan((record,), {"new_horizons_lorri:positive": 1}, ())
    client = _FileClient(image_source.as_uri(), label_source.as_uri())
    log_path = tmp_path / "acquisition_log.json"

    first = acquire_sample(
        plan,
        client,  # type: ignore[arg-type]
        tmp_path / "images",
        delay_seconds=0,
        log_path=log_path,
    )

    assert len(first) == 1
    assert first[0].download_status == "downloaded"
    assert Path(first[0].image_path or "").read_bytes() == b"fake-fits-bytes"
    assert Path(first[0].label_path or "").is_file()
    assert first[0].image_sha256 == hashlib.sha256(b"fake-fits-bytes").hexdigest()
    assert log_path.is_file()

    restored = acquisition_entry_from_dict(first[0].to_dict())
    assert restored.annotation_relative_path == record.annotation_relative_path

    second = acquire_sample(
        plan,
        client,  # type: ignore[arg-type]
        tmp_path / "images",
        delay_seconds=0,
        log_path=log_path,
    )
    assert second[0].download_status == "skipped_existing"
    assert Path(second[0].image_path or "").read_bytes() == b"fake-fits-bytes"
