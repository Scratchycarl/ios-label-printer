from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ios_label_printer.models import QR_FIELD_CHOICES

CHIP_STYLE = """
QPushButton {
    border: none;
    background: transparent;
    color: #111111;
    text-align: left;
    padding: 4px 10px;
    font-size: 13px;
}
QPushButton:hover {
    color: #0a7ea4;
}
QPushButton:checked {
    color: #0a7ea4;
    font-weight: 600;
}
"""


class QrCustomizeDialog(QDialog):
    def __init__(self, selected_fields: list[str], separator: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Select Items to Add QR Code")
        self.setMinimumWidth(720)
        self.setStyleSheet(
            "QDialog { background: #f3f3f3; color: #111111; }"
            "QLabel { color: #111111; }"
            "QLineEdit { background: #ffffff; color: #111111; }"
        )
        self._order = [key for key in selected_fields if key in dict(QR_FIELD_CHOICES)]
        self._buttons: dict[str, QPushButton] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(10)

        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        columns = 7
        for index, (key, title) in enumerate(QR_FIELD_CHOICES):
            button = QPushButton(title)
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setFlat(True)
            button.setStyleSheet(CHIP_STYLE)
            button.setChecked(key in self._order)
            button.clicked.connect(lambda checked, field=key: self._toggle(field, checked))
            self._buttons[key] = button
            grid.addWidget(button, index // columns, index % columns)
        layout.addWidget(grid_host)

        selected_row = QHBoxLayout()
        selected_caption = QLabel("Selected:")
        selected_caption.setStyleSheet("color: #555555;")
        self.selected_label = QLabel()
        self.selected_label.setWordWrap(True)
        self.selected_label.setStyleSheet("color: #111111;")
        selected_row.addWidget(selected_caption)
        selected_row.addWidget(self.selected_label, 1)
        layout.addLayout(selected_row)

        hint = QLabel("Please enter separator between items, such as: , . / ; space, etc.")
        hint.setStyleSheet("color: #333333;")
        layout.addWidget(hint)
        self.separator_edit = QLineEdit(separator if separator is not None else ",")
        self.separator_edit.setMaximumWidth(220)
        self.separator_edit.textChanged.connect(self._refresh_selected)
        layout.addWidget(self.separator_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons, alignment=Qt.AlignRight)
        self._refresh_selected()

    def _toggle(self, field: str, checked: bool) -> None:
        if checked:
            if field not in self._order:
                self._order.append(field)
        elif field in self._order:
            self._order.remove(field)
        self._refresh_selected()

    def _refresh_selected(self) -> None:
        titles = dict(QR_FIELD_CHOICES)
        separator = self.separator_edit.text()
        self.selected_label.setText(separator.join(titles[key] for key in self._order))

    def selected_fields(self) -> list[str]:
        return list(self._order)

    def separator(self) -> str:
        return self.separator_edit.text()
