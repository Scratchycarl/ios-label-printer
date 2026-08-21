from __future__ import annotations

import traceback
from io import BytesIO
from pathlib import Path

from PySide6.QtCore import QMarginsF, QObject, QSize, QSizeF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QImage, QKeySequence, QPageLayout, QPageSize, QPainter, QPixmap
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ios_label_printer.designer import LabelCanvas
from ios_label_printer.device import DeviceReadError, read_connected_device
from ios_label_printer.models import LABEL_FIELDS, LOCK_STATUS_OPTIONS, DeviceInfo, LabelElement, LabelTemplate
from ios_label_printer.qr_dialog import QrCustomizeDialog
from ios_label_printer.renderer import render_label
from ios_label_printer.template import (
    bundled_default_template,
    ensure_user_default_template,
    load_template,
    save_template,
    user_templates_dir,
)


def pil_to_qimage(image) -> QImage:
    buf = BytesIO()
    image.save(buf, format="PNG")
    return QImage.fromData(buf.getvalue(), "PNG")


class DeviceWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def run(self) -> None:
        try:
            self.finished.emit(read_connected_device())
        except DeviceReadError as exc:
            self.failed.emit(str(exc))
        except Exception:
            self.failed.emit(traceback.format_exc(limit=4))


class FieldList(QListWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setDefaultDropAction(Qt.CopyAction)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        for field, title in LABEL_FIELDS:
            item = QListWidgetItem(title)
            item.setData(Qt.UserRole, field)
            if field == "custom":
                item.setToolTip("Drag onto the label to add a blank text box you can type in")
            elif field == "lock_status":
                item.setToolTip("Drag onto the label, then click to choose lock status")
            else:
                item.setToolTip("Drag onto the label to place this field")
            self.addItem(item)

    def mimeTypes(self):
        return ["text/plain"]

    def mimeData(self, items):
        mime = super().mimeData(items)
        if items:
            mime.setText(str(items[0].data(Qt.UserRole)))
        return mime


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("iOS Label Printer")
        self.resize(1280, 760)
        self.template_path = ensure_user_default_template()
        try:
            self.template = load_template(self.template_path)
        except Exception:
            self.template = bundled_default_template()
        self.device = DeviceInfo.sample()
        self.dirty = False
        self._thread: QThread | None = None
        self._worker: DeviceWorker | None = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(120)
        self._preview_timer.timeout.connect(self.refresh_preview)
        self._building = False
        self._setup_ui()
        self.reload_document()
        self.statusBar().showMessage("Showing sample data. Connect an iPhone and press Read device.")

    def _setup_ui(self) -> None:
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(18, 18))
        self.addToolBar(toolbar)

        read_action = QAction("Read device", self)
        read_action.setShortcut(QKeySequence("F5"))
        read_action.triggered.connect(self.read_device)
        toolbar.addAction(read_action)

        sample_action = QAction("Sample data", self)
        sample_action.triggered.connect(self.use_sample)
        toolbar.addAction(sample_action)
        toolbar.addSeparator()

        print_action = QAction("Print", self)
        print_action.setShortcut(QKeySequence.Print)
        print_action.triggered.connect(self.print_label)
        toolbar.addAction(print_action)

        png_action = QAction("Save PNG", self)
        png_action.setShortcut(QKeySequence("Ctrl+E"))
        png_action.triggered.connect(self.save_png)
        toolbar.addAction(png_action)
        toolbar.addSeparator()

        load_action = QAction("Load template", self)
        load_action.setShortcut(QKeySequence.Open)
        load_action.triggered.connect(self.load_template_dialog)
        toolbar.addAction(load_action)

        save_action = QAction("Save template", self)
        save_action.setShortcut(QKeySequence.Save)
        save_action.triggered.connect(self.save_current_template)
        toolbar.addAction(save_action)

        save_as_action = QAction("Save template as…", self)
        save_as_action.triggered.connect(self.save_template_as)
        toolbar.addAction(save_as_action)

        reset_action = QAction("Reset layout", self)
        reset_action.triggered.connect(self.reset_template)
        toolbar.addAction(reset_action)

        splitter = QSplitter(Qt.Horizontal)
        left = self._build_left_panel()
        left.setMinimumWidth(230)
        splitter.addWidget(left)
        self.canvas = LabelCanvas()
        self.canvas.setMinimumWidth(360)
        self.canvas.geometryChanged.connect(self._on_geometry_changed)
        self.canvas.selectionChanged.connect(self._on_canvas_selection)
        self.canvas.fieldDropped.connect(self.place_field)
        self.canvas.qrEditRequested.connect(self.open_qr_dialog)
        right = self._build_right_panel()
        right.setMinimumWidth(240)
        splitter.addWidget(self.canvas)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([260, 720, 300])
        self.setCentralWidget(splitter)
        self.setStatusBar(QStatusBar())

        self.field_list.itemClicked.connect(self._on_field_list_clicked)
        self.field_list.itemDoubleClicked.connect(self._on_field_double_clicked)

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)

        device_box = QGroupBox("Device")
        device_layout = QFormLayout(device_box)
        self.device_model_label = QLabel("—")
        self.device_source_label = QLabel("sample")
        device_layout.addRow("Model", self.device_model_label)
        device_layout.addRow("Source", self.device_source_label)
        layout.addWidget(device_box)

        fields_box = QGroupBox("Fields")
        fields_layout = QVBoxLayout(fields_box)
        hint = QLabel("Drag onto the label. Custom text can be added more than once. Double-click a text box to type.")
        hint.setWordWrap(True)
        fields_layout.addWidget(hint)
        self.field_list = FieldList()
        fields_layout.addWidget(self.field_list)
        layout.addWidget(fields_box, 1)

        props_box = QGroupBox("Selected field")
        form = QFormLayout(props_box)
        self.props_form = form
        self.prefix_edit = QComboBox()
        self.prefix_edit.setEditable(True)
        self.prefix_edit.addItems(["", "BH ", "iOS ", "SN ", "IMEI ", "Storage "])
        self.text_edit = QLineEdit()
        self.text_edit.setPlaceholderText("Type custom text")
        self.lock_combo = QComboBox()
        self.lock_combo.setPlaceholderText("Lock Status")
        self.lock_combo.addItems(LOCK_STATUS_OPTIONS)
        self.lock_combo.currentTextChanged.connect(self._apply_selected_props)
        self.lock_combo.setVisible(False)
        self.x_spin = self._mm_spin()
        self.y_spin = self._mm_spin()
        self.w_spin = self._mm_spin(0.5, 200)
        self.h_spin = self._mm_spin(0.5, 200)
        self.font_spin = QDoubleSpinBox()
        self.font_spin.setRange(3, 24)
        self.font_spin.setSingleStep(0.5)
        self.font_spin.setSuffix(" pt")
        self.bold_check = QCheckBox("Bold")
        self.visible_check = QCheckBox("Visible")
        self.qr_button = QPushButton("Customize QR code…")
        self.qr_button.clicked.connect(self.open_qr_dialog)
        self.qr_button.setVisible(False)
        for widget in (
            self.prefix_edit,
            self.text_edit,
            self.x_spin,
            self.y_spin,
            self.w_spin,
            self.h_spin,
            self.font_spin,
            self.bold_check,
            self.visible_check,
        ):
            if isinstance(widget, QComboBox):
                widget.currentTextChanged.connect(self._apply_selected_props)
            elif isinstance(widget, QLineEdit):
                widget.textChanged.connect(self._apply_selected_props)
            elif isinstance(widget, QCheckBox):
                widget.toggled.connect(self._apply_selected_props)
            else:
                widget.valueChanged.connect(self._apply_selected_props)
        form.addRow("Text", self.text_edit)
        form.addRow("Lock Status", self.lock_combo)
        lock_label = form.labelForField(self.lock_combo)
        if lock_label:
            lock_label.setVisible(False)
        form.addRow("Prefix", self.prefix_edit)
        form.addRow("X", self.x_spin)
        form.addRow("Y", self.y_spin)
        form.addRow("Width", self.w_spin)
        form.addRow("Height", self.h_spin)
        form.addRow("Font", self.font_spin)
        form.addRow("", self.bold_check)
        form.addRow(self.qr_button)
        form.addRow("", self.visible_check)
        layout.addWidget(props_box)
        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)

        size_box = QGroupBox("Label")
        form = QFormLayout(size_box)
        self.width_spin = self._mm_spin(10, 200)
        self.height_spin = self._mm_spin(10, 200)
        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(203, 1200)
        self.dpi_spin.setSingleStep(1)
        self.margin_top = self._mm_spin(0, 20)
        self.margin_right = self._mm_spin(0, 20)
        self.margin_bottom = self._mm_spin(0, 20)
        self.margin_left = self._mm_spin(0, 20)
        for spin in (
            self.width_spin,
            self.height_spin,
            self.dpi_spin,
            self.margin_top,
            self.margin_right,
            self.margin_bottom,
            self.margin_left,
        ):
            spin.valueChanged.connect(self._apply_page_settings)
        form.addRow("Width", self.width_spin)
        form.addRow("Height", self.height_spin)
        form.addRow("DPI", self.dpi_spin)
        form.addRow("Margin top", self.margin_top)
        form.addRow("Margin right", self.margin_right)
        form.addRow("Margin bottom", self.margin_bottom)
        form.addRow("Margin left", self.margin_left)
        layout.addWidget(size_box)

        preview_box = QGroupBox("High-res preview")
        preview_layout = QVBoxLayout(preview_box)
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(160)
        self.preview_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.preview_label.setStyleSheet("background:#9aa3b0; border:1px solid #64748b;")
        self.preview_meta = QLabel()
        self.preview_meta.setWordWrap(True)
        preview_layout.addWidget(self.preview_label, 1)
        preview_layout.addWidget(self.preview_meta)
        layout.addWidget(preview_box, 1)
        return panel

    def _mm_spin(self, minimum: float = 0, maximum: float = 80) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(2)
        spin.setSingleStep(0.1)
        spin.setSuffix(" mm")
        return spin

    def reload_document(self) -> None:
        self._building = True
        self.width_spin.setValue(self.template.width_mm)
        self.height_spin.setValue(self.template.height_mm)
        self.dpi_spin.setValue(self.template.dpi)
        self.margin_top.setValue(self.template.margin_mm.top)
        self.margin_right.setValue(self.template.margin_mm.right)
        self.margin_bottom.setValue(self.template.margin_mm.bottom)
        self.margin_left.setValue(self.template.margin_mm.left)
        self.device_model_label.setText(self.device.model or "—")
        self.device_source_label.setText(self.device.source or "—")
        self.canvas.set_document(self.template, self.device)
        self._building = False
        self.refresh_preview()
        self._update_window_title()

    def _update_window_title(self) -> None:
        mark = " *" if self.dirty else ""
        self.setWindowTitle(f"iOS Label Printer — {self.template.name}{mark}")

    def mark_dirty(self) -> None:
        self.dirty = True
        self._update_window_title()
        self._preview_timer.start()

    def _on_geometry_changed(self) -> None:
        element = self.canvas.selected_element()
        if element:
            self._load_element_props(element)
        self.mark_dirty()

    def _on_canvas_selection(self, element: LabelElement | None) -> None:
        self._load_element_props(element)

    def _on_field_list_clicked(self, item: QListWidgetItem) -> None:
        field = str(item.data(Qt.UserRole))
        if field != "custom":
            self.canvas.select_field(field)

    def _on_field_double_clicked(self, item: QListWidgetItem) -> None:
        field = str(item.data(Qt.UserRole))
        if field == "custom":
            count = sum(1 for element in self.template.elements if element.is_custom())
            y = min(self.template.height_mm - 5.0, 24.0 + count * 0.4)
            self.place_field(field, 1.4, y)
            return
        if field == "lock_status":
            self.place_field(field, 1.4, 24.0)
            return
        self.place_field(field, 1.4, 1.4)

    def place_field(self, field: str, x_mm: float, y_mm: float) -> None:
        if field == "custom":
            element = LabelElement.default_for_field("custom")
            element.id = self.template.next_custom_id()
            element.x_mm = round(x_mm, 3)
            element.y_mm = round(y_mm, 3)
            self.template.elements.append(element)
            self.canvas.rebuild()
            self.canvas.select_id(element.id)
            self.mark_dirty()
            self.text_edit.setFocus()
            self.text_edit.selectAll()
            return
        existing = self.template.element_by_field(field)
        if existing:
            existing.visible = True
            existing.x_mm = round(x_mm, 3)
            existing.y_mm = round(y_mm, 3)
        else:
            element = LabelElement.default_for_field(field)
            element.x_mm = round(x_mm, 3)
            element.y_mm = round(y_mm, 3)
            self.template.elements.append(element)
        self.canvas.rebuild()
        self.canvas.select_field(field)
        self.mark_dirty()
        if field == "lock_status":
            item = self.canvas._items.get("lock_status")
            if item:
                self.canvas.start_lock_status_edit(item)

    def _set_row_visible(self, widget, visible: bool) -> None:
        widget.setVisible(visible)
        label = self.props_form.labelForField(widget)
        if label:
            label.setVisible(visible)

    def _load_element_props(self, element: LabelElement | None) -> None:
        enabled = element is not None
        custom = bool(element and element.is_custom())
        is_qr = bool(element and element.is_qr())
        is_lock = bool(element and element.is_lock_status())
        widgets = (
            self.prefix_edit,
            self.text_edit,
            self.lock_combo,
            self.x_spin,
            self.y_spin,
            self.w_spin,
            self.h_spin,
            self.font_spin,
            self.bold_check,
            self.visible_check,
        )
        for widget in widgets:
            widget.blockSignals(True)
        self._set_row_visible(self.text_edit, custom)
        self._set_row_visible(self.lock_combo, is_lock)
        self._set_row_visible(self.prefix_edit, enabled and not custom and not is_qr and not is_lock)
        self._set_row_visible(self.font_spin, enabled and not is_qr)
        self._set_row_visible(self.bold_check, enabled and not is_qr)
        self.qr_button.setVisible(is_qr)
        self.prefix_edit.setEnabled(enabled and not custom and not is_qr and not is_lock)
        self.text_edit.setEnabled(custom)
        self.lock_combo.setEnabled(is_lock)
        self.font_spin.setEnabled(enabled and not is_qr)
        self.bold_check.setEnabled(enabled and not is_qr)
        for widget in (self.x_spin, self.y_spin, self.w_spin, self.h_spin, self.visible_check):
            widget.setEnabled(enabled)
        if element:
            self.prefix_edit.setEditText(element.prefix)
            self.text_edit.setText(element.text if custom else "")
            if is_lock and element.text in LOCK_STATUS_OPTIONS:
                self.lock_combo.setCurrentText(element.text)
            else:
                self.lock_combo.setCurrentIndex(-1)
            self.x_spin.setValue(element.x_mm)
            self.y_spin.setValue(element.y_mm)
            self.w_spin.setValue(element.width_mm)
            self.h_spin.setValue(element.height_mm)
            self.font_spin.setValue(element.font_size_pt)
            self.bold_check.setChecked(element.bold)
            self.visible_check.setChecked(element.visible)
        else:
            self.text_edit.clear()
            self.lock_combo.setCurrentIndex(-1)
        for widget in widgets:
            widget.blockSignals(False)

    def open_qr_dialog(self, element: LabelElement | None = None) -> None:
        current = element if isinstance(element, LabelElement) else self.canvas.selected_element()
        if current is None or not current.is_qr():
            current = self.template.element_by_field("qr_payload")
        if current is None or not current.is_qr():
            return
        dialog = QrCustomizeDialog(current.qr_fields, current.qr_separator, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        current.qr_fields = dialog.selected_fields()
        current.qr_separator = dialog.separator()
        self.canvas.update_element(current)
        self.canvas.select_id(current.id)
        self.mark_dirty()

    def _apply_selected_props(self) -> None:
        if self._building:
            return
        element = self.canvas.selected_element()
        if not element:
            return
        element.prefix = self.prefix_edit.currentText()
        if element.is_custom():
            element.text = self.text_edit.text()
        if element.is_lock_status() and self.lock_combo.currentIndex() >= 0:
            element.text = self.lock_combo.currentText()
        element.x_mm = self.x_spin.value()
        element.y_mm = self.y_spin.value()
        element.width_mm = self.w_spin.value()
        element.height_mm = self.h_spin.value()
        element.font_size_pt = self.font_spin.value()
        element.bold = self.bold_check.isChecked()
        was_visible = element.visible
        element.visible = self.visible_check.isChecked()
        if was_visible != element.visible:
            self.canvas.rebuild()
            if element.visible:
                self.canvas.select_id(element.id)
        else:
            self.canvas.update_element(element)
        self.mark_dirty()

    def _apply_page_settings(self) -> None:
        if self._building:
            return
        self.template.width_mm = self.width_spin.value()
        self.template.height_mm = self.height_spin.value()
        self.template.dpi = int(self.dpi_spin.value())
        self.template.margin_mm.top = self.margin_top.value()
        self.template.margin_mm.right = self.margin_right.value()
        self.template.margin_mm.bottom = self.margin_bottom.value()
        self.template.margin_mm.left = self.margin_left.value()
        self.canvas.rebuild()
        self.mark_dirty()

    def refresh_preview(self) -> None:
        image = render_label(self.template, self.device)
        qimage = pil_to_qimage(image)
        pixmap = QPixmap.fromImage(qimage)
        available = self.preview_label.size() - QSize(12, 12)
        if available.width() > 10 and available.height() > 10:
            pixmap = pixmap.scaled(available, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.preview_label.setPixmap(pixmap)
        self.preview_meta.setText(
            f"{self.template.width_mm:g}×{self.template.height_mm:g} mm  ·  "
            f"{self.template.dpi} DPI  ·  {image.width}×{image.height} px"
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._preview_timer.start()

    def read_device(self) -> None:
        if self._thread and self._thread.isRunning():
            return
        self.statusBar().showMessage("Reading connected iPhone…")
        self._thread = QThread(self)
        self._worker = DeviceWorker()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_device_read)
        self._worker.failed.connect(self._on_device_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_device_read(self, info: DeviceInfo) -> None:
        self.device = info
        self.reload_document()
        self.statusBar().showMessage(f"Connected: {info.model}  ({info.source})")

    def _on_device_failed(self, message: str) -> None:
        self.statusBar().showMessage("No device — showing sample data")
        QMessageBox.warning(self, "Could not read device", message)

    def use_sample(self) -> None:
        self.device = DeviceInfo.sample()
        self.reload_document()
        self.statusBar().showMessage("Showing sample data")

    def save_png(self) -> None:
        default = Path.home() / "Desktop" / f"{self.device.serial or 'label'}.png"
        path, _ = QFileDialog.getSaveFileName(self, "Save label PNG", str(default), "PNG (*.png)")
        if not path:
            return
        render_label(self.template, self.device).save(path, "PNG")
        self.statusBar().showMessage(f"Saved {path}")

    def print_label(self) -> None:
        printer = QPrinter(QPrinter.HighResolution)
        page_size = QPageSize(
            QSizeF(self.template.width_mm, self.template.height_mm),
            QPageSize.Millimeter,
        )
        layout = QPageLayout(
            page_size,
            QPageLayout.Portrait,
            QMarginsF(0, 0, 0, 0),
            QPageLayout.Millimeter,
        )
        layout.setMode(QPageLayout.FullPageMode)
        printer.setPageLayout(layout)
        printer.setFullPage(True)
        printer.setResolution(self.template.dpi)
        dialog = QPrintDialog(printer, self)
        if dialog.exec() != QPrintDialog.Accepted:
            return
        image = render_label(self.template, self.device, dpi=printer.resolution() or self.template.dpi)
        qimage = pil_to_qimage(image)
        painter = QPainter(printer)
        try:
            target = printer.pageRect(QPrinter.DevicePixel)
            painter.drawImage(target, qimage)
        finally:
            painter.end()
        self.statusBar().showMessage("Sent label to printer")

    def load_template_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load template",
            str(user_templates_dir()),
            "JSON templates (*.json)",
        )
        if not path:
            return
        self.template_path = Path(path)
        self.template = load_template(self.template_path)
        self.dirty = False
        self.reload_document()
        self.statusBar().showMessage(f"Loaded {self.template_path.name}")

    def save_current_template(self) -> None:
        save_template(self.template_path, self.template)
        self.dirty = False
        self._update_window_title()
        self.statusBar().showMessage(f"Saved {self.template_path}")

    def save_template_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save template as",
            str(user_templates_dir() / f"{self.template.name}.json"),
            "JSON templates (*.json)",
        )
        if not path:
            return
        self.template_path = Path(path)
        self.template.name = self.template_path.stem
        self.save_current_template()

    def reset_template(self) -> None:
        if QMessageBox.question(self, "Reset layout", "Restore the bundled 40×30 mm template?") != QMessageBox.Yes:
            return
        self.template = bundled_default_template()
        self.dirty = True
        self.reload_document()

    def closeEvent(self, event) -> None:
        if self.dirty:
            answer = QMessageBox.question(
                self,
                "Unsaved template",
                "Save the current label template before closing?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            )
            if answer == QMessageBox.Save:
                self.save_current_template()
            elif answer == QMessageBox.Cancel:
                event.ignore()
                return
        super().closeEvent(event)
