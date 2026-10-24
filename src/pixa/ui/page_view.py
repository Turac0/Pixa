"""The central page canvas: continuous scrolling, zoom, and the editing tools."""

from __future__ import annotations

import math
from collections import OrderedDict
from enum import Enum

import pymupdf as fitz
from PySide6.QtCore import (
    QEvent,
    QLineF,
    QPoint,
    QPointF,
    QRectF,
    QSize,
    QSizeF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QFont,
    QFontDatabase,
    QFontMetrics,
    QImage,
    QImageReader,
    QKeyEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsPolygonItem,
    QGraphicsProxyWidget,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QPlainTextEdit,
    QStyleOptionGraphicsItem,
    QWidget,
)

from pixa.document import (
    LAYER_MOVES,
    BoxStyle,
    ImageGeometry,
    ImageInfo,
    Markup,
    PdfDocument,
    PdfError,
    TextBlock,
    TextLine,
    TextStyle,
    image_size,
)
from pixa.i18n import N_, ntr, tr
from pixa.ui import dnd

PAGE_GAP = 24.0
MIN_ZOOM, MAX_ZOOM = 0.25, 6.0
CACHE_SIZE = 16

QT_FONT_FAMILIES = {
    "helv": ("Helvetica", ["Arial", "Liberation Sans", "DejaVu Sans"], QFont.StyleHint.SansSerif),
    "tiro": ("Times New Roman", ["Times", "Liberation Serif", "DejaVu Serif"],
             QFont.StyleHint.Serif),
    "cour": ("Courier New", ["Courier", "Liberation Mono", "DejaVu Sans Mono"],
             QFont.StyleHint.Monospace),
}


def is_inside(widget: QWidget | None, object_name: str) -> bool:
    """True if ``widget`` or one of its parents has this object name."""
    while widget is not None:
        if widget.objectName() == object_name:
            return True
        widget = widget.parentWidget()
    return False


class Tool(Enum):
    SELECT = "select"
    EDIT_TEXT = "edit_text"
    ADD_TEXT = "add_text"
    ADD_IMAGE = "add_image"
    HIGHLIGHT = "highlight"
    ADD_BOX = "add_box"


_FAMILIES: set[str] | None = None


def _installed_families() -> set[str]:
    global _FAMILIES
    if _FAMILIES is None:
        _FAMILIES = {f.lower() for f in QFontDatabase.families()}
    return _FAMILIES


def qfont_for(style: TextStyle, zoom: float, preview_family: str | None = None) -> QFont:
    """The Qt font for previewing ``style`` while typing.

    ``preview_family`` is a Qt family that renders the real face (installed,
    or registered from the PDF); otherwise the standard stack for its class.
    """
    primary, fallbacks, hint = QT_FONT_FAMILIES[style.family]
    families = [primary, *fallbacks]
    if preview_family is None and style.typeface and \
            style.typeface.lower() in _installed_families():
        preview_family = style.typeface
    if preview_family:
        families.insert(0, preview_family)  # preview in the document's real font
    font = QFont(families[0])
    font.setFamilies(families)
    font.setStyleHint(hint)
    font.setPixelSize(max(1, round(style.size * zoom)))
    weight = style.weight if style.font else (700 if style.bold else 400)
    if style.bold and weight < 600:
        weight = 700
    font.setWeight(QFont.Weight(weight))  # SemiBold is 600, not just "bold"
    font.setItalic(style.italic)
    font.setUnderline(style.underline)
    return font


def fit_image(width: float, height: float, page_w: float, page_h: float) -> tuple[float, float]:
    """The size a new image starts with: its own (a pixel per point), but at most
    half the page wide and 60% of it high."""
    w = min(page_w * 0.5, width)
    h = w * height / width
    if h > page_h * 0.6:
        h = page_h * 0.6
        w = h * width / height
    return w, h


def qcolor(rgb: tuple[float, float, float]) -> QColor:
    return QColor.fromRgbF(*rgb)


def pixmap_to_qimage(pix: fitz.Pixmap) -> QImage:
    image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
    return image.copy()  # detach from the pixmap's buffer


# --------------------------------------------------------------------------- items
class PageItem(QGraphicsItem):
    """A page that renders itself lazily at the view's current zoom."""

    def __init__(self, view: PageView, index: int, size: QSizeF) -> None:
        super().__init__()
        self.view = view
        self.index = index
        self.size = size

    @property
    def page_rect(self) -> QRectF:
        return QRectF(QPointF(0, 0), self.size)

    def boundingRect(self) -> QRectF:  # noqa: N802 (Qt API)
        return self.page_rect.adjusted(-6, -6, 6, 8)

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget=None) -> None:
        rect = self.page_rect
        # Cheap soft shadow: a few translucent outlines.
        painter.setPen(Qt.PenStyle.NoPen)
        for i, alpha in enumerate((10, 14, 20)):
            grow = 3 - i
            painter.setBrush(QColor(0, 0, 0, alpha))
            painter.drawRoundedRect(rect.adjusted(-grow, -grow + 1, grow, grow + 2), 3, 3)
        image = self.view.page_image(self.index)
        if image is None:
            painter.fillRect(rect, Qt.GlobalColor.white)
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(rect, image)


