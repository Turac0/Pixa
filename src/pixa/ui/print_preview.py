"""Print preview: the pages as they will print, with zoom, page and orientation controls.

Made from Qt's preview *widget* rather than ``QPrintPreviewDialog``: with
PySide6 the dialog crashes as soon as anything is connected to its
``paintRequested`` signal.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtPrintSupport import QPrinter, QPrintPreviewWidget
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from pixa.i18n import tr
from pixa.ui import icons, theme, widgets


class PrintPreview(QDialog):
    """``paint(printer)`` draws every page on the printer it is given (and is called
    again whenever the paper or orientation changes). The Print button closes the
    preview and emits ``printRequested``."""

    printRequested = Signal()  # noqa: N815

    def __init__(self, paint: Callable[[QPrinter], None], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Print preview"))
        self.resize(1000, 780)
        self.printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        self.preview = QPrintPreviewWidget(self.printer, self)
        self.preview.paintRequested.connect(paint)

        bar = QToolBar()
        bar.setMovable(False)
        bar.setIconSize(QSize(18, 18))
        self.actions_by_name: dict[str, QAction] = {}

        color = theme.current().text

        def act(name: str, text: str, slot, tip: str, checkable: bool = False,
                icon: str = "") -> QAction:
            action = QAction(text, self)
            if icon:
                action.setIcon(icons.icon(icon, color))
            action.setToolTip(tip)
            action.setCheckable(checkable)
            action.triggered.connect(slot)
            self.actions_by_name[name] = action
            return action

        orientation = QActionGroup(self)
        portrait = act("portrait", tr("Portrait"), self.preview.setPortraitOrientation,
                       tr("Portrait paper"), checkable=True)
        landscape = act("landscape", tr("Landscape"), self.preview.setLandscapeOrientation,
                        tr("Landscape paper"), checkable=True)
        for action in (portrait, landscape):
            orientation.addAction(action)
        portrait.setChecked(True)
        self.all_pages = act("all_pages", tr("All pages"), self._set_all_pages,
                             tr("Show all pages side by side"), checkable=True)
        for action in (
            act("fit_width", tr("Fit width"), self.preview.fitToWidth,
                tr("Fit the page to the width")),
            act("fit_page", tr("Fit page"), self.preview.fitInView, tr("Show a whole page")),
            act("zoom_out", tr("Zoom out"), self.preview.zoomOut, tr("Zoom out"), icon="zoom-out"),
            act("zoom_in", tr("Zoom in"), self.preview.zoomIn, tr("Zoom in"), icon="zoom-in"),
        ):
            bar.addAction(action)
        bar.addSeparator()
        bar.addAction(self.actions_by_name["portrait"])
        bar.addAction(self.actions_by_name["landscape"])
        bar.addSeparator()
        bar.addAction(act("previous", tr("Previous"), self._previous, tr("Previous page"),
                          icon="chevron-left"))
        self.page_label = QLabel()
        self.page_label.setMinimumWidth(110)
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bar.addWidget(self.page_label)
        bar.addAction(act("next", tr("Next"), self._next, tr("Next page"),
                          icon="chevron-right"))
        bar.addSeparator()
        bar.addAction(self.all_pages)

        self.print_button = QPushButton(tr("Print…"))
        self.print_button.setProperty("primary", True)
        self.print_button.setDefault(True)
        self.print_button.clicked.connect(self._print)
        close = QPushButton(tr("Close"))
        close.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.setContentsMargins(16, 12, 16, 12)
        row.addStretch(1)
        row.addWidget(close)
        row.addWidget(self.print_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(bar)
        layout.addWidget(self.preview, 1)
        layout.addLayout(row)
        widgets.theme_preview(self.preview, theme.current().canvas)

        self.preview.previewChanged.connect(self._update_page_label)
        self._timer = QTimer(self)  # the page shown changes as the preview is scrolled
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._update_page_label)
        self._timer.start()
        QTimer.singleShot(0, self.preview.fitToWidth)

    # ------------------------------------------------------------------ pages
    def page_count(self) -> int:
        return self.preview.pageCount()

    def _update_page_label(self) -> None:
        count = self.preview.pageCount()
        page = min(max(self.preview.currentPage(), 1), max(count, 1))
        self.page_label.setText(tr("Page {page} of {count}", page=page, count=count)
                                if count else "")
        self.actions_by_name["previous"].setEnabled(page > 1)
        self.actions_by_name["next"].setEnabled(page < count)

    def _previous(self) -> None:
        self.preview.setCurrentPage(max(1, self.preview.currentPage() - 1))
        self._update_page_label()

    def _next(self) -> None:
        self.preview.setCurrentPage(min(self.preview.pageCount(), self.preview.currentPage() + 1))
        self._update_page_label()

    def _set_all_pages(self, on: bool) -> None:
        self.preview.setViewMode(QPrintPreviewWidget.ViewMode.AllPagesView if on
                                 else QPrintPreviewWidget.ViewMode.SinglePageView)
        if on:
            self.preview.fitInView()
        else:
            self.preview.fitToWidth()

    def _print(self) -> None:
        self.accept()
        self.printRequested.emit()
