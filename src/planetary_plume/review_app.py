"""Local PySide6 application for independent plume-candidate annotation.

The application reads only a sanitized review manifest.  It never imports the
released-label parser, never reads ``release_label_map.json``, and never shows
released plume sectors or class labels.  Comparison is a separate command-line
stage.
"""

from __future__ import annotations

import argparse
import getpass
import math
import os
import sys
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QFont, QImage, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from planetary_plume.angle_intervals import AngularInterval
from planetary_plume.annotation_store import (
    AnnotationStoreError,
    CandidateGeometry,
    ImageReview,
    file_sha256,
    load_session,
    new_candidate,
    new_session,
    save_session,
)
from planetary_plume.display import DisplayAdjustmentError, adjust_display
from planetary_plume.image_readers import ImageReadError, load_image, normalize_for_display
from planetary_plume.qt_canvas import ImageCanvas
from planetary_plume.review_manifest import ReviewImage, ReviewManifest, ReviewManifestError, load_review_manifest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = PROJECT_ROOT / "annotations" / "independent" / "review_manifest.json"
DEFAULT_SESSION = PROJECT_ROOT / "annotations" / "independent" / "independent_review.json"


def _default_reviewer() -> str:
    for variable in ("USERNAME", "USER", "LOGNAME"):
        value = os.environ.get(variable)
        if value and value.strip():
            return value.strip()
    try:
        return getpass.getuser() or "independent-reviewer"
    except Exception:
        return "independent-reviewer"


def qimage_from_array(array: np.ndarray) -> QImage:
    """Convert a 2-D uint8 array to an owning QImage."""

    contiguous = np.ascontiguousarray(array)
    if contiguous.ndim != 2 or contiguous.dtype != np.uint8:
        raise ValueError("qimage_from_array requires a 2-D uint8 array.")
    height, width = contiguous.shape
    image = QImage(
        contiguous.data,
        width,
        height,
        contiguous.strides[0],
        QImage.Format.Format_Grayscale8,
    )
    return image.copy()


