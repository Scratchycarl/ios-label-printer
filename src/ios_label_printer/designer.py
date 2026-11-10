from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsItem,
    QGraphicsRectItem,
    QGraphicsObject,
    QGraphicsScene,
    QGraphicsView,
    QComboBox,
    QLineEdit,
)

from ios_label_printer.models import LOCK_STATUS_OPTIONS, DeviceInfo, LabelElement, LabelTemplate

HANDLE_SIZE = 8


class ResizeHandle(QGraphicsRectItem):
    def __init__(self, parent: "ElementItem") -> None:
        super().__init__(0, 0, HANDLE_SIZE, HANDLE_SIZE, parent)
        self.setBrush(QBrush(QColor("#2563eb")))
        self.setPen(QPen(Qt.NoPen))
        self.setCursor(Qt.SizeFDiagCursor)
        self.setFlag(QGraphicsItem.ItemIsMovable, False)
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        self.setZValue(10)

    def mousePressEvent(self, event) -> None:
        parent = self.parentItem()
        if isinstance(parent, ElementItem):
            parent._set_interacting(True)
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        parent = self.parentItem()
        if isinstance(parent, ElementItem):
            parent.resize_to_scene(event.scenePos())
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        parent = self.parentItem()
        if isinstance(parent, ElementItem):
            parent._set_interacting(False)
        event.accept()


