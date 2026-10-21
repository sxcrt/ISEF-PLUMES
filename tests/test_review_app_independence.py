"""Ensure the annotation GUI is isolated from released labels.

The runtime test uses Qt's offscreen platform so it does not require an
interactive desktop session.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QLabel, QMessageBox  # noqa: E402

from planetary_plume.review_app import ReviewWindow  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _fits_card(key: str, value: object) -> str:
    if isinstance(value, str):
        rendered = f"'{value}'"
    else:
        rendered = str(value)
    return f"{key:<8}= {rendered:>20}".ljust(80)


def _write_fits(path: Path) -> Path:
    array = np.linspace(0, 1, 32 * 32, dtype=np.float32).reshape(32, 32)
    cards = [
        _fits_card("SIMPLE", "T"),
        _fits_card("BITPIX", -32),
        _fits_card("NAXIS", 2),
        _fits_card("NAXIS1", 32),
        _fits_card("NAXIS2", 32),
        "END".ljust(80),
    ]
    header = "".join(cards).encode("ascii")
    header += b" " * ((2880 - len(header) % 2880) % 2880)
    data = array.astype(">f4").tobytes()
    data += b"\0" * ((2880 - len(data) % 2880) % 2880)
    path.write_bytes(header + data)
    return path


def _write_manifest(
    path: Path, fits_path: Path, *, image_sha: str | None = None
) -> Path:
    if image_sha is None:
        image_sha = (
            hashlib.sha256(fits_path.read_bytes()).hexdigest()
            if fits_path.is_file()
            else "a" * 64
        )
    payload = {
        "format": "planetary-plume-review-manifest",
        "format_version": 1,
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
                "product_id": "TEST",
                "product_path": str(fits_path),
                "pds_label_path": None,
                "image_sha256": image_sha,
                "limb": {
                    "center_x": 16.0,
                    "center_y": 16.0,
                    "radius": 10.0,
                    "rms_residual": 0.1,
                },
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_gui_sources_do_not_import_label_parser_or_comparison() -> None:
    for name in ("review_app.py", "qt_canvas.py"):
        source = (PROJECT_ROOT / "src" / "planetary_plume" / name).read_text(encoding="utf-8")
        for forbidden in (
            "from planetary_plume.annotations",
            "import planetary_plume.annotations",
            "from planetary_plume.validation",
            "import planetary_plume.validation",
            "from planetary_plume.review_compare",
            "import planetary_plume.review_compare",
            "from planetary_plume.review_manifest_builder",
            "import planetary_plume.review_manifest_builder",
            "load_release_label_map",
            "import yaml",
            "plume_status",
            "plume_intervals",
            "plume_interval_count",
            "_label.yml",
        ):
            assert forbidden not in source, f"{name} unexpectedly references {forbidden!r}"


def test_missing_image_disables_annotation_without_crashing(tmp_path: Path, qapp) -> None:
    manifest_path = _write_manifest(
        tmp_path / "review_manifest.json", tmp_path / "missing.fit"
    )
    window = ReviewWindow(manifest_path, tmp_path / "session.json", "tester")
    try:
        assert window._base_display is None
        assert window.complete_button.isEnabled() is False
        assert window.add_candidate_button.isEnabled() is False
        assert window.mode_combo.isEnabled() is False
    finally:
        window.close()
        qapp.processEvents()


def test_checksum_mismatch_disables_annotation(tmp_path: Path, qapp) -> None:
    fits_path = _write_fits(tmp_path / "test.fit")
    manifest_path = _write_manifest(
        tmp_path / "review_manifest.json", fits_path, image_sha="0" * 64
    )
    window = ReviewWindow(manifest_path, tmp_path / "session.json", "tester")
    try:
        assert window._base_display is None
        assert window.complete_button.isEnabled() is False
    finally:
        window.close()
        qapp.processEvents()


def test_runtime_workflow_is_isolated_and_persists(
    tmp_path: Path, qapp, monkeypatch
) -> None:
    fits_path = _write_fits(tmp_path / "test.fit")
    manifest_path = _write_manifest(tmp_path / "review_manifest.json", fits_path)
    session_path = tmp_path / "independent_review.json"

    window = ReviewWindow(manifest_path, session_path, "tester")
    try:
        assert window.image_list.count() == 1
        assert window.session.reviews[0].candidates == ()
        assert "released labels hidden" in window.windowTitle().lower()

        texts = [label.text() for label in window.findChildren(QLabel)]
        texts.append(window.image_list.item(0).text())
        for text in texts:
            lowered = text.lower()
            assert "plume_status" not in lowered
            assert "plume_intervals" not in lowered
            assert "released positive" not in lowered
        assert "candidate" in window.image_list.item(0).text().lower()

        # Simulate a click direction and add one candidate through the GUI model.
        window._on_direction_picked(math.pi / 2)
        assert window._pending_geometry is not None
        window._add_candidate()
        assert len(window._current_review.candidates) == 1
        assert window.candidate_list.count() == 1
        created_at = window._current_review.candidates[0].created_at_utc

        # Edit classification, confidence, and notes through the GUI model.
        window.class_combo.setCurrentIndex(window.class_combo.findData("UNCERTAIN"))
        window.conf_combo.setCurrentIndex(window.conf_combo.findData("HIGH"))
        window.candidate_notes.setPlainText("revised candidate")
        window._update_candidate()
        edited = window._current_review.candidates[0]
        assert edited.classification == "UNCERTAIN"
        assert edited.confidence == "HIGH"
        assert edited.notes == "revised candidate"
        assert edited.created_at_utc == created_at
        assert edited.updated_at_utc != created_at

        # Image-level flag and completion.
        window.flag_ambiguous.setChecked(True)
        assert window._current_review.image_flags == ("AMBIGUOUS",)
        window._on_complete_clicked()
        assert window._current_review.is_complete is True
        assert session_path.is_file()
        payload = json.loads(session_path.read_text(encoding="utf-8"))
        assert payload["format"] == "planetary-plume-independent-annotations"
        assert payload["format_version"] == 1
        assert payload["protocol_version"] == "independent-annotation-v1"
        serialized = json.dumps(payload).lower()
        assert "plume_status" not in serialized
        assert "plume_intervals" not in serialized
        assert payload["images"][0]["candidates"][0]["classification"] == "UNCERTAIN"

        # Reopen, replace candidates with a negative assessment, and complete again.
        window._on_complete_clicked()
        assert window._current_review.is_complete is False
        monkeypatch.setattr(
            "planetary_plume.review_app.QMessageBox.question",
            lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
        )
        window.no_candidate_check.setChecked(True)
        assert window._current_review.no_candidate_identified is True
        assert window._current_review.candidates == ()
        window._on_complete_clicked()
        assert window._current_review.is_complete is True

        # Reopen, clear the negative assessment, add and delete a candidate.
        window._on_complete_clicked()
        window.no_candidate_check.setChecked(False)
        assert window._current_review.no_candidate_identified is False
        window._on_direction_picked(0.0)
        window._add_candidate()
        assert len(window._current_review.candidates) == 1
        window._delete_candidate(confirm=False)
        assert window._current_review.candidates == ()
        assert window._save() is True
    finally:
        window.close()
        qapp.processEvents()
