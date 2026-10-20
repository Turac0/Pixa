"""Printing: each page is rendered at the printer's resolution and placed on the paper."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtPrintSupport import QPrinter

from pixa.document import PdfDocument, PdfError
from pixa.i18n import tr
from pixa.ui.page_view import pixmap_to_qimage

MAX_DPI = 300  # sharp on paper, while a page stays a manageable image
PREVIEW_DPI = 150  # the preview is drawn on screen: sharp enough zoomed in, quick to draw


class Sizing(Enum):
    FIT = "fit"  # scaled up or down to fill the printable area
    ACTUAL = "actual"  # true size, cut off at the edges if it doesn't fit
    SHRINK = "shrink"  # true size, but pages too big for the paper are scaled down
    CUSTOM = "custom"  # true size times ``Layout.scale`` percent


@dataclass
class Layout:
    """How pages are placed on the paper."""

    sizing: Sizing = Sizing.FIT
    scale: int = 100  # percent, for Sizing.CUSTOM
    auto_rotate: bool = True  # turn pages whose orientation differs from the paper's
    grayscale: bool = False


def page_scale(layout: Layout, page: tuple[float, float], area: tuple[float, float],
               dots_per_point: float) -> float:
    """Device pixels per PDF point for a page of ``page`` points in an ``area`` of pixels."""
    fit = min(area[0] / page[0], area[1] / page[1])
    if layout.sizing is Sizing.FIT:
        return fit
    if layout.sizing is Sizing.SHRINK:
        return min(fit, dots_per_point)
    if layout.sizing is Sizing.CUSTOM:
        return dots_per_point * layout.scale / 100
    return dots_per_point


def print_pages(doc: PdfDocument, printer: QPrinter, pages: Sequence[int],
                progress: Callable[[int, int], None] | None = None,
                dpi: int | None = None, layout: Layout | None = None) -> None:
    """Print pages (in the given order) on a printer that has been set up.

    ``dpi`` is the resolution the pages are rendered at (the printer's, up to
    ``MAX_DPI``, by default).

    With ``layout.auto_rotate`` a landscape page on portrait paper (or the other
    way round) is turned to match the paper. Every page is centred in the
    printable area and sized as ``layout.sizing`` says (fitted by default).
    """
    if not pages:
        return
    layout = layout or Layout()
    painter = QPainter()
    if not painter.begin(printer):
        raise PdfError(tr("Could not start printing. Check the printer and try again."))
    try:
        dpi = dpi or min(printer.resolution(), MAX_DPI)
        for n, index in enumerate(pages):
            if n and not printer.newPage():
                raise PdfError(tr("The printer stopped accepting pages."))
            if progress is not None:
                progress(n, len(pages))
            area = QRectF(painter.viewport())
            width, height = doc.page_size(index)
            turn = (layout.auto_rotate and width != height
                    and (width > height) != (area.width() > area.height()))
            image = pixmap_to_qimage(doc.render(index, dpi / 72))
            if layout.grayscale:
                image = image.convertToFormat(QImage.Format.Format_Grayscale8)
            w, h = (height, width) if turn else (width, height)
            scale = page_scale(layout, (w, h), (area.width(), area.height()),
                               printer.resolution() / 72)
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.setClipRect(area)
            painter.translate(area.center())
            if turn:
                painter.rotate(90)
            target = QRectF(-width * scale / 2, -height * scale / 2, width * scale,
                            height * scale)
            painter.drawImage(target, image)
            painter.restore()
    finally:
        painter.end()


def copies(pages: Sequence[int], printer: QPrinter) -> list[int]:
    """The pages to send, with copies and page order applied where the printer
    doesn't do that itself."""
    order = list(pages)
    if printer.pageOrder() == QPrinter.PageOrder.LastPageFirst:
        order.reverse()
    count = printer.copyCount()
    if count <= 1 or printer.supportsMultipleCopies():
        return order
    if printer.collateCopies():
        return order * count
    return [p for p in order for _ in range(count)]


def parse_pages(text: str, count: int) -> list[int]:
    """Page indexes for a range like "1-3, 5, 8-" (page numbers start at 1).

    "-4" means pages 1 to 4 and "8-" page 8 to the end. Raises ValueError for
    anything else, or a page outside 1..count.
    """
    pages: list[int] = []
    parts = [part.strip() for part in text.split(",")]
    if not any(parts):
        raise ValueError("No pages given")
    for part in parts:
        if not part:
            continue
        match = re.fullmatch(r"(\d*)\s*[-–]\s*(\d*)|(\d+)", part)
        if not match:
            raise ValueError(f"Not a page range: {part}")
        if match.group(3):
            first = last = int(match.group(3))
        else:
            if not match.group(1) and not match.group(2):
                raise ValueError(f"Not a page range: {part}")
            first = int(match.group(1) or 1)
            last = int(match.group(2) or count)
        if not 1 <= first <= last <= count:
            raise ValueError(f"Pages must be between 1 and {count}")
        pages.extend(range(first - 1, last))
    return pages
