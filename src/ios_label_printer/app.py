from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from ios_label_printer.main_window import MainWindow


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    app = QApplication(argv)
    app.setApplicationName("iOS Label Printer")
    app.setOrganizationName("ios-label-printer")
    window = MainWindow()
    window.show()
    return app.exec()