class ReviewWindow(QMainWindow):
    """Single-window independent review interface."""

    def __init__(
        self,
        manifest_path: str | Path,
        session_path: str | Path,
        reviewer: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.manifest_path = Path(manifest_path).expanduser().resolve(strict=False)
        self.session_path = Path(session_path).expanduser().resolve(strict=False)
        self.reviewer = reviewer.strip() or _default_reviewer()
        self.manifest: ReviewManifest = load_review_manifest(self.manifest_path)
        self._session_sha: str | None = None
        self._dirty = False
        self._updating_widgets = False
        self._current_image_id: str | None = None
        self._current_review: ImageReview | None = None
        self._current_image: ReviewImage | None = None
        self._current_image_info = None
        self._base_display: np.ndarray | None = None
        self._pending_geometry: CandidateGeometry | None = None
        self._selected_candidate_id: str | None = None

        if self.session_path.is_file():
            self.session = load_session(self.session_path)
            self._session_sha = file_sha256(self.session_path)
            self.reviewer = self.session.reviewer
            self.session.validate_against_manifest(self.manifest)
            extended = self.session.add_missing_from_manifest(self.manifest)
            if extended is not self.session:
                self.session = extended
                self._dirty = True
        else:
            self.session = new_session(self.manifest, self.reviewer)
        self._saved_session = self.session

        self._build_ui()
        self._populate_image_list()
        self._update_title_and_status()

    # ------------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        self.setWindowTitle("Planetary Plume Candidate Review — Independent (released labels hidden)")
        self.setMinimumSize(1120, 720)
        self.resize(1360, 860)

        central = QWidget(self)
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(8)

        banner = QLabel(
            "INDEPENDENT REVIEW MODE — released plume sectors and positive/negative "
            "labels are not loaded or shown. The fitted limb circle is the only "
            "released annotation geometry used here."
        )
        banner.setWordWrap(True)
        banner.setStyleSheet(
            "background: #143d2b; color: #d7ffe9; padding: 8px; "
            "border: 1px solid #2f8f63; border-radius: 4px;"
        )
        outer.addWidget(banner)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter, 1)

        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_center_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([280, 900, 430])

        self._build_menu()
        self._build_status_bar()

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 6, 0)
        title = QLabel("Images")
        title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        layout.addWidget(title)
        self.image_count_label = QLabel("")
        self.image_count_label.setStyleSheet("color: #555;")
        layout.addWidget(self.image_count_label)
        self.image_list = QListWidget()
        self.image_list.setAlternatingRowColors(True)
        self.image_list.setSpacing(2)
        self.image_list.currentItemChanged.connect(self._on_image_selected)
        self.image_list.setToolTip(
            "Only your own review status is shown. Released labels are not loaded."
        )
        layout.addWidget(self.image_list, 1)
        note = QLabel(
            "Order is neutral (instrument and image identifier), not released class."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(note)
        return panel

    def _build_center_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Navigate / pan", "navigate")
        self.mode_combo.addItem("Mark direction (click)", "direction")
        self.mode_combo.addItem("Mark interval (drag clockwise)", "interval")
        self.mode_combo.currentIndexChanged.connect(lambda _index: self._on_mode_changed())
        toolbar.addWidget(self.mode_combo)

        self.fit_button = QPushButton("Fit")
        self.fit_button.clicked.connect(lambda: self._fit())
        toolbar.addWidget(self.fit_button)
        self.actual_button = QPushButton("1:1")
        self.actual_button.clicked.connect(lambda: self._actual_size())
        toolbar.addWidget(self.actual_button)
        self.zoom_in_button = QPushButton("Zoom +")
        self.zoom_in_button.clicked.connect(lambda: self._zoom_in())
        toolbar.addWidget(self.zoom_in_button)
        self.zoom_out_button = QPushButton("Zoom −")
        self.zoom_out_button.clicked.connect(lambda: self._zoom_out())
        toolbar.addWidget(self.zoom_out_button)
        toolbar.addStretch(1)
        self.limb_check = QCheckBox("Limb circle")
        self.limb_check.setChecked(True)
        self.limb_check.toggled.connect(self._on_limb_toggled)
        toolbar.addWidget(self.limb_check)
        layout.addLayout(toolbar)

        self.canvas = ImageCanvas()
        self.canvas.direction_picked.connect(self._on_direction_picked)
        self.canvas.interval_picked.connect(self._on_interval_picked)
        self.canvas.cursor_moved.connect(self._on_cursor_moved)
        layout.addWidget(self.canvas, 1)

        display_row = QHBoxLayout()
        display_row.addWidget(QLabel("Brightness"))
        self.brightness_slider = QSlider(Qt.Orientation.Horizontal)
        self.brightness_slider.setRange(-100, 100)
        self.brightness_slider.setValue(0)
        self.brightness_slider.valueChanged.connect(self._refresh_display)
        display_row.addWidget(self.brightness_slider, 1)
        self.brightness_value = QLabel("+0")
        self.brightness_value.setMinimumWidth(34)
        display_row.addWidget(self.brightness_value)

        display_row.addSpacing(12)
        display_row.addWidget(QLabel("Contrast"))
        self.contrast_slider = QSlider(Qt.Orientation.Horizontal)
        self.contrast_slider.setRange(20, 300)
        self.contrast_slider.setValue(100)
        self.contrast_slider.valueChanged.connect(self._refresh_display)
        display_row.addWidget(self.contrast_slider, 1)
        self.contrast_value = QLabel("1.00×")
        self.contrast_value.setMinimumWidth(48)
        display_row.addWidget(self.contrast_value)
        self.reset_display_button = QPushButton("Reset display")
        self.reset_display_button.clicked.connect(lambda: self._reset_display())
        display_row.addWidget(self.reset_display_button)
        layout.addLayout(display_row)
        return panel

    def _build_right_panel(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(400)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(8, 0, 8, 8)
        layout.setSpacing(10)

        metadata = QGroupBox("Image identity")
        meta_layout = QFormLayout(metadata)
        self.meta_name = QLabel("—")
        self.meta_name.setWordWrap(True)
        self.meta_name.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.meta_image_id = QLabel("—")
        self.meta_image_id.setWordWrap(True)
        self.meta_image_id.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.meta_target = QLabel("—")
        self.meta_instrument = QLabel("—")
        self.meta_dimensions = QLabel("—")
        self.meta_format = QLabel("—")
        self.meta_limb = QLabel("—")
        self.meta_product = QLabel("—")
        self.meta_product.setWordWrap(True)
        self.meta_product.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        meta_layout.addRow("Image:", self.meta_name)
        meta_layout.addRow("Image ID:", self.meta_image_id)
        meta_layout.addRow("Target:", self.meta_target)
        meta_layout.addRow("Instrument:", self.meta_instrument)
        meta_layout.addRow("Dimensions:", self.meta_dimensions)
        meta_layout.addRow("Format:", self.meta_format)
        meta_layout.addRow("Limb fit:", self.meta_limb)
        meta_layout.addRow("Product:", self.meta_product)
        layout.addWidget(metadata)

        review_group = QGroupBox("Your independent review")
        review_layout = QVBoxLayout(review_group)
        self.no_candidate_check = QCheckBox(
            "No candidate identified in this image (NO_CANDIDATE_IDENTIFIED)"
        )
        self.no_candidate_check.setToolTip(
            "Use this to record an explicit negative assessment. It cannot coexist "
            "with candidate annotations."
        )
        self.no_candidate_check.toggled.connect(self._on_no_candidate_toggled)
        review_layout.addWidget(self.no_candidate_check)
        self.flag_ambiguous = QCheckBox("AMBIGUOUS — image-level ambiguity")
        self.flag_ambiguous.toggled.connect(self._on_flags_changed)
        review_layout.addWidget(self.flag_ambiguous)
        self.flag_needs_review = QCheckBox("NEEDS_REVIEW — image-level flag")
        self.flag_needs_review.toggled.connect(self._on_flags_changed)
        review_layout.addWidget(self.flag_needs_review)
        review_layout.addWidget(QLabel("Image notes:"))
        self.image_notes = QPlainTextEdit()
        self.image_notes.setPlaceholderText(
            "Optional: observing conditions, display stretch, feature description, "
            "or reasons for ambiguity."
        )
        self.image_notes.setMaximumHeight(78)
        self.image_notes.textChanged.connect(self._on_image_notes_changed)
        review_layout.addWidget(self.image_notes)
        self.review_state_label = QLabel("Not started")
        self.review_state_label.setStyleSheet("color: #555;")
        review_layout.addWidget(self.review_state_label)
        self.complete_button = QPushButton("Mark review complete and save")
        self.complete_button.clicked.connect(lambda: self._on_complete_clicked())
        review_layout.addWidget(self.complete_button)
        layout.addWidget(review_group)

        candidate_group = QGroupBox("Candidate annotation")
        candidate_layout = QVBoxLayout(candidate_group)
        instruction = QLabel(
            "Choose “Mark direction” and click the image, or “Mark interval” and "
            "drag clockwise. Then classify and add the candidate. Candidate "
            "classifications here are PLAUSIBLE or UNCERTAIN; use the image-level "
            "checkbox for NO_CANDIDATE_IDENTIFIED."
        )
        instruction.setWordWrap(True)
        instruction.setStyleSheet("color: #555;")
        candidate_layout.addWidget(instruction)
        self.pending_label = QLabel("No geometry selected.")
        self.pending_label.setWordWrap(True)
        self.pending_label.setStyleSheet("color: #1f5f8b;")
        candidate_layout.addWidget(self.pending_label)

        form = QFormLayout()
        self.class_combo = QComboBox()
        self.class_combo.addItem("PLAUSIBLE", "PLAUSIBLE")
        self.class_combo.addItem("UNCERTAIN", "UNCERTAIN")
        self.class_combo.setToolTip(
            "Use the image-level “No candidate identified” checkbox to record "
            "NO_CANDIDATE_IDENTIFIED."
        )
        self.conf_combo = QComboBox()
        self.conf_combo.addItem("LOW", "LOW")
        self.conf_combo.addItem("MEDIUM", "MEDIUM")
        self.conf_combo.addItem("HIGH", "HIGH")
        self.conf_combo.setCurrentIndex(1)
        form.addRow("Classification:", self.class_combo)
        form.addRow("Confidence:", self.conf_combo)
        candidate_layout.addLayout(form)

        candidate_layout.addWidget(QLabel("Candidate notes:"))
        self.candidate_notes = QPlainTextEdit()
        self.candidate_notes.setPlaceholderText(
            "Optional: why this candidate is plausible or uncertain; no confirmed-plume claims."
        )
        self.candidate_notes.setMaximumHeight(64)
        candidate_layout.addWidget(self.candidate_notes)

        button_row = QHBoxLayout()
        self.add_candidate_button = QPushButton("Add candidate")
        self.add_candidate_button.clicked.connect(lambda: self._add_candidate())
        self.update_candidate_button = QPushButton("Update selected")
        self.update_candidate_button.clicked.connect(lambda: self._update_candidate())
        self.delete_candidate_button = QPushButton("Delete selected")
        self.delete_candidate_button.clicked.connect(lambda: self._delete_candidate())
        button_row.addWidget(self.add_candidate_button)
        button_row.addWidget(self.update_candidate_button)
        button_row.addWidget(self.delete_candidate_button)
        candidate_layout.addLayout(button_row)

        candidate_layout.addWidget(QLabel("Candidates in this image:"))
        self.candidate_list = QListWidget()
        self.candidate_list.setMaximumHeight(170)
        self.candidate_list.currentItemChanged.connect(self._on_candidate_selected)
        candidate_layout.addWidget(self.candidate_list)

        protocol = QLabel(
            "Angle convention: 0° up; increasing clockwise; origin at the fitted "
            "limb-circle center. An interval is swept clockwise from start to end, "
            "so it may cross 0°/360°. Intervals and directions are candidates, not "
            "confirmed physical plumes."
        )
        protocol.setWordWrap(True)
        protocol.setStyleSheet("color: #555; font-size: 11px;")
        candidate_layout.addWidget(protocol)
        layout.addWidget(candidate_group)
        layout.addStretch(1)

        scroll.setWidget(content)
        return scroll

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        save_action = QAction("&Save", self)
        save_action.setShortcut(QKeySequence.StandardKey.Save)
        save_action.triggered.connect(lambda: self._save())
        file_menu.addAction(save_action)
        complete_action = QAction("Save and mark &complete", self)
        complete_action.triggered.connect(lambda: self._on_complete_clicked())
        file_menu.addAction(complete_action)
        file_menu.addSeparator()
        quit_action = QAction("E&xit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(lambda: self.close())
        file_menu.addAction(quit_action)

        help_menu = self.menuBar().addMenu("&Help")
        protocol_action = QAction("Review &protocol", self)
        protocol_action.triggered.connect(lambda: self._show_protocol())
        help_menu.addAction(protocol_action)
        about_action = QAction("&About", self)
        about_action.triggered.connect(lambda: self._show_about())
        help_menu.addAction(about_action)

    def _build_status_bar(self) -> None:
        self.status_coords = QLabel("cursor: —")
        self.status_angle = QLabel("angle: —")
        self.status_zoom = QLabel("zoom: —")
        self.status_saved = QLabel("not saved")
        self.statusBar().addWidget(self.status_coords)
        self.statusBar().addWidget(self.status_angle)
        self.statusBar().addPermanentWidget(self.status_zoom)
        self.statusBar().addPermanentWidget(self.status_saved)

    # ----------------------------------------------------------- list/loading
    def _populate_image_list(self, *, load_if_needed: bool = True) -> None:
        current = self._current_image_id
        self._updating_widgets = True
        self.image_list.clear()
        for image in self.manifest.images:
            review = self.session.review(image.image_id)
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, image.image_id)
            item.setText(f"{image.display_name}\n{review.summary()}")
            item.setToolTip(
                f"{image.display_name}\n{image.target} · {image.instrument}\n"
                f"{image.width} × {image.height} · {image.image_format.upper()}"
            )
            self._style_image_item(item, review)
            self.image_list.addItem(item)
        self._updating_widgets = False
        ids = [self.image_list.item(index).data(Qt.ItemDataRole.UserRole) for index in range(self.image_list.count())]
        if not ids:
            return
        target = current if current in ids else ids[0]
        self._select_image_item(target)
        self._update_image_list_items()
        if load_if_needed and target != current:
            self._load_image(target)

    def _select_image_item(self, image_id: str) -> None:
        previous = self._updating_widgets
        self._updating_widgets = True
        for index in range(self.image_list.count()):
            item = self.image_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == image_id:
                self.image_list.setCurrentItem(item)
                break
        self._updating_widgets = previous

    def _style_image_item(self, item: QListWidgetItem, review: ImageReview) -> None:
        if review.is_complete:
            item.setForeground(QColor("#176b3a"))
        elif review.candidates or review.no_candidate_identified or review.image_flags or review.notes:
            item.setForeground(QColor("#8a5a00"))
        else:
            item.setForeground(QColor("#222222"))

    def _update_image_list_items(self) -> None:
        for index in range(self.image_list.count()):
            item = self.image_list.item(index)
            image_id = item.data(Qt.ItemDataRole.UserRole)
            try:
                review = self.session.review(image_id)
            except AnnotationStoreError:
                continue
            image = self.manifest.by_id()[image_id]
            item.setText(f"{image.display_name}\n{review.summary()}")
            self._style_image_item(item, review)
        complete = sum(1 for review in self.session.reviews if review.is_complete)
        self.image_count_label.setText(
            f"{len(self.session.reviews)} image(s) · {complete} complete · "
            f"{len(self.session.reviews) - complete} open"
        )

    def _on_image_selected(
        self, current: QListWidgetItem | None, previous: QListWidgetItem | None
    ) -> None:
        if self._updating_widgets or current is None:
            return
        image_id = current.data(Qt.ItemDataRole.UserRole)
        if not image_id or image_id == self._current_image_id:
            return
        if not self._maybe_save_before_navigation():
            if self._current_image_id:
                self._select_image_item(self._current_image_id)
            return
        self._load_image(str(image_id))

    def _load_image(self, image_id: str) -> None:
        review = self.session.review(image_id)
        image = self.manifest.by_id()[image_id]
        self._current_image_id = image_id
        self._current_review = review
        self._current_image = image
        self._selected_candidate_id = None
        self._pending_geometry = None
        self._current_image_info = None
        self._base_display = None

        self.meta_name.setText(image.display_name)
        self.meta_image_id.setText(image.image_id)
        self.meta_target.setText(image.target)
        self.meta_instrument.setText(image.instrument)
        self.meta_dimensions.setText(f"{image.width} × {image.height} px")
        self.meta_format.setText(image.image_format.upper())
        self.meta_limb.setText(
            f"center=({image.limb.center_x:.1f}, {image.limb.center_y:.1f}), "
            f"r={image.limb.radius:.1f} px, RMS={image.limb.rms_residual:.2f} px"
        )
        self.meta_product.setText(image.product_path)

        self._updating_widgets = True
        self.no_candidate_check.setChecked(review.no_candidate_identified)
        self.flag_ambiguous.setChecked("AMBIGUOUS" in review.image_flags)
        self.flag_needs_review.setChecked("NEEDS_REVIEW" in review.image_flags)
        self.image_notes.setPlainText(review.notes)
        self._updating_widgets = False

        self._pending_geometry = None
        self.pending_label.setText("No geometry selected.")
        self.candidate_notes.clear()
        self.class_combo.setCurrentIndex(0)
        self.conf_combo.setCurrentIndex(1)
        self._refresh_candidate_list()
        self._update_review_state()

        try:
            actual_sha = file_sha256(image.product_path)
            if actual_sha != image.image_sha256:
                raise ValueError(
                    "Source image SHA256 does not match the review manifest. "
                    "Refusing to annotate a different or modified product."
                )
            image_info = load_image(image.product_path, image.pds_label_path)
            if (image_info.width, image_info.height) != (image.width, image.height):
                raise ValueError(
                    "Image dimensions do not match the review manifest "
                    f"({image_info.width}x{image_info.height} vs "
                    f"{image.width}x{image.height})."
                )
            self._current_image_info = image_info
            self._base_display = normalize_for_display(image_info.array)
        except (ImageReadError, OSError, ValueError) as exc:
            self.canvas.set_error(
                "Image could not be loaded safely. The review can be inspected but "
                f"not annotated.\n\n{exc}"
            )
            self._update_controls_enabled()
            self._update_title_and_status()
            return

        self._refresh_display(fit=True)
        self.canvas.set_limb(image.limb)
        self.canvas.set_candidates(review.candidates, None)
        self.canvas.set_pending_geometry(None)
        self.mode_combo.setCurrentIndex(0)
        self.canvas.set_mode("navigate")
        self._update_controls_enabled()
        self._update_zoom_label()
        self._update_title_and_status()

    def _refresh_display(self, *args: object, fit: bool = False) -> None:
        if self._base_display is None:
            return
        brightness = self.brightness_slider.value()
        contrast = self.contrast_slider.value() / 100.0
        try:
            adjusted = adjust_display(
                self._base_display, brightness=brightness, contrast=contrast
            )
        except DisplayAdjustmentError:
            return
        self.brightness_value.setText(f"{brightness:+d}")
        self.contrast_value.setText(f"{contrast:.2f}×")
        image = qimage_from_array(adjusted)
        if fit:
            self.canvas.set_image(image, adjusted.shape[1], adjusted.shape[0])
        else:
            self.canvas.set_display_image(image)
        self._update_zoom_label()

    def _reset_display(self) -> None:
        self.brightness_slider.setValue(0)
        self.contrast_slider.setValue(100)

    # ------------------------------------------------------------- candidates
    def _refresh_candidate_list(self, select_id: str | None = None) -> None:
        self._updating_widgets = True
        self.candidate_list.clear()
        review = self._current_review
        if review is not None:
            for index, candidate in enumerate(review.candidates):
                geometry = candidate.geometry
                if geometry is None:
                    geometry_text = "no geometry"
                else:
                    geometry_text = geometry.format()
                item = QListWidgetItem(
                    f"#{index + 1}  {candidate.classification} · "
                    f"{candidate.confidence} · {geometry_text}"
                )
                item.setData(Qt.ItemDataRole.UserRole, candidate.candidate_id)
                item.setToolTip(candidate.notes or "(no candidate notes)")
                self.candidate_list.addItem(item)
            if not review.candidates:
                empty = QListWidgetItem("No candidates marked.")
                empty.setFlags(Qt.ItemFlag.NoItemFlags)
                self.candidate_list.addItem(empty)
        self._updating_widgets = False
        if select_id is not None:
            self._select_candidate_item(select_id)
        else:
            self._selected_candidate_id = None
            self.candidate_list.clearSelection()
            self._update_controls_enabled()

    def _select_candidate_item(self, candidate_id: str) -> None:
        self._updating_widgets = True
        for index in range(self.candidate_list.count()):
            item = self.candidate_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == candidate_id:
                self.candidate_list.setCurrentItem(item)
                break
        self._updating_widgets = False
        self._show_candidate_fields(candidate_id)

    def _on_candidate_selected(
        self, current: QListWidgetItem | None, previous: QListWidgetItem | None
    ) -> None:
        if self._updating_widgets or current is None:
            return
        candidate_id = current.data(Qt.ItemDataRole.UserRole)
        if not candidate_id:
            return
        self._show_candidate_fields(str(candidate_id))

    def _show_candidate_fields(self, candidate_id: str) -> None:
        if self._current_review is None:
            return
        try:
            candidate = self._current_review.candidate(candidate_id)
        except AnnotationStoreError:
            return
        self._selected_candidate_id = candidate_id
        self._updating_widgets = True
        if candidate.classification in {"PLAUSIBLE", "UNCERTAIN"}:
            index = self.class_combo.findData(candidate.classification)
            if index >= 0:
                self.class_combo.setCurrentIndex(index)
        index = self.conf_combo.findData(candidate.confidence)
        if index >= 0:
            self.conf_combo.setCurrentIndex(index)
        self.candidate_notes.setPlainText(candidate.notes)
        self._updating_widgets = False
        if candidate.geometry is not None:
            self.pending_label.setText(f"Selected geometry: {candidate.geometry.format()}")
        else:
            self.pending_label.setText("Selected candidate has no geometry.")
        self.canvas.set_selected_candidate(candidate_id)
        self._update_controls_enabled()

    def _on_direction_picked(self, angle: float) -> None:
        if self._current_review is None or self._current_review.no_candidate_identified:
            return
        self._set_pending_geometry(CandidateGeometry.direction_from_radians(angle))

    def _on_interval_picked(self, start: float, end: float) -> None:
        if self._current_review is None or self._current_review.no_candidate_identified:
            return
        interval = AngularInterval.from_radians(start, end)
        if interval.width_deg < 0.5:
            self._set_pending_geometry(CandidateGeometry.direction_from_radians(start))
        else:
            self._set_pending_geometry(CandidateGeometry("interval", interval))

    def _set_pending_geometry(self, geometry: CandidateGeometry) -> None:
        self._pending_geometry = geometry
        self.pending_label.setText(f"New geometry: {geometry.format()}")
        self.canvas.set_pending_geometry(geometry)
        self._update_controls_enabled()

    def _add_candidate(self) -> None:
        if self._current_review is None:
            return
        if self._current_review.no_candidate_identified:
            QMessageBox.information(
                self,
                "No-candidate assessment",
                "Uncheck “No candidate identified” before adding a candidate.",
            )
            return
        if self._pending_geometry is None:
            QMessageBox.information(
                self,
                "No geometry",
                "Click a direction or drag an interval on the image first.",
            )
            return
        try:
            candidate = new_candidate(
                classification=str(self.class_combo.currentData()),
                confidence=str(self.conf_combo.currentData()),
                geometry=self._pending_geometry,
                notes=self.candidate_notes.toPlainText().strip(),
            )
            review = self._current_review.with_candidate(candidate)
        except AnnotationStoreError as exc:
            QMessageBox.warning(self, "Could not add candidate", str(exc))
            return
        self._apply_review(review, refresh_candidates=True, select_candidate=candidate.candidate_id)
        self._pending_geometry = None
        self.canvas.set_pending_geometry(None)
        self.pending_label.setText(f"Added candidate #{len(review.candidates)}.")
        self.candidate_notes.clear()

    def _update_candidate(self) -> None:
        if self._current_review is None or self._selected_candidate_id is None:
            QMessageBox.information(self, "No selection", "Select a candidate to update.")
            return
        try:
            existing = self._current_review.candidate(self._selected_candidate_id)
            geometry = self._pending_geometry or existing.geometry
            updated = existing.with_updates(
                classification=str(self.class_combo.currentData()),
                confidence=str(self.conf_combo.currentData()),
                geometry=geometry,
                notes=self.candidate_notes.toPlainText().strip(),
            )
            review = self._current_review.replace_candidate(updated)
        except AnnotationStoreError as exc:
            QMessageBox.warning(self, "Could not update candidate", str(exc))
            return
        self._apply_review(review, refresh_candidates=True, select_candidate=updated.candidate_id)
        self._pending_geometry = None
        self.canvas.set_pending_geometry(None)
        self.pending_label.setText(f"Updated candidate: {updated.geometry.format()}")

    def _delete_candidate(self, *, confirm: bool = True) -> None:
        if self._current_review is None or self._selected_candidate_id is None:
            QMessageBox.information(self, "No selection", "Select a candidate to delete.")
            return
        if confirm:
            answer = QMessageBox.question(
                self,
                "Delete candidate",
                "Delete the selected candidate annotation? This cannot be undone "
                "except by discarding unsaved changes.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            review = self._current_review.delete_candidate(self._selected_candidate_id)
        except AnnotationStoreError as exc:
            QMessageBox.warning(self, "Could not delete candidate", str(exc))
            return
        self._apply_review(review, refresh_candidates=True)
        self._selected_candidate_id = None
        self.canvas.set_selected_candidate(None)
        self.pending_label.setText("Candidate deleted.")

    def _on_no_candidate_toggled(self, checked: bool) -> None:
        if self._updating_widgets or self._current_review is None:
            return
        if checked and self._current_review.candidates:
            answer = QMessageBox.question(
                self,
                "Replace candidates with a negative assessment?",
                f"This image has {len(self._current_review.candidates)} candidate(s). "
                "Marking “No candidate identified” will delete them from this review.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self._updating_widgets = True
                self.no_candidate_check.setChecked(False)
                self._updating_widgets = False
                return
        try:
            review = self._current_review.with_no_candidate(checked)
        except AnnotationStoreError as exc:
            QMessageBox.warning(self, "Could not update review", str(exc))
            self._updating_widgets = True
            self.no_candidate_check.setChecked(not checked)
            self._updating_widgets = False
            return
        self._selected_candidate_id = None
        self._pending_geometry = None
        self.canvas.set_pending_geometry(None)
        self._apply_review(review, refresh_candidates=True)
        self.pending_label.setText(
            "Image marked NO_CANDIDATE_IDENTIFIED." if checked else "No geometry selected."
        )

    def _on_flags_changed(self, checked: bool) -> None:
        if self._updating_widgets or self._current_review is None:
            return
        flags = []
        if self.flag_ambiguous.isChecked():
            flags.append("AMBIGUOUS")
        if self.flag_needs_review.isChecked():
            flags.append("NEEDS_REVIEW")
        try:
            review = self._current_review.with_flags(tuple(flags))
        except AnnotationStoreError as exc:
            QMessageBox.warning(self, "Could not update flags", str(exc))
            return
        self._apply_review(review, refresh_candidates=False)

    def _on_image_notes_changed(self) -> None:
        if self._updating_widgets or self._current_review is None:
            return
        review = self._current_review.with_notes(self.image_notes.toPlainText())
        self.session = self.session.replace_review(review)
        self._current_review = review
        self._mark_dirty()
        self._update_image_list_items()
        self._update_review_state()

    def _on_complete_clicked(self) -> None:
        if self._current_review is None:
            return
        if self._current_review.is_complete:
            review = self._current_review.mark_complete(False)
            self._apply_review(review, refresh_candidates=False)
            self._save()
            return
        if not self._current_review.no_candidate_identified and not self._current_review.candidates:
            QMessageBox.information(
                self,
                "Review outcome required",
                "Add at least one candidate, or check “No candidate identified in "
                "this image”, before marking the review complete.",
            )
            return
        try:
            review = self._current_review.mark_complete(True)
        except AnnotationStoreError as exc:
            QMessageBox.warning(self, "Could not complete review", str(exc))
            return
        self._apply_review(review, refresh_candidates=False)
        self._save()

    def _update_review_state(self) -> None:
        if self._current_review is None:
            self.review_state_label.setText("No image selected")
            self.complete_button.setText("Mark review complete and save")
            return
        review = self._current_review
        outcome = (
            "no candidate identified"
            if review.no_candidate_identified
            else f"{len(review.candidates)} candidate(s)"
        )
        self.review_state_label.setText(
            ("COMPLETE" if review.is_complete else "INCOMPLETE") + f" · {outcome}"
        )
        self.complete_button.setText(
            "Reopen review and save" if review.is_complete else "Mark review complete and save"
        )

    def _apply_review(
        self,
        review: ImageReview,
        *,
        refresh_candidates: bool,
        select_candidate: str | None = None,
    ) -> None:
        self.session = self.session.replace_review(review)
        self._current_review = review
        self._mark_dirty()
        self._updating_widgets = True
        self.no_candidate_check.setChecked(review.no_candidate_identified)
        self.flag_ambiguous.setChecked("AMBIGUOUS" in review.image_flags)
        self.flag_needs_review.setChecked("NEEDS_REVIEW" in review.image_flags)
        self._updating_widgets = False
        if refresh_candidates:
            self._refresh_candidate_list(select_id=select_candidate)
        self.canvas.set_candidates(review.candidates, select_candidate or self._selected_candidate_id)
        self._update_image_list_items()
        self._update_review_state()
        self._update_controls_enabled()

    # --------------------------------------------------------------- actions
    def _on_mode_changed(self) -> None:
        mode = str(self.mode_combo.currentData())
        self.canvas.set_mode(mode)
        if mode == "navigate":
            self.pending_label.setText("Navigate mode: drag to pan; wheel to zoom.")
        elif mode == "direction":
            self.pending_label.setText("Click a direction on the image.")
        else:
            self.pending_label.setText(
                "Drag clockwise from the interval start to its end. A short drag "
                "becomes a single direction."
            )

    def _on_limb_toggled(self, checked: bool) -> None:
        self.canvas.set_limb_visible(checked)

    def _on_cursor_moved(self, x: float, y: float, angle: object) -> None:
        if math.isnan(x) or math.isnan(y):
            self.status_coords.setText("cursor: —")
        else:
            self.status_coords.setText(f"cursor: x={x:.1f} y={y:.1f}")
        if angle is None:
            self.status_angle.setText("angle: —")
        else:
            self.status_angle.setText(
                f"angle: {math.degrees(float(angle)):.1f}° clockwise from up"
            )

    def _fit(self) -> None:
        self.canvas.fit_to_window()
        self._update_zoom_label()

    def _actual_size(self) -> None:
        self.canvas.actual_size()
        self._update_zoom_label()

    def _zoom_in(self) -> None:
        self.canvas.zoom_in()
        self._update_zoom_label()

    def _zoom_out(self) -> None:
        self.canvas.zoom_out()
        self._update_zoom_label()

    def _update_zoom_label(self) -> None:
        self.status_zoom.setText(f"zoom: {self.canvas.zoom_scale * 100:.0f}%")

    def _update_controls_enabled(self) -> None:
        has_image = self._base_display is not None
        no_candidate = bool(
            self._current_review and self._current_review.no_candidate_identified
        )
        candidate_enabled = has_image and not no_candidate
        self.mode_combo.setEnabled(has_image and not no_candidate)
        self.add_candidate_button.setEnabled(candidate_enabled and self._pending_geometry is not None)
        self.update_candidate_button.setEnabled(
            candidate_enabled and self._selected_candidate_id is not None
        )
        self.delete_candidate_button.setEnabled(
            candidate_enabled and self._selected_candidate_id is not None
        )
        self.no_candidate_check.setEnabled(has_image)
        self.flag_ambiguous.setEnabled(has_image)
        self.flag_needs_review.setEnabled(has_image)
        self.image_notes.setEnabled(has_image)
        self.complete_button.setEnabled(has_image)
        self.fit_button.setEnabled(has_image)
        self.actual_button.setEnabled(has_image)
        self.zoom_in_button.setEnabled(has_image)
        self.zoom_out_button.setEnabled(has_image)
        self.limb_check.setEnabled(has_image)
        self.brightness_slider.setEnabled(has_image)
        self.contrast_slider.setEnabled(has_image)
        self.reset_display_button.setEnabled(has_image)

    # ------------------------------------------------------------------ save
    def _mark_dirty(self) -> None:
        if not self._dirty:
            self._dirty = True
            self._update_title_and_status()

    def _update_title_and_status(self) -> None:
        marker = " *" if self._dirty else ""
        suffix = f" — {self._current_image_id}" if self._current_image_id else ""
        self.setWindowTitle(
            "Planetary Plume Candidate Review — Independent (released labels hidden)"
            + suffix
            + marker
        )
        if self._dirty:
            self.status_saved.setText("unsaved changes")
        elif self._session_sha is None:
            self.status_saved.setText("new session (not saved)")
        else:
            self.status_saved.setText("saved")

    def _save(self) -> bool:
        try:
            result = save_session(
                self.session,
                self.session_path,
                expected_sha256=self._session_sha,
            )
        except AnnotationStoreError as exc:
            QMessageBox.critical(self, "Could not save annotations", str(exc))
            return False
        self.session = result.session
        self._saved_session = result.session
        self._session_sha = result.sha256
        self._dirty = False
        if self._current_image_id:
            self._current_review = result.session.review(self._current_image_id)
        self._update_title_and_status()
        self._update_image_list_items()
        self._update_review_state()
        self.status_saved.setText(f"saved · {result.path.name}")
        return True

    def _maybe_save_before_navigation(self) -> bool:
        if not self._dirty:
            return True
        answer = QMessageBox.question(
            self,
            "Unsaved review changes",
            "Save your independent annotations before continuing?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self._save()
        if answer == QMessageBox.StandardButton.Discard:
            self.session = self._saved_session
            self._dirty = False
            if self._current_image_id:
                self._current_review = self.session.review(self._current_image_id)
            self._update_title_and_status()
            self._update_image_list_items()
            return True
        return False

    # ------------------------------------------------------------------ help
    def _show_protocol(self) -> None:
        QMessageBox.information(
            self,
            "Independent review protocol",
            "1. Do not open the released YAML labels, released-label map, or prior "
            "comparison reports during this review.\n\n"
            "2. Inspect each image. Brightness and contrast change only the display; "
            "source pixels are untouched.\n\n"
            "3. Click a direction or drag a clockwise interval. Angles use the "
            "project convention: 0° up, increasing clockwise, origin at the fitted "
            "limb-circle center.\n\n"
            "4. Classify each candidate as PLAUSIBLE or UNCERTAIN and record LOW, "
            "MEDIUM, or HIGH confidence. Use the image-level checkbox for "
            "NO_CANDIDATE_IDENTIFIED.\n\n"
            "5. Mark the image AMBIGUOUS or NEEDS_REVIEW if appropriate, then mark "
            "the review complete and save.\n\n"
            "Annotations are candidates, not confirmed physical plumes. Comparison "
            "is a separate command-line step run only after saving.",
        )

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About this tool",
            "Planetary Plume Candidate Review\n\n"
            "A local human-annotation tool for independent plume-candidate review. "
            "It is not a plume detector. It uses the project's existing image "
            "readers and its documented 0°-up clockwise angle convention.\n\n"
            "Released plume labels are excluded from this application.",
        )

    def closeEvent(self, event: object) -> None:  # noqa: N802 - Qt API
        if self._maybe_save_before_navigation():
            event.accept()  # type: ignore[attr-defined]
        else:
            event.ignore()  # type: ignore[attr-defined]


def _resolve_path(value: str | Path | None, default: Path) -> Path:
    if value is None:
        return default
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve(strict=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Launch the independent plume-candidate annotation GUI. "
            "Released labels are not loaded or shown."
        )
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help=f"Sanitized review manifest (default: {DEFAULT_MANIFEST}).",
    )
    parser.add_argument(
        "--session",
        type=Path,
        default=None,
        help=f"Independent annotation JSON file (default: {DEFAULT_SESSION}).",
    )
    parser.add_argument(
        "--reviewer",
        type=str,
        default=None,
        help="Reviewer name stored in a new annotation file. Defaults to the OS user.",
    )
    args = parser.parse_args(argv)

    app = QApplication(sys.argv[:1])
    app.setApplicationName("Planetary Plume Candidate Review")
    app.setStyle("Fusion")
    manifest_path = _resolve_path(args.manifest, DEFAULT_MANIFEST)
    session_path = _resolve_path(args.session, DEFAULT_SESSION)
    reviewer = args.reviewer or _default_reviewer()
    try:
        window = ReviewWindow(manifest_path, session_path, reviewer)
    except ReviewManifestError as exc:
        QMessageBox.critical(
            None,
            "Cannot start independent review",
            f"{exc}\n\nBuild the sanitized manifest first:\n"
            "python scripts\\build_review_manifest.py",
        )
        return 2
    except (AnnotationStoreError, OSError, ValueError) as exc:
        QMessageBox.critical(
            None,
            "Cannot start independent review",
            f"{exc}\n\nCheck the annotation session file or reload it after "
            "the review manifest has been rebuilt.",
        )
        return 2
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
