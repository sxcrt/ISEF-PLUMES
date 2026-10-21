"""Evidence-backed PDS product resolution for the Io pilot.

Only the Galileo SSI and New Horizons LORRI adapters are implemented.  A
resolver result is accepted only when the product identifier and target are
consistent; similar filenames are never treated as substitutes.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from planetary_plume.annotations import AnnotationRecord

PDS_SOLR_URL = "https://pds-imaging.jpl.nasa.gov/solr/pds_archives/select"
DEFAULT_USER_AGENT = (
    "planetary-plume-ai/0.1 (+https://github.com/sxcrt/ISEF-PLUMES)"
)


class PdsError(RuntimeError):
    """Base class for PDS mapping failures."""


class ProductNotFoundError(PdsError):
    """No product matched the requested identifier and target."""


class AmbiguousProductError(PdsError):
    """More than one incompatible product matched; no silent substitution."""


def _first(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _text(value: Any) -> str:
    first = _first(value)
    return "" if first is None else str(first).strip()


def _int_or_none(value: Any) -> int | None:
    text = _text(value)
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def target_matches(candidate: str | None, expected: str | None) -> bool:
    """Token-based target match, so ``J1 IO`` matches ``Io`` but ``RADIO`` does not."""

    if not expected:
        return True
    if not candidate:
        return False
    candidate_tokens = {token for token in re.split(r"[^A-Za-z0-9]+", candidate.upper()) if token}
    expected_tokens = {token for token in re.split(r"[^A-Za-z0-9]+", expected.upper()) if token}
    return bool(expected_tokens) and expected_tokens.issubset(candidate_tokens)


@dataclass(frozen=True)
class PdsProduct:
    """A PDS product selected from a Solr document."""

    product_id: str
    image_id: str | None
    target: str
    instrument: str | None
    data_url: str
    label_url: str | None
    data_set_id: str | None
    volume_id: str | None
    product_type: str | None
    lines: int | None
    line_samples: int | None
    sample_bits: int | None
    source_query: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "image_id": self.image_id,
            "target": self.target,
            "instrument": self.instrument,
            "data_url": self.data_url,
            "label_url": self.label_url,
            "data_set_id": self.data_set_id,
            "volume_id": self.volume_id,
            "product_type": self.product_type,
            "lines": self.lines,
            "line_samples": self.line_samples,
            "sample_bits": self.sample_bits,
            "source_query": self.source_query,
        }

    @classmethod
    def from_doc(cls, doc: dict[str, Any], *, query: str) -> "PdsProduct":
        return cls(
            product_id=_text(doc.get("PRODUCT_ID") or doc.get("identifier")),
            image_id=_text(doc.get("IMAGE_ID")) or None,
            target=_text(doc.get("TARGET_NAME")),
            instrument=_text(doc.get("INSTRUMENT_ID") or doc.get("INSTRUMENT_NAME")) or None,
            data_url=_text(doc.get("ATLAS_DATA_URL")),
            label_url=_text(doc.get("ATLAS_LABEL_URL")) or None,
            data_set_id=_text(doc.get("DATA_SET_ID")) or None,
            volume_id=_text(doc.get("VOLUME_ID")) or None,
            product_type=_text(doc.get("ATLAS_PRODUCT_TYPE") or doc.get("PRODUCT_TYPE")) or None,
            lines=_int_or_none(doc.get("LINES")),
            line_samples=_int_or_none(doc.get("LINE_SAMPLES")),
            sample_bits=_int_or_none(doc.get("SAMPLE_BITS")),
            source_query=query,
        )


@dataclass(frozen=True)
class ProductMapping:
    """Mapping outcome for one annotation record."""

    annotation_relative_path: str
    product_family: str
    retrieval_identifier: str
    mapping_status: str
    product: PdsProduct | None
    candidates: tuple[str, ...]
    evidence: str
    error: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "annotation_relative_path": self.annotation_relative_path,
            "product_family": self.product_family,
            "retrieval_identifier": self.retrieval_identifier,
            "mapping_status": self.mapping_status,
            "product": self.product.to_dict() if self.product else None,
            "candidates": list(self.candidates),
            "evidence": self.evidence,
            "error": self.error,
        }


class PdsSolrClient:
    """Small read-only client for the PDS Imaging Atlas Solr index."""

    def __init__(
        self,
        base_url: str = PDS_SOLR_URL,
        *,
        timeout_seconds: float = 60.0,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        if timeout_seconds <= 0:
            raise PdsError("timeout_seconds must be positive.")
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent
        self._cache: dict[tuple[str, str], list[dict[str, Any]]] = {}

    def _query(self, term: str, *, rows: int = 20) -> list[dict[str, Any]]:
        key = ("term", term)
        if key in self._cache:
            return self._cache[key]

        query = urllib.parse.urlencode({"q": term, "wt": "json", "rows": rows})
        url = f"{self.base_url}?{query}"
        request = urllib.request.Request(
            url,
            headers={"User-Agent": self.user_agent, "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            raise PdsError(f"PDS query failed for {term!r}: {exc}") from exc

        response_data = payload.get("response", {})
        docs = response_data.get("docs", [])
        if not isinstance(docs, list):
            raise PdsError(f"Unexpected PDS response for {term!r}: missing docs list.")
        self._cache[key] = docs
        return docs

    def find_by_image_id(self, image_id: str) -> tuple[list[dict[str, Any]], str]:
        term = f"IMAGE_ID:{image_id}"
        return self._query(term), term

    def find_by_product_id(self, product_id: str) -> tuple[list[dict[str, Any]], str]:
        term = f"identifier:{product_id}"
        docs = self._query(term)
        if docs:
            return docs, term
        term = f"PRODUCT_ID:{product_id}"
        return self._query(term), term

    def resolve_galileo(self, image_id: str, target: str) -> PdsProduct:
        docs, term = self.find_by_image_id(image_id)
        return self.select_product(
            docs,
            expected_target=target,
            expected_image_id=image_id,
            query=term,
        )

    def resolve_lorri(self, product_id: str, target: str) -> PdsProduct:
        docs, term = self.find_by_product_id(product_id)
        return self.select_product(
            docs,
            expected_target=target,
            expected_product_id=product_id,
            query=term,
        )

    @staticmethod
    def select_product(
        docs: list[dict[str, Any]],
        *,
        expected_target: str,
        expected_product_id: str | None = None,
        expected_image_id: str | None = None,
        query: str = "",
    ) -> PdsProduct:
        """Select one product, rejecting filename-only lookalikes."""

        candidates: list[PdsProduct] = []
        for doc in docs:
            product = PdsProduct.from_doc(doc, query=query)
            if not product.data_url:
                continue
            if expected_image_id and (product.image_id or "").casefold() != expected_image_id.casefold():
                continue
            if expected_product_id:
                identifiers = {
                    product.product_id.casefold(),
                    _text(doc.get("identifier")).casefold(),
                }
                if expected_product_id.casefold() not in identifiers:
                    continue
            if not target_matches(product.target, expected_target):
                continue
            candidates.append(product)

        if not candidates:
            reasons = [
                f"{_text(doc.get('PRODUCT_ID') or doc.get('identifier'))} "
                f"(target={_text(doc.get('TARGET_NAME')) or '?'})"
                for doc in docs[:5]
            ]
            detail = "; ".join(reasons) if reasons else "no documents returned"
            raise ProductNotFoundError(
                f"No product matched target={expected_target!r}, "
                f"image_id={expected_image_id!r}, product_id={expected_product_id!r}. "
                f"Candidates: {detail}"
            )

        unique: dict[tuple[str, str, str], PdsProduct] = {}
        for product in candidates:
            key = (
                product.product_id.casefold(),
                product.data_url,
                product.label_url or "",
            )
            unique.setdefault(key, product)

        selected = list(unique.values())
        if len(selected) > 1:
            descriptions = [
                f"{product.product_id} target={product.target} url={product.data_url}"
                for product in selected[:8]
            ]
            raise AmbiguousProductError(
                "Multiple PDS products matched; refusing to substitute silently. "
                + " | ".join(descriptions)
            )
        return selected[0]


def resolve_record(record: AnnotationRecord, client: PdsSolrClient) -> ProductMapping:
    """Resolve one manifest record through the correct family adapter."""

    if record.product_family == "galileo_ssi":
        if record.mapping_status != "sidecar_mapped":
            return ProductMapping(
                annotation_relative_path=record.annotation_relative_path,
                product_family=record.product_family,
                retrieval_identifier=record.retrieval_identifier,
                mapping_status="unresolved",
                product=None,
                candidates=(),
                evidence=record.mapping_evidence,
                error="Galileo record has no unique image-ID sidecar mapping.",
            )
        try:
            product = client.resolve_galileo(record.retrieval_identifier, record.target_body or "")
        except PdsError as exc:
            return _failed_mapping(record, exc)
        return ProductMapping(
            annotation_relative_path=record.annotation_relative_path,
            product_family=record.product_family,
            retrieval_identifier=record.retrieval_identifier,
            mapping_status="resolved",
            product=product,
            candidates=(product.product_id,),
            evidence=f"PDS Solr {product.source_query}; target={product.target}",
            error=None,
        )

    if record.product_family == "new_horizons_lorri":
        try:
            product = client.resolve_lorri(record.retrieval_identifier, record.target_body or "")
        except PdsError as exc:
            return _failed_mapping(record, exc)
        return ProductMapping(
            annotation_relative_path=record.annotation_relative_path,
            product_family=record.product_family,
            retrieval_identifier=record.retrieval_identifier,
            mapping_status="resolved",
            product=product,
            candidates=(product.product_id,),
            evidence=f"PDS Solr {product.source_query}; target={product.target}",
            error=None,
        )

    return ProductMapping(
        annotation_relative_path=record.annotation_relative_path,
        product_family=record.product_family,
        retrieval_identifier=record.retrieval_identifier,
        mapping_status="unsupported",
        product=None,
        candidates=(),
        evidence=record.mapping_evidence,
        error=f"No acquisition adapter for family {record.product_family!r}.",
    )


def _failed_mapping(record: AnnotationRecord, exc: PdsError) -> ProductMapping:
    if isinstance(exc, AmbiguousProductError):
        status = "ambiguous"
    elif isinstance(exc, ProductNotFoundError):
        status = "not_found"
    else:
        status = "error"
    return ProductMapping(
        annotation_relative_path=record.annotation_relative_path,
        product_family=record.product_family,
        retrieval_identifier=record.retrieval_identifier,
        mapping_status=status,
        product=None,
        candidates=(),
        evidence=record.mapping_evidence,
        error=str(exc),
    )


def mapping_report(
    records: list[AnnotationRecord] | tuple[AnnotationRecord, ...],
    client: PdsSolrClient,
    *,
    target_body: str | None = "Io",
    families: tuple[str, ...] = ("galileo_ssi", "new_horizons_lorri"),
) -> list[ProductMapping]:
    """Resolve selected records and retain unsupported families explicitly."""

    selected = [
        record
        for record in records
        if (target_body is None or record.target_body == target_body)
        and record.product_family in families
    ]
    return [resolve_record(record, client) for record in selected]


def mapping_summary(mappings: list[ProductMapping] | tuple[ProductMapping, ...]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for mapping in mappings:
        counts[mapping.mapping_status] = counts.get(mapping.mapping_status, 0) + 1
    return {
        "total": len(mappings),
        "by_status": dict(sorted(counts.items())),
        "resolved_product_families": sorted(
            {mapping.product_family for mapping in mappings if mapping.product is not None}
        ),
    }


def write_mapping_report(
    mappings: list[ProductMapping] | tuple[ProductMapping, ...],
    path: str | Path,
) -> Path:
    destination = Path(path).expanduser().resolve(strict=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "summary": mapping_summary(mappings),
        "mappings": [mapping.to_dict() for mapping in mappings],
    }
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)
    return destination
