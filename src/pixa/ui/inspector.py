"""Right-hand panel: context help, text style, image and page actions."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pixa.document import FONT_FAMILIES, BoxStyle, DocFace, TextStyle, fallback_family
from pixa.i18n import N_, tr
from pixa.ui import widgets
from pixa.ui.page_view import Tool

SWATCHES = ["#000000", "#6b7280", "#d93025", "#e37400", "#188038", "#1a73e8", "#9334e6"]
HIGHLIGHT_SWATCHES = ["#ffeb4d", "#a5f08a", "#8fd6ff", "#ffa6d5", "#ffbf70", "#d0a8ff"]
# The − / + buttons (and the arrow keys) step through these common sizes.
FONT_SIZES = [6, 7, 8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36, 48, 60, 72, 96, 144]
BORDER_WIDTHS = [0, 0.5, 1, 1.5, 2, 3, 4, 6, 8, 10, 12, 16, 20, 24]
WIDTH = 260  # the panel is wider only when its contents need it (longer translations)
FILL_SWATCHES = ["#ffffff", "#fff3b0", "#d7f5c8", "#cfe8ff", "#ffd6e7", "#e5e7eb"]

HINTS = {
    Tool.SELECT: N_("Click a text box, image, highlight or box to select it. Drag a text box "
                    "or box to move it, or "
                    "nudge it with the arrow keys (Shift for bigger steps). Delete removes the "
                    "selection; right-click it for its layer. "
                    "Drag thumbnails to reorder pages, or to another Pixa window to copy them. "
                    "Drop PDFs and images onto the pages or the thumbnails."),
    Tool.EDIT_TEXT: N_("Hover over text to see editable lines. Click a line to edit it. "
                       "Enter saves, Shift+Enter adds a line break, Esc cancels."),
    Tool.ADD_TEXT: N_("Click anywhere on a page to start typing. Choose the font, size and "
                      "colour below. Enter places the text."),
    Tool.ADD_IMAGE: N_("Choose an image, then drag it into position and resize it from the "
                       "corner handle (Shift for free resize). Enter places it."),
    Tool.HIGHLIGHT: N_("Drag across text to highlight it, like with a marker. Where there is no "
                       "text (a scan, a picture) the dragged area is highlighted. To recolour or "
                       "remove a highlight, click it with the Select tool."),
    Tool.ADD_BOX: N_("Drag on a page to draw a box. Choose its border and fill below. To move, "
                     "resize or restyle a box later, click it with the Select tool."),
}
TITLES = {
    Tool.SELECT: N_("Select"),
    Tool.EDIT_TEXT: N_("Edit text"),
    Tool.ADD_TEXT: N_("Add text"),
    Tool.ADD_IMAGE: N_("Add image"),
    Tool.HIGHLIGHT: N_("Highlight"),
    Tool.ADD_BOX: N_("Add box"),
}

Rgb = tuple[float, float, float]


def _heading(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setProperty("role", "heading")
    return label


def _control(widget: QWidget) -> QWidget:
    # Clicking style controls must not take keyboard focus away from the text
    # being edited on the page (the size box is the exception: it takes typing).
    widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return widget


def _rgb(color: QColor) -> Rgb:
    return (color.redF(), color.greenF(), color.blueF())


class StepSpinBox(QDoubleSpinBox):
    """A number box that steps through a list of common values instead of fixed increments.

    Any value in range can still be typed.
    """

    def __init__(self, steps: list[float]) -> None:
        super().__init__()
        self.steps = steps

    def stepBy(self, count: int) -> None:  # noqa: N802
        value = self.value()
        for _ in range(abs(count)):
            if count > 0:
                value = next((s for s in self.steps if s > value + 1e-6), self.maximum())
            else:
                value = next((s for s in reversed(self.steps) if s < value - 1e-6),
                             self.minimum())
        self.setValue(value)

    def stepper(self) -> QHBoxLayout:
        """The box between a − and a + button."""
        return widgets.stepper(self, (tr("Smaller"), tr("Larger")), steady_focus=True)


class ColorPicker(QWidget):
    """A row of colour swatches and a custom colour button.

    With ``allow_none`` the first swatch stands for no colour (transparent).
    """

    changed = Signal(object)  # (r, g, b) or None

    def __init__(self, colors: list[str], title: str, allow_none: bool = False) -> None:
        super().__init__()
        self._title = title
        self._color: Rgb | None = _rgb(QColor(colors[0]))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.buttons: list[widgets.Swatch] = []
        for color in ([None] if allow_none else []) + colors:
            btn = _control(widgets.Swatch(color))
            if color is None:
                btn.clicked.connect(lambda _=False: self._choose(None))
            else:
                btn.clicked.connect(lambda _=False, c=color: self._choose(_rgb(QColor(c))))
            self.buttons.append(btn)
        self.custom = _control(QPushButton())
        self.custom.clicked.connect(self._pick)
        layout.addLayout(widgets.swatch_row(self.buttons))
        layout.addWidget(self.custom)
        self._refresh()

    def color(self) -> Rgb | None:
        return self._color

    def set_color(self, color: Rgb | None) -> None:
        self._color = color
        self._refresh()

    def _choose(self, color: Rgb | None) -> None:
        self.set_color(color)
        self.changed.emit(color)

    def _pick(self) -> None:
        start = QColor.fromRgbF(*self._color) if self._color else QColor("#ffffff")
        color = QColorDialog.getColor(start, self, self._title)
        if color.isValid():
            self._choose(_rgb(color))

    def _refresh(self) -> None:
        current = QColor.fromRgbF(*self._color).name() if self._color else None
        for btn in self.buttons:
            btn.set_selected(btn.color == current)
        self.custom.setIcon(widgets.colour_icon(current))
        # The chip shows the colour; the text stays the same, so its length never widens
        # the panel (the value is in the tooltip).
        self.custom.setText(tr("Custom colour…"))
        self.custom.setToolTip(current or tr("Transparent"))


class Inspector(QWidget):
    styleChanged = Signal(object)  # TextStyle  # noqa: N815
    highlightChanged = Signal(object)  # (r, g, b)  # noqa: N815
    boxChanged = Signal(object)  # BoxStyle  # noqa: N815
    action = Signal(str)
    returnToEditor = Signal()  # noqa: N815 - Enter/Esc in the size box

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Inspector")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(WIDTH)
        self._style = TextStyle()
        self._updating = False

        # The sections scroll when the window is too low for them all.
        content = QWidget()
        content.setObjectName("InspectorContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 8, 16, 16)
        layout.setSpacing(8)
        scroll = QScrollArea()
        scroll.setObjectName("InspectorScroll")
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        self._scroll, self._content = scroll, content
        content.installEventFilter(self)  # to widen the panel when its contents need it

        self.tool_title = QLabel()
        self.tool_title.setStyleSheet("font-size: 15px; font-weight: 600; padding-top: 8px;")
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setProperty("role", "hint")
        layout.addWidget(self.tool_title)
        layout.addWidget(self.hint)

        # ---- text style
        self.text_box = QWidget()
        tl = QVBoxLayout(self.text_box)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(8)
        tl.addWidget(_heading(tr("Text")))
        # Fonts used in the document, then the standard ones. Item data is
        # "doc:<family>" or "std:<helv|tiro|cour>".
        self.family = _control(QComboBox())
        self.family.setMaxVisibleItems(16)
        # Long font names are cut short instead of widening the panel; the list shows them whole.
        self.family.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.family.setMinimumContentsLength(12)
        self.family.view().setTextElideMode(Qt.TextElideMode.ElideNone)
        self._doc_fonts: list[DocFace] = []
        self._fill_fonts()
        tl.addWidget(self.family)
        row = QHBoxLayout()
        self.size = StepSpinBox(FONT_SIZES)
        self.size.setObjectName("SizeBox")
        self.size.installEventFilter(self)
        self.size.lineEdit().installEventFilter(self)
        self.size.setRange(4, 200)
        self.size.setDecimals(1)
        self.size.setSuffix(" " + tr("pt"))
        self.size.setValue(12)
        self.bold = _control(QPushButton(tr("B", "bold")))
        self.bold.setCheckable(True)
        self.bold.setStyleSheet("font-weight: 800;")
        self.italic = _control(QPushButton(tr("I", "italic")))
        self.italic.setCheckable(True)
        self.italic.setStyleSheet("font-style: italic; font-family: serif;")
        self.underline = _control(QPushButton(tr("U", "underline")))
        self.underline.setCheckable(True)
        self.underline.setStyleSheet("text-decoration: underline;")
        self.bold.setToolTip(tr("Bold"))
        self.italic.setToolTip(tr("Italic"))
        self.underline.setToolTip(tr("Underline"))
        tl.addLayout(self.size.stepper())
        for b in (self.bold, self.italic, self.underline):
            row.addWidget(b, 1)
        tl.addLayout(row)
        self._swatch_buttons: list[widgets.Swatch] = []
        for color in SWATCHES:
            btn = _control(widgets.Swatch(color))
            btn.clicked.connect(lambda _=False, c=color: self._set_color(QColor(c)))
            self._swatch_buttons.append(btn)
        self.custom_color = _control(QPushButton(tr("Custom colour…")))
        self.custom_color.clicked.connect(self._pick_color)
        tl.addLayout(widgets.swatch_row(self._swatch_buttons))
        tl.addWidget(self.custom_color)
        layout.addWidget(self.text_box)

        self.family.currentIndexChanged.connect(self._font_selected)
        self.size.valueChanged.connect(self._emit_style)
        self.bold.toggled.connect(self._weight_toggled)
        self.italic.toggled.connect(self._weight_toggled)
        self.underline.toggled.connect(self._emit_style)

        # ---- highlight colour
        self.highlight_box = QWidget()
        hl = QVBoxLayout(self.highlight_box)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(8)
        hl.addWidget(_heading(tr("Highlight colour")))
        self.highlight_color = ColorPicker(HIGHLIGHT_SWATCHES, tr("Highlight colour"))
        self.highlight_color.changed.connect(self.highlightChanged)
        hl.addWidget(self.highlight_color)
        layout.addWidget(self.highlight_box)

        # ---- box border and fill
        self.box_box = QWidget()
        bl = QVBoxLayout(self.box_box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(8)
        bl.addWidget(_heading(tr("Border")))
        self.box_width = StepSpinBox(BORDER_WIDTHS)
        self.box_width.setRange(0, 24)
        self.box_width.setDecimals(1)
        self.box_width.setSuffix(" " + tr("pt"))
        self.box_width.setSpecialValueText(tr("No border"))
        # Apply a typed width once (on Enter or when leaving the box), not per digit.
        self.box_width.setKeyboardTracking(False)
        self.box_width.setToolTip(tr("Border width (0 for no border)"))
        self.box_color = ColorPicker(SWATCHES, tr("Border colour"))
        bl.addLayout(self.box_width.stepper())
        bl.addWidget(self.box_color)
        bl.addWidget(_heading(tr("Fill")))
        self.box_fill = ColorPicker(FILL_SWATCHES, tr("Fill colour"), allow_none=True)
        bl.addWidget(self.box_fill)
        layout.addWidget(self.box_box)
        self.set_box_style(BoxStyle())
        self.box_width.valueChanged.connect(self._emit_box)
        self.box_color.changed.connect(self._emit_box)
        self.box_fill.changed.connect(self._emit_box)

        # ---- image
        self.image_box = QWidget()
        il = QVBoxLayout(self.image_box)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(8)
        il.addWidget(_heading(tr("Image")))
        self.choose_image = _control(QPushButton(tr("Choose image…")))
        self.choose_image.clicked.connect(lambda: self.action.emit("choose_image"))
        self.place_image = _control(QPushButton(tr("Place image")))
        self.place_image.setProperty("primary", True)
        self.place_image.clicked.connect(lambda: self.action.emit("place_image"))
        self.cancel_image = _control(QPushButton(tr("Cancel")))
        self.cancel_image.clicked.connect(lambda: self.action.emit("cancel_image"))
        self.image_hint = QLabel(tr("Drag to move. Corners resize (Shift: free). The round "
                                    "handle rotates (Shift: no snapping). Arrow keys nudge."))
        self.image_hint.setWordWrap(True)
        self.image_hint.setProperty("role", "hint")
        rotate_row = QHBoxLayout()
        self.rotate_image_left = _control(QPushButton(tr("Rotate") + " ⟲"))
        self.rotate_image_left.clicked.connect(lambda: self.action.emit("rotate_image_left"))
        self.rotate_image_right = _control(QPushButton(tr("Rotate") + " ⟳"))
        self.rotate_image_right.clicked.connect(lambda: self.action.emit("rotate_image_right"))
        rotate_row.addWidget(self.rotate_image_left)
        rotate_row.addWidget(self.rotate_image_right)
        self.delete_image = _control(QPushButton(tr("Delete image")))
        self.delete_image.clicked.connect(lambda: self.action.emit("delete_selection"))
        il.addWidget(self.image_hint)
        il.addLayout(rotate_row)
        for w in (self.choose_image, self.place_image, self.cancel_image, self.delete_image):
            il.addWidget(w)
        layout.addWidget(self.image_box)

        # ---- selected text box
        self.textbox_box = QWidget()
        xl = QVBoxLayout(self.textbox_box)
        xl.setContentsMargins(0, 0, 0, 0)
        xl.setSpacing(8)
        xl.addWidget(_heading(tr("Text box")))
        hint = QLabel(tr("Drag to move. Arrow keys nudge by 1 pt, with Shift by 10 pt."))
        hint.setWordWrap(True)
        hint.setProperty("role", "hint")
        xl.addWidget(hint)
        self.delete_text = _control(QPushButton(tr("Delete text box")))
        self.delete_text.clicked.connect(lambda: self.action.emit("delete_selection"))
        xl.addWidget(self.delete_text)
        layout.addWidget(self.textbox_box)

        # ---- selected highlight or box
        self.markup_box = QWidget()
        ml = QVBoxLayout(self.markup_box)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(8)
        self.markup_heading = _heading(tr("Box"))
        self.markup_hint = QLabel(tr("Drag to move, drag a corner to resize. Arrow keys nudge."))
        self.markup_hint.setWordWrap(True)
        self.markup_hint.setProperty("role", "hint")
        self.delete_markup = _control(QPushButton())
        self.delete_markup.clicked.connect(lambda: self.action.emit("delete_selection"))
        ml.addWidget(self.markup_heading)
        ml.addWidget(self.markup_hint)
        ml.addWidget(self.delete_markup)
        layout.addWidget(self.markup_box)

        # ---- layer of the selected text box, image or box
        self.arrange_box = QWidget()
        al = QVBoxLayout(self.arrange_box)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(8)
        al.addWidget(_heading(tr("Arrange")))
        arrange = QGridLayout()
        arrange.setSpacing(6)
        for i, (key, label, tip) in enumerate((
            ("front", N_("To front"), N_("Bring to front (Ctrl+Shift+Page Up)")),
            ("forward", N_("Forward"), N_("Bring forward, past what it overlaps (Ctrl+Page Up)")),
            ("backward", N_("Backward"),
             N_("Send backward, behind what it overlaps (Ctrl+Page Down)")),
            ("back", N_("To back"), N_("Send to back (Ctrl+Shift+Page Down)")),
        )):
            btn = _control(QPushButton(tr(label)))
            btn.setToolTip(tr(tip))
            btn.clicked.connect(lambda _=False, k=key: self.action.emit(f"arrange_{k}"))
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            arrange.addWidget(btn, i // 2, i % 2)
        al.addLayout(arrange)
        layout.addWidget(self.arrange_box)

        # ---- page
        self.page_box = QWidget()
        pl = QVBoxLayout(self.page_box)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(8)
        pl.addWidget(_heading(tr("Page")))
        self.page_label = QLabel()
        self.page_label.setProperty("role", "hint")
        pl.addWidget(self.page_label)
        grid = QGridLayout()
        grid.setSpacing(6)
        buttons = [
            ("rotate_left", N_("Rotate left")),
            ("rotate_right", N_("Rotate right")),
            ("move_up", N_("Move up")),
            ("move_down", N_("Move down")),
            ("insert_blank", N_("Blank page")),
            ("insert_pdf", N_("Insert PDF…")),
        ]
        for i, (key, label) in enumerate(buttons):
            btn = _control(QPushButton(tr(label)))
            btn.clicked.connect(lambda _=False, k=key: self.action.emit(k))
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            grid.addWidget(btn, i // 2, i % 2)
        pl.addLayout(grid)
        delete = _control(QPushButton(tr("Delete page")))
        delete.clicked.connect(lambda: self.action.emit("delete"))
        pl.addWidget(delete)
        layout.addWidget(self.page_box)
        layout.addStretch(1)

        self.set_tool(Tool.SELECT)
        self.set_style(self._style)
        self.set_selection_state(placing=False, selected=None)
        # The width is fitted on the content's layout requests, once it is styled: measured
        # before the theme applies, Qt keeps the native style's sizes in nested layouts.

    def _fit_width(self) -> None:
        """Make the panel wide enough for its widest section, so nothing is cut off on
        the right (Swedish buttons are longer than English ones). Hidden sections count
        too, so the panel keeps its width when the tool or selection changes. Room is kept
        for the scroll bar, which appears when the window is too low for the sections."""
        layout = self._content.layout()
        need = 0
        for i in range(layout.count()):
            widget = layout.itemAt(i).widget()
            if widget is None:
                continue
            inner = widget.layout()
            need = max(need, inner.totalMinimumSize().width() if inner is not None
                       else widget.minimumSizeHint().width())
        margins = layout.contentsMargins()
        need += margins.left() + margins.right()
        need += self._scroll.verticalScrollBar().sizeHint().width() + 1  # + the left border
        width = max(WIDTH, need)
        if width != self.width():
            self.setFixedWidth(width)

    # -------------------------------------------------------------- state
    def set_tool(self, tool: Tool) -> None:
        self.tool = tool
        self.tool_title.setText(tr(TITLES[tool]))
        self.hint.setText(tr(HINTS[tool]))
        self.text_box.setVisible(tool in (Tool.EDIT_TEXT, Tool.ADD_TEXT))

    def set_selection_state(self, placing: bool, selected: str | None) -> None:
        """``selected`` is "image", "text", "highlight", "box" or None."""
        image = selected == "image"
        self.image_box.setVisible(placing or image or self.tool == Tool.ADD_IMAGE)
        self.choose_image.setVisible(self.tool == Tool.ADD_IMAGE and not placing)
        self.place_image.setVisible(placing)
        self.cancel_image.setVisible(placing)
        self.delete_image.setVisible(image and not placing)
        self.image_hint.setVisible(placing or image)
        for b in (self.rotate_image_left, self.rotate_image_right):
            b.setVisible(image and not placing)
        self.textbox_box.setVisible(selected == "text" and not placing)
        # The colour and border controls also edit a selected highlight or box.
        self.highlight_box.setVisible(self.tool == Tool.HIGHLIGHT or selected == "highlight")
        self.box_box.setVisible(self.tool == Tool.ADD_BOX or selected == "box")
        self.markup_box.setVisible(selected in ("highlight", "box") and not placing)
        self.arrange_box.setVisible(selected in ("text", "image", "box") and not placing)
        # Their controls need the room; the section has its own short hint.
        self.hint.setVisible(selected not in ("highlight", "box"))
        if selected in ("highlight", "box"):
            box = selected == "box"
            self.markup_heading.setText((tr("Box") if box else tr("Highlight", "noun")).upper())
            self.markup_hint.setVisible(box)
            self.delete_markup.setText(tr("Delete box") if box else tr("Delete highlight"))

    def set_highlight_color(self, color: Rgb) -> None:
        self.highlight_color.set_color(color)

    def box_style(self) -> BoxStyle:
        return BoxStyle(round(self.box_width.value(), 1), self.box_color.color(),
                        self.box_fill.color())

    def set_box_style(self, style: BoxStyle) -> None:
        self._updating = True
        self.box_width.setValue(style.width)
        self.box_color.set_color(style.color)
        self.box_fill.set_color(style.fill)
        self._updating = False

    def _emit_box(self) -> None:
        if not self._updating:
            self.boxChanged.emit(self.box_style())

    def set_page_info(self, current: int, total: int) -> None:
        self.page_label.setText(tr("Page {page} of {count}", page=current + 1, count=total)
                                if total else tr("No document"))

    def set_document_fonts(self, faces: list[DocFace]) -> None:
        """Offer the font faces used in the open document in the picker."""
        if [f.label for f in faces] != [f.label for f in self._doc_fonts]:
            self._doc_fonts = list(faces)
            self._fill_fonts()

    def _face(self, label: str | None) -> DocFace | None:
        return next((f for f in self._doc_fonts if label and f.label == label), None)

    def _fill_fonts(self) -> None:
        was = self._updating
        self._updating = True
        self.family.clear()
        installed = {f.lower() for f in QFontDatabase.families()}
        for face in self._doc_fonts:
            self.family.addItem(face.label, f"doc:{face.label}")
            if face.family.lower() in installed:  # preview the face in the list itself
                font = QFont(face.family)
                font.setWeight(QFont.Weight(face.weight))
                font.setItalic(face.italic)
                self.family.setItemData(self.family.count() - 1, font,
                                        Qt.ItemDataRole.FontRole)
        if self._doc_fonts:
            self.family.insertSeparator(self.family.count())
        for label, code in FONT_FAMILIES.items():
            self.family.addItem(tr(label), f"std:{code}")
        self._select_font(self._style)
        self._updating = was

    def _select_font(self, style: TextStyle) -> None:
        key = f"doc:{style.font}" if style.font else f"std:{style.family}"
        index = self.family.findData(key)
        if index < 0 and style.font:
            # Used by this text but not listed yet (e.g. a font inside a form).
            self.family.insertItem(0, style.font, key)
            index = 0
        self.family.setCurrentIndex(max(index, 0))
        self.family.setToolTip(tr("Font of this text: {font}", font=self.family.currentText()))

    def set_style(self, style: TextStyle) -> None:
        self._updating = True
        self._style = TextStyle(**vars(style))
        self._select_font(style)
        self.size.setValue(style.size)
        self.bold.setChecked(style.bold)
        self.italic.setChecked(style.italic)
        self.underline.setChecked(style.underline)
        self._refresh_swatches()
        self._updating = False

    def style(self) -> TextStyle:  # noqa: A003 - mirrors Qt naming
        return TextStyle(**vars(self._style))

    # ------------------------------------------------------------ helpers
    def _refresh_swatches(self) -> None:
        current = QColor.fromRgbF(*self._style.color).name()
        for btn in self._swatch_buttons:
            btn.set_selected(btn.color == current)
        self.custom_color.setIcon(widgets.colour_icon(current))
        self.custom_color.setToolTip(current)

    def _set_color(self, color: QColor) -> None:
        self._style.color = (color.redF(), color.greenF(), color.blueF())
        self._refresh_swatches()
        self._emit_style()

    def _pick_color(self) -> None:
        color = QColorDialog.getColor(QColor.fromRgbF(*self._style.color), self, tr("Text colour"))
        if color.isValid():
            self._set_color(color)

    def _font_selected(self) -> None:
        if self._updating:
            return
        kind, _, value = (self.family.currentData() or "std:helv").partition(":")
        face = self._face(value) if kind == "doc" else None
        if face is not None:
            face.apply(self._style)
        elif kind == "doc":  # listed for this text only (no face details)
            self._style.font = value
            self._style.typeface = self._style.typeface or value
            self._style.family = fallback_family(value)
        else:
            self._style.font = self._style.typeface = None
            self._style.family = value
            self._style.weight = 700 if self._style.bold else 400
        self._sync_toggles()
        self._emit_style()

    def _weight_toggled(self) -> None:
        """B/I: move to the document's matching face of the same family, if it has one."""
        if self._updating:
            return
        st = self._style
        bold, italic = self.bold.isChecked(), self.italic.isChecked()
        if bold != st.bold:
            st.weight = 700 if bold else 400
        st.bold, st.italic = bold, italic
        if st.typeface:
            match = next((f for f in self._doc_fonts
                          if f.family.lower() == st.typeface.lower() and f.italic == italic
                          and (f.weight >= 600) == bold), None)
            if match is not None:
                match.apply(st)
                self._updating = True
                self._select_font(st)
                self._updating = False
        self._emit_style()

    def _sync_toggles(self) -> None:
        self._updating = True
        self.bold.setChecked(self._style.bold)
        self.italic.setChecked(self._style.italic)
        self._updating = False

    def _emit_style(self) -> None:
        if self._updating:
            return
        self.family.setToolTip(tr("Font of this text: {font}", font=self.family.currentText()))
        self._style.size = round(self.size.value(), 2)
        self._style.underline = self.underline.isChecked()
        self.styleChanged.emit(self.style())

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self._content:
            if event.type() == QEvent.Type.LayoutRequest:
                self._fit_width()
            return False
        # Enter/Esc in the size box: apply and go back to typing on the page.
        if event.type() == QEvent.Type.KeyPress and event.key() in (
            Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape
        ):
            self.size.interpretText()
            self.returnToEditor.emit()
            return True
        return super().eventFilter(obj, event)