class ElementItem(QGraphicsObject):
    def __init__(self, element: LabelElement, scale: float, device: DeviceInfo) -> None:
        super().__init__()
        self.element = element
        self.scale = scale
        self.device = device
        self._pixmap = QPixmap()
        self.handle = ResizeHandle(self)
        self.setFlags(
            QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.SizeAllCursor)
        self._press_pos: QPointF | None = None
        self.sync_from_element()

    def _canvas(self) -> "LabelCanvas | None":
        if self.scene() and self.scene().views():
            view = self.scene().views()[0]
            if isinstance(view, LabelCanvas):
                return view
        return None

    def _set_interacting(self, value: bool) -> None:
        canvas = self._canvas()
        if canvas:
            canvas.set_interacting(value)

    def mousePressEvent(self, event) -> None:
        self._press_pos = event.scenePos()
        self._set_interacting(True)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        moved = False
        if self._press_pos is not None:
            moved = (event.scenePos() - self._press_pos).manhattanLength() >= 8
        self._press_pos = None
        self._set_interacting(False)
        if not moved and self.element.is_lock_status():
            canvas = self._canvas()
            if canvas:
                canvas.start_lock_status_edit(self)

    def mouseDoubleClickEvent(self, event) -> None:
        canvas = self._canvas()
        if canvas and self.element.is_custom():
            canvas.start_text_edit(self)
            event.accept()
            return
        if canvas and self.element.is_qr():
            canvas.qrEditRequested.emit(self.element)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self.element.width_mm * self.scale, self.element.height_mm * self.scale)

    def sync_from_element(self) -> None:
        self.prepareGeometryChange()
        self.setPos(self.element.x_mm * self.scale, self.element.y_mm * self.scale)
        self._update_handle()
        self.update()

    def _update_handle(self) -> None:
        rect = self.boundingRect()
        self.handle.setPos(rect.right() - HANDLE_SIZE, rect.bottom() - HANDLE_SIZE)
        self.handle.setVisible(self.isSelected())

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemSelectedChange:
            self.handle.setVisible(bool(value))
        if change == QGraphicsItem.ItemPositionChange and self.scene():
            pos: QPointF = value
            scene_rect = self.scene().sceneRect()
            width = self.boundingRect().width()
            height = self.boundingRect().height()
            pos.setX(min(max(pos.x(), 0), max(0, scene_rect.width() - width)))
            pos.setY(min(max(pos.y(), 0), max(0, scene_rect.height() - height)))
            return pos
        if change == QGraphicsItem.ItemPositionHasChanged:
            self._write_geometry()
            canvas = self._canvas()
            if canvas:
                canvas.notify_geometry_changed()
        return super().itemChange(change, value)

    def _write_geometry(self) -> None:
        self.element.x_mm = round(self.pos().x() / self.scale, 3)
        self.element.y_mm = round(self.pos().y() / self.scale, 3)

    def resize_to_scene(self, scene_pos: QPointF) -> None:
        local = self.mapFromScene(scene_pos)
        min_size = 2.0 * self.scale
        width = max(min_size, local.x())
        height = max(min_size, local.y())
        scene_rect = self.scene().sceneRect() if self.scene() else QRectF()
        width = min(width, scene_rect.width() - self.pos().x())
        height = min(height, scene_rect.height() - self.pos().y())
        self.element.width_mm = round(width / self.scale, 3)
        self.element.height_mm = round(height / self.scale, 3)
        self.prepareGeometryChange()
        self._update_handle()
        self.update()
        canvas = self._canvas()
        if canvas:
            canvas.notify_geometry_changed()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        rect = self.boundingRect()
        painter.setRenderHint(QPainter.Antialiasing, True)
        if self.isSelected():
            painter.setPen(QPen(QColor("#2563eb"), 1.4, Qt.DashLine))
        else:
            painter.setPen(QPen(QColor(0, 0, 0, 40), 1))
        painter.setBrush(QBrush(QColor(255, 255, 255, 0)))
        painter.drawRect(rect.adjusted(0.5, 0.5, -0.5, -0.5))

        if self.element.type == "qr" or self.element.field == "qr_payload":
            if not self._pixmap.isNull():
                painter.drawPixmap(rect.toRect(), self._pixmap)
            else:
                painter.fillRect(rect.adjusted(2, 2, -2, -2), QColor("#111"))
                painter.setPen(QColor("#fff"))
                painter.drawText(rect, Qt.AlignCenter, "QR")
            return

        font = QFont(self.element.font_family)
        font.setBold(self.element.bold)
        font.setPointSizeF(max(5.0, self.element.font_size_pt * (self.scale / 4.0)))
        painter.setFont(font)
        text = self.element.display_text(self.device)
        if not text and (self.element.is_custom() or self.element.is_lock_status()):
            painter.setPen(QColor(0, 0, 0, 110))
            placeholder = "Lock Status" if self.element.is_lock_status() else "Text"
            painter.drawText(rect.adjusted(2, 1, -2, -1), Qt.AlignLeft | Qt.AlignVCenter, placeholder)
            return
        painter.setPen(QColor(self.element.color))
        align = Qt.AlignLeft | Qt.AlignVCenter
        if self.element.align == "center":
            align = Qt.AlignCenter
        elif self.element.align == "right":
            align = Qt.AlignRight | Qt.AlignVCenter
        painter.drawText(rect.adjusted(2, 1, -2, -1), align, self.element.display_text(self.device))


