"""Headless tests for the Qt image canvas painting and mouse interactions."""

from __future__ import annotations

import math
from datetime import datetime, timezone

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from planetary_plume.annotation_store import (  # noqa: E402
    CandidateGeometry,
    new_candidate,
)
from planetary_plume.qt_canvas import ImageCanvas  # noqa: E402
from planetary_plume.review_manifest import LimbCircle  # noqa: E402

FIXED = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def canvas(qapp):
    widget = ImageCanvas()
    widget.resize(500, 500)
    image = QImage(100, 100, QImage.Format.Format_Grayscale8)
    image.fill(128)
    widget.set_image(image, 100, 100)
    widget.set_limb(LimbCircle(50.0, 50.0, 30.0, 0.1))
    widget.show()
    qapp.processEvents()
    yield widget
    widget.close()


def _candidates():
    interval = new_candidate(
        classification="PLAUSIBLE",
        confidence="MEDIUM",
        geometry=CandidateGeometry.interval_from_degrees(350.0, 10.0),
        candidate_id="interval",
        now=FIXED,
    )
    direction = new_candidate(
        classification="UNCERTAIN",
        confidence="LOW",
        geometry=CandidateGeometry.direction_from_degrees(90.0),
        candidate_id="direction",
        now=FIXED,
    )
    negative = new_candidate(
        classification="NO_CANDIDATE_IDENTIFIED",
        confidence="HIGH",
        geometry=None,
        candidate_id="negative",
        now=FIXED,
    )
    return interval, direction, negative


def _screen(canvas: ImageCanvas, x: float, y: float) -> QPoint:
    sx, sy = canvas._transform.image_to_screen(x, y)  # noqa: SLF001 - test geometry
    return QPoint(round(sx), round(sy))


def test_paint_all_states_and_zoom(canvas: ImageCanvas) -> None:
    interval, direction, negative = _candidates()
    canvas.set_candidates((interval, direction, negative), "interval")
    canvas.set_pending_geometry(CandidateGeometry.interval_from_degrees(20.0, 40.0))
    assert not canvas.grab().isNull()

    canvas.set_limb_visible(False)
    assert not canvas.grab().isNull()
    canvas.set_limb_visible(True)

    canvas.set_selected_candidate("direction")
    assert not canvas.grab().isNull()

    canvas.actual_size()
    assert canvas.zoom_scale == pytest.approx(1.0)
    canvas.zoom_in()
    assert canvas.zoom_scale > 1.0
    canvas.zoom_out()
    canvas.fit_to_window()
    assert canvas.zoom_scale > 0

    canvas.resize(400, 300)
    assert not canvas.grab().isNull()


def test_paint_without_image_and_with_error(canvas: ImageCanvas) -> None:
    canvas.set_error("Image unavailable")
    assert not canvas.grab().isNull()
    canvas.set_error(None)
    assert not canvas.grab().isNull()


def test_direction_click_emits_documented_angle(canvas: ImageCanvas) -> None:
    emitted: list[float] = []
    canvas.direction_picked.connect(emitted.append)
    canvas.set_mode("direction")

    # Image point (50, 20) is directly above the limb center.
    QTest.mouseClick(
        canvas,
        Qt.MouseButton.LeftButton,
        pos=_screen(canvas, 50.0, 20.0),
    )

    assert len(emitted) == 1
    assert emitted[0] == pytest.approx(0.0, abs=1e-6)


def test_interval_drag_emits_clockwise_start_and_end(canvas: ImageCanvas) -> None:
    emitted: list[tuple[float, float]] = []
    canvas.interval_picked.connect(lambda start, end: emitted.append((start, end)))
    canvas.set_mode("interval")

    start = _screen(canvas, 50.0, 20.0)  # up
    end = _screen(canvas, 80.0, 50.0)  # right
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)

    assert len(emitted) == 1
    assert emitted[0][0] == pytest.approx(0.0, abs=1e-6)
    assert emitted[0][1] == pytest.approx(math.pi / 2, abs=1e-6)


def test_navigation_pan_and_cursor_signal(canvas: ImageCanvas) -> None:
    moved: list[tuple[float, float, object]] = []
    canvas.cursor_moved.connect(lambda x, y, angle: moved.append((x, y, angle)))
    canvas.set_mode("navigate")
    before = (canvas._transform.offset_x, canvas._transform.offset_y)  # noqa: SLF001

    QTest.mousePress(
        canvas, Qt.MouseButton.LeftButton, pos=QPoint(100, 100)
    )
    QTest.mouseMove(canvas, QPoint(150, 130))
    QTest.mouseRelease(
        canvas, Qt.MouseButton.LeftButton, pos=QPoint(150, 130)
    )

    after = (canvas._transform.offset_x, canvas._transform.offset_y)  # noqa: SLF001
    assert after != before
    assert moved
    assert moved[-1][2] is not None


def test_center_click_is_ignored_and_modes_validate(canvas: ImageCanvas) -> None:
    emitted: list[float] = []
    canvas.direction_picked.connect(emitted.append)
    canvas.set_mode("direction")
    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, pos=_screen(canvas, 50.0, 50.0)
    )
    assert emitted == []

    with pytest.raises(ValueError, match="Unknown canvas mode"):
        canvas.set_mode("unknown")
