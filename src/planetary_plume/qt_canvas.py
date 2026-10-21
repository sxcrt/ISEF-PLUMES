"""Qt image canvas for independent plume-candidate annotation.

This module imports only the sanitized review manifest, the annotation store,
and the established angle utilities.  It does not import the released-label
parser or the comparison stage.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QImage,
    QPainter,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import QWidget

from planetary_plume.angle_convention import angle_to_image_point, image_point_to_angle
from planetary_plume.angle_intervals import (
    AngularInterval,
    direction_line,
    format_interval_deg,
    wrapped_interval_polygon,
)
from planetary_plume.annotation_store import CandidateAnnotation, CandidateGeometry
from planetary_plume.review_manifest import LimbCircle
from planetary_plume.viewport import ViewTransform, ViewportError

_COLORS = {
    "PLAUSIBLE": QColor("#38d39f"),
    "UNCERTAIN": QColor("#f4b942"),
    "NO_CANDIDATE_IDENTIFIED": QColor("#9aa0a6"),
}
_DEFAULT_COLOR = QColor("#d0d4da")
_MODES = ("navigate", "direction", "interval")


class ImageCanvas(QWidget):
    """Paint an image, limb reference, and the reviewer's own candidates."""

    direction_picked = Signal(float)
    interval_picked = Signal(float, float)
    cursor_moved = Signal(float, float, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(480, 420)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

        self._qimage: QImage | None = None
        self._image_width = 0
        self._image_height = 0
        self._limb: LimbCircle | None = None
        self._candidates: tuple[CandidateAnnotation, ...] = ()
        self._selected_id: str | None = None
        self._mode = "navigate"
        self._transform = ViewTransform(1.0, 0.0, 0.0)
        self._auto_fit = True
        self._limb_visible = True
        self._error: str | None = None
        self._pan_last: QPointF | None = None
        self._drag_start_image: tuple[float, float] | None = None
        self._drag_current_image: tuple[float, float] | None = None
        self._hover_image: tuple[float, float] | None = None
        self._pending_geometry: CandidateGeometry | None = None

    # ------------------------------------------------------------------ state
    def set_image(self, image: QImage, width: int, height: int) -> None:
        self._qimage = image
        self._image_width = int(width)
        self._image_height = int(height)
        self._error = None
        self.fit_to_window()

    def set_display_image(self, image: QImage) -> None:
        """Replace the displayed pixels without changing zoom or pan."""

        self._qimage = image
        self.update()

    def set_pending_geometry(self, geometry: CandidateGeometry | None) -> None:
        self._pending_geometry = geometry
        self.update()

    def set_limb(self, limb: LimbCircle | None) -> None:
        self._limb = limb
        self.update()

    def set_candidates(
        self,
        candidates: tuple[CandidateAnnotation, ...] | list[CandidateAnnotation],
        selected_id: str | None = None,
    ) -> None:
        self._candidates = tuple(candidates)
        self._selected_id = selected_id
        self.update()

    def set_selected_candidate(self, candidate_id: str | None) -> None:
        self._selected_id = candidate_id
        self.update()

    def set_mode(self, mode: str) -> None:
        if mode not in _MODES:
            raise ValueError(f"Unknown canvas mode: {mode!r}.")
        self._mode = mode
        self._drag_start_image = None
        self._drag_current_image = None
        self._hover_image = None
        self.setCursor(
            Qt.CursorShape.CrossCursor
            if mode in {"direction", "interval"}
            else Qt.CursorShape.OpenHandCursor
        )
        self.update()

    def set_limb_visible(self, visible: bool) -> None:
        self._limb_visible = bool(visible)
        self.update()

    def set_error(self, message: str | None) -> None:
        self._error = message
        self._qimage = None
        self.update()

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def zoom_scale(self) -> float:
        return self._transform.scale

    # --------------------------------------------------------------- viewport
    def fit_to_window(self) -> None:
        if self._image_width <= 0 or self._image_height <= 0:
            return
        try:
            self._transform = ViewTransform.fit(
                self._image_width,
                self._image_height,
                max(1, self.width()),
                max(1, self.height()),
                margin=0.05,
            )
        except ViewportError:
            return
        self._auto_fit = True
        self.update()

    def actual_size(self) -> None:
        if self._image_width <= 0 or self._image_height <= 0:
            return
        self._transform = ViewTransform(
            1.0,
            (self.width() - self._image_width) / 2.0,
            (self.height() - self._image_height) / 2.0,
        )
        self._auto_fit = False
        self.update()

    def zoom_in(self) -> None:
        self._zoom_at(1.25, self.width() / 2.0, self.height() / 2.0)

    def zoom_out(self) -> None:
        self._zoom_at(0.8, self.width() / 2.0, self.height() / 2.0)

    def _zoom_at(self, factor: float, x: float, y: float) -> None:
        try:
            self._transform = self._transform.zoom_at(factor, x, y)
        except ViewportError:
            return
        self._auto_fit = False
        self.update()

    # ------------------------------------------------------------------ paint
    def paintEvent(self, event: object) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.fillRect(self.rect(), QColor("#1e1f22"))

        if self._error:
            self._draw_centered_message(painter, self._error)
            painter.end()
            return
        if self._qimage is None or self._image_width <= 0 or self._image_height <= 0:
            self._draw_centered_message(painter, "No image loaded.")
            painter.end()
            return

        target = QRectF(
            self._transform.offset_x,
            self._transform.offset_y,
            self._image_width * self._transform.scale,
            self._image_height * self._transform.scale,
        )
        painter.drawImage(target, self._qimage)
        painter.setPen(QPen(QColor("#4a4d52"), 1))
        painter.drawRect(target)

        if self._limb_visible and self._limb is not None:
            self._draw_limb(painter)
        self._draw_candidates(painter)
        self._draw_drag_preview(painter)
        self._draw_legend(painter)
        painter.end()

    def _draw_centered_message(self, painter: QPainter, message: str) -> None:
        painter.setPen(QColor("#e8e8e8"))
        painter.setFont(QFont("Segoe UI", 11))
        rect = self.rect().adjusted(30, 30, -30, -30)
        painter.drawText(
            rect,
            int(Qt.AlignmentFlag.AlignCenter) | int(Qt.TextFlag.TextWordWrap),
            message,
        )

    def _draw_limb(self, painter: QPainter) -> None:
        assert self._limb is not None
        center = (self._limb.center_x, self._limb.center_y)
        cx, cy = self._transform.image_to_screen(*center)
        radius = self._limb.radius * self._transform.scale
        painter.setPen(QPen(QColor("#ff6262"), 1.6, Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), radius, radius)

        painter.setPen(QPen(QColor("#ff9a9a"), 1.2))
        painter.drawLine(QPointF(cx - 6, cy), QPointF(cx + 6, cy))
        painter.drawLine(QPointF(cx, cy - 6), QPointF(cx, cy + 6))

        top = angle_to_image_point(center, self._limb.radius, 0.0)
        tx, ty = self._transform.image_to_screen(top.x, top.y)
        painter.setPen(QPen(QColor("#ffd166"), 1.8))
        painter.drawLine(QPointF(cx, cy), QPointF(tx, ty))
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        painter.drawText(QPointF(tx + 4, ty - 4), "0°")

    def _draw_candidates(self, painter: QPainter) -> None:
        if self._limb is None:
            return
        center = (self._limb.center_x, self._limb.center_y)
        radius = self._limb.radius
        for index, candidate in enumerate(self._candidates):
            geometry = candidate.geometry
            if geometry is None:
                continue
            color = _COLORS.get(candidate.classification, _DEFAULT_COLOR)
            selected = candidate.candidate_id == self._selected_id
            pen = QPen(color, 2.8 if selected else 1.6)
            painter.setPen(pen)
            if geometry.kind == "interval":
                polygon = wrapped_interval_polygon(
                    center,
                    radius,
                    radius * 1.22,
                    geometry.interval,
                    steps=72,
                )
                screen_polygon = QPolygonF(
                    [QPointF(*self._transform.image_to_screen(x, y)) for x, y in polygon]
                )
                fill = QColor(color)
                fill.setAlpha(70 if selected else 38)
                painter.setBrush(QBrush(fill))
                painter.drawPolygon(screen_polygon)
                mid_angle = geometry.start_rad + geometry.width_rad / 2.0
                label_point = angle_to_image_point(center, radius * 1.34, mid_angle)
                self._draw_label(
                    painter,
                    self._transform.image_to_screen(label_point.x, label_point.y),
                    f"#{index + 1}",
                    color,
                )
                if selected:
                    for angle, suffix in (
                        (geometry.start_rad, "start"),
                        (geometry.end_rad, "end"),
                    ):
                        point = angle_to_image_point(center, radius * 1.42, angle)
                        self._draw_label(
                            painter,
                            self._transform.image_to_screen(point.x, point.y),
                            f"{suffix} {math.degrees(angle):.1f}°",
                            color,
                        )
            else:
                inner, outer = direction_line(
                    center,
                    radius,
                    radius * 1.22,
                    geometry.interval,
                )
                start = QPointF(*self._transform.image_to_screen(*inner))
                end = QPointF(*self._transform.image_to_screen(*outer))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawLine(start, end)
                painter.setBrush(QBrush(color))
                painter.drawEllipse(end, 3.5, 3.5)
                label_point = angle_to_image_point(
                    center, radius * 1.32, geometry.start_rad
                )
                self._draw_label(
                    painter,
                    self._transform.image_to_screen(label_point.x, label_point.y),
                    f"#{index + 1}",
                    color,
                )

    def _draw_label(
        self,
        painter: QPainter,
        point: tuple[float, float],
        text: str,
        color: QColor,
    ) -> None:
        painter.setFont(QFont("Segoe UI", 8))
        metrics = painter.fontMetrics()
        width = metrics.horizontalAdvance(text) + 6
        height = metrics.height() + 2
        x, y = point
        rect = QRectF(x - width / 2.0, y - height / 2.0, width, height)
        background = QColor("#111214")
        background.setAlpha(190)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(background))
        painter.drawRoundedRect(rect, 3, 3)
        painter.setPen(QPen(color))
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), text)

    def _draw_drag_preview(self, painter: QPainter) -> None:
        if self._limb is None:
            return
        center = (self._limb.center_x, self._limb.center_y)
        radius = self._limb.radius
        if self._drag_start_image is not None:
            current = self._drag_current_image or self._drag_start_image
            start_angle = image_point_to_angle(self._drag_start_image, center)
            end_angle = image_point_to_angle(current, center)
            interval = AngularInterval.from_radians(start_angle, end_angle)
            label_color = QColor("#e8f1ff")
        elif self._pending_geometry is not None:
            interval = self._pending_geometry.interval
            label_color = QColor("#9fd2ff")
        else:
            return
        if interval.is_direction:
            inner, outer = direction_line(center, radius, radius * 1.22, interval)
            points = [inner, outer]
        else:
            polygon = wrapped_interval_polygon(
                center, radius, radius * 1.22, interval, steps=72
            )
            points = polygon
        if not points:
            return
        screen_points = [
            QPointF(*self._transform.image_to_screen(x, y)) for x, y in points
        ]
        pen = QPen(QColor("#e8f1ff"), 1.8, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        fill = QColor(120, 180, 255, 45)
        painter.setBrush(QBrush(fill))
        if interval.is_direction:
            painter.drawLine(screen_points[0], screen_points[1])
        else:
            painter.drawPolygon(QPolygonF(screen_points))
        mid = angle_to_image_point(
            center, radius * 1.34, interval.start_rad + interval.width_rad / 2.0
        )
        self._draw_label(
            painter,
            self._transform.image_to_screen(mid.x, mid.y),
            format_interval_deg(interval),
            label_color,
        )

    def _draw_legend(self, painter: QPainter) -> None:
        text = "0° up · clockwise · from fitted limb center"
        painter.setFont(QFont("Segoe UI", 8))
        metrics = painter.fontMetrics()
        width = metrics.horizontalAdvance(text) + 16
        height = metrics.height() + 8
        rect = QRectF(8, self.height() - height - 8, width, height)
        background = QColor("#111214")
        background.setAlpha(190)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(background))
        painter.drawRoundedRect(rect, 4, 4)
        painter.setPen(QColor("#c9cdd3"))
        painter.drawText(rect.adjusted(8, 0, -8, 0), int(Qt.AlignmentFlag.AlignVCenter), text)

    # ------------------------------------------------------------------ input
    def _event_image_point(self, event: object) -> tuple[float, float] | None:
        position = event.position()  # type: ignore[attr-defined]
        x, y = self._transform.screen_to_image(position.x(), position.y())
        if 0 <= x < self._image_width and 0 <= y < self._image_height:
            return x, y
        return None

    def _near_limb_center(self, point: tuple[float, float]) -> bool:
        if self._limb is None:
            return True
        distance = math.hypot(
            point[0] - self._limb.center_x, point[1] - self._limb.center_y
        )
        return distance < 1.0

    def mousePressEvent(self, event: object) -> None:  # noqa: N802 - Qt API
        button = event.button()  # type: ignore[attr-defined]
        if button == Qt.MouseButton.MiddleButton:
            self._pan_last = event.position()  # type: ignore[attr-defined]
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if button != Qt.MouseButton.LeftButton:
            return
        if self._mode == "navigate":
            self._pan_last = event.position()  # type: ignore[attr-defined]
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        point = self._event_image_point(event)
        if point is None or self._limb is None or self._near_limb_center(point):
            return
        self._drag_start_image = point
        self._drag_current_image = point
        self.update()

    def mouseMoveEvent(self, event: object) -> None:  # noqa: N802 - Qt API
        if self._pan_last is not None:
            position = event.position()  # type: ignore[attr-defined]
            delta = position - self._pan_last
            self._transform = self._transform.pan(delta.x(), delta.y())
            self._pan_last = position
            self._auto_fit = False
            self.update()
        point = self._event_image_point(event)
        if point is not None:
            angle = (
                image_point_to_angle(point, (self._limb.center_x, self._limb.center_y))
                if self._limb is not None
                else None
            )
            self.cursor_moved.emit(point[0], point[1], angle)
            if self._drag_start_image is not None:
                self._drag_current_image = point
                self.update()
            elif self._mode == "direction":
                self._hover_image = point
                self.update()
        else:
            self.cursor_moved.emit(float("nan"), float("nan"), None)

    def mouseReleaseEvent(self, event: object) -> None:  # noqa: N802 - Qt API
        if self._pan_last is not None:
            self._pan_last = None
            self.setCursor(
                Qt.CursorShape.CrossCursor
                if self._mode in {"direction", "interval"}
                else Qt.CursorShape.OpenHandCursor
            )
            return
        if event.button() != Qt.MouseButton.LeftButton:  # type: ignore[attr-defined]
            return
        if self._mode not in {"direction", "interval"}:
            return
        if self._drag_start_image is None or self._limb is None:
            return
        end_point = self._event_image_point(event)
        if end_point is None:
            self._drag_start_image = None
            self._drag_current_image = None
            self.update()
            return
        center = (self._limb.center_x, self._limb.center_y)
        start_angle = image_point_to_angle(self._drag_start_image, center)
        end_angle = image_point_to_angle(end_point, center)
        if self._mode == "direction":
            self.direction_picked.emit(start_angle)
        else:
            self.interval_picked.emit(start_angle, end_angle)
        self._drag_start_image = None
        self._drag_current_image = None
        self.update()

    def leaveEvent(self, event: object) -> None:  # noqa: N802 - Qt API
        self._hover_image = None
        self.cursor_moved.emit(float("nan"), float("nan"), None)
        self.update()

    def wheelEvent(self, event: object) -> None:  # noqa: N802 - Qt API
        if self._qimage is None or self._image_width <= 0:
            return
        delta = event.angleDelta().y()  # type: ignore[attr-defined]
        if delta == 0:
            return
        position = event.position()  # type: ignore[attr-defined]
        self._zoom_at(1.2 if delta > 0 else 1.0 / 1.2, position.x(), position.y())
        event.accept()  # type: ignore[attr-defined]

    def resizeEvent(self, event: object) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)  # type: ignore[arg-type]
        if self._auto_fit:
            self.fit_to_window()