class LabelCanvas(QGraphicsView):
    geometryChanged = Signal()
    selectionChanged = Signal(object)
    fieldDropped = Signal(str, float, float)
    qrEditRequested = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.template = LabelTemplate()
        self.device = DeviceInfo.sample()
        self.scale_px = 12.0
        self._items: dict[str, ElementItem] = {}
        self._updating = False
        self._fitting = False
        self._interacting = False
        self._text_editor: QLineEdit | None = None
        self._choice_editor: QComboBox | None = None
        self._edit_item: ElementItem | None = None
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setBackgroundBrush(QBrush(QColor("#cfd6e0")))
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.AnchorViewCenter)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.scene().selectionChanged.connect(self._emit_selection)

    def set_interacting(self, value: bool) -> None:
        if self._interacting == value:
            return
        self._interacting = value
        if not value:
            self.notify_geometry_changed()

    def notify_geometry_changed(self) -> None:
        if not self._updating and not self._interacting:
            self.geometryChanged.emit()

    def set_document(self, template: LabelTemplate, device: DeviceInfo, scale_px: float | None = None) -> None:
        self.template = template
        self.device = device
        if scale_px:
            self.scale_px = scale_px
        self.rebuild()

    def refresh_device(self, device: DeviceInfo) -> None:
        self.device = device
        for item in self._items.values():
            item.device = device
            if item.element.type == "qr" or item.element.field == "qr_payload":
                item._pixmap = self._qr_pixmap(item.element)
            item.update()

    def rebuild(self) -> None:
        self._finish_text_edit()
        self._finish_choice_edit()
        self._updating = True
        selected_id = None
        items = self.scene().selectedItems()
        if items and isinstance(items[0], ElementItem):
            selected_id = items[0].element.id
        self.scene().clear()
        self._items.clear()
        width = self.template.width_mm * self.scale_px
        height = self.template.height_mm * self.scale_px
        self.scene().setSceneRect(0, 0, width, height)
        paper = QGraphicsRectItem(0, 0, width, height)
        paper.setBrush(QBrush(QColor(self.template.background)))
        paper.setPen(QPen(QColor("#111"), 1))
        paper.setZValue(-2)
        paper.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self.scene().addItem(paper)

        m = self.template.margin_mm
        margin = QGraphicsRectItem(
            m.left * self.scale_px,
            m.top * self.scale_px,
            max(1, (self.template.width_mm - m.left - m.right) * self.scale_px),
            max(1, (self.template.height_mm - m.top - m.bottom) * self.scale_px),
        )
        margin.setPen(QPen(QColor("#94a3b8"), 1, Qt.DashLine))
        margin.setBrush(QBrush(Qt.NoBrush))
        margin.setZValue(-1)
        margin.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self.scene().addItem(margin)

        for element in self.template.elements:
            if not element.visible:
                continue
            item = ElementItem(element, self.scale_px, self.device)
            if element.type == "qr" or element.field == "qr_payload":
                item._pixmap = self._qr_pixmap(element)
            self.scene().addItem(item)
            self._items[element.id] = item
            if element.id == selected_id:
                item.setSelected(True)
        self._updating = False
        self._fit_scene()

    def update_element(self, element: LabelElement) -> None:
        item = self._items.get(element.id)
        if item is None:
            self.rebuild()
            return
        if element.type == "qr" or element.field == "qr_payload":
            item._pixmap = self._qr_pixmap(element)
        item.sync_from_element()

    def _fit_scene(self) -> None:
        if self._fitting or self._interacting or not self.scene():
            return
        rect = self.scene().sceneRect()
        if rect.isEmpty() or self.viewport().size().width() < 2:
            return
        self._fitting = True
        try:
            self.resetTransform()
            self.fitInView(rect, Qt.KeepAspectRatio)
        finally:
            self._fitting = False

    def _qr_pixmap(self, element: LabelElement) -> QPixmap:
        from io import BytesIO
        from PySide6.QtGui import QImage

        from ios_label_printer.renderer import render_qr_image
        from ios_label_printer.units import mm_to_px

        size = min(mm_to_px(element.width_mm, 300), mm_to_px(element.height_mm, 300))
        payload = element.build_qr_payload(self.device, self.template)
        image = render_qr_image(payload, size)
        buf = BytesIO()
        image.save(buf, format="PNG")
        qimage = QImage.fromData(buf.getvalue(), "PNG")
        return QPixmap.fromImage(qimage)

    def _emit_selection(self) -> None:
        items = [item for item in self.scene().selectedItems() if isinstance(item, ElementItem)]
        self.selectionChanged.emit(items[0].element if items else None)

    def selected_element(self) -> LabelElement | None:
        items = [item for item in self.scene().selectedItems() if isinstance(item, ElementItem)]
        return items[0].element if items else None

    def select_field(self, field_name: str) -> None:
        if field_name == "custom":
            return
        for item in self._items.values():
            item.setSelected(item.element.field == field_name)

    def select_id(self, element_id: str) -> None:
        for item in self._items.values():
            item.setSelected(item.element.id == element_id)

    def start_text_edit(self, item: ElementItem) -> None:
        self._finish_text_edit()
        self._edit_item = item
        scene_rect = item.mapToScene(item.boundingRect()).boundingRect()
        view_rect = self.mapFromScene(scene_rect).boundingRect()
        editor = QLineEdit(self.viewport())
        editor.setGeometry(view_rect.adjusted(0, 0, 0, 4))
        editor.setText(item.element.text)
        editor.setPlaceholderText("Type custom text")
        editor.setFrame(True)
        editor.selectAll()
        editor.editingFinished.connect(self._finish_text_edit)
        self._text_editor = editor
        editor.show()
        editor.setFocus(Qt.MouseFocusReason)

    def _finish_text_edit(self) -> None:
        editor = self._text_editor
        item = self._edit_item
        if editor is None:
            return
        self._text_editor = None
        self._edit_item = None
        text = editor.text()
        editor.hide()
        editor.deleteLater()
        if item is not None:
            item.element.text = text
            item.update()
            self.notify_geometry_changed()

    def start_lock_status_edit(self, item: ElementItem) -> None:
        self._finish_text_edit()
        self._finish_choice_edit()
        self._edit_item = item
        scene_rect = item.mapToScene(item.boundingRect()).boundingRect()
        view_rect = self.mapFromScene(scene_rect).boundingRect()
        combo = QComboBox(self.viewport())
        combo.addItems(LOCK_STATUS_OPTIONS)
        combo.setPlaceholderText("Lock Status")
        combo.setGeometry(view_rect.adjusted(0, 0, 8, 6))
        if item.element.text in LOCK_STATUS_OPTIONS:
            combo.setCurrentText(item.element.text)
        else:
            combo.setCurrentIndex(-1)
        combo.activated.connect(self._finish_choice_edit)
        self._choice_editor = combo
        combo.show()
        combo.setFocus(Qt.MouseFocusReason)
        combo.showPopup()

    def _finish_choice_edit(self, *_args) -> None:
        editor = self._choice_editor
        item = self._edit_item
        if editor is None:
            return
        self._choice_editor = None
        text = editor.currentText() if editor.currentIndex() >= 0 else ""
        editor.hide()
        editor.deleteLater()
        self._edit_item = None
        if item is not None and text:
            item.element.text = text
            item.update()
            self.notify_geometry_changed()

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        field = event.mimeData().text().strip()
        if not field:
            return
        scene_pos = self.mapToScene(event.position().toPoint())
        x_mm = scene_pos.x() / self.scale_px
        y_mm = scene_pos.y() / self.scale_px
        self.fieldDropped.emit(field, x_mm, y_mm)
        event.acceptProposedAction()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not self._interacting:
            self._fit_scene()

    def keyPressEvent(self, event) -> None:
        step = 1.0 if event.modifiers() & Qt.ShiftModifier else 0.1
        dx = dy = 0.0
        if event.key() == Qt.Key_Left:
            dx = -step
        elif event.key() == Qt.Key_Right:
            dx = step
        elif event.key() == Qt.Key_Up:
            dy = -step
        elif event.key() == Qt.Key_Down:
            dy = step
        elif event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            if self._text_editor or self._choice_editor:
                return
            element = self.selected_element()
            if element:
                if element.is_custom():
                    self.template.elements = [item for item in self.template.elements if item.id != element.id]
                else:
                    element.visible = False
                self.rebuild()
                self.geometryChanged.emit()
            return
        else:
            super().keyPressEvent(event)
            return
        element = self.selected_element()
        if not element:
            return
        element.x_mm = round(max(0, element.x_mm + dx), 3)
        element.y_mm = round(max(0, element.y_mm + dy), 3)
        item = self._items.get(element.id)
        if item:
            item.sync_from_element()
        self.geometryChanged.emit()
