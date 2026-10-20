"""Small widgets shared by the inspector and the dialogs, drawn to match the theme."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPaintEvent, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QApplication,
    QGraphicsView,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from pixa.i18n import tr
from pixa.ui import icons

NO_COLOUR = QColor("#d93025")  # the red slash of a "no colour" swatch


def _accent() -> QColor:
    return QApplication.palette().highlight().color()


def _text() -> QColor:
    return QApplication.palette().windowText().color()


class Swatch(QAbstractButton):
    """A round colour button, painted smoothly (a stylesheet's round border is jagged).

    ``color`` None draws white with a red slash: "no colour". A selected swatch
    gets an accent ring around it.
    """

    SIZE = 28

    def __init__(self, color: str | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.color = color
        self._selected = False
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(color or tr("Transparent"))
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def is_selected(self) -> bool:
        return self._selected

    def set_selected(self, selected: bool) -> None:
        if selected != self._selected:
            self._selected = selected
            self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.SIZE, self.SIZE)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bounds = QRectF(self.rect())
        # Ring (selected or hovered) on the outside, then a small gap, then the colour.
        if self._selected or self.underMouse():
            ring = _accent() if self._selected else QColor(_text())
            if not self._selected:
                ring.setAlphaF(0.3)
            p.setPen(QPen(ring, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(bounds.adjusted(1, 1, -1, -1))
        dot = bounds.adjusted(3.5, 3.5, -3.5, -3.5)
        edge = QColor(_text())
        edge.setAlphaF(0.22)
        p.setPen(QPen(edge, 1))
        p.setBrush(QColor(self.color or "#ffffff"))
        p.drawEllipse(dot.adjusted(0.5, 0.5, -0.5, -0.5))
        if self.color is None:
            pen = QPen(NO_COLOUR, 1.8)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            inset = dot.width() * 0.22
            p.drawLine(dot.bottomLeft() + QPointF(inset, -inset),
                       dot.topRight() + QPointF(-inset, inset))
        p.end()


def colour_icon(color: str | None, size: int = 14) -> QIcon:
    """A small round chip of ``color`` (None: "no colour") for a button's icon."""
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    edge = QColor(_text())
    edge.setAlphaF(0.3)
    p.setPen(QPen(edge, 1))
    p.setBrush(QColor(color or "#ffffff"))
    rect = QRectF(1, 1, size - 2, size - 2)
    p.drawEllipse(rect)
    if color is None:
        pen = QPen(NO_COLOUR, 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawLine(rect.bottomLeft() + QPointF(3, -3), rect.topRight() + QPointF(-3, 3))
    p.end()
    return QIcon(pixmap)


def swatch_row(swatches: list[Swatch]) -> QHBoxLayout:
    """``swatches`` spread evenly across the full width."""
    row = QHBoxLayout()
    row.setSpacing(0)
    for i, swatch in enumerate(swatches):
        if i:
            row.addStretch(1)
        row.addWidget(swatch)
    return row


def icon_button(name: str, tip: str) -> QPushButton:
    """A square button showing one of the theme's line icons."""
    button = QPushButton()
    button.setProperty("iconButton", True)
    button.setProperty("iconName", name)
    button.setIcon(icons.icon(name, _text().name()))
    button.setIconSize(QSize(16, 16))
    button.setToolTip(tip)
    return button


def retint(root: QWidget) -> None:
    """Redraw the icons of ``root``'s icon buttons in the current theme's text colour."""
    for button in root.findChildren(QPushButton):
        name = button.property("iconName")
        if name:
            button.setIcon(icons.icon(name, _text().name()))


def stepper(box: QAbstractSpinBox, tips: tuple[str, str] | None = None,
            steady_focus: bool = False) -> QHBoxLayout:
    """``box`` between a − and a + button, which replace its small built-in arrows.

    With ``steady_focus`` the buttons don't take keyboard focus when clicked
    (the inspector keeps it on the text being edited).
    """
    tips = tips or (tr("Less"), tr("More"))
    box.setProperty("stepped", True)
    box.setAlignment(Qt.AlignmentFlag.AlignCenter)
    row = QHBoxLayout()
    row.setSpacing(6)
    buttons = []
    for name, count, tip in (("minus", -1, tips[0]), ("plus", 1, tips[1])):
        button = icon_button(name, tip)
        button.setFixedWidth(34)
        button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        button.setAutoRepeat(True)
        if steady_focus:
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.clicked.connect(lambda _=False, n=count: box.stepBy(n))
        buttons.append(button)
    box.minus, box.plus = buttons
    row.addWidget(box.minus)
    row.addWidget(box, 1)
    row.addWidget(box.plus)
    return row


def theme_preview(preview: QWidget, background: str) -> None:
    """Give a QPrintPreviewWidget the canvas colour behind its pages instead of Qt's grey."""
    for view in preview.findChildren(QGraphicsView):
        view.setFrameShape(QGraphicsView.Shape.NoFrame)
        if view.scene() is not None:
            view.scene().setBackgroundBrush(QColor(background))
        view.setBackgroundBrush(QColor(background))
