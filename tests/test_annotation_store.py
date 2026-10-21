"""Tests for saving, loading, editing, and deleting independent annotations."""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from planetary_plume.annotation_store import (
    ANNOTATION_FORMAT,
    ANNOTATION_FORMAT_VERSION,
    PROTOCOL_VERSION,
    AnnotationStoreError,
    CandidateAnnotation,
    CandidateGeometry,
    ConcurrentModificationError,
    ImageReview,
    ReviewSession,
    file_sha256,
    load_session,
    new_candidate,
    new_session,
    save_session,
    utc_now_iso,
)
from planetary_plume.review_manifest import LimbCircle, ReviewImage, ReviewManifest

FIXED = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)
FIXED_LATER = datetime(2026, 10, 20, 12, 1, 0, tzinfo=timezone.utc)


def _image(image_id: str = "test:001", **overrides: object) -> ReviewImage:
    values = {
        "image_id": image_id,
        "display_name": f"Test image {image_id}",
        "product_family": "test",
        "target": "Io",
        "instrument": "Test camera",
        "width": 32,
        "height": 32,
        "image_format": "fits",
        "product_id": image_id.split(":")[-1],
        "product_path": f"C:/data/{image_id.split(':')[-1]}.fit",
        "pds_label_path": None,
        "image_sha256": "a" * 64,
        "limb": LimbCircle(16.0, 16.0, 10.0, 0.1),
    }
    values.update(overrides)
    return ReviewImage(**values)


def _manifest(*images: ReviewImage) -> ReviewManifest:
    return ReviewManifest(
        generated_at_utc="2026-10-20T00:00:00Z",
        source={"note": "test"},
        images=tuple(images or (_image(),)),
    )


def _session(*images: ReviewImage) -> ReviewSession:
    return new_session(_manifest(*images), "tester", now=FIXED)


def _candidate(kind: str = "interval", **overrides: object) -> CandidateAnnotation:
    geometry = (
        CandidateGeometry.interval_from_degrees(350.0, 10.0)
        if kind == "interval"
        else CandidateGeometry.direction_from_degrees(45.0)
    )
    values = {
        "classification": "PLAUSIBLE",
        "confidence": "MEDIUM",
        "geometry": geometry,
        "notes": "candidate note",
        "candidate_id": "candidate-1",
        "now": FIXED,
    }
    values.update(overrides)
    return new_candidate(**values)


def test_save_load_round_trip_and_schema(tmp_path: Path) -> None:
    session = _session()
    review = session.review("test:001")
    review = review.with_candidate(_candidate("interval", candidate_id="interval-1"), now=FIXED)
    review = review.with_candidate(
        _candidate("direction", candidate_id="direction-1", classification="UNCERTAIN"),
        now=FIXED,
    )
    review = review.with_flags(("NEEDS_REVIEW", "AMBIGUOUS"), now=FIXED)
    review = review.with_notes("image note", now=FIXED)
    session = session.replace_review(review, now=FIXED)

    path = tmp_path / "session.json"
    result = save_session(session, path, now=FIXED_LATER)
    assert result.sha256 == file_sha256(path)
    assert not path.with_suffix(".json.tmp").exists()

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["format"] == ANNOTATION_FORMAT
    assert payload["format_version"] == ANNOTATION_FORMAT_VERSION
    assert payload["protocol_version"] == PROTOCOL_VERSION
    assert payload["reviewer"] == "tester"
    assert payload["convention"]["zero"] == "up"
    assert payload["images"][0]["candidates"][0]["geometry"]["crosses_zero"] is True

    loaded = load_session(path)
    saved_review = loaded.review("test:001")
    assert saved_review == review
    assert len(saved_review.candidates) == 2
    assert saved_review.image_flags == ("AMBIGUOUS", "NEEDS_REVIEW")
    assert saved_review.candidates[0].created_at_utc == utc_now_iso(FIXED)


