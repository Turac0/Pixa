"""Sidebar with page thumbnails: drag to reorder, multi-select, context menu."""

from __future__ import annotations

from PySide6.QtCore import QItemSelectionModel, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QDrag, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QStyle,
    QStyledItemDelegate,
)

from pixa.document import PdfDocument
from pixa.i18n import N_, tr
from pixa.ui import dnd
from pixa.ui.page_view import pixmap_to_qimage

THUMB_WIDTH = 132
ORIGINAL_INDEX = Qt.ItemDataRole.UserRole
IMAGE_ROLE = Qt.ItemDataRole.UserRole + 1
HEIGHT_ROLE = Qt.ItemDataRole.UserRole + 2
SIZE_ROLE = Qt.ItemDataRole.UserRole + 3
BATCH = 6


class ThumbnailDelegate(QStyledItemDelegate):
    def __init__(self, parent, accent: QColor) -> None:
        super().__init__(parent)
        self.accent = accent

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(THUMB_WIDTH + 28, int(index.data(HEIGHT_ROLE) or THUMB_WIDTH) + 34)

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        r = option.rect.adjusted(6, 3, -6, -3)
        if selected or hovered:
            fill = QColor(self.accent)
            fill.setAlpha(40 if selected else 16)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(r, 8, 8)
        image: QImage | None = index.data(IMAGE_ROLE)
        w, h = index.data(SIZE_ROLE) or (THUMB_WIDTH, THUMB_WIDTH)
        page = QRect(r.center().x() - w // 2, r.top() + 8, w, h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 30))
        painter.drawRect(page.adjusted(-1, 0, 1, 2))
        if image is not None and not image.isNull():
            painter.drawImage(page, image)
        else:
            painter.fillRect(page, Qt.GlobalColor.white)
        if selected:
            pen = QPen(self.accent, 2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(page.adjusted(-1, -1, 1, 1))
        painter.setPen(option.palette.text().color() if selected
                       else option.palette.placeholderText().color())
        label_rect = QRect(r.left(), page.bottom() + 4, r.width(), 20)
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, index.data())
        painter.restore()


class ThumbnailList(QListWidget):
    """Page thumbnails. Dragging them reorders the pages; dropped elsewhere (also on
    another Pixa window) they are copied there. PDF and image files and pages from
    other windows can be dropped between them."""

    pageActivated = Signal(int)  # noqa: N815
    orderChanged = Signal(list)  # noqa: N815
    contextAction = Signal(str)  # noqa: N815
    dropped = Signal(object, int)  # dnd.Dropped, the page index to insert at  # noqa: N815

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Thumbnails")
        self.setViewMode(QListView.ViewMode.ListMode)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDropIndicatorShown(False)  # drawn by paintEvent
        self.source_id = dnd.new_source_id()
        self._drop_row: int | None = None
        self.setMouseTracking(True)
        self.setUniformItemSizes(False)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFixedWidth(THUMB_WIDTH + 48)
        self.delegate = ThumbnailDelegate(self, QColor("#4f6bed"))
        self.setItemDelegate(self.delegate)
        self.doc: PdfDocument | None = None
        self._pending: list[int] = []
        self._timer = QTimer(self)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._render_batch)
        self._syncing = False
        self.itemClicked.connect(self._clicked)
        self.currentRowChanged.connect(self._row_changed)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    def set_accent(self, color: str) -> None:
        self.delegate.accent = QColor(color)
        self.viewport().update()

    def set_document(self, doc: PdfDocument | None) -> None:
        self.doc = doc
        self.rebuild()

    def rebuild(self, keep_row: int | None = None) -> None:
        self._timer.stop()
        row = self.currentRow() if keep_row is None else keep_row
        self._syncing = True
        self.clear()
        if not self.doc:
            self._syncing = False
            return
        for i in range(self.doc.page_count):
            w, h = self.doc.page_size(i)
            zoom = self._thumb_zoom(i)
            item = QListWidgetItem(str(i + 1))
            item.setData(ORIGINAL_INDEX, i)
            item.setData(HEIGHT_ROLE, round(h * zoom))
            item.setData(SIZE_ROLE, (round(w * zoom), round(h * zoom)))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsDragEnabled)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDropEnabled)
            self.addItem(item)
        if self.count():
            self.setCurrentRow(max(0, min(row, self.count() - 1)))
        self._syncing = False
        self._pending = list(range(self.doc.page_count))
        self._timer.start()

    def _thumb_zoom(self, index: int) -> float:
        w, h = self.doc.page_size(index)
        # Landscape pages fit the width, portrait pages fit a square-ish box.
        return THUMB_WIDTH / w if w >= h else THUMB_WIDTH / h

    def _render_batch(self) -> None:
        if not self.doc:
            self._timer.stop()
            return
        dpr = self.devicePixelRatioF()
        for _ in range(BATCH):
            if not self._pending:
                self._timer.stop()
                return
            i = self._pending.pop(0)
            if i >= self.count() or i >= self.doc.page_count:
                continue
            image = pixmap_to_qimage(self.doc.render(i, self._thumb_zoom(i) * dpr))
            image.setDevicePixelRatio(dpr)
            self.item(i).setData(IMAGE_ROLE, image)

    def refresh_page(self, index: int) -> None:
        if index not in self._pending:
            self._pending.insert(0, index)
        self._timer.start()

    def refresh_all(self) -> None:
        self._pending = list(range(self.count()))
        self._timer.start()

    # ------------------------------------------------------------ selection
    def selected_pages(self) -> list[int]:
        rows = sorted(self.row(item) for item in self.selectedItems())
        return rows or ([self.currentRow()] if self.currentRow() >= 0 else [])

    def set_current_page(self, index: int) -> None:
        if index == self.currentRow() or not (0 <= index < self.count()):
            return
        self._syncing = True
        if self.item(index).isSelected():  # keep a selection of several pages
            self.setCurrentRow(index, QItemSelectionModel.SelectionFlag.NoUpdate)
        else:
            self.setCurrentRow(index)
        self.scrollToItem(self.item(index))
        self._syncing = False

    def _clicked(self, item: QListWidgetItem) -> None:
        self.pageActivated.emit(self.row(item))

    def _row_changed(self, row: int) -> None:
        if not self._syncing and row >= 0:
            self.pageActivated.emit(row)

    # --------------------------------------------------------------- drag
    def startDrag(self, actions) -> None:  # noqa: N802
        pages = self.selected_pages()
        if not self.doc or not pages:
            return
        drag = QDrag(self)
        drag.setMimeData(dnd.pages_mime(self.doc.pages_pdf(pages), self.source_id))
        image = self.item(pages[0]).data(IMAGE_ROLE)
        if isinstance(image, QImage) and not image.isNull():
            pixmap = QPixmap.fromImage(image).scaledToWidth(
                round(THUMB_WIDTH * 0.6 * image.devicePixelRatio()),
                Qt.TransformationMode.SmoothTransformation)
            pixmap.setDevicePixelRatio(image.devicePixelRatio())
            drag.setPixmap(pixmap)
            drag.setHotSpot(QPoint(12, 12))
        # Here the pages move; in another window they are copied.
        drag.exec(Qt.DropAction.MoveAction | Qt.DropAction.CopyAction,
                  Qt.DropAction.MoveAction)

    def _accepts(self, event) -> dnd.Dropped | None:
        data = dnd.read(event.mimeData())
        if self.doc is None or not (data.pages or data.pdfs):
            return None  # images and drops without a document: the window takes them
        return data

    def _row_at(self, pos: QPoint) -> int:
        """Where pages dropped at ``pos`` go: before the page under it, or after it
        when over its lower half."""
        item = self.itemAt(pos)
        if item is None:
            return self.count() if pos.y() > 0 else 0
        row = self.row(item)
        rect = self.visualItemRect(item)
        return row + 1 if pos.y() > rect.center().y() else row

    def _show_drop(self, event) -> bool:
        data = self._accepts(event)
        if data is None:
            self._set_drop_row(None)
            event.ignore()
            return False
        self._set_drop_row(self._row_at(event.position().toPoint()))
        event.setDropAction(Qt.DropAction.MoveAction if data.from_list(self.source_id)
                            else Qt.DropAction.CopyAction)
        event.accept()
        return True

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        super().dragEnterEvent(event)  # starts auto scrolling
        self._show_drop(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        super().dragMoveEvent(event)
        self._show_drop(event)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        super().dragLeaveEvent(event)
        self._set_drop_row(None)

    def dropEvent(self, event) -> None:  # noqa: N802
        self.stopAutoScroll()
        self.setState(QAbstractItemView.State.NoState)
        data = self._accepts(event)
        self._set_drop_row(None)
        if data is None:
            event.ignore()
            return
        row = self._row_at(event.position().toPoint())
        if data.from_list(self.source_id):
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
            moving = self.selected_pages()
            rest = [r for r in range(self.count()) if r not in moving]
            at = sum(1 for r in rest if r < row)
            order = rest[:at] + moving + rest[at:]
            if order != list(range(len(order))):
                # Defer: handling the change rebuilds this list, which must not
                # happen while Qt is still inside its drop handling.
                QTimer.singleShot(0, lambda: self.orderChanged.emit(order))
            return
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        QTimer.singleShot(0, lambda: self.dropped.emit(data, row))

    def _set_drop_row(self, row: int | None) -> None:
        if row != self._drop_row:
            self._drop_row = row
            self.viewport().update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self._drop_row is None or not self.count():
            return
        if self._drop_row < self.count():
            y = self.visualItemRect(self.item(self._drop_row)).top()
        else:
            y = self.visualItemRect(self.item(self.count() - 1)).bottom()
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(self.delegate.accent, 3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(14, y, self.viewport().width() - 14, y)
        painter.end()

    def _menu(self, pos) -> None:
        item = self.itemAt(pos)
        if item is None:
            return
        if not item.isSelected():
            self.setCurrentItem(item)
        menu = QMenu(self)
        entries = [
            ("rotate_left", N_("Rotate left")),
            ("rotate_right", N_("Rotate right")),
            None,
            ("move_up", N_("Move up")),
            ("move_down", N_("Move down")),
            None,
            ("insert_blank", N_("Insert blank page after")),
            ("insert_pdf", N_("Insert pages from PDF…")),
            None,
            ("delete", N_("Delete page(s)")),
        ]
        for entry in entries:
            if entry is None:
                menu.addSeparator()
                continue
            key, label = entry
            menu.addAction(tr(label), lambda k=key: self.contextAction.emit(k))
        menu.exec(self.viewport().mapToGlobal(pos))
