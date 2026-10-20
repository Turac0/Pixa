"""The print dialog: printer, pages, sizing, two-sided and orientation, with a live preview.

Pixa's own dialog rather than the system's,
so the same choices and a preview are there on every platform. The printer
driver's own settings are one click away under Properties (Windows).
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QLocale, QSettings, Qt, QTimer
from PySide6.QtGui import QPageLayout, QPageSize
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo, QPrintPreviewWidget
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from pixa.document import PdfDocument, PdfError
from pixa.i18n import tr
from pixa.ui import printing, theme, widgets, winprint
from pixa.ui.printing import Layout, Sizing

PDF = ""  # printer combo data for "Save as PDF file"
COMMON_PAPER = (QPageSize.PageSizeId.A4, QPageSize.PageSizeId.Letter, QPageSize.PageSizeId.Legal,
                QPageSize.PageSizeId.A3, QPageSize.PageSizeId.A5)
MM_PER_POINT = 25.4 / 72


class PrintDialog(QDialog):
    """Ask how to print ``doc``. After it is accepted, ``pages()`` and ``print_layout()``
    say what to print and ``apply_to(printer)`` sets a printer up for it."""

    def __init__(self, doc: PdfDocument, current_page: int, selected_pages: Sequence[int],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Print"))
        self.doc = doc
        self.current_page = current_page
        self.selected_pages = list(selected_pages)
        self.pdf_path = ""
        self._papers: list[QPageSize] = []

        # ---- printer, copies, colour
        self.printer_combo = QComboBox()
        self.printer_combo.setMinimumWidth(260)
        for name in QPrinterInfo.availablePrinterNames():
            self.printer_combo.addItem(name, name)
        self.printer_combo.addItem(tr("Save as PDF file"), PDF)
        self.properties_button = QPushButton(tr("Properties…"))
        self.properties_button.setToolTip(tr("The printer's own settings"))
        self.properties_button.clicked.connect(self._show_properties)
        self.properties_button.setVisible(winprint.available())
        self.copies = QSpinBox()
        self.copies.setRange(1, 999)
        self.copies.setFixedWidth(64)
        self.collate = QCheckBox(tr("Collate"))
        self.collate.setChecked(True)
        self.collate.setEnabled(False)
        self.copies.valueChanged.connect(lambda n: self.collate.setEnabled(n > 1))
        self.grayscale = QCheckBox(tr("Print in grayscale (black and white)"))

        top = QGridLayout()
        top.setHorizontalSpacing(10)
        top.setVerticalSpacing(10)
        top.addWidget(QLabel(tr("Printer:")), 0, 0)
        top.addWidget(self.printer_combo, 0, 1)
        top.addWidget(self.properties_button, 0, 2)
        top.setColumnStretch(3, 1)
        copies_row = QHBoxLayout()
        copies_row.addLayout(widgets.stepper(self.copies, (tr("Fewer copies"), tr("More copies"))))
        copies_row.addSpacing(10)
        copies_row.addWidget(self.collate)
        copies_row.addSpacing(16)
        copies_row.addWidget(self.grayscale)
        copies_row.addStretch(1)
        top.addWidget(QLabel(tr("Copies:")), 1, 0)
        top.addLayout(copies_row, 1, 1, 1, 3)

        # ---- pages
        count = doc.page_count
        self.all_pages = QRadioButton(tr("All"))
        self.current = QRadioButton(tr("Current page ({page})", page=current_page + 1))
        self.selection = QRadioButton(tr("Selected pages ({count})",
                                          count=len(self.selected_pages)))
        self.selection.setVisible(len(self.selected_pages) > 1)
        self.range = QRadioButton(tr("Pages:"))
        self.range_text = QLineEdit(f"1-{count}" if count > 1 else "1")
        self.range_text.setPlaceholderText(tr("e.g. 1-3, 5"))
        self.range_text.textEdited.connect(lambda _: self.range.setChecked(True))
        self.range_hint = QLabel()
        self.range_hint.setWordWrap(True)
        self.range_hint.setProperty("role", "hint")
        self.range_hint.hide()
        self.page_buttons = QButtonGroup(self)
        for button in (self.all_pages, self.current, self.selection, self.range):
            self.page_buttons.addButton(button)
        (self.selection if len(self.selected_pages) > 1 else self.all_pages).setChecked(True)
        pages_box = QGroupBox(tr("Pages to print").upper())
        grid = QGridLayout(pages_box)
        grid.addWidget(self.all_pages, 0, 0)
        grid.addWidget(self.current, 0, 1)
        grid.addWidget(self.selection, 0, 2)
        grid.addWidget(self.range, 1, 0)
        grid.addWidget(self.range_text, 1, 1, 1, 2)
        grid.addWidget(self.range_hint, 2, 0, 1, 3)

        # ---- sizing
        self.fit = QRadioButton(tr("Fit to paper"))
        self.actual = QRadioButton(tr("Actual size"))
        self.shrink = QRadioButton(tr("Shrink oversized pages"))
        self.custom = QRadioButton(tr("Custom scale:"))
        self.scale = QSpinBox()
        self.scale.setRange(10, 400)
        self.scale.setValue(100)
        self.scale.setSuffix(" %")
        self.scale.setSingleStep(5)
        self.scale.setFixedWidth(72)
        self.scale.valueChanged.connect(lambda _: self.custom.setChecked(True))
        self.sizing_buttons = QButtonGroup(self)
        for button, sizing in ((self.fit, Sizing.FIT), (self.actual, Sizing.ACTUAL),
                               (self.shrink, Sizing.SHRINK), (self.custom, Sizing.CUSTOM)):
            button.setProperty("sizing", sizing.value)
            self.sizing_buttons.addButton(button)
        self.fit.setChecked(True)
        self.paper = QComboBox()
        sizing_box = QGroupBox(tr("Page sizing").upper())
        grid = QGridLayout(sizing_box)
        grid.addWidget(self.fit, 0, 0)
        grid.addWidget(self.actual, 0, 1)
        grid.addWidget(self.shrink, 1, 0)
        scale_row = QHBoxLayout()
        scale_row.addWidget(self.custom)
        scale_row.addLayout(widgets.stepper(self.scale, (tr("Smaller"), tr("Larger"))))
        scale_row.addStretch(1)
        grid.addLayout(scale_row, 1, 1)
        paper_row = QHBoxLayout()
        paper_row.addWidget(QLabel(tr("Paper:")))
        paper_row.addWidget(self.paper, 1)
        grid.addLayout(paper_row, 2, 0, 1, 2)

        # ---- two-sided and orientation
        self.duplex = QCheckBox(tr("Print on both sides of the paper"))
        self.long_edge = QRadioButton(tr("Flip on long edge"))
        self.short_edge = QRadioButton(tr("Flip on short edge"))
        self.long_edge.setChecked(True)
        edges = QButtonGroup(self)
        edges.addButton(self.long_edge)
        edges.addButton(self.short_edge)
        self.duplex.toggled.connect(self._update_duplex)
        self.auto = QRadioButton(tr("Auto"))
        self.portrait = QRadioButton(tr("Portrait"))
        self.landscape = QRadioButton(tr("Landscape"))
        self.auto.setChecked(True)
        self.auto.setToolTip(tr("Paper turned to suit the pages; pages that don't suit it "
                                 "are turned"))
        orientations = QButtonGroup(self)
        for button in (self.auto, self.portrait, self.landscape):
            orientations.addButton(button)
        sides_box = QGroupBox(tr("Two-sided and orientation").upper())
        grid = QGridLayout(sides_box)
        grid.addWidget(self.duplex, 0, 0, 1, 3)
        grid.addWidget(self.long_edge, 1, 0)
        grid.addWidget(self.short_edge, 1, 1)
        grid.addWidget(QLabel(tr("Orientation:")), 2, 0, 1, 3)
        grid.addWidget(self.auto, 3, 0)
        grid.addWidget(self.portrait, 3, 1)
        grid.addWidget(self.landscape, 3, 2)

        left = QVBoxLayout()
        left.addWidget(pages_box)
        left.addWidget(sizing_box)
        left.addWidget(sides_box)
        left.addStretch(1)

        # ---- preview
        self.doc_size = QLabel()
        self.doc_size.setObjectName("PreviewInfo")
        self.paper_size = QLabel()
        self.paper_size.setObjectName("PreviewInfo")
        self.preview_printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        self.preview = QPrintPreviewWidget(self.preview_printer, self)
        self.preview.setMinimumSize(320, 360)
        self.preview.setViewMode(QPrintPreviewWidget.ViewMode.SinglePageView)
        widgets.theme_preview(self.preview, theme.current().canvas)
        preview_frame = QFrame()
        preview_frame.setObjectName("PreviewFrame")
        frame_layout = QVBoxLayout(preview_frame)
        frame_layout.setContentsMargins(1, 1, 1, 1)
        frame_layout.addWidget(self.preview)
        self.preview.paintRequested.connect(self._paint)
        self.preview.previewChanged.connect(self._update_page_label)
        self.previous = widgets.icon_button("chevron-left", tr("Previous page"))
        self.previous.clicked.connect(lambda: self._step(-1))
        self.next = widgets.icon_button("chevron-right", tr("Next page"))
        self.next.clicked.connect(lambda: self._step(1))
        self.page_label = QLabel()
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_label.setMinimumWidth(110)
        nav = QHBoxLayout()
        nav.addWidget(self.previous)
        nav.addWidget(self.page_label, 1)
        nav.addWidget(self.next)
        info = QHBoxLayout()
        info.addWidget(self.doc_size)
        info.addStretch(1)
        info.addWidget(self.paper_size)
        right = QVBoxLayout()
        right.setSpacing(8)
        right.setContentsMargins(0, 24, 0, 0)  # level with the first box, below its title
        right.addLayout(info)
        right.addWidget(preview_frame, 1)
        right.addLayout(nav)

        body = QHBoxLayout()
        body.setSpacing(20)
        body.addLayout(left, 0)
        body.addLayout(right, 1)

        # ---- buttons
        self.print_button = QPushButton(tr("Print"))
        self.print_button.setProperty("primary", True)
        self.print_button.setDefault(True)
        self.print_button.clicked.connect(self.accept)
        cancel = QPushButton(tr("Cancel"))
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(self.print_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        layout.addLayout(top)
        layout.addLayout(body, 1)
        layout.addLayout(buttons)
        self.resize(1000, 700)

        # The preview is drawn again shortly after a change, not on every keystroke.
        self._refresh = QTimer(self)
        self._refresh.setSingleShot(True)
        self._refresh.setInterval(150)
        self._refresh.timeout.connect(self._update_preview)
        for button in (self.page_buttons, self.sizing_buttons, orientations, edges):
            button.buttonToggled.connect(self._changed)
        for signal in (self.range_text.textChanged, self.scale.valueChanged,
                       self.paper.currentIndexChanged, self.grayscale.toggled,
                       self.duplex.toggled):
            signal.connect(self._changed)
        self.printer_combo.currentIndexChanged.connect(self._printer_changed)

        last = QSettings().value("print/printer", "", str)
        index = self.printer_combo.findData(last) if last else -1
        if index < 0:
            index = self.printer_combo.findData(QPrinterInfo.defaultPrinterName())
        self.printer_combo.setCurrentIndex(max(index, 0))
        self._printer_changed()

    # ------------------------------------------------------------ choices
    def printer_name(self) -> str:
        """The chosen printer, or "" for a PDF file."""
        return self.printer_combo.currentData() or PDF

    def pages(self) -> list[int]:
        """Page indexes to print, in order; empty if the range isn't valid."""
        if self.current.isChecked():
            return [self.current_page]
        if self.selection.isChecked():
            return list(self.selected_pages)
        if self.range.isChecked():
            try:
                return printing.parse_pages(self.range_text.text(), self.doc.page_count)
            except ValueError:
                return []
        return list(range(self.doc.page_count))

    def print_layout(self) -> Layout:
        sizing = Sizing(self.sizing_buttons.checkedButton().property("sizing"))
        return Layout(sizing=sizing, scale=self.scale.value(), auto_rotate=self.auto.isChecked(),
                      grayscale=self.grayscale.isChecked())

    def page_size(self) -> QPageSize:
        index = self.paper.currentIndex()
        return self._papers[index] if 0 <= index < len(self._papers) else QPageSize(
            QPageSize.PageSizeId.A4)

    def orientation(self) -> QPageLayout.Orientation:
        """The paper's orientation; with Auto, the first page's."""
        if self.landscape.isChecked():
            return QPageLayout.Orientation.Landscape
        if self.auto.isChecked():
            pages = self.pages()
            if pages:
                width, height = self.doc.page_size(pages[0])
                if width > height:
                    return QPageLayout.Orientation.Landscape
        return QPageLayout.Orientation.Portrait

    def duplex_mode(self) -> QPrinter.DuplexMode:
        if not (self.duplex.isEnabled() and self.duplex.isChecked()):
            return QPrinter.DuplexMode.DuplexNone
        return (QPrinter.DuplexMode.DuplexShortSide if self.short_edge.isChecked()
                else QPrinter.DuplexMode.DuplexLongSide)

    def apply_to(self, printer: QPrinter, preview: bool = False) -> None:
        """Set ``printer`` up as chosen. The printer name goes first: changing
        it resets the other settings."""
        name = self.printer_name()
        if name:
            if (printer.printerName() != name
                    or printer.outputFormat() != QPrinter.OutputFormat.NativeFormat):
                printer.setPrinterName(name)
        else:
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            if not preview:
                printer.setOutputFileName(self.pdf_path)
        printer.setPageSize(self.page_size())
        printer.setPageOrientation(self.orientation())
        if preview:
            return
        printer.setDuplex(self.duplex_mode())
        printer.setCopyCount(self.copies.value())
        printer.setCollateCopies(self.collate.isChecked())
        printer.setColorMode(QPrinter.ColorMode.GrayScale if self.grayscale.isChecked()
                             else QPrinter.ColorMode.Color)

    # ------------------------------------------------------------ printer
    def _printer_changed(self) -> None:
        name = self.printer_name()
        info = QPrinterInfo.printerInfo(name) if name else None
        if info is not None and info.isNull():
            info = None
        sizes = list(info.supportedPageSizes()) if info is not None else []
        default = info.defaultPageSize() if info is not None else None
        if not sizes:
            sizes = [QPageSize(size) for size in COMMON_PAPER]
        if default is None or not default.isValid():
            us = QLocale().measurementSystem() == QLocale.MeasurementSystem.ImperialUSSystem
            default = QPageSize(QPageSize.PageSizeId.Letter if us else QPageSize.PageSizeId.A4)
        current = self.page_size() if self._papers else default
        self._papers = sizes
        self.paper.blockSignals(True)
        self.paper.clear()
        self.paper.addItems([size.name() for size in sizes])
        self._select_paper(current) or self._select_paper(default) or self.paper.setCurrentIndex(0)
        self.paper.blockSignals(False)

        modes = info.supportedDuplexModes() if info is not None else []
        self.duplex.setEnabled(QPrinter.DuplexMode.DuplexLongSide in modes
                               or QPrinter.DuplexMode.DuplexAuto in modes)
        self.duplex.setToolTip("" if self.duplex.isEnabled()
                               else tr("This printer can't print on both sides"))
        self._update_duplex()
        self.properties_button.setEnabled(bool(name))
        self._changed()

    def _select_paper(self, size: QPageSize) -> bool:
        for i, paper in enumerate(self._papers):
            if paper.isEquivalentTo(size):
                self.paper.setCurrentIndex(i)
                return True
        return False

    def _update_duplex(self) -> None:
        on = self.duplex.isEnabled() and self.duplex.isChecked()
        self.long_edge.setEnabled(on)
        self.short_edge.setEnabled(on)

    def _show_properties(self) -> None:
        """The driver's own window; what it changes that this dialog shows comes back here."""
        name = self.printer_name()
        if not name:
            return
        duplex = {QPrinter.DuplexMode.DuplexLongSide: winprint.DMDUP_VERTICAL,
                  QPrinter.DuplexMode.DuplexShortSide: winprint.DMDUP_HORIZONTAL}
        current = winprint.DriverSettings(
            paper=self.page_size().windowsId() or None,
            landscape=self.orientation() == QPageLayout.Orientation.Landscape,
            copies=self.copies.value(), collate=self.collate.isChecked(),
            duplex=duplex.get(self.duplex_mode(), winprint.DMDUP_SIMPLEX),
            color=not self.grayscale.isChecked())
        chosen = winprint.show_properties(int(self.winId()), name, current)
        if chosen is not None:
            self.set_driver_settings(chosen)

    def set_driver_settings(self, s: winprint.DriverSettings) -> None:
        """Show settings that came back from the printer's Properties window."""
        if s.paper:
            size = QPageSize(QPageSize.id(s.paper))
            if size.isValid() and not self._select_paper(size):
                self._papers.append(size)
                self.paper.addItem(size.name())
                self.paper.setCurrentIndex(len(self._papers) - 1)
        if s.landscape != (self.orientation() == QPageLayout.Orientation.Landscape):
            (self.landscape if s.landscape else self.portrait).setChecked(True)
        self.copies.setValue(s.copies)
        self.collate.setChecked(s.collate)
        if self.duplex.isEnabled():
            self.duplex.setChecked(s.duplex != winprint.DMDUP_SIMPLEX)
            (self.short_edge if s.duplex == winprint.DMDUP_HORIZONTAL
             else self.long_edge).setChecked(True)
        self.grayscale.setChecked(not s.color)

    # ------------------------------------------------------------ preview
    def _changed(self, *_) -> None:
        valid = bool(self.pages())
        self.print_button.setEnabled(valid)
        count = self.doc.page_count
        self.range_hint.setText("" if valid or not self.range.isChecked() else
                                tr("Type page numbers and ranges between 1 and {count}, "
                                   "e.g. 1-3, 5", count=count))
        self.range_hint.setVisible(bool(self.range_hint.text()))
        self._refresh.start()

    def _update_preview(self) -> None:
        self.apply_to(self.preview_printer, preview=True)
        size = self.page_size().size(QPageSize.Unit.Millimeter)
        if self.orientation() == QPageLayout.Orientation.Landscape:
            size.transpose()
        self.paper_size.setText(tr("Paper: {name}, {width} × {height} mm",
                                   name=self.page_size().name(),
                                   width=f"{size.width():.0f}", height=f"{size.height():.0f}"))
        self.preview.updatePreview()
        self.preview.fitInView()

    def _paint(self, printer: QPrinter) -> None:
        try:
            printing.print_pages(self.doc, printer, self.pages(), dpi=printing.PREVIEW_DPI,
                                 layout=self.print_layout())
        except PdfError:
            pass  # nothing to show; printing itself reports the error

    def page_count(self) -> int:
        return self.preview.pageCount()

    def _step(self, by: int) -> None:
        page = self.preview.currentPage() + by
        self.preview.setCurrentPage(min(max(page, 1), self.preview.pageCount()))
        self._update_page_label()

    def _update_page_label(self) -> None:
        count = self.preview.pageCount()
        page = min(max(self.preview.currentPage(), 1), max(count, 1))
        self.page_label.setText(tr("Page {page} of {count}", page=page, count=count)
                                if count else tr("No pages"))
        self.previous.setEnabled(page > 1)
        self.next.setEnabled(page < count)
        pages = self.pages()
        if count and page <= len(pages):
            width, height = self.doc.page_size(pages[page - 1])
            self.doc_size.setText(tr("Document: {width} × {height} mm",
                                     width=f"{width * MM_PER_POINT:.1f}",
                                     height=f"{height * MM_PER_POINT:.1f}"))
        else:
            self.doc_size.setText("")

    # ------------------------------------------------------------ finish
    def ask_pdf_path(self) -> str:
        path, _ = QFileDialog.getSaveFileName(self, tr("Save as PDF"), "",
                                              tr("PDF documents (*.pdf)"))
        if path and not path.lower().endswith(".pdf"):
            path += ".pdf"
        return path

    def accept(self) -> None:
        if not self.pages():
            return
        if not self.printer_name():
            self.pdf_path = self.ask_pdf_path()
            if not self.pdf_path:
                return
        QSettings().setValue("print/printer", self.printer_name())
        super().accept()