def test_wrap_interval_round_trip(tmp_path: Path) -> None:
    session = _session()
    review = session.review("test:001").with_candidate(
        _candidate("interval", candidate_id="wrap"), now=FIXED
    )
    session = session.replace_review(review, now=FIXED)
    path = tmp_path / "session.json"
    save_session(session, path, now=FIXED)

    loaded = load_session(path).review("test:001")
    geometry = loaded.candidates[0].geometry
    assert geometry is not None
    assert geometry.kind == "interval"
    assert geometry.crosses_zero is True
    assert geometry.start_deg == pytest.approx(350.0)
    assert geometry.end_deg == pytest.approx(10.0)
    assert geometry.width_deg == pytest.approx(20.0)
    assert geometry.end_rad < geometry.start_rad


def test_edit_and_delete_candidate() -> None:
    review = _session().review("test:001").with_candidate(_candidate(), now=FIXED)
    original = review.candidates[0]

    updated = original.with_updates(
        classification="UNCERTAIN",
        confidence="HIGH",
        notes="revised",
        now=FIXED_LATER,
    )
    review = review.replace_candidate(updated)

    assert review.candidates[0].classification == "UNCERTAIN"
    assert review.candidates[0].confidence == "HIGH"
    assert review.candidates[0].notes == "revised"
    assert review.candidates[0].created_at_utc == original.created_at_utc
    assert review.candidates[0].updated_at_utc == utc_now_iso(FIXED_LATER)

    review = review.delete_candidate(original.candidate_id, now=FIXED_LATER)
    assert review.candidates == ()


def test_no_candidate_workflow_and_reopen() -> None:
    review = _session().review("test:001")
    review = review.with_no_candidate(True, now=FIXED)
    assert review.no_candidate_identified is True
    assert review.candidates == ()

    review = review.mark_complete(True, now=FIXED)
    assert review.is_complete is True
    assert review.completed_at_utc == utc_now_iso(FIXED)

    review = review.with_no_candidate(False, now=FIXED_LATER)
    assert review.no_candidate_identified is False
    assert review.is_complete is False
    assert review.completed_at_utc is None

    with pytest.raises(AnnotationStoreError, match="Cannot complete"):
        review.mark_complete(True)


def test_multiple_candidates_and_completion(tmp_path: Path) -> None:
    session = _session()
    review = session.review("test:001")
    review = review.with_candidate(_candidate("interval", candidate_id="a"), now=FIXED)
    review = review.with_candidate(_candidate("direction", candidate_id="b"), now=FIXED)
    review = review.mark_complete(True, now=FIXED)
    session = session.replace_review(review, now=FIXED)
    path = tmp_path / "session.json"
    save_session(session, path, now=FIXED)

    loaded = load_session(path)
    assert len(loaded.review("test:001").candidates) == 2
    assert loaded.review("test:001").is_complete is True

    edited = loaded.review("test:001").with_candidate(
        _candidate("direction", candidate_id="c"), now=FIXED_LATER
    )
    assert edited.is_complete is False
    assert edited.completed_at_utc is None


def test_invalid_records_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(AnnotationStoreError, match="classification"):
        new_candidate(
            classification="CONFIRMED",
            confidence="HIGH",
            geometry=CandidateGeometry.direction_from_degrees(0.0),
        )
    with pytest.raises(AnnotationStoreError, match="requires a direction or interval"):
        new_candidate(classification="PLAUSIBLE", confidence="HIGH", geometry=None)
    with pytest.raises(AnnotationStoreError, match="zero width"):
        CandidateGeometry("interval", CandidateGeometry.direction_from_degrees(0).interval)

    session = _session()
    review = session.review("test:001")
    bad = _candidate()
    bad_payload = bad.to_dict()
    bad_payload["start_deg"] = 999.0
    bad_payload["geometry"]["start_deg"] = 999.0
    with pytest.raises(AnnotationStoreError, match="inconsistent"):
        CandidateAnnotation.from_dict(bad_payload)

    with pytest.raises(AnnotationStoreError, match="cannot coexist"):
        ImageReview.from_dict(
            {
                **review.to_dict(),
                "no_candidate_identified": True,
                "candidates": [_candidate().to_dict()],
            }
        )

    payload = review.to_dict()
    payload["image_flags"] = ["UNKNOWN"]
    with pytest.raises(AnnotationStoreError, match="image_flags"):
        ImageReview.from_dict(payload)

    payload = review.to_dict()
    payload["candidates"] = [_candidate().to_dict(), _candidate().to_dict()]
    with pytest.raises(AnnotationStoreError, match="Duplicate candidate_id"):
        ImageReview.from_dict(payload)