class ImageTransformer(QGraphicsObject):
    """Move / resize / rotate handles around an image (new or already on the page).

    Also used for a selected box: without a pixmap or rotate handle, resizing
    freely (Shift keeps the proportions) and showing the box while it is dragged.

    Geometry is kept in scene coordinates: ``center``, ``width``, ``height``
    and ``angle`` (degrees, clockwise). Drag inside to move, drag a corner to
    resize (aspect ratio kept; Shift for free), drag the round handle above
    the top edge to rotate (snaps to 15°; Shift for free). ``changed`` fires
    when a drag ends.
    """

    changed = Signal()
    HANDLE = 9.0
    ROTATE_GAP = 26.0
    SNAP = 15.0

    def __init__(self, pixmap: QPixmap | None, center: QPointF, width: float, height: float,
                 angle: float, accent: QColor, flipped: bool = False,
                 dashed: bool = False, rotatable: bool = True,
                 keep_aspect: bool = True) -> None:
        super().__init__()
        self.pixmap = pixmap
        self.rotatable = rotatable
        self.keep_aspect = keep_aspect
        self.preview_pen = QPen(Qt.PenStyle.NoPen)  # the box drawn while dragging
        self.preview_brush = QBrush(Qt.BrushStyle.NoBrush)
        # A hollow box is only grabbed near its border, so what is inside
        # it can still be clicked.
        self.move_band: float | None = None
        self.accent = accent
        self.width, self.height = width, height
        self.flipped = flipped
        self.dashed = dashed
        self.setPos(center)
        self.setRotation(angle)
        self.setZValue(10)
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable)
        self._mode: str | None = None
        self._press: dict = {}

    # ------------------------------------------------------------- geometry
    @property
    def center(self) -> QPointF:
        return self.pos()

    @property
    def angle(self) -> float:
        return self.rotation() % 360

    def local_rect(self) -> QRectF:
        return QRectF(-self.width / 2, -self.height / 2, self.width, self.height)

    def boundingRect(self) -> QRectF:  # noqa: N802
        m = self.HANDLE + 2
        return self.local_rect().adjusted(-m, -m - self.ROTATE_GAP, m, m)

    def _corners(self) -> list[QPointF]:
        r = self.local_rect()
        return [r.topLeft(), r.topRight(), r.bottomRight(), r.bottomLeft()]

    def _rotate_handle(self) -> QPointF:
        return QPointF(0, -self.height / 2 - self.ROTATE_GAP)

    def _hit(self, local: QPointF) -> str | int | None:
        reach = self.HANDLE + 3
        if self.rotatable and QLineF(local, self._rotate_handle()).length() <= reach:
            return "rotate"
        for i, corner in enumerate(self._corners()):
            if QLineF(local, corner).length() <= reach:
                return i
        if self.local_rect().contains(local):
            band = self.move_band
            if band is None or not self.local_rect().adjusted(
                    band, band, -band, -band).contains(local):
                return "move"
        return None

    # -------------------------------------------------------------- painting
    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = self.local_rect()
        painter.save()
        if self.pixmap is not None:
            if self.flipped:
                painter.scale(1, -1)
            painter.setOpacity(0.95)
            painter.drawPixmap(r, self.pixmap, QRectF(self.pixmap.rect()))
        elif self._mode is not None:
            painter.setOpacity(0.85)
            painter.setPen(self.preview_pen)
            painter.setBrush(self.preview_brush)
            painter.drawRect(r)
        painter.restore()
        pen = QPen(self.accent, 1.5, Qt.PenStyle.DashLine if self.dashed else Qt.PenStyle.SolidLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(r)
        if self.rotatable:
            painter.drawLine(QPointF(0, r.top()), self._rotate_handle())
        painter.setPen(QPen(self.accent, 1.5))
        painter.setBrush(Qt.GlobalColor.white)
        h = self.HANDLE
        for corner in self._corners():
            painter.drawRect(QRectF(corner.x() - h / 2, corner.y() - h / 2, h, h))
        if self.rotatable:
            painter.setBrush(self.accent)
            painter.drawEllipse(self._rotate_handle(), h / 2 + 1, h / 2 + 1)

    def hoverMoveEvent(self, event) -> None:  # noqa: N802
        hit = self._hit(event.pos())
        if hit == "rotate":
            cursor = Qt.CursorShape.CrossCursor
        elif isinstance(hit, int):
            # Diagonal arrows, adjusted for the item's own rotation.
            diagonal = (hit + round(self.angle / 90)) % 2
            cursor = Qt.CursorShape.SizeFDiagCursor if diagonal == 0 else \
                Qt.CursorShape.SizeBDiagCursor
        elif hit == "move":
            cursor = Qt.CursorShape.SizeAllCursor
        else:
            cursor = Qt.CursorShape.ArrowCursor
        self.setCursor(cursor)

    # ------------------------------------------------------------- dragging
    def mousePressEvent(self, event) -> None:  # noqa: N802
        hit = self._hit(event.pos())
        if hit is None:
            event.ignore()
            return
        self._mode = hit
        self._press = {
            "scene": event.scenePos(), "center": QPointF(self.pos()), "angle": self.rotation(),
            "w": self.width, "h": self.height,
        }
        if isinstance(hit, int):
            # The corner opposite the dragged one stays put.
            self._press["fixed"] = self.mapToScene(self._corners()[(hit + 2) % 4])
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._mode is None:
            return
        press = self._press
        free = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if self._mode == "move":
            self.setPos(press["center"] + (event.scenePos() - press["scene"]))
        elif self._mode == "rotate":
            v = event.scenePos() - self.pos()
            angle = math.degrees(math.atan2(v.y(), v.x())) + 90
            if not free:
                angle = round(angle / self.SNAP) * self.SNAP
            self.setRotation(angle % 360)
        else:
            self._resize(event.scenePos(), free)
        self.update()

    def _resize(self, scene_pos: QPointF, free: bool) -> None:
        press = self._press
        fixed = press["fixed"]
        rad = math.radians(press["angle"])
        cos, sin = math.cos(rad), math.sin(rad)
        v = scene_pos - fixed
        # The fixed->mouse vector in the item's own (unrotated) axes.
        lx, ly = v.x() * cos + v.y() * sin, -v.x() * sin + v.y() * cos
        w0, h0 = press["w"], press["h"]
        corner = self._mode
        sx = 1 if corner in (1, 2) else -1  # direction from fixed corner to dragged one
        sy = 1 if corner in (2, 3) else -1
        w, h = max(8.0, lx * sx), max(8.0, ly * sy)
        if self.keep_aspect != free:  # Shift switches between free and proportional
            scale = max(w / w0, h / h0)
            w, h = max(8.0, w0 * scale), max(8.0, h0 * scale)
        self.prepareGeometryChange()
        self.width, self.height = w, h
        # New centre: halfway from the fixed corner along the item's axes.
        cx, cy = sx * w / 2, sy * h / 2
        self.setPos(fixed + QPointF(cx * cos - cy * sin, cx * sin + cy * cos))

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        mode, press = self._mode, self._press
        self._mode = None
        if mode is None:
            return
        self.update()
        moved = (
            (self.pos() - press["center"]).manhattanLength() > 0.5
            or abs(self.rotation() - press["angle"]) > 0.01
            or abs(self.width - press["w"]) > 0.5
            or abs(self.height - press["h"]) > 0.5
        )
        if moved:
            self.changed.emit()


class InlineEditor(QPlainTextEdit):
    """Text box overlaid on the page. Enter adds a line, Ctrl+Enter commits, Esc cancels.

    Clicking outside it commits too (the view handles clicks on the canvas).
    """

    committed = Signal(str)
    cancelled = Signal()

    def __init__(self, text: str, font: QFont, color: QColor, accent: QColor) -> None:
        super().__init__()
        self.accent = accent
        self.setObjectName("InlineEditor")
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.document().setDocumentMargin(1)
        self._done = False
        self.min_width = 60
        self.set_look(font, color)
        self.setPlainText(text)
        self.selectAll()
        self.textChanged.connect(self._fit)
        self._fit()

    def set_look(self, font: QFont, color: QColor) -> None:
        self.setFont(font)
        # Keep the text readable: light text gets a dark backdrop and vice versa.
        bg = "rgba(20, 22, 28, 0.92)" if color.lightnessF() > 0.6 else "rgba(255, 255, 255, 0.96)"
        family = font.families()[0] if font.families() else font.family()
        self.setStyleSheet(
            f"QPlainTextEdit {{ color: {color.name()}; background: {bg};"
            f" border: 2px solid {self.accent.name()}; border-radius: 4px; padding: 0;"
            f" font-family: '{family}'; font-size: {font.pixelSize()}px;"
            f" font-weight: {int(font.weight())};"
            f" font-style: {'italic' if font.italic() else 'normal'};"
            f" text-decoration: {'underline' if font.underline() else 'none'}; }}"
        )
        self.setFont(font)
        self._fit()

    def _fit(self) -> None:
        self.ensurePolished()
        fm = QFontMetrics(self.font())
        lines = self.toPlainText().split("\n") or [""]
        width = max(fm.horizontalAdvance(ln) for ln in lines) + fm.averageCharWidth() * 2 + 8
        height = fm.lineSpacing() * len(lines) + 10
        self.setFixedSize(max(self.min_width, width), height)
        proxy = self.graphicsProxyWidget()
        if proxy is not None:  # the proxy keeps its own size limits; sync them
            size = QSizeF(self.size())
            proxy.setMinimumSize(size)
            proxy.setMaximumSize(size)
            proxy.resize(size)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and (
            event.modifiers() & Qt.KeyboardModifier.ControlModifier  # Cmd on macOS
        ):
            self.commit()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.cancel()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802
        super().focusOutEvent(event)
        QTimer.singleShot(0, self._commit_if_focus_moved)

    def _commit_if_focus_moved(self) -> None:
        """Commit only when the user moved on to another control in Pixa.

        Focus also "leaves" when the window is deactivated (focus-follows-mouse,
        a notification, alt-tab), a dialog or popup opens, or the user changes
        the font, size or colour in the right-hand pane; none of those should
        end editing. Clicks elsewhere on the canvas are handled by the view.
        """
        if self._done or self.hasFocus():
            return
        focus = QApplication.focusWidget()
        if (
            focus is None
            or QApplication.activeModalWidget() is not None
            or QApplication.activePopupWidget() is not None
        ):
            return
        proxy = self.graphicsProxyWidget()
        canvas = proxy.scene().views() if proxy is not None and proxy.scene() else []
        if focus in canvas or is_inside(focus, "Inspector"):
            return
        self.commit()

    def commit(self) -> None:
        if not self._done:
            self._done = True
            self.committed.emit(self.toPlainText())

    def cancel(self) -> None:
        if not self._done:
            self._done = True
            self.cancelled.emit()


# ---------------------------------------------------------------------------- view
class PageView(QGraphicsView):
    currentPageChanged = Signal(int)  # noqa: N815
    zoomChanged = Signal(float)  # noqa: N815
    # ImageInfo | TextBlock | Markup | None, or a list when several are selected
    selectionChanged = Signal(object)  # noqa: N815
    editingChanged = Signal(object)  # TextStyle | None while an inline editor is open  # noqa: N815
    placementChanged = Signal(bool)  # noqa: N815
    # Files or pages dropped on the pages: (dnd.Dropped, page index, display point)
    dropped = Signal(object, int, object)
    contextMenuWanted = Signal(QPoint)  # noqa: N815 - right click with the Select tool
    message = Signal(str)
    error = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PageView")
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.RenderHint.Antialiasing
                            | QPainter.RenderHint.SmoothPixmapTransform)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.own_pages_source = ""  # pages dragged from this window's sidebar aren't taken
        self.doc: PdfDocument | None = None
        self.zoom = 1.0
        self.fit_width = True
        self.tool = Tool.SELECT
        self.text_style = TextStyle()
        self.highlight_color: tuple[float, float, float] = (1.0, 0.92, 0.3)
        self.box_style = BoxStyle()
        self.accent = QColor("#4f6bed")
        self.pages: list[PageItem] = []
        self._cache: OrderedDict[tuple[int, float, int], QImage] = OrderedDict()
        self._lines_cache: dict[tuple[int, int], list[TextLine]] = {}
        self._current = 0
        self._jumping = False
        self._registered_fonts: dict[str, str | None] = {}  # face label -> Qt family
        self._hover = QGraphicsRectItem()
        self._hover.setZValue(5)
        self._hover.setPen(QPen(Qt.PenStyle.NoPen))
        self._hover.hide()
        self._selection_box = QGraphicsRectItem()
        self._selection_box.setZValue(6)
        self._selection_box.hide()
        # ``selected`` is the one selected element; with several, it is None and
        # ``selection`` lists them (each outlined by one of ``_multi_boxes``).
        self.selected: ImageInfo | TextBlock | Markup | None = None
        self.selection: list[ImageInfo | TextBlock | Markup] = []
        self._multi_boxes: list[QGraphicsRectItem] = []
        self._band: dict | None = None  # rubber band being dragged to select
        self._blocks_cache: dict[tuple[int, int], list[TextBlock]] = {}
        self._drag: dict | None = None  # in-progress text box / box drag
        self._draw: dict | None = None  # highlight or box being drawn
        self._editor_proxy: QGraphicsProxyWidget | None = None
        self._editor: InlineEditor | None = None
        self._editing_line: TextLine | None = None
        self._editing_page = 0
        self._editing_point: fitz.Point | None = None
        # Move/resize/rotate handles: for placing a new image ("place") or for
        # the selected image on the page ("edit").
        self._transformer: ImageTransformer | None = None
        self._transformer_mode = ""
        self._placement_source: str | bytes | None = None
        self._veil: QGraphicsPolygonItem | None = None
        # Pinch zoom scales the view at once and renders the pages anew when
        # the fingers rest, so it stays smooth.
        self._pinch_zoom: float | None = None
        self._pinch_anchor = QPointF()
        self._pinch_timer = QTimer(self)
        self._pinch_timer.setSingleShot(True)
        self._pinch_timer.setInterval(180)
        self._pinch_timer.timeout.connect(self._finish_pinch)
        self.verticalScrollBar().valueChanged.connect(self._update_current)

    # ---------------------------------------------------------------- setup
    def set_accent(self, color: str) -> None:
        self.accent = QColor(color)
        fill = QColor(self.accent)
        fill.setAlpha(40)
        self._hover.setBrush(QBrush(fill))
        pen = QPen(self.accent, 2)
        pen.setCosmetic(True)
        self._selection_box.setPen(pen)
        sel_fill = QColor(self.accent)
        sel_fill.setAlpha(28)
        self._selection_box.setBrush(sel_fill)

    def set_document(self, doc: PdfDocument | None) -> None:
        self.cancel_interactions()
        self.doc = doc
        self._registered_fonts = {}
        self._current = 0
        self.fit_width = True
        self.rebuild()
        self.verticalScrollBar().setValue(0)

    def rebuild(self) -> None:
        """Re-layout all pages (after the document changed or zoom changed)."""
        old_page, old_frac = self._scroll_anchor()
        self._cache.clear()
        self._lines_cache.clear()
        self._blocks_cache.clear()
        self._drag = None
        self._draw = None
        self._band = None
        self._multi_boxes = []  # the scene deletes them below
        self._drop_transformer()
        scene = self.scene()
        for item in (self._hover, self._selection_box):
            if item.scene():
                scene.removeItem(item)
        scene.clear()
        self.pages = []
        if not self.doc:
            return
        if self.fit_width:
            self.zoom = self._fit_zoom()
        widest = max(self.doc.page_size(i)[0] for i in range(self.doc.page_count)) * self.zoom
        y = PAGE_GAP
        for i in range(self.doc.page_count):
            w, h = self.doc.page_size(i)
            item = PageItem(self, i, QSizeF(w * self.zoom, h * self.zoom))
            item.setPos((widest - w * self.zoom) / 2, y)
            scene.addItem(item)
            self.pages.append(item)
            y += h * self.zoom + PAGE_GAP
        scene.addItem(self._hover)
        scene.addItem(self._selection_box)
        self._hover.hide()
        self._selection_box.hide()
        self.selected = None
        self.selection = []
        self.selectionChanged.emit(None)
        scene.setSceneRect(QRectF(-PAGE_GAP, 0, widest + 2 * PAGE_GAP, y))
        self._restore_anchor(old_page, old_frac)
        self.zoomChanged.emit(self.zoom)

    def _scroll_anchor(self) -> tuple[int, float]:
        if not self.pages:
            return 0, 0.0
        index = min(self._current, len(self.pages) - 1)
        item = self.pages[index]
        top = self.mapToScene(0, 0).y()
        frac = (top - item.pos().y()) / max(item.size.height(), 1)
        return index, frac

    def _restore_anchor(self, index: int, frac: float) -> None:
        if not self.pages:
            return
        item = self.pages[min(index, len(self.pages) - 1)]
        y = item.pos().y() + frac * item.size.height()
        self.verticalScrollBar().setValue(round(y))

    def _fit_zoom(self) -> float:
        if not self.doc or not self.doc.page_count:
            return 1.0
        # Fit the typical page, so one landscape page doesn't shrink everything.
        widths = sorted(self.doc.page_size(i)[0] for i in range(self.doc.page_count))
        typical = widths[len(widths) // 2]
        avail = self.viewport().width() - 2 * PAGE_GAP - 4
        return max(MIN_ZOOM, min(MAX_ZOOM, avail / typical))

    def refresh_pages(self) -> None:
        """Re-render without re-layout (content changed but sizes didn't)."""
        self._cache.clear()
        self._lines_cache.clear()
        self._blocks_cache.clear()
        self.viewport().update()
        for item in self.pages:
            item.update()

    # ---------------------------------------------------------------- render
    def page_image(self, index: int) -> QImage | None:
        if not self.doc or index >= self.doc.page_count:
            return None
        dpr = self.devicePixelRatioF()
        key = (index, round(self.zoom * dpr, 4), self.doc.revision)
        image = self._cache.get(key)
        if image is None:
            image = pixmap_to_qimage(self.doc.render(index, self.zoom * dpr))
            image.setDevicePixelRatio(dpr)
            self._cache[key] = image
            while len(self._cache) > CACHE_SIZE:
                self._cache.popitem(last=False)
        else:
            self._cache.move_to_end(key)
        return image

    def _blocks(self, index: int) -> list[TextBlock]:
        """The text boxes the Select tool picks: one per line, like the Edit text tool."""
        key = (index, self.doc.revision)
        if key not in self._blocks_cache:
            self._blocks_cache[key] = self.doc.line_blocks(index)
        return self._blocks_cache[key]

    def _block_at(self, index: int, pt: fitz.Point) -> TextBlock | None:
        hits = [b for b in self._blocks(index) if pt in b.bbox]
        return min(hits, key=lambda b: b.bbox.get_area()) if hits else None

    def _lines(self, index: int) -> list[TextLine]:
        key = (index, self.doc.revision)
        if key not in self._lines_cache:
            self._lines_cache[key] = self.doc.text_lines(index)
        return self._lines_cache[key]

    # ------------------------------------------------------------------ zoom
    def set_zoom(self, zoom: float, fit: bool = False, anchor: QPointF | None = None) -> None:
        """Zoom so that the point under ``anchor`` (viewport coordinates; by default
        the middle of the view) stays where it is."""
        self.fit_width = fit
        new = max(MIN_ZOOM, min(MAX_ZOOM, zoom))
        if abs(new - self.zoom) < 1e-4 and not fit and self._pinch_zoom is None:
            return
        self.cancel_interactions()
        if anchor is None:
            anchor = QPointF(self.viewport().rect().center())
        spot = self._page_spot(self.mapToScene(anchor.toPoint()))
        self._pinch_timer.stop()
        self._pinch_zoom = None
        self.resetTransform()
        self.zoom = new
        self.rebuild()
        if spot is not None:
            index, x, y = spot
            target = self.pages[index].pos() + QPointF(x * self.zoom, y * self.zoom)
            off = self.mapFromScene(target) - anchor.toPoint()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + off.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() + off.y())

    def _page_spot(self, scene_pos: QPointF) -> tuple[int, float, float] | None:
        """The closest page and the point (in display points) a scene position is at."""
        if not self.pages:
            return None
        item = min(self.pages, key=lambda it: 0 if it.mapRectToScene(it.page_rect).contains(
            scene_pos) else abs(it.mapRectToScene(it.page_rect).center().y() - scene_pos.y()))
        local = scene_pos - item.pos()
        return item.index, local.x() / self.zoom, local.y() / self.zoom

    @property
    def shown_zoom(self) -> float:
        """The zoom as seen, also while a pinch is under way."""
        return self._pinch_zoom if self._pinch_zoom is not None else self.zoom

    def zoom_in(self) -> None:
        self.set_zoom(self.shown_zoom * 1.2)

    def zoom_out(self) -> None:
        self.set_zoom(self.shown_zoom / 1.2)

    def _pinch(self, factor: float, anchor: QPointF) -> None:
        """Zoom by ``factor`` around ``anchor`` by scaling the view; the pages are
        rendered at the new zoom once the gesture pauses."""
        if not self.pages or factor <= 0:
            return
        new = max(MIN_ZOOM, min(MAX_ZOOM, self.shown_zoom * factor))
        if abs(new - self.shown_zoom) < 1e-4:
            return
        before = self.mapToScene(anchor.toPoint())
        self._pinch_zoom = new
        self._pinch_anchor = QPointF(anchor)
        self.setTransform(QTransform.fromScale(new / self.zoom, new / self.zoom))
        off = self.mapFromScene(before) - anchor.toPoint()
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + off.x())
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() + off.y())
        self.zoomChanged.emit(new)
        self._pinch_timer.start()

    def _finish_pinch(self) -> None:
        if self._pinch_zoom is not None:
            self.set_zoom(self._pinch_zoom, anchor=self._pinch_anchor)

    def zoom_fit(self) -> None:
        self.set_zoom(self._fit_zoom(), fit=True)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.fit_width and self.doc and not self.is_placing and self._editor is None:
            new = self._fit_zoom()
            if abs(new - self.zoom) > 0.01:
                self.zoom = new
                self.rebuild()

    def wheelEvent(self, event) -> None:  # noqa: N802
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            # Ctrl+wheel, and pinching on touchpads that send it that way (Windows).
            delta = event.angleDelta().y()
            if delta:
                factor = 1.2 ** (delta / 120)
                if event.pixelDelta().isNull() and abs(delta) % 120 == 0:
                    self.set_zoom(self.shown_zoom * factor, anchor=event.position())
                else:  # small steps from a touchpad or a smooth wheel
                    self._pinch(factor, event.position())
            event.accept()
            return
        pixels = event.pixelDelta()
        if not pixels.isNull():
            # Two-finger scrolling: Qt would only scroll along the main direction.
            h, v = self.horizontalScrollBar(), self.verticalScrollBar()
            h.setValue(h.value() - pixels.x())
            v.setValue(v.value() - pixels.y())
            event.accept()
            return
        super().wheelEvent(event)

    def _gesture(self, event, receiver: QWidget) -> bool:
        """Pinch to zoom on touchpads with native gestures (macOS, Wayland)."""
        if event.type() != QEvent.Type.NativeGesture:
            return False
        kind = event.gestureType()
        if kind == Qt.NativeGestureType.ZoomNativeGesture:
            pos = event.position()
            if receiver is not self.viewport():
                pos = QPointF(self.viewport().mapFrom(receiver, pos.toPoint()))
            self._pinch(1 + event.value(), pos)
            event.accept()  # or Qt hands it on to the view as well
            return True
        if kind == Qt.NativeGestureType.EndNativeGesture and self._pinch_zoom is not None:
            self._finish_pinch()
            event.accept()
            return True
        return False

    def viewportEvent(self, event) -> bool:  # noqa: N802
        return self._gesture(event, self.viewport()) or super().viewportEvent(event)

    def event(self, event) -> bool:
        return self._gesture(event, self) or super().event(event)

    # ------------------------------------------------------------ navigation
    @property
    def current_page(self) -> int:
        return self._current

    def _update_current(self) -> None:
        if not self.pages or self._jumping:
            return
        center = self.mapToScene(self.viewport().rect().center()).y()
        top = self.mapToScene(0, 0).y()
        probe = top + (center - top) * 0.5
        index = len(self.pages) - 1
        for item in self.pages:
            if item.pos().y() + item.size.height() + PAGE_GAP / 2 > probe:
                index = item.index
                break
        if index != self._current:
            self._current = index
            self.currentPageChanged.emit(index)

    def scroll_to_page(self, index: int) -> None:
        if 0 <= index < len(self.pages):
            # The last pages may not scroll to the top; don't let the clamped
            # scroll position "correct" the page the user just picked. (Don't
            # block the scrollbar's signals: the view scrolls through them.)
            self._jumping = True
            try:
                self.verticalScrollBar().setValue(
                    round(self.pages[index].pos().y() - PAGE_GAP / 2)
                )
            finally:
                self._jumping = False
            self._current = index
            self.currentPageChanged.emit(index)

    # -------------------------------------------------------------- geometry
    def _hit(self, scene_pos: QPointF) -> tuple[int, fitz.Point] | None:
        """Page index and *display* point (in PDF points) under a scene position."""
        for item in self.pages:
            local = scene_pos - item.pos()
            if item.page_rect.contains(local):
                return item.index, fitz.Point(local.x() / self.zoom, local.y() / self.zoom)
        return None

    def _scene_rect(self, index: int, unrotated: fitz.Rect) -> QRectF:
        r = self.doc.to_display(index, unrotated)
        pos = self.pages[index].pos()
        return QRectF(pos.x() + r.x0 * self.zoom, pos.y() + r.y0 * self.zoom,
                      r.width * self.zoom, r.height * self.zoom)

    # ----------------------------------------------------------------- tools
    def set_tool(self, tool: Tool) -> None:
        if tool != self.tool:
            self.cancel_interactions(commit=True)
        self.tool = tool
        self._hover.hide()
        cursors = {
            Tool.SELECT: Qt.CursorShape.ArrowCursor,
            Tool.EDIT_TEXT: Qt.CursorShape.IBeamCursor,
            Tool.ADD_TEXT: Qt.CursorShape.CrossCursor,
            Tool.ADD_IMAGE: Qt.CursorShape.ArrowCursor,
            Tool.HIGHLIGHT: Qt.CursorShape.CrossCursor,
            Tool.ADD_BOX: Qt.CursorShape.CrossCursor,
        }
        self.viewport().setCursor(QCursor(cursors[tool]))
        if tool != Tool.SELECT:
            self.clear_selection()

    def cancel_interactions(self, commit: bool = False) -> None:
        self._cancel_draw()
        if self._editor is not None:
            if commit:
                self._editor.commit()
            else:
                self._editor.cancel()
        if self.is_placing:
            if commit:
                self.commit_placement()
            else:
                self.cancel_placement()

    @property
    def selected_image(self) -> ImageInfo | None:
        return self.selected if isinstance(self.selected, ImageInfo) else None

    @property
    def selected_text(self) -> TextBlock | None:
        return self.selected if isinstance(self.selected, TextBlock) else None

    @property
    def selected_markup(self) -> Markup | None:
        return self.selected if isinstance(self.selected, Markup) else None

    def clear_selection(self) -> None:
        self.selected = None
        self.selection = []
        self._selection_box.hide()
        self._clear_multi_boxes()
        if self._transformer_mode in ("edit", "box"):
            self._drop_transformer()
        self.selectionChanged.emit(None)

    def _clear_multi_boxes(self) -> None:
        for box in self._multi_boxes:
            if box.scene() is not None:
                box.scene().removeItem(box)
        self._multi_boxes = []

    def _select(self, item: ImageInfo | TextBlock | Markup) -> None:
        if self._transformer_mode in ("edit", "box"):
            self._drop_transformer()
        self._clear_multi_boxes()
        self.selected = item
        self.selection = [item]
        if isinstance(item, ImageInfo) and item.name:
            self._selection_box.hide()
            self._show_image_transformer(item)
        elif isinstance(item, Markup) and item.kind == "box":
            self._selection_box.hide()
            self._show_box_transformer(item)
        else:
            pad = 0 if isinstance(item, ImageInfo) else 2
            self._selection_box.setRect(
                self._scene_rect(item.page, item.bbox).adjusted(-pad, -pad, pad, pad)
            )
            self._selection_box.show()
        self.selectionChanged.emit(item)

    def select_items(self, items: list[ImageInfo | TextBlock | Markup]) -> None:
        """Select several elements, to move or delete them together."""
        items = [it for n, it in enumerate(items) if it not in items[:n]]
        if len(items) < 2:
            if items:
                self._select(items[0])
            else:
                self.clear_selection()
            return
        if self._transformer_mode in ("edit", "box"):
            self._drop_transformer()
        self._selection_box.hide()
        self._clear_multi_boxes()
        self.selected = None
        self.selection = items
        for item in items:
            box = QGraphicsRectItem(self._scene_rect(item.page, item.bbox).adjusted(-2, -2, 2, 2))
            box.setPen(self._selection_box.pen())
            box.setBrush(self._selection_box.brush())
            box.setZValue(6)
            self.scene().addItem(box)
            self._multi_boxes.append(box)
        self.selectionChanged.emit(list(items))
        self.message.emit(ntr(
            "{n} item selected.",
            "{n} items selected. Drag one of them or use the arrow keys to move them "
            "together; Delete removes them.", len(items)))

    def _toggle_selected(self, item: ImageInfo | TextBlock | Markup) -> None:
        """Shift- or Ctrl-click: add an element to the selection, or take it out."""
        items = list(self.selection)
        if item in items:
            items.remove(item)
        else:
            items.append(item)
        self.select_items(items)

    def _selectable_at(self, index: int, pt: fitz.Point) -> ImageInfo | TextBlock | Markup | None:
        """Image, text box, highlight or box under a point.

        Highlights lie on top of the page. Below them the smaller one wins
        (text over a photo or on a filled box); the inside of a hollow box
        only counts when nothing else is there.
        """
        marks = [m for m in self.doc.markups(index) if m.contains(pt)]
        on_top = [m for m in marks if m.kind == "highlight"]
        if on_top:
            return min(on_top, key=lambda m: m.bbox.get_area())
        hits: list[ImageInfo | TextBlock | Markup] = [
            b for b in self._blocks(index) if pt in b.bbox]
        hits += [m for m in marks if m.covers(pt)]
        if not hits:
            hits += marks
        image = self.doc.image_at(index, pt)
        if image:
            hits.append(image)
        return min(hits, key=lambda h: h.bbox.get_area()) if hits else None

    def _selectables_in(self, index: int, area: fitz.Rect) -> list[ImageInfo | TextBlock | Markup]:
        """Everything selectable on a page that a rubber band (unrotated) touches."""
        found: list[ImageInfo | TextBlock | Markup] = [
            *self._blocks(index), *self.doc.markups(index), *self.doc.images(index)]
        return [it for it in found if it.bbox.intersects(area)]

    def _drag_items(self, target: ImageInfo | TextBlock | Markup | None, index: int,
                    pt: fitz.Point) -> list[ImageInfo | TextBlock | Markup]:
        """What dragging from ``target`` moves: a text box or box itself, the text
        under a highlight (the highlight goes along), or anything in a selection
        of several: the whole selection."""
        if len(self.selection) > 1 and target in self.selection:
            return list(self.selection)
        if isinstance(target, TextBlock) or (isinstance(target, Markup) and target.kind == "box"):
            return [target]
        if isinstance(target, Markup):
            text = self._block_at(index, pt)
            return [text] if text is not None else []
        return []

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag is not None:
            self._drag_to(self.mapToScene(event.position().toPoint()))
            return
        if self._draw is not None:
            self._draw_to(self.mapToScene(event.position().toPoint()))
            return
        if self._band is not None:
            self._band_to(self.mapToScene(event.position().toPoint()))
            return
        super().mouseMoveEvent(event)
        if not self.doc or self._editor is not None:
            return
        scene_pos = self.mapToScene(event.position().toPoint())
        t = self._transformer
        if t is not None and t._hit(t.mapFromScene(scene_pos)) is not None:
            # Over the image handles: their own cursor (resize/rotate/move) wins.
            self._hover.hide()
            return
        hit = self._hit(scene_pos)
        if hit is None or self.tool not in (Tool.EDIT_TEXT, Tool.SELECT):
            self._hover.hide()
            return
        index, display_pt = hit
        pt = self.doc.from_display(index, display_pt)
        rect = None
        if self.tool == Tool.EDIT_TEXT:
            hits = [ln for ln in self._lines(index) if pt in ln.bbox]
            if hits:
                rect = min(hits, key=lambda ln: ln.bbox.get_area()).bbox
        elif self.tool == Tool.SELECT and not self.is_placing:
            target = self._selectable_at(index, pt)
            if target is not None and target not in self.selection:
                rect = target.bbox
            self._set_cursor(
                Qt.CursorShape.SizeAllCursor if self._drag_items(target, index, pt)
                else Qt.CursorShape.ArrowCursor
            )
        if rect is None:
            self._hover.hide()
        else:
            self._hover.setRect(self._scene_rect(index, rect).adjusted(-2, -1, 2, 1))
            self._hover.show()

    def _on_selected_box(self, scene_pos: QPointF) -> bool:
        """True if something lying on the selected box (text typed on it) is under the mouse."""
        box, hit = self.selected_markup, self._hit(scene_pos)
        if box is None or hit is None or self._transformer_mode != "box":
            return False
        target = self._selectable_at(hit[0], self.doc.from_display(*hit))
        return target is not None and not (
            isinstance(target, Markup) and (target.xref, target.tag) == (box.xref, box.tag))

    def _set_cursor(self, shape: Qt.CursorShape) -> None:
        # Only on change: re-setting it on every move fights Qt's item cursors.
        if self.viewport().cursor().shape() != shape:
            self.viewport().setCursor(shape)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover.hide()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        scene_pos = self.mapToScene(event.position().toPoint())
        t = self._transformer
        grab = t._hit(t.mapFromScene(scene_pos)) if t is not None else None
        adding = bool(event.modifiers() & (Qt.KeyboardModifier.ShiftModifier
                                           | Qt.KeyboardModifier.ControlModifier))
        if grab is not None and not (grab == "move" and (
                self._on_selected_box(scene_pos) or (adding and not self.is_placing))):
            super().mousePressEvent(event)  # the handles take it from here
            return
        if self.is_placing or self._editor is not None:
            item = self.scene().itemAt(scene_pos, self.transform())
            if item is self._editor_proxy:
                super().mousePressEvent(event)
                return
            # Clicking elsewhere commits what's in progress.
            self.cancel_interactions(commit=True)
            if self.tool != Tool.SELECT:
                return
        if not self.doc or event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        hit = self._hit(scene_pos)
        if hit is None:
            self.clear_selection()
            super().mousePressEvent(event)
            return
        index, display_pt = hit
        pt = self.doc.from_display(index, display_pt)
        if self.tool == Tool.EDIT_TEXT:
            hits = [ln for ln in self._lines(index) if pt in ln.bbox]
            if hits:
                self.begin_edit_line(min(hits, key=lambda ln: ln.bbox.get_area()))
            else:
                self.message.emit(tr("No text here. Use “Add text” to place new text."))
        elif self.tool == Tool.ADD_TEXT:
            self.begin_add_text(index, display_pt)
        elif self.tool in (Tool.HIGHLIGHT, Tool.ADD_BOX):
            self._begin_draw(index, display_pt)
        elif self.tool == Tool.SELECT:
            target = self._selectable_at(index, pt)
            if target is None:
                if not adding:
                    self.clear_selection()
                self._begin_band(index, scene_pos, adding)
            elif adding:
                self._toggle_selected(target)
            else:
                if target not in self.selection or len(self.selection) < 2:
                    self._select(target)
                items = self._drag_items(target, index, pt)
                if items:
                    self._drag = {"start": scene_pos, "items": items, "ghosts": None}
            self._hover.hide()
            self.setFocus()

    # ----------------------------------------------------- rubber band select
    def _begin_band(self, index: int, scene_pos: QPointF, adding: bool) -> None:
        item = QGraphicsRectItem()
        pen = QPen(self.accent, 1, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        item.setPen(pen)
        fill = QColor(self.accent)
        fill.setAlpha(24)
        item.setBrush(fill)
        item.setZValue(8)
        item.hide()
        self.scene().addItem(item)
        self._band = {"page": index, "start": scene_pos, "item": item,
                      "keep": list(self.selection) if adding else []}

    def _band_to(self, scene_pos: QPointF) -> None:
        band = self._band
        page = self.pages[band["page"]]
        area = page.mapRectToScene(page.page_rect)  # kept on the page it started on
        end = QPointF(min(max(scene_pos.x(), area.left()), area.right()),
                      min(max(scene_pos.y(), area.top()), area.bottom()))
        band["item"].setRect(QRectF(band["start"], end).normalized())
        band["item"].show()

    def _finish_band(self) -> None:
        band, self._band = self._band, None
        item = band["item"]
        if item.scene() is not None:
            item.scene().removeItem(item)
        rect = item.rect()
        if not item.isVisible() or rect.width() + rect.height() < 4:
            return  # a plain click on an empty spot
        index = band["page"]
        r = rect.translated(-self.pages[index].pos())
        z = self.zoom
        area = self.doc.from_display_rect(
            index, fitz.Rect(r.left() / z, r.top() / z, r.right() / z, r.bottom() / z))
        self.select_items(band["keep"] + self._selectables_in(index, area))

    # --------------------------------------------- moving text boxes and boxes
    def _drag_to(self, scene_pos: QPointF) -> None:
        drag = self._drag
        offset = scene_pos - drag["start"]
        if drag["ghosts"] is None:
            if abs(offset.x()) + abs(offset.y()) < 4:  # ignore tiny jitters of a click
                return
            drag["ghosts"] = [self._make_ghost(item) for item in drag["items"]
                              if not (isinstance(item, Markup) and item.kind == "highlight")]
            if self._transformer_mode == "box":
                self._transformer.hide()  # the ghost shows where the box goes
        for item, ghost in zip((it for it in drag["items"] if not (
                isinstance(it, Markup) and it.kind == "highlight")), drag["ghosts"], strict=True):
            ghost.setPos(self._scene_rect(item.page, item.bbox).topLeft() + offset)
        boxes = self._multi_boxes or [self._selection_box]
        for item, box in zip(drag["items"], boxes, strict=False):
            if not (isinstance(item, Markup) and item.kind == "highlight"):
                rect = self._scene_rect(item.page, item.bbox)
                box.setRect(rect.translated(offset).adjusted(-2, -2, 2, 2))

    def _make_ghost(self, block: ImageInfo | TextBlock | Markup) -> QGraphicsItem:
        """A picture of the element, cut from the rendered page, that follows the mouse
        (for a box: the box itself)."""
        rect = self._scene_rect(block.page, block.bbox)
        if isinstance(block, Markup) and block.kind == "box":
            ghost = self._box_item(block.style)
            ghost.setRect(QRectF(QPointF(0, 0), rect.size()))
            ghost.setPos(rect.topLeft())
            self.scene().addItem(ghost)
            return ghost
        image = self.page_image(block.page)
        dpr = image.devicePixelRatio()
        local = rect.translated(-self.pages[block.page].pos())
        crop = image.copy(
            round(local.x() * dpr), round(local.y() * dpr),
            round(local.width() * dpr), round(local.height() * dpr),
        )
        pixmap = QPixmap.fromImage(crop)
        pixmap.setDevicePixelRatio(dpr)
        ghost = QGraphicsPixmapItem(pixmap)
        ghost.setOpacity(0.85)
        ghost.setZValue(7)
        ghost.setPos(rect.topLeft())
        self.scene().addItem(ghost)
        return ghost

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._draw is not None:
            self._finish_draw()
            return
        if self._band is not None:
            self._finish_band()
            return
        drag, self._drag = self._drag, None
        if drag is None:
            super().mouseReleaseEvent(event)
            return
        if drag["ghosts"] is None:
            return  # plain click: just a selection
        for ghost in drag["ghosts"]:
            self.scene().removeItem(ghost)
        offset = self.mapToScene(event.position().toPoint()) - drag["start"]
        dx, dy = offset.x() / self.zoom, offset.y() / self.zoom
        if drag["items"] != [self.selected]:  # several, or the text under a highlight
            self.move_selection(dx, dy, drag["items"])
        elif self.selected_markup is not None:
            self.move_selected_markup(dx, dy)
        else:
            self.move_selected_text(dx, dy)

    def move_selection(self, dx: float, dy: float,
                       items: list[ImageInfo | TextBlock | Markup] | None = None) -> None:
        """Move all selected elements (or ``items``) by (dx, dy) points as seen on screen."""
        selection = list(self.selection)
        items = selection if items is None else items
        if not items or (dx == 0 and dy == 0):
            return
        try:
            self.doc.move_items(items, dx, dy)
        except Exception as exc:
            self.error.emit(str(exc))
            dx = dy = 0  # nothing moved
        # Keep them selected so they can be dragged or nudged again.
        again = [self._find_moved(item, dx, dy) for item in selection]
        self.select_items([it for it in again if it is not None])

    def _find_moved_highlight(self, item: Markup, dx: float, dy: float) -> Markup | None:
        shown = self.doc.to_display(item.page, item.bbox)
        center = self.doc.from_display(item.page, fitz.Point(
            (shown.x0 + shown.x1) / 2 + dx, (shown.y0 + shown.y1) / 2 + dy))
        marks = [m for m in self.doc.markups(item.page)
                 if m.kind == "highlight" and m.contains(center)]
        return min(marks, key=lambda m: m.bbox.get_area(), default=None)

    def _find_moved(self, item: ImageInfo | TextBlock | Markup, dx: float, dy: float
                    ) -> ImageInfo | TextBlock | Markup | None:
        """The element again after the document changed, moved by (dx, dy) display points."""
        if isinstance(item, Markup) and item.kind == "highlight":
            # It moved if its text did; it is a new annotation then.
            return self._find_moved_highlight(item, dx, dy) or \
                self._find_moved_highlight(item, 0, 0)
        page = item.page
        shown = self.doc.to_display(page, item.bbox)
        center = self.doc.from_display(page, fitz.Point(
            (shown.x0 + shown.x1) / 2 + dx, (shown.y0 + shown.y1) / 2 + dy))
        if isinstance(item, TextBlock):
            return self._block_at(page, center)
        if isinstance(item, ImageInfo):
            return next((im for im in self.doc.images(page)
                         if im.xref == item.xref and center in im.bbox), None)
        marks = [m for m in self.doc.markups(page) if m.kind == item.kind]
        return next((m for m in marks if (m.xref, m.tag) == (item.xref, item.tag)
                     and center in m.bbox), None) or min(
            (m for m in marks if center in m.bbox), key=lambda m: m.bbox.get_area(), default=None)

    def move_selected_text(self, dx: float, dy: float) -> None:
        """Move the selected text box by (dx, dy) points as seen on screen."""
        block = self.selected_text
        if block is None or (dx == 0 and dy == 0):
            return
        center = self.doc.to_display(block.page, block.bbox)
        target = fitz.Point((center.x0 + center.x1) / 2 + dx, (center.y0 + center.y1) / 2 + dy)
        try:
            self.doc.move_text_block(block, dx, dy)
        except Exception as exc:
            self.error.emit(str(exc))
            return
        # Keep the moved box selected so it can be dragged or nudged again.
        moved = self._block_at(block.page, self.doc.from_display(block.page, target))
        if moved is not None:
            self._select(moved)
        else:
            self.clear_selection()

    def move_selected_markup(self, dx: float, dy: float) -> None:
        """Move the selected box by (dx, dy) points as seen on screen."""
        markup = self.selected_markup
        if markup is None or markup.kind != "box" or (dx == 0 and dy == 0):
            return
        self._change_box(markup, lambda: self.doc.move_markup(markup, dx, dy))

    def _change_box(self, markup: Markup, change) -> None:
        """Run a document change that returns the box as it is afterwards; keep it selected."""
        try:
            markup = change()
        except Exception as exc:
            self.error.emit(str(exc))
        self._reselect_markup(markup)

    def _reselect_markup(self, markup: Markup | None) -> None:
        """Select the same highlight or box again after the document changed."""
        again = markup and next((m for m in self.doc.markups(markup.page)
                                 if (m.xref, m.tag) == (markup.xref, markup.tag)), None)
        if again is not None:
            self._select(again)
        else:
            self.clear_selection()

    def restyle_selected_markup(self) -> None:
        """Give the selected box the current box style (a highlight: the current colour)."""
        markup = self.selected_markup
        if markup is None:
            return

        def same(a, b) -> bool:
            return (a is None) == (b is None) and (
                a is None or all(abs(x - y) < 0.002 for x, y in zip(a, b, strict=True)))

        old, new = markup.style, self.box_style
        if markup.kind == "highlight":
            unchanged = same(markup.color, self.highlight_color)
        else:
            unchanged = abs(old.width - new.width) < 0.01 and same(old.fill, new.fill) and (
                new.width <= 0 or same(old.color, new.color))
        if unchanged:
            return  # e.g. a click on the swatch it already has: no undo step
        if markup.kind == "box":
            self._change_box(markup, lambda: self.doc.set_box_style(markup, self.box_style))
            if new.width <= 0 and new.fill is None:
                self.message.emit(tr("The box has no border and no fill now, so it is invisible "
                                     "until you give it one."))
            return
        try:
            self.doc.set_highlight_color(markup, self.highlight_color)
        except Exception as exc:
            self.error.emit(str(exc))
        self._reselect_markup(markup)

    def _show_box_transformer(self, markup: Markup) -> None:
        """Corner handles to resize the selected box; dragging it moves it."""
        rect = self._scene_rect(markup.page, markup.bbox)
        t = ImageTransformer(None, rect.center(), rect.width(), rect.height(), 0, self.accent,
                             rotatable=False, keep_aspect=False)
        look = self._box_item(markup.style)
        t.preview_pen, t.preview_brush = look.pen(), look.brush()
        if markup.fill is None:
            t.move_band = max(4.0, markup.width * self.zoom / 2 + 3)
        t.changed.connect(self._transformer_changed)
        self.scene().addItem(t)
        self._transformer, self._transformer_mode = t, "box"

    def _box_transformed(self) -> None:
        markup, t = self.selected_markup, self._transformer
        page = self.pages[markup.page]
        r = t.local_rect().translated(t.center - page.pos())
        # Keep it on its page: a box dragged off the page could not be found again.
        r.translate(max(0.0, -r.left()) + min(0.0, page.size.width() - r.right()),
                    max(0.0, -r.top()) + min(0.0, page.size.height() - r.bottom()))
        z = self.zoom
        display = fitz.Rect(r.left() / z, r.top() / z, r.right() / z, r.bottom() / z)
        rect = self.doc.from_display_rect(markup.page, display)
        self._change_box(markup, lambda: self.doc.set_box_rect(markup, rect))

    # ------------------------------------------------- highlight and box tools
    def _scene_point(self, index: int, display_pt: fitz.Point) -> QPointF:
        return self.pages[index].pos() + QPointF(display_pt.x * self.zoom,
                                                 display_pt.y * self.zoom)

    def _box_item(self, style: BoxStyle) -> QGraphicsRectItem:
        """A box as it will look on the page, at the current zoom."""
        item = QGraphicsRectItem()
        pen = QPen(Qt.PenStyle.NoPen)
        if style.width > 0:
            pen = QPen(qcolor(style.color), style.width * self.zoom)
            pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        item.setPen(pen)
        item.setBrush(QBrush(qcolor(style.fill)) if style.fill is not None
                      else QBrush(Qt.BrushStyle.NoBrush))
        item.setOpacity(0.85)
        item.setZValue(7)
        return item

    def _begin_draw(self, index: int, display_pt: fitz.Point) -> None:
        if self.tool == Tool.ADD_BOX:
            if self.box_style.width <= 0 and self.box_style.fill is None:
                self.message.emit(tr("Give the box a border or a fill colour first."))
                return
            item = self._box_item(self.box_style)
        else:
            item = QGraphicsPathItem()
            item.setPen(QPen(Qt.PenStyle.NoPen))
            color = qcolor(self.highlight_color)
            color.setAlphaF(0.5)
            item.setBrush(color)
            item.setZValue(7)
        self.scene().addItem(item)
        self._draw = {"tool": self.tool, "page": index, "start": display_pt, "end": None,
                      "item": item, "rects": []}

    def _draw_to(self, scene_pos: QPointF) -> None:
        draw = self._draw
        index = draw["page"]
        page = self.pages[index]
        local = scene_pos - page.pos()  # kept on the page the drag started on
        end = fitz.Point(min(max(local.x(), 0), page.size.width()) / self.zoom,
                         min(max(local.y(), 0), page.size.height()) / self.zoom)
        draw["end"] = end
        if draw["tool"] == Tool.ADD_BOX:
            draw["item"].setRect(QRectF(self._scene_point(index, draw["start"]),
                                        self._scene_point(index, end)).normalized())
            return
        draw["rects"] = self.doc.highlight_rects(
            index, self.doc.from_display(index, draw["start"]), self.doc.from_display(index, end))
        path = QPainterPath()
        path.setFillRule(Qt.FillRule.WindingFill)
        for rect in draw["rects"]:
            path.addRect(self._scene_rect(index, rect))
        draw["item"].setPath(path)

    def _finish_draw(self) -> None:
        draw = self._draw
        self._cancel_draw()
        index, start, end = draw["page"], draw["start"], draw["end"]
        try:
            if draw["tool"] == Tool.ADD_BOX:
                area = fitz.Rect(start, end or start).normalize()
                if area.width < 3 or area.height < 3:
                    self.message.emit(tr("Drag on the page to draw a box."))
                    return
                self.doc.add_box(index, self.doc.from_display_rect(index, area), self.box_style)
            elif draw["rects"]:
                self.doc.add_highlight(index, draw["rects"], self.highlight_color)
            else:
                self.message.emit(tr("Drag across the text you want to highlight."))
        except Exception as exc:
            self.error.emit(str(exc))

    def _cancel_draw(self) -> None:
        draw, self._draw = self._draw, None
        if draw is not None and draw["item"].scene() is not None:
            draw["item"].scene().removeItem(draw["item"])

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape and self._draw is not None:
            self._cancel_draw()
            return
        if self.is_placing:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.commit_placement()
                return
            if event.key() == Qt.Key.Key_Escape:
                self.cancel_placement()
                return
        if event.key() == Qt.Key.Key_Escape and self.selection:
            self.clear_selection()
            return
        arrows = {
            Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0),
            Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1),
        }
        if self.selection and event.key() in arrows:
            step = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
            dx, dy = arrows[event.key()]
            if len(self.selection) > 1:
                self.move_selection(dx * step, dy * step)
            elif self.selected_text is not None:
                self.move_selected_text(dx * step, dy * step)
            elif self.selected_markup is not None:
                self.move_selected_markup(dx * step, dy * step)
            elif self.selected_image is not None and self.selected_image.name:
                geo = self.doc.image_geometry(self.selected_image)
                geo.center = fitz.Point(geo.center.x + dx * step, geo.center.y + dy * step)
                self._apply_image_geometry(self.selected_image, geo)
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------ text tools
    def _open_editor(self, text: str, style: TextStyle, top_left: QPointF) -> None:
        editor = InlineEditor(text, self._preview_font(style), qcolor(style.color), self.accent)
        editor.committed.connect(self._editor_committed)
        editor.cancelled.connect(self._close_editor)
        proxy = self.scene().addWidget(editor)
        proxy.setZValue(20)
        fm = editor.fontMetrics()
        # Line up the editor's text baseline roughly with the PDF's.
        proxy.setPos(top_left - QPointF(3, 3 + max(0, fm.ascent() - style.size * self.zoom * 0.9)))
        self._editor, self._editor_proxy = editor, proxy
        self._hover.hide()
        editor.setFocus()
        self.editingChanged.emit(style)

    def begin_edit_line(self, line: TextLine) -> None:
        self._editing_line = line
        self._editing_page = line.page
        self._editing_point = None
        rect = self._scene_rect(line.page, line.bbox)
        self.text_style = TextStyle(**vars(line.style))
        self._open_editor(line.text, self.text_style, rect.topLeft())
        self._editor.min_width = rect.width() + 12
        self._editor._fit()

    def begin_add_text(self, index: int, display_pt: fitz.Point) -> None:
        self._editing_line = None
        self._editing_page = index
        self._editing_point = display_pt
        pos = self.pages[index].pos() + QPointF(display_pt.x * self.zoom, display_pt.y * self.zoom)
        self._open_editor("", self.text_style, pos)

    def update_editor_style(self, style: TextStyle) -> None:
        self.text_style = style
        if self._editor is not None:
            self._editor.set_look(self._preview_font(style), qcolor(style.color))
            # Typing "14" in the size box must not send the "4" into the text.
            if not is_inside(QApplication.focusWidget(), "Inspector"):
                self._editor.setFocus()

    def _preview_font(self, style: TextStyle) -> QFont:
        return qfont_for(style, self.zoom, self._preview_family(style))

    def _preview_family(self, style: TextStyle) -> str | None:
        """A Qt family that draws this face: installed, or loaded from the PDF itself."""
        if style.typeface and style.typeface.lower() in _installed_families():
            return style.typeface
        if not style.font or self.doc is None:
            return None
        if style.font not in self._registered_fonts:
            family = None
            data = self.doc.preview_font_data(style.font)
            if data:
                font_id = QFontDatabase.addApplicationFontFromData(data)
                names = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
                family = names[0] if names else None
            self._registered_fonts[style.font] = family
        return self._registered_fonts[style.font]

    def focus_editor(self) -> None:
        if self._editor is not None:
            self._editor.setFocus()

    @property
    def is_editing(self) -> bool:
        return self._editor is not None

    def _editor_committed(self, text: str) -> None:
        line, index, point = self._editing_line, self._editing_page, self._editing_point
        style = TextStyle(**vars(self.text_style))
        self._close_editor()
        try:
            if line is not None:
                if text != line.text or style != line.style:
                    note = self.doc.replace_text(line, text, style)
                    if note:
                        self.message.emit(note)
            elif point is not None and text.strip():
                note = self.doc.add_text(index, self.doc.from_display(index, point), text, style)
                if note:
                    self.message.emit(note)
        except Exception as exc:  # surface to the user rather than crash
            self.error.emit(str(exc))

    def _close_editor(self) -> None:
        editor, proxy = self._editor, self._editor_proxy
        self._editor = self._editor_proxy = None
        self._editing_line = None
        self._editing_point = None
        if proxy is not None and proxy.scene() is not None:
            QTimer.singleShot(0, lambda: self._remove_proxy(proxy))
        if editor is not None:
            editor.deleteLater()
        self.editingChanged.emit(None)
        self.setFocus()

    @staticmethod
    def _remove_proxy(proxy: QGraphicsProxyWidget) -> None:
        try:
            if proxy.scene() is not None:
                proxy.scene().removeItem(proxy)
        except RuntimeError:  # already deleted by a scene rebuild
            pass

    # ----------------------------------------------------------- image tools
    @property
    def is_placing(self) -> bool:
        return self._transformer_mode == "place"

    def _drop_transformer(self) -> None:
        for item in (self._transformer, self._veil):
            if item is not None and item.scene() is not None:
                item.scene().removeItem(item)
        self._transformer = self._veil = None
        self._transformer_mode = ""

    def _to_scene(self, index: int, geo: ImageGeometry) -> tuple[QPointF, float, float]:
        pos = self.pages[index].pos()
        center = QPointF(pos.x() + geo.center.x * self.zoom, pos.y() + geo.center.y * self.zoom)
        return center, geo.width * self.zoom, geo.height * self.zoom

    def _from_scene(self, index: int, t: ImageTransformer) -> ImageGeometry:
        pos = self.pages[index].pos()
        return ImageGeometry(
            center=fitz.Point((t.center.x() - pos.x()) / self.zoom,
                              (t.center.y() - pos.y()) / self.zoom),
            width=t.width / self.zoom,
            height=t.height / self.zoom,
            angle=t.angle,
            flipped=t.flipped,
        )

    def _image_pixmap(self, image: ImageInfo) -> QPixmap:
        """The image's own pixels (with transparency) for the handles' preview."""
        try:
            if image.vector:
                pix = self.doc.render_vector(image, self.zoom * self.devicePixelRatioF())
            else:
                pix = fitz.Pixmap(self.doc.doc, image.xref)
            if pix.colorspace and pix.colorspace.n not in (1, 3):
                pix = fitz.Pixmap(fitz.csRGB, pix)
            smask = 0 if image.vector else next(
                (e[1] for e in self.doc.doc[image.page].get_images(full=True)
                 if e[0] == image.xref), 0)
            if smask:
                pix = fitz.Pixmap(pix, fitz.Pixmap(self.doc.doc, smask))
            if pix.n == 1:
                pix = fitz.Pixmap(fitz.csRGB, pix)
            fmt = QImage.Format.Format_RGBA8888 if pix.alpha else QImage.Format.Format_RGB888
            qimage = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt).copy()
            return QPixmap.fromImage(qimage)
        except Exception:
            # Fall back to a crop of the rendered page.
            rect = self._scene_rect(image.page, image.bbox).translated(
                -self.pages[image.page].pos())
            img = self.page_image(image.page)
            dpr = img.devicePixelRatio()
            return QPixmap.fromImage(img.copy(round(rect.x() * dpr), round(rect.y() * dpr),
                                              round(rect.width() * dpr),
                                              round(rect.height() * dpr)))

    def _show_image_transformer(self, image: ImageInfo) -> None:
        geo = self.doc.image_geometry(image)
        center, w, h = self._to_scene(image.page, geo)
        t = ImageTransformer(self._image_pixmap(image), center, w, h, geo.angle, self.accent,
                             flipped=geo.flipped)
        t.changed.connect(self._transformer_changed)
        # A veil over the original, so a moved image doesn't look duplicated.
        quad = [fitz.Point(x, y) * image.transform for x, y in ((0, 0), (1, 0), (1, 1), (0, 1))]
        poly = QPolygonF()
        for q in quad:
            r = self._scene_rect(image.page, fitz.Rect(q, q))
            poly.append(r.topLeft())
        veil = QGraphicsPolygonItem(poly)
        veil.setBrush(QColor(255, 255, 255, 170))
        veil.setPen(QPen(Qt.PenStyle.NoPen))
        veil.setZValue(4)
        self.scene().addItem(veil)
        self.scene().addItem(t)
        self._transformer, self._veil, self._transformer_mode = t, veil, "edit"

    def _transformer_changed(self) -> None:
        if self._transformer_mode == "box" and self.selected_markup is not None:
            self._box_transformed()
            return
        if self._transformer_mode != "edit" or self.selected_image is None:
            return
        image = self.selected_image
        self._apply_image_geometry(image, self._from_scene(image.page, self._transformer))

    def _apply_image_geometry(self, image: ImageInfo, geo: ImageGeometry) -> None:
        try:
            self.doc.transform_image(image, geo)
        except PdfError as exc:
            self.error.emit(str(exc))
        self._reselect_image(image)

    def _reselect_image(self, image: ImageInfo) -> None:
        """Select the same image again after the document changed."""
        again = next((im for im in self.doc.images(image.page)
                      if im.xref == image.xref and im.name == image.name), None)
        if again is not None:
            self._select(again)
        else:
            self.clear_selection()

    def rotate_selected_image(self, degrees: float) -> None:
        image = self.selected_image
        if image is None:
            return
        try:
            self.doc.rotate_image(image, degrees)
        except PdfError as exc:
            self.error.emit(str(exc))
        self._reselect_image(image)

    def begin_image_placement(self, source: str | bytes) -> bool:
        """Show an image (file path or contents) on the current page, to be placed."""
        pixmap = QPixmap(source) if isinstance(source, str) else QPixmap()
        if isinstance(source, bytes):
            pixmap.loadFromData(source)
        if pixmap.isNull() or not self.pages:
            self.error.emit(tr("That file could not be read as an image."))
            return False
        self.cancel_interactions(commit=True)
        self.clear_selection()
        item = self.pages[self._current]
        page_w, page_h = item.size.width(), item.size.height()
        w, h = fit_image(pixmap.width() * self.zoom, pixmap.height() * self.zoom, page_w, page_h)
        visible = self.mapToScene(self.viewport().rect()).boundingRect()
        top = max(item.pos().y() + 20, min(visible.center().y() - h / 2,
                                            item.pos().y() + page_h - h - 20))
        center = QPointF(item.pos().x() + page_w / 2, top + h / 2)
        t = ImageTransformer(pixmap, center, w, h, 0, self.accent, dashed=True)
        self.scene().addItem(t)
        self._transformer, self._transformer_mode = t, "place"
        self._placement_source = source
        self.setFocus()
        self.placementChanged.emit(True)
        self.message.emit(tr("Drag to position, corners resize, the top handle rotates. "
                             "Enter places, Esc cancels."))
        return True

    def commit_placement(self) -> None:
        t, source = self._transformer, self._placement_source
        if not self.is_placing:
            return
        self._drop_transformer()
        self.placementChanged.emit(False)
        # Place on the page containing the image's centre (or the closest).
        center = t.center
        target = min(
            self.pages,
            key=lambda it: 0
            if it.mapRectToScene(it.page_rect).contains(center)
            else abs(it.mapRectToScene(it.page_rect).center().y() - center.y()),
        )
        try:
            geometry = self._from_scene(target.index, t)
            if isinstance(source, str):
                self.doc.add_image(target.index, geometry, path=source)
            else:
                self.doc.add_image(target.index, geometry, data=source)
        except Exception as exc:
            self.error.emit(str(exc))

    def cancel_placement(self) -> None:
        if self.is_placing:
            self._drop_transformer()
            self.placementChanged.emit(False)

    def delete_selected(self) -> bool:
        """Delete the selected image, text box, highlight or box (or all of several);
        False if nothing is selected."""
        target, items = self.selected, list(self.selection)
        if not items:
            return False
        self.clear_selection()
        try:
            if len(items) > 1:
                self.doc.delete_items(items)
            elif isinstance(target, TextBlock):
                self.doc.delete_text_block(target)
            elif isinstance(target, Markup):
                self.doc.delete_markup(target)
            else:
                self.doc.delete_image(target)
        except Exception as exc:
            self.error.emit(str(exc))
        return True

    # ---------------------------------------------------------------- layers
    def arrange_selected(self, how: str) -> None:
        """Bring the selected text box, image or box to the front, forward, backward
        or to the back."""
        target = self.selected
        if target is None or not self.doc:
            return
        self.cancel_interactions(commit=True)
        try:
            changed = self.doc.arrange(target, how)
        except PdfError as exc:
            self.error.emit(str(exc))
            return
        kind = "text" if isinstance(target, TextBlock) else \
            "image" if isinstance(target, ImageInfo) else "box"
        if not changed:
            front = how in ("front", "forward")
            self.message.emit(tr({
                ("text", True): N_("The text box is already in front of everything it overlaps."),
                ("text", False): N_("The text box is already behind everything it overlaps."),
                ("image", True): N_("The image is already in front of everything it overlaps."),
                ("image", False): N_("The image is already behind everything it overlaps."),
                ("box", True): N_("The box is already in front of everything it overlaps."),
                ("box", False): N_("The box is already behind everything it overlaps."),
            }[kind, front]))
            return
        self.message.emit(tr({
            "text": N_("{action}: done. Undo puts the text box back."),
            "image": N_("{action}: done. Undo puts the image back."),
            "box": N_("{action}: done. Undo puts the box back."),
        }[kind], action=tr(LAYER_MOVES[how])))
        self._reselect(target)

    def _reselect(self, item: ImageInfo | TextBlock | Markup) -> None:
        """Select an element again after the document changed (its layer, say)."""
        page = item.page
        center = (item.bbox.tl + item.bbox.br) * 0.5
        again = None
        if isinstance(item, ImageInfo):
            again = next((im for im in self.doc.images(page)
                          if im.xref == item.xref and center in im.bbox
                          and abs(im.bbox.width - item.bbox.width) < 0.5), None)
        elif isinstance(item, Markup):
            boxes = [m for m in self.doc.markups(page) if m.kind == item.kind]
            again = next((m for m in boxes if (m.xref, m.tag) == (item.xref, item.tag)), None) \
                or next((m for m in boxes if not m.xref
                         and abs(m.bbox.x0 - item.bbox.x0) < 0.5
                         and abs(m.bbox.y1 - item.bbox.y1) < 0.5), None)
        else:
            again = self._block_at(page, center)
        if again is not None:
            self._select(again)
        else:
            self.clear_selection()

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        if not self.doc or self.tool != Tool.SELECT or self.is_placing or self._editor:
            super().contextMenuEvent(event)
            return
        hit = self._hit(self.mapToScene(event.pos()))
        if hit is not None:
            target = self._selectable_at(hit[0], self.doc.from_display(*hit))
            if target is None:
                self.clear_selection()
            elif target not in self.selection:
                self._select(target)
        self._hover.hide()
        self.setFocus()
        self.contextMenuWanted.emit(event.globalPos())

    # ---------------------------------------------------------- drag and drop
    def _wanted(self, event) -> dnd.Dropped | None:
        data = dnd.read(event.mimeData())
        if not self.doc or not self.pages or not data or data.from_list(self.own_pages_source):
            return None
        return data

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._wanted(event) is None:
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        self.dragEnterEvent(event)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        event.accept()

    def dropEvent(self, event) -> None:  # noqa: N802
        data = self._wanted(event)
        if data is None:
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        index, point = self._drop_point(self.mapToScene(event.position().toPoint()))
        # Deferred: what follows may open a dialog, which must not happen while
        # the system is still busy with the drag.
        QTimer.singleShot(0, lambda: self.dropped.emit(data, index, point))

    def _drop_point(self, scene_pos: QPointF) -> tuple[int, fitz.Point]:
        """The page (the closest one) and display point under a scene position."""
        item = min(self.pages, key=lambda it: 0 if it.mapRectToScene(it.page_rect).contains(
            scene_pos) else abs(it.mapRectToScene(it.page_rect).center().y() - scene_pos.y()))
        local = scene_pos - item.pos()
        x = min(max(local.x(), 0.0), item.size.width()) / self.zoom
        y = min(max(local.y(), 0.0), item.size.height()) / self.zoom
        return item.index, fitz.Point(x, y)

    def place_images(self, index: int, point: fitz.Point, sources: list[str | bytes]) -> None:
        """Put images (file paths or contents) on a page, centred on a display point
        (the next ones a bit further along), and select the last one so it can be
        adjusted at once."""
        if not self.doc or not sources:
            return
        self.cancel_interactions(commit=True)
        page_w, page_h = self.doc.page_size(index)
        placements = []
        for n, source in enumerate(sources):
            size = QImageReader(source).size() if isinstance(source, str) else QSize()
            try:
                width, height = (size.width(), size.height()) if size.isValid() \
                    else image_size(source)
            except PdfError as exc:
                self.error.emit(str(exc))
                return
            w, h = fit_image(width, height, page_w, page_h)
            cx = min(max(point.x + 18 * n, w / 2), max(w / 2, page_w - w / 2))
            cy = min(max(point.y + 18 * n, h / 2), max(h / 2, page_h - h / 2))
            placements.append((ImageGeometry(fitz.Point(cx, cy), w, h, 0.0), source))
        try:
            names = self.doc.add_images(index, placements)
        except PdfError as exc:
            self.error.emit(str(exc))
            return
        image = next((im for im in self.doc.images(index) if im.name == names[-1]), None)
        if image is not None:
            self._select(image)
        self.setFocus()
