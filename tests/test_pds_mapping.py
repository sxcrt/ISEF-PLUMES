"""Tests for evidence-backed PDS product selection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from planetary_plume.annotations import AnnotationRecord
from planetary_plume.pds import (
    AmbiguousProductError,
    PdsProduct,
    PdsSolrClient,
    ProductNotFoundError,
    mapping_summary,
    resolve_record,
    target_matches,
    write_mapping_report,
)


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


def _doc(
    *,
    product_id: str,
    image_id: str,
    target: str,
    url: str,
    instrument: str = "LORRI",
    label: str | None = None,
) -> dict[str, object]:
    return {
        "PRODUCT_ID": product_id,
        "IMAGE_ID": image_id,
        "TARGET_NAME": target,
        "INSTRUMENT_ID": instrument,
        "ATLAS_DATA_URL": url,
        "ATLAS_LABEL_URL": label or url.replace(".fit", ".lbl"),
        "DATA_SET_ID": "TEST-DATA-SET",
        "VOLUME_ID": "test_volume",
        "ATLAS_PRODUCT_TYPE": "RDR",
        "LINES": 1024,
        "LINE_SAMPLES": 1024,
        "SAMPLE_BITS": 32,
    }


def test_target_matching_is_token_based() -> None:
    assert target_matches("J1 IO", "Io")
    assert target_matches("IO", "Io")
    assert target_matches("CALLISTO", "Callisto")
    assert not target_matches("RADIO", "Io")
    assert not target_matches("EUROPA", "Io")
    assert not target_matches(None, "Io")


def test_select_product_rejects_wrong_target_and_similar_name() -> None:
    docs = [
        _doc(product_id="0085r.img", image_id="11I0012", target="IO", url="https://example/io.img"),
        _doc(
            product_id="0085r.img",
            image_id="E1H0818",
            target="BET_ARI",
            url="https://example/star.img",
        ),
    ]

    product = PdsSolrClient.select_product(
        docs,
        expected_target="Io",
        expected_image_id="11I0012",
        query="IMAGE_ID:11I0012",
    )

    assert product.target == "IO"
    assert product.data_url == "https://example/io.img"


def test_select_product_refuses_ambiguous_matches() -> None:
    docs = [
        _doc(product_id="A.fit", image_id="A1", target="J1 IO", url="https://example/a.fit"),
        _doc(product_id="B.fit", image_id="A1", target="IO", url="https://example/b.fit"),
    ]

    with pytest.raises(AmbiguousProductError, match="refusing to substitute"):
        PdsSolrClient.select_product(
            docs,
            expected_target="Io",
            expected_image_id="A1",
            query="IMAGE_ID:A1",
        )


def test_select_product_not_found() -> None:
    docs = [
        _doc(product_id="A.fit", image_id="A1", target="EUROPA", url="https://example/a.fit")
    ]

    with pytest.raises(ProductNotFoundError, match="No product matched"):
        PdsSolrClient.select_product(
            docs,
            expected_target="Io",
            expected_image_id="A1",
            query="IMAGE_ID:A1",
        )


def _record(
    *,
    family: str,
    status: str,
    retrieval_identifier: str,
    target: str = "Io",
) -> AnnotationRecord:
    return AnnotationRecord(
        annotation_filename="x_label.yml",
        annotation_relative_path="galileo_ssi_io/x_label.yml",
        annotation_sha256="0" * 64,
        directory="galileo_ssi_io",
        target_body=target,
        instrument="Galileo SSI",
        product_family=family,
        label_identifier="x",
        retrieval_identifier=retrieval_identifier,
        retrieval_identifier_kind="galileo_image_id",
        mapping_status=status,
        mapping_evidence="test evidence",
        plume_status=True,
        plume_interval_count=1,
        plume_intervals=((1.0, 1.1),),
        limb_point_count=3,
        limb_points=((1.0, 2.0), (3.0, 4.0), (5.0, 6.0)),
        annotator="tester",
        warnings=(),
    )


class _StubClient:
    def resolve_galileo(self, image_id: str, target: str) -> PdsProduct:
        return PdsProduct(
            product_id="0085r.img",
            image_id=image_id,
            target=target.upper(),
            instrument="SSI",
            data_url="https://example/0085r.img",
            label_url="https://example/0085r.lbl",
            data_set_id="GO-J/JSA-SSI-2-REDR-V1.0",
            volume_id="go_0020",
            product_type="EDR",
            lines=800,
            line_samples=800,
            sample_bits=8,
            source_query=f"IMAGE_ID:{image_id}",
        )

    def resolve_lorri(self, product_id: str, target: str) -> PdsProduct:
        return PdsProduct(
            product_id=product_id.upper(),
            image_id=None,
            target="J1 IO",
            instrument="LORRI",
            data_url="https://example/lor.fit",
            label_url="https://example/lor.lbl",
            data_set_id="NH-J-LORRI-3-JUPITER-V3.0",
            volume_id="nhjulo_2001",
            product_type="RDR",
            lines=1024,
            line_samples=1024,
            sample_bits=32,
            source_query=f"identifier:{product_id}",
        )


def test_resolve_record_uses_family_adapter() -> None:
    galileo = resolve_record(
        _record(family="galileo_ssi", status="sidecar_mapped", retrieval_identifier="11I0012"),
        _StubClient(),  # type: ignore[arg-type]
    )
    assert galileo.mapping_status == "resolved"
    assert galileo.product is not None
    assert galileo.product.product_id == "0085r.img"

    lorri = resolve_record(
        _record(
            family="new_horizons_lorri",
            status="label_stem_candidate",
            retrieval_identifier="lor_0034769759_0x630_sci",
        ),
        _StubClient(),  # type: ignore[arg-type]
    )
    assert lorri.mapping_status == "resolved"
    assert lorri.product is not None
    assert lorri.product.instrument == "LORRI"


def test_resolve_record_marks_unsupported_family() -> None:
    mapping = resolve_record(
        _record(family="cassini_iss", status="unresolved_adapter", retrieval_identifier="N1"),
        _StubClient(),  # type: ignore[arg-type]
    )
    assert mapping.mapping_status == "unsupported"
    assert mapping.product is None


def test_mapping_report_round_trip(tmp_path: Path) -> None:
    mapping = resolve_record(
        _record(family="galileo_ssi", status="sidecar_mapped", retrieval_identifier="11I0012"),
        _StubClient(),  # type: ignore[arg-type]
    )

    path = write_mapping_report([mapping], tmp_path / "mapping.json")
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["summary"]["by_status"] == {"resolved": 1}
    assert payload["mappings"][0]["product"]["product_id"] == "0085r.img"
    assert mapping_summary([mapping])["total"] == 1


def test_solr_client_queries_and_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    doc = _doc(
        product_id="0085r.img",
        image_id="11I0012",
        target="IO",
        url="https://example/io.img",
    )

    def fake_urlopen(request: object, timeout: float) -> _FakeResponse:
        calls.append(request.full_url)  # type: ignore[attr-defined]
        return _FakeResponse({"response": {"docs": [doc]}})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = PdsSolrClient()

    docs, term = client.find_by_image_id("11I0012")
    second_docs, second_term = client.find_by_image_id("11I0012")

    assert docs == second_docs
    assert term == second_term == "IMAGE_ID:11I0012"
    assert len(calls) == 1


class _FailingClient:
    def resolve_lorri(self, product_id: str, target: str) -> PdsProduct:
        raise ProductNotFoundError("No LORRI product matched.")


def test_resolve_record_maps_not_found_status() -> None:
    mapping = resolve_record(
        _record(
            family="new_horizons_lorri",
            status="label_stem_candidate",
            retrieval_identifier="lor_missing",
        ),
        _FailingClient(),  # type: ignore[arg-type]
    )

    assert mapping.mapping_status == "not_found"
    assert mapping.product is None
    assert "No LORRI product" in (mapping.error or "")