def test_invalid_session_format_and_version(tmp_path: Path) -> None:
    session = _session()
    path = tmp_path / "session.json"
    save_session(session, path, now=FIXED)
    payload = json.loads(path.read_text(encoding="utf-8"))

    bad_format = dict(payload)
    bad_format["format"] = "other"
    path.write_text(json.dumps(bad_format), encoding="utf-8")
    with pytest.raises(AnnotationStoreError, match="Unsupported annotation format"):
        load_session(path)

    bad_version = dict(payload)
    bad_version["format_version"] = 99
    path.write_text(json.dumps(bad_version), encoding="utf-8")
    with pytest.raises(AnnotationStoreError, match="Unsupported annotation format version"):
        load_session(path)


def test_wrong_convention_is_rejected(tmp_path: Path) -> None:
    session = _session()
    path = tmp_path / "session.json"
    save_session(session, path, now=FIXED)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["convention"]["zero"] = "right"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(AnnotationStoreError, match="convention.zero"):
        load_session(path)


def test_save_backup_and_concurrent_modification(tmp_path: Path) -> None:
    session = _session()
    path = tmp_path / "session.json"
    first = save_session(session, path, now=FIXED)

    session2 = session.replace_review(
        session.review("test:001").with_notes("second", now=FIXED_LATER),
        now=FIXED_LATER,
    )
    second = save_session(session2, path, expected_sha256=first.sha256, now=FIXED_LATER)
    assert second.backup_path is not None
    assert second.backup_path.is_file()

    # An external edit must be detected rather than silently overwritten.
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ConcurrentModificationError, match="changed on disk"):
        save_session(session2, path, expected_sha256=second.sha256, now=FIXED_LATER)

    # A pre-existing file cannot be overwritten without its prior hash.
    with pytest.raises(ConcurrentModificationError, match="no prior hash"):
        save_session(session2, path, expected_sha256=None)


def test_validate_against_manifest_and_add_missing() -> None:
    image_a = _image("test:a")
    image_b = _image("test:b")
    manifest = _manifest(image_a, image_b)
    session = new_session(manifest, "tester", now=FIXED)
    session = ReviewSession.from_dict(
        {
            **session.to_dict(),
            "images": [session.review("test:a").to_dict()],
        }
    )

    extended = session.add_missing_from_manifest(manifest, now=FIXED)
    assert {review.image_id for review in extended.reviews} == {"test:a", "test:b"}

    bad_sha = dataclasses.replace(
        extended.review("test:a"), source_product_sha256="b" * 64
    )
    with pytest.raises(AnnotationStoreError, match="SHA256"):
        extended.replace_review(bad_sha).validate_against_manifest(manifest)

    bad_limb = dataclasses.replace(
        extended.review("test:a"), limb=LimbCircle(17.0, 16.0, 10.0, 0.1)
    )
    with pytest.raises(AnnotationStoreError, match="limb geometry"):
        extended.replace_review(bad_limb).validate_against_manifest(manifest)


def test_extra_review_is_rejected_by_manifest_validation() -> None:
    manifest = _manifest(_image("test:a"))
    session = _session(_image("test:a"), _image("test:b"))

    with pytest.raises(AnnotationStoreError, match="not in the review manifest"):
        session.validate_against_manifest(manifest)
