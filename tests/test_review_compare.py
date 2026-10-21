"""Tests for the separate independent-vs-released comparison stage."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pytest

from planetary_plume.angle_intervals import AngularInterval
from planetary_plume.annotation_store import (
    CandidateGeometry,
    ImageReview,
    new_candidate,
    new_session,
)
from planetary_plume.review_compare import (
    DISCLAIMER,
    STATUS_AGREEMENT,
    STATUS_AMBIGUOUS_MAPPING,
    STATUS_DISAGREEMENT,
    STATUS_INCONCLUSIVE,
    STATUS_MISSING_MAPPING,
    STATUS_MISSING_RELEASED_ANNOTATION,
    STATUS_MISSING_REVIEW_MANIFEST_IMAGE,
    STATUS_STALE_RELEASED_ANNOTATION,
    ComparisonError,
    LabelMap,
    ReleasedAnnotation,
    compare_image,
    compare_session,
    format_markdown,
    load_label_map,
    write_report,
)
from planetary_plume.review_manifest import LimbCircle, ReviewImage, ReviewManifest

FIXED = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)


def _image(image_id: str = "galileo_ssi:TEST") -> ReviewImage:
    return ReviewImage(
        image_id=image_id,
        display_name="Test image",
        product_family="galileo_ssi",
        target="Io",
        instrument="Galileo SSI",
        width=64,
        height=64,
        image_format="pds3",
        product_id="TEST.img",
        product_path="C:/data/TEST.img",
        pds_label_path="C:/data/TEST.lbl",
        image_sha256="a" * 64,
        limb=LimbCircle(32.0, 32.0, 20.0, 0.1),
    )


def _manifest(*images: ReviewImage) -> ReviewManifest:
    return ReviewManifest(
        generated_at_utc="2026-10-20T00:00:00Z",
        source={"note": "test"},
        images=tuple(images or (_image(),)),
    )


def _review_with_interval(
    start: float,
    end: float,
    *,
    complete: bool = True,
    flags: tuple[str, ...] = (),
) -> ImageReview:
    session = new_session(_manifest(), "tester", now=FIXED)
    review = session.review("galileo_ssi:TEST")
    candidate = new_candidate(
        classification="PLAUSIBLE",
        confidence="MEDIUM",
        geometry=CandidateGeometry.interval_from_degrees(start, end),
        notes="candidate",
        candidate_id="c1",
        now=FIXED,
    )
    review = review.with_candidate(candidate, now=FIXED)
    review = review.with_flags(flags, now=FIXED)
    if complete:
        review = review.mark_complete(True, now=FIXED)
    return review


def _review_negative(*, complete: bool = True) -> ImageReview:
    review = new_session(_manifest(), "tester", now=FIXED).review("galileo_ssi:TEST")
    review = review.with_no_candidate(True, now=FIXED)
    if complete:
        review = review.mark_complete(True, now=FIXED)
    return review


def _released(
    intervals: tuple[tuple[float, float], ...] = ((355.0, 5.0),),
    *,
    positive: bool = True,
) -> ReleasedAnnotation:
    return ReleasedAnnotation(
        image_id="galileo_ssi:TEST",
        annotation_relative_path="galileo_ssi_io/TEST_label.yml",
        annotation_sha256="b" * 64,
        plume_status=positive,
        intervals=tuple(
            AngularInterval.from_degrees(start, end) for start, end in intervals
        ),
        warnings=(),
    )


def test_overlap_agreement_across_zero() -> None:
    result = compare_image(
        _review_with_interval(350.0, 10.0),
        _image(),
        _released(((355.0, 5.0),)),
        tolerance_deg=10.0,
    )

    assert result.status == STATUS_AGREEMENT
    assert result.comparison_kind == "POSITIVE_OVERLAP"
    assert result.reviewed_positive is True
    assert result.released_positive is True
    assert result.max_overlap_deg == pytest.approx(10.0)
    assert result.min_distance_deg == pytest.approx(0.0)
    assert result.partial_coverage is False


def test_direction_inside_released_interval_is_agreement() -> None:
    session = new_session(_manifest(), "tester", now=FIXED)
    review = session.review("galileo_ssi:TEST")
    review = review.with_candidate(
        new_candidate(
            classification="UNCERTAIN",
            confidence="LOW",
            geometry=CandidateGeometry.direction_from_degrees(0.0),
            candidate_id="d1",
            now=FIXED,
        ),
        now=FIXED,
    )
    review = review.mark_complete(True, now=FIXED)

    result = compare_image(
        review,
        _image(),
        _released(((350.0, 10.0),)),
        tolerance_deg=10.0,
    )

    assert result.status == STATUS_AGREEMENT
    assert result.candidates[0].kind == "direction"
    assert result.candidates[0].exact_match is True


def test_positive_no_overlap_is_disagreement() -> None:
    result = compare_image(
        _review_with_interval(10.0, 20.0),
        _image(),
        _released(((100.0, 110.0),)),
        tolerance_deg=10.0,
    )

    assert result.status == STATUS_DISAGREEMENT
    assert result.comparison_kind == "POSITIVE_NO_OVERLAP"
    assert result.min_distance_deg == pytest.approx(80.0)


def test_near_miss_is_inconclusive() -> None:
    result = compare_image(
        _review_with_interval(10.0, 20.0),
        _image(),
        _released(((25.0, 35.0),)),
        tolerance_deg=10.0,
    )

    assert result.status == STATUS_INCONCLUSIVE
    assert result.comparison_kind == "POSITIVE_NEAR_MISS"
    assert result.min_distance_deg == pytest.approx(5.0)


def test_partial_overlap_is_inconclusive() -> None:
    result = compare_image(
        _review_with_interval(0.0, 10.0),
        _image(),
        _released(((0.0, 10.0), (100.0, 110.0))),
        tolerance_deg=10.0,
    )

    assert result.status == STATUS_INCONCLUSIVE
    assert result.comparison_kind == "PARTIAL_OVERLAP"
    assert result.released_intervals_total == 2
    assert result.released_intervals_matched == 1
    assert result.partial_coverage is True


def test_multiple_candidates_all_matched() -> None:
    session = new_session(_manifest(), "tester", now=FIXED)
    review = session.review("galileo_ssi:TEST")
    for candidate_id, bounds in (("a", (0.0, 10.0)), ("b", (100.0, 110.0))):
        review = review.with_candidate(
            new_candidate(
                classification="PLAUSIBLE",
                confidence="MEDIUM",
                geometry=CandidateGeometry.interval_from_degrees(*bounds),
                candidate_id=candidate_id,
                now=FIXED,
            ),
            now=FIXED,
        )
    review = review.mark_complete(True, now=FIXED)

    result = compare_image(
        review,
        _image(),
        _released(((0.0, 10.0), (100.0, 110.0))),
        tolerance_deg=10.0,
    )

    assert result.status == STATUS_AGREEMENT
    assert result.reviewed_candidates_total == 2
    assert result.reviewed_candidates_matched == 2


def test_negative_review_agrees_with_negative_release() -> None:
    result = compare_image(
        _review_negative(),
        _image(),
        _released((), positive=False),
        tolerance_deg=10.0,
    )

    assert result.status == STATUS_AGREEMENT
    assert result.comparison_kind == "BOTH_NEGATIVE"


def test_negative_review_misses_positive_release() -> None:
    result = compare_image(
        _review_negative(),
        _image(),
        _released(((0.0, 10.0),)),
        tolerance_deg=10.0,
    )

    assert result.status == STATUS_DISAGREEMENT
    assert result.comparison_kind == "MISSED_RELEASED_POSITIVE"


def test_positive_review_without_released_positive() -> None:
    result = compare_image(
        _review_with_interval(0.0, 10.0),
        _image(),
        _released((), positive=False),
        tolerance_deg=10.0,
    )

    assert result.status == STATUS_DISAGREEMENT
    assert result.comparison_kind == "CANDIDATE_WITHOUT_RELEASED_POSITIVE"


def test_incomplete_and_flagged_reviews_are_inconclusive() -> None:
    incomplete = compare_image(
        _review_with_interval(0.0, 10.0, complete=False),
        _image(),
        _released(((0.0, 10.0),)),
        tolerance_deg=10.0,
    )
    flagged = compare_image(
        _review_with_interval(0.0, 10.0, flags=("AMBIGUOUS",)),
        _image(),
        _released(((0.0, 10.0),)),
        tolerance_deg=10.0,
    )

    assert incomplete.status == STATUS_INCONCLUSIVE
    assert incomplete.comparison_kind == "REVIEW_INCOMPLETE"
    assert flagged.status == STATUS_INCONCLUSIVE
    assert flagged.comparison_kind == "IMAGE_FLAGGED"


def test_missing_mapping_and_missing_manifest_image() -> None:
    no_mapping = compare_image(
        _review_negative(), _image(), None, tolerance_deg=10.0
    )
    no_manifest = compare_image(
        _review_negative(), None, _released((), positive=False), tolerance_deg=10.0
    )

    assert no_mapping.status == STATUS_MISSING_MAPPING
    assert no_manifest.status == STATUS_MISSING_REVIEW_MANIFEST_IMAGE


def test_source_sha_mismatch_is_inconclusive() -> None:
    import dataclasses

    review = dataclasses.replace(
        _review_negative(), source_product_sha256="b" * 64
    )
    result = compare_image(
        review, _image(), _released((), positive=False), tolerance_deg=10.0
    )

    assert result.status == STATUS_INCONCLUSIVE
    assert result.comparison_kind == "SOURCE_IMAGE_CHANGED"


def _write_release(path: Path, intervals: list[list[float]] | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["points:", "- [10, 5]", "- [15, 10]", "- [10, 15]", "user: tester"]
    if intervals is not None:
        lines = ["plumes:", "  intervals:"] + [
            f"  - [{start}, {end}]" for start, end in intervals
        ] + ["  user: tester"] + lines
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _label_map_payload(
    image_id: str, relative: str, sha: str, *, duplicate: bool = False
) -> dict:
    mapping = {
        "image_id": image_id,
        "annotation_relative_path": relative,
        "annotation_sha256": sha,
        "annotation_filename": Path(relative).name,
        "release_directory": Path(relative).parent.name,
        "product_family": "galileo_ssi",
    }
    mappings = [mapping, dict(mapping)] if duplicate else [mapping]
    return {
        "format": "planetary-plume-release-label-map",
        "format_version": 1,
        "generated_at_utc": "2026-10-20T00:00:00Z",
        "source": {"note": "test"},
        "mappings": mappings,
    }


def _write_label_map(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_session_comparison_missing_mapping_and_unreviewed(tmp_path: Path) -> None:
    session = new_session(_manifest(), "tester", now=FIXED)
    session = session.replace_review(
        session.review("galileo_ssi:TEST").with_no_candidate(True, now=FIXED).mark_complete(True, now=FIXED),
        now=FIXED,
    )
    label_map_path = _write_label_map(
        tmp_path / "labels.json",
        _label_map_payload("galileo_ssi:OTHER", "galileo_ssi_io/OTHER_label.yml", "0" * 64),
    )
    label_map = load_label_map(label_map_path)
    (tmp_path / "annotations").mkdir()

    report = compare_session(
        session,
        _manifest(_image(), _image("galileo_ssi:OTHER")),
        label_map,
        tmp_path / "annotations",
        tolerance_deg=10.0,
    )

    assert report.images[0].status == STATUS_MISSING_MAPPING
    assert report.unreviewed_image_ids == ("galileo_ssi:OTHER",)


def test_ambiguous_mapping_is_reported(tmp_path: Path) -> None:
    session = new_session(_manifest(), "tester", now=FIXED)
    session = session.replace_review(
        session.review("galileo_ssi:TEST").with_no_candidate(True, now=FIXED).mark_complete(True, now=FIXED),
        now=FIXED,
    )
    label_map = load_label_map(
        _write_label_map(
            tmp_path / "labels.json",
            _label_map_payload(
                "galileo_ssi:TEST", "galileo_ssi_io/TEST_label.yml", "0" * 64, duplicate=True
            ),
        )
    )
    (tmp_path / "annotations").mkdir()

    report = compare_session(
        session, _manifest(), label_map, tmp_path / "annotations", tolerance_deg=10.0
    )

    assert report.images[0].status == STATUS_AMBIGUOUS_MAPPING


def test_duplicate_released_path_for_two_image_ids_is_ambiguous(tmp_path: Path) -> None:
    session = new_session(_manifest(), "tester", now=FIXED)
    session = session.replace_review(
        session.review("galileo_ssi:TEST")
        .with_no_candidate(True, now=FIXED)
        .mark_complete(True, now=FIXED),
        now=FIXED,
    )
    payload = _label_map_payload(
        "galileo_ssi:TEST", "galileo_ssi_io/TEST_label.yml", "0" * 64
    )
    other = dict(payload["mappings"][0])
    other["image_id"] = "galileo_ssi:OTHER"
    payload["mappings"].append(other)
    label_map = load_label_map(_write_label_map(tmp_path / "labels.json", payload))
    (tmp_path / "annotations").mkdir()

    assert label_map.ambiguous_image_ids == frozenset(
        {"galileo_ssi:TEST", "galileo_ssi:OTHER"}
    )
    report = compare_session(
        session, _manifest(), label_map, tmp_path / "annotations", tolerance_deg=10.0
    )

    assert report.images[0].status == STATUS_AMBIGUOUS_MAPPING
    assert report.problems


def test_missing_and_stale_released_annotations(tmp_path: Path) -> None:
    session = new_session(_manifest(), "tester", now=FIXED)
    session = session.replace_review(
        session.review("galileo_ssi:TEST").with_no_candidate(True, now=FIXED).mark_complete(True, now=FIXED),
        now=FIXED,
    )
    annotations = tmp_path / "annotations"
    annotations.mkdir()
    relative = "galileo_ssi_io/TEST_label.yml"

    missing_map = load_label_map(
        _write_label_map(
            tmp_path / "missing.json",
            _label_map_payload("galileo_ssi:TEST", relative, "0" * 64),
        )
    )
    missing = compare_session(
        session, _manifest(), missing_map, annotations, tolerance_deg=10.0
    )
    assert missing.images[0].status == STATUS_MISSING_RELEASED_ANNOTATION

    release_path = _write_release(annotations / relative)
    from planetary_plume.annotation_store import file_sha256

    actual_sha = file_sha256(release_path)
    stale_map = load_label_map(
        _write_label_map(
            tmp_path / "stale.json",
            _label_map_payload("galileo_ssi:TEST", relative, "0" * 64),
        )
    )
    stale = compare_session(
        session, _manifest(), stale_map, annotations, tolerance_deg=10.0
    )
    assert stale.images[0].status == STATUS_STALE_RELEASED_ANNOTATION

    good_map = load_label_map(
        _write_label_map(
            tmp_path / "good.json",
            _label_map_payload("galileo_ssi:TEST", relative, actual_sha),
        )
    )
    good = compare_session(
        session,
        _manifest(),
        good_map,
        annotations,
        tolerance_deg=10.0,
        session_path=tmp_path / "session.json",
        session_sha256="c" * 64,
        review_manifest_path=tmp_path / "review_manifest.json",
        review_manifest_sha256="d" * 64,
    )
    assert good.images[0].status == STATUS_AGREEMENT
    assert good.images[0].comparison_kind == "BOTH_NEGATIVE"


def test_released_interval_crossing_zero_is_loaded_for_comparison(tmp_path: Path) -> None:
    session = new_session(_manifest(), "tester", now=FIXED)
    session = session.replace_review(
        _review_with_interval(350.0, 10.0), now=FIXED
    )
    annotations = tmp_path / "annotations"
    relative = "galileo_ssi_io/TEST_label.yml"
    release = _write_release(
        annotations / relative,
        [[math.radians(350.0), math.radians(10.0)]],
    )
    from planetary_plume.annotation_store import file_sha256

    label_map = load_label_map(
        _write_label_map(
            tmp_path / "labels.json",
            _label_map_payload("galileo_ssi:TEST", relative, file_sha256(release)),
        )
    )

    report = compare_session(
        session, _manifest(), label_map, annotations, tolerance_deg=10.0
    )

    assert report.images[0].status == STATUS_AGREEMENT
    assert report.images[0].max_overlap_deg == pytest.approx(20.0)


def test_report_and_markdown_disclaimer_and_no_overwrite(tmp_path: Path) -> None:
    session = new_session(_manifest(), "tester", now=FIXED)
    session = session.replace_review(
        session.review("galileo_ssi:TEST").with_no_candidate(True, now=FIXED).mark_complete(True, now=FIXED),
        now=FIXED,
    )
    annotations = tmp_path / "annotations"
    relative = "galileo_ssi_io/TEST_label.yml"
    release = _write_release(annotations / relative)
    from planetary_plume.annotation_store import file_sha256

    label_map = load_label_map(
        _write_label_map(
            tmp_path / "labels.json",
            _label_map_payload("galileo_ssi:TEST", relative, file_sha256(release)),
        )
    )
    report = compare_session(
        session, _manifest(), label_map, annotations, tolerance_deg=10.0
    )

    assert DISCLAIMER in format_markdown(report)
    json_path = tmp_path / "report.json"
    markdown_path = tmp_path / "report.md"
    written_json, written_markdown = write_report(report, json_path, markdown_path)
    assert written_json.is_file()
    assert written_markdown is not None and written_markdown.is_file()
    assert DISCLAIMER in written_markdown.read_text(encoding="utf-8")
    payload = json.loads(written_json.read_text(encoding="utf-8"))
    assert payload["disclaimer"] == DISCLAIMER

    with pytest.raises(ComparisonError, match="Refusing to overwrite"):
        write_report(report, json_path, markdown_path)


def test_complete_only_requires_a_complete_review(tmp_path: Path) -> None:
    session = new_session(_manifest(), "tester", now=FIXED)
    session = session.replace_review(
        _review_with_interval(0.0, 10.0, complete=False), now=FIXED
    )
    (tmp_path / "annotations").mkdir()
    label_map = LabelMap(
        path=tmp_path / "labels.json",
        entries_by_image={},
        problems=(),
    )

    with pytest.raises(ComparisonError, match="No reviews are eligible"):
        compare_session(
            session,
            _manifest(),
            label_map,
            tmp_path / "annotations",
            complete_only=True,
        )


def test_label_map_rejects_unsafe_paths_and_duplicate_entries(tmp_path: Path) -> None:
    payload = _label_map_payload("galileo_ssi:TEST", "../escape.yml", "0" * 64)
    label_map = load_label_map(_write_label_map(tmp_path / "bad.json", payload))
    assert label_map.problems

    payload = _label_map_payload("galileo_ssi:TEST", "galileo_ssi_io/TEST_label.yml", "0" * 64)
    payload["mappings"].append(dict(payload["mappings"][0]))
    label_map = load_label_map(_write_label_map(tmp_path / "dupe.json", payload))
    assert len(label_map.entries_by_image["galileo_ssi:TEST"]) == 2
