"""Headless GUI tests: drive the main window like a user would."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")

import pymupdf as fitz  # noqa: E402
from PySide6.QtCore import QPoint, QPointF, QSettings, Qt  # noqa: E402
from PySide6.QtGui import QKeySequence  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from pixa.document import BoxStyle  # noqa: E402
from pixa.ui.main_window import MainWindow  # noqa: E402
from pixa.ui.page_view import Tool  # noqa: E402


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path, sample_pdf):
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    w = MainWindow()
    w.errors = []
    w.show_error = w.errors.append  # record instead of opening a modal dialog
    w.resize(1200, 800)
    w.show()
    assert w.open_path(sample_pdf, ask_save=False)
    pump(app)
    yield w
    if w.doc:
        w.doc.dirty = False
    w.close()


def pump(app, n=20):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(5)


def click_page(window, page, x, y):
    v = window.view
    pos = v.mapFromScene(v.pages[page].pos() + QPointF(x * v.zoom, y * v.zoom))
    QTest.mouseClick(v.viewport(), Qt.MouseButton.LeftButton, pos=pos)


def test_opens_document(window):
    assert window.stack.currentIndex() == 1
    assert len(window.view.pages) == 3
    assert window.thumbs.count() == 3
    assert "sample.pdf" in window.windowTitle()


def test_edit_existing_text(window, app):
    window.set_tool(Tool.EDIT_TEXT)
    line = window.doc.text_lines(0)[0]
    center = line.bbox.tl + (line.bbox.br - line.bbox.tl) * 0.5
    click_page(window, 0, center.x, center.y)
    pump(app)
    editor = window.view._editor
    assert editor is not None and editor.toPlainText() == "Page 1 title"
    QTest.keyClicks(editor, "Edited heading")
    QTest.keyClick(editor, Qt.Key.Key_Return)
    pump(app)
    text = window.doc.doc[0].get_text()
    assert "Edited heading" in text and "Page 1 title" not in text
    assert window.doc.dirty and "•" in window.windowTitle()


def test_escape_cancels_edit(window, app):
    window.set_tool(Tool.EDIT_TEXT)
    line = window.doc.text_lines(0)[1]
    click_page(window, 0, line.bbox.x0 + 5, (line.bbox.y0 + line.bbox.y1) / 2)
    pump(app)
    QTest.keyClicks(window.view._editor, "nope")
    QTest.keyClick(window.view._editor, Qt.Key.Key_Escape)
    pump(app)
    assert not window.doc.can_undo
    assert window.view._editor is None


def test_add_text_uses_add_style(window, app):
    window.set_tool(Tool.ADD_TEXT)
    click_page(window, 1, 100, 400)
    pump(app)
    QTest.keyClicks(window.view._editor, "Hello Pixa")
    QTest.keyClick(window.view._editor, Qt.Key.Key_Return)
    pump(app)
    added = [ln for ln in window.doc.text_lines(1) if ln.text == "Hello Pixa"]
    assert added and added[0].style.size == pytest.approx(12)
    assert added[0].style.color == pytest.approx((0, 0, 0))


def test_select_and_delete_image(window, app):
    window.set_tool(Tool.SELECT)
    click_page(window, 0, 350, 350)
    pump(app)
    assert window.view.selected_image is not None
    assert window.inspector.delete_image.isVisibleTo(window.inspector)
    window.delete_selection()
    pump(app)
    assert window.doc.images(0) == []
    window.undo()
    pump(app)
    assert len(window.doc.images(0)) == 1


def test_place_image(window, app, tmp_path, png_bytes):
    img = tmp_path / "pic.png"
    img.write_bytes(png_bytes)
    window.view.scroll_to_page(2)
    pump(app)
    assert window.view.begin_image_placement(str(img))
    assert window.inspector.place_image.isVisibleTo(window.inspector)
    QTest.keyClick(window.view, Qt.Key.Key_Return)
    pump(app)
    assert len(window.doc.images(2)) == 1


def test_page_operations(window, app):
    window.thumbs.setCurrentRow(1)
    window.rotate(90)
    pump(app)
    assert window.doc.doc[1].rotation == 90
    assert window.view.pages[1].size.width() > window.view.pages[1].size.height()
    window.thumbs.orderChanged.emit([2, 0, 1])  # what a drag & drop produces
    pump(app)
    assert window.doc.doc[0].get_text().startswith("Page 3")
    window.thumbs.setCurrentRow(0)
    window.delete_pages()
    pump(app)
    assert window.doc.page_count == 2 and window.thumbs.count() == 2
    window.insert_blank()
    pump(app)
    assert window.doc.page_count == 3
    window.undo()
    window.undo()
    pump(app)
    assert window.doc.page_count == 3
    assert window.doc.doc[0].get_text().startswith("Page 3")


def test_move_pages(window, app):
    window.thumbs.setCurrentRow(0)
    window.move_pages(1)
    pump(app)
    assert window.doc.doc[1].get_text().startswith("Page 1")
    assert window.thumbs.selected_pages() == [1]


def test_save_asks_before_overwriting(window, app, sample_pdf, monkeypatch):
    from pixa.document import PdfDocument

    asked = []
    monkeypatch.setattr(window, "_ask_overwrite", lambda name: asked.append(name) or "cancel")
    window.rotate(180)
    assert not window.save()  # cancelled: nothing written
    assert PdfDocument.open(sample_pdf).doc[0].rotation == 0
    assert window.doc.dirty

    monkeypatch.setattr(window, "_ask_overwrite", lambda name: asked.append(name) or "overwrite")
    assert window.save()
    assert asked == ["sample.pdf", "sample.pdf"]
    assert not window.doc.dirty
    assert PdfDocument.open(sample_pdf).doc[0].rotation == 180

    window.rotate(90)
    assert window.save()  # confirmed once per document: no second prompt
    assert len(asked) == 2


def test_save_as_copy_keeps_original(window, app, sample_pdf, tmp_path, monkeypatch):
    from pixa.document import PdfDocument
    from pixa.ui import main_window

    copy = tmp_path / "copy.pdf"
    monkeypatch.setattr(window, "_ask_overwrite", lambda name: "copy")
    monkeypatch.setattr(
        main_window.QFileDialog, "getSaveFileName", lambda *a, **k: (str(copy), "")
    )
    window.rotate(90)
    assert window.save()
    assert PdfDocument.open(sample_pdf).doc[0].rotation == 0
    assert PdfDocument.open(str(copy)).doc[0].rotation == 90
    assert window.doc.path == str(copy)


def test_thumbnail_click_scrolls_view(window, app):
    window.resize(1200, 500)  # short window so pages need scrolling
    pump(app)
    rect = window.thumbs.visualItemRect(window.thumbs.item(1))
    QTest.mouseClick(window.thumbs.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    pump(app)
    top = window.view.mapToScene(0, 0).y()
    assert abs(top - window.view.pages[1].pos().y()) < 30
    assert window.view.current_page == 1


def test_editor_survives_window_deactivation(window, app):
    from PySide6.QtWidgets import QWidget

    window.set_tool(Tool.EDIT_TEXT)
    line = window.doc.text_lines(0)[1]
    click_page(window, 0, line.bbox.x0 + 5, (line.bbox.y0 + line.bbox.y1) / 2)
    pump(app)
    assert window.view.is_editing
    other = QWidget()
    other.show()
    other.activateWindow()
    pump(app, 30)
    assert window.view.is_editing  # e.g. focus-follows-mouse moved focus away
    other.close()
    window.activateWindow()
    pump(app)
    QTest.keyClick(window.view._editor, Qt.Key.Key_Escape)
    pump(app)
    assert not window.view.is_editing


def test_drag_text_box(window, app):
    window.set_tool(Tool.SELECT)
    block = next(b for b in window.doc.text_blocks(0) if b.text.startswith("The quick"))
    v = window.view
    start = v.mapFromScene(v._scene_rect(0, block.bbox).center())
    QTest.mousePress(v.viewport(), Qt.MouseButton.LeftButton, pos=start)
    pump(app)
    assert v.selected_text is not None
    delta = QPoint(round(100 * v.zoom), round(200 * v.zoom))
    for i in range(1, 6):  # move in steps like a real drag
        QTest.mouseMove(v.viewport(), start + delta * (i / 5))
        pump(app, 2)
    QTest.mouseRelease(v.viewport(), Qt.MouseButton.LeftButton, pos=start + delta)
    pump(app)
    moved = next(b for b in window.doc.text_blocks(0) if b.text.startswith("The quick"))
    assert moved.bbox.x0 == pytest.approx(block.bbox.x0 + 100, abs=2)
    assert moved.bbox.y0 == pytest.approx(block.bbox.y0 + 200, abs=2)
    assert v.selected_text is not None  # stays selected for further moves
    QTest.keyClick(v, Qt.Key.Key_Left, Qt.KeyboardModifier.ShiftModifier)
    pump(app)
    nudged = next(b for b in window.doc.text_blocks(0) if b.text.startswith("The quick"))
    assert nudged.bbox.x0 == pytest.approx(moved.bbox.x0 - 10, abs=0.5)
    window.delete_selection()
    pump(app)
    assert "The quick" not in window.doc.doc[0].get_text()


def test_editor_survives_style_changes_in_inspector(window, app):
    insp = window.inspector
    window.set_tool(Tool.EDIT_TEXT)
    line = window.doc.text_lines(0)[1]
    click_page(window, 0, line.bbox.x0 + 5, (line.bbox.y0 + line.bbox.y1) / 2)
    pump(app)
    editor = window.view._editor
    QTest.keyClicks(editor, "Typed on the page")
    # Size box: click into it and type; nothing may leak into the page text.
    QTest.mouseClick(insp.size.lineEdit(), Qt.MouseButton.LeftButton)
    pump(app)
    insp.size.lineEdit().selectAll()
    QTest.keyClicks(insp.size.lineEdit(), "18")
    pump(app)
    assert window.view.is_editing
    assert editor.toPlainText() == "Typed on the page"
    QTest.keyClick(insp.size.lineEdit(), Qt.Key.Key_Return)  # back to the editor
    pump(app)
    assert editor.hasFocus()
    # Font combo popup, a colour swatch and the underline toggle.
    insp.family.showPopup()
    pump(app)
    insp.family.hidePopup()
    insp.family.setCurrentIndex(insp.family.findData("std:cour"))
    assert insp._swatch_buttons[0].is_selected()  # black, the default
    QTest.mouseClick(insp._swatch_buttons[2], Qt.MouseButton.LeftButton)
    assert [b.is_selected() for b in insp._swatch_buttons].index(True) == 2
    QTest.mouseClick(insp.underline, Qt.MouseButton.LeftButton)
    pump(app, 30)
    assert window.view.is_editing and editor.hasFocus()
    QTest.keyClick(editor, Qt.Key.Key_Return)
    pump(app)
    edited = next(ln for ln in window.doc.text_lines(0) if ln.text == "Typed on the page")
    assert edited.style.size == pytest.approx(18)
    assert edited.style.family == "cour"
    assert edited.style.underline


def _select_image(window, app):
    window.set_tool(Tool.SELECT)
    click_page(window, 0, 350, 350)  # the sample image spans 300..400
    pump(app)
    t = window.view._transformer
    assert t is not None and window.view.selected_image is not None
    return t


def _drag(view, start, end, modifiers=Qt.KeyboardModifier.NoModifier):
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, modifiers, start)
    for i in range(1, 6):
        QTest.mouseMove(view.viewport(), start + (end - start) * (i / 5))
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, modifiers, end)


def test_drag_image_moves_it(window, app):
    v = window.view
    t = _select_image(window, app)
    start = v.mapFromScene(t.center)
    _drag(v, start, start + QPoint(round(50 * v.zoom), round(30 * v.zoom)))
    pump(app)
    geo = window.doc.image_geometry(window.doc.images(0)[0])
    assert (geo.center.x, geo.center.y) == pytest.approx((400, 380), abs=1.5)
    assert v.selected_image is not None  # still selected for more changes
    assert not window.errors


def test_rotate_handle_snaps(window, app):
    v = window.view
    t = _select_image(window, app)
    handle = v.mapFromScene(t.mapToScene(t._rotate_handle()))
    center = v.mapFromScene(t.center)
    # Drag the handle to the right of the centre: a quarter turn clockwise (snapped).
    _drag(v, handle, center + QPoint(round(120 * v.zoom), 3))
    pump(app)
    geo = window.doc.image_geometry(window.doc.images(0)[0])
    assert geo.angle % 360 == pytest.approx(90, abs=0.01)
    assert (geo.width, geo.height) == pytest.approx((100, 100), abs=1)


def test_corner_resize_keeps_aspect(window, app):
    v = window.view
    t = _select_image(window, app)
    corner = v.mapFromScene(t.mapToScene(t._corners()[2]))  # bottom-right
    _drag(v, corner, corner + QPoint(round(100 * v.zoom), round(20 * v.zoom)))
    pump(app)
    geo = window.doc.image_geometry(window.doc.images(0)[0])
    assert geo.width == pytest.approx(200, abs=2) and geo.height == pytest.approx(200, abs=2)
    # The opposite (top-left) corner stayed where it was.
    assert (geo.center.x - geo.width / 2, geo.center.y - geo.height / 2) == pytest.approx(
        (300, 300), abs=2
    )


def test_inspector_rotates_and_arrow_keys_nudge_image(window, app):
    v = window.view
    _select_image(window, app)
    QTest.mouseClick(window.inspector.rotate_image_right, Qt.MouseButton.LeftButton)
    pump(app)
    geo = window.doc.image_geometry(window.doc.images(0)[0])
    assert geo.angle % 360 == pytest.approx(90, abs=0.01)
    QTest.keyClick(v, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
    pump(app)
    moved = window.doc.image_geometry(window.doc.images(0)[0])
    assert moved.center.x == pytest.approx(geo.center.x + 10, abs=0.1)


def _page_pos(view, page, x, y):
    return view.mapFromScene(view.pages[page].pos() + QPointF(x * view.zoom, y * view.zoom))


def test_highlight_text_with_chosen_colour(window, app):
    v, insp = window.view, window.inspector
    window.set_tool(Tool.HIGHLIGHT)
    assert insp.highlight_box.isVisibleTo(insp) and not insp.box_box.isVisibleTo(insp)
    QTest.mouseClick(insp.highlight_color.buttons[1], Qt.MouseButton.LeftButton)  # green
    body = window.doc.text_lines(0)[1]
    y = (body.bbox.y0 + body.bbox.y1) / 2
    _drag(v, _page_pos(v, 0, body.bbox.x0 + 2, y), _page_pos(v, 0, body.bbox.x1 - 2, y))
    pump(app)
    (mark,) = window.doc.markups(0)
    assert mark.kind == "highlight"
    assert mark.color == pytest.approx(insp.highlight_color.color(), abs=0.01)
    assert mark.color[1] > mark.color[0] and mark.color[1] > mark.color[2]
    assert mark.bbox.x0 == pytest.approx(body.bbox.x0, abs=1)
    assert mark.bbox.x1 == pytest.approx(body.bbox.x1, abs=1)
    assert window.a_undo.text() == "Undo Highlight"
    # Select it again and delete it.
    window.set_tool(Tool.SELECT)
    click_page(window, 0, body.bbox.x0 + 5, y)
    pump(app)
    assert v.selected_markup is not None
    assert insp.markup_box.isVisibleTo(insp) and insp.delete_markup.text() == "Delete highlight"
    window.delete_selection()
    pump(app)
    assert window.doc.markups(0) == []
    assert "The quick brown fox" in window.doc.doc[0].get_text()


def test_draw_move_and_delete_box(window, app):
    v, insp = window.view, window.inspector
    window.set_tool(Tool.ADD_BOX)
    assert insp.box_box.isVisibleTo(insp)
    insp.box_width.setValue(3)
    QTest.mouseClick(insp.box_color.buttons[5], Qt.MouseButton.LeftButton)  # blue border
    QTest.mouseClick(insp.box_fill.buttons[2], Qt.MouseButton.LeftButton)  # pale yellow fill
    _drag(v, _page_pos(v, 1, 100, 400), _page_pos(v, 1, 260, 480))
    pump(app)
    (box,) = window.doc.markups(1)
    assert box.kind == "box" and box.width == pytest.approx(3)
    assert box.color == pytest.approx(insp.box_color.color(), abs=0.01)
    assert box.fill == pytest.approx(insp.box_fill.color(), abs=0.01)
    assert tuple(box.bbox) == pytest.approx((100, 400, 260, 480), abs=1.5)
    # Transparent fill for the next one; a click without dragging draws nothing.
    QTest.mouseClick(insp.box_fill.buttons[0], Qt.MouseButton.LeftButton)
    click_page(window, 1, 300, 600)
    _drag(v, _page_pos(v, 1, 300, 600), _page_pos(v, 1, 380, 640))
    pump(app)
    boxes = window.doc.markups(1)
    assert len(boxes) == 2 and boxes[1].fill is None
    # Text inside a hollow box is still selectable; the box is picked by its border.
    window.set_tool(Tool.SELECT)
    title = window.doc.text_lines(1)[0].bbox
    window.doc.add_box(1, title + (-8, -8, 8, 8), window.view.box_style)
    click_page(window, 1, title.x0 + 5, (title.y0 + title.y1) / 2)
    pump(app)
    assert v.selected_text is not None
    click_page(window, 1, title.x0 - 8, (title.y0 + title.y1) / 2)
    pump(app)
    assert v.selected_markup is not None
    window.delete_selection()
    pump(app)
    # Move the first box with the Select tool, nudge it, then delete it.
    window.set_tool(Tool.SELECT)
    _drag(v, _page_pos(v, 1, 180, 440), _page_pos(v, 1, 230, 500))
    pump(app)
    moved = window.doc.markups(1)[0]
    assert tuple(moved.bbox) == pytest.approx((150, 460, 310, 540), abs=2.5)
    assert v.selected_markup is not None and insp.delete_markup.text() == "Delete box"
    QTest.keyClick(v, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
    pump(app)
    assert window.doc.markups(1)[0].bbox.x0 == pytest.approx(moved.bbox.x0 + 10, abs=0.1)
    window.delete_selection()
    pump(app)
    assert len(window.doc.markups(1)) == 1
    assert not window.errors


def _add_and_select_box(window, app, style):
    window.doc.add_box(1, fitz.Rect(100, 400, 260, 480), style)
    window.set_tool(Tool.SELECT)
    click_page(window, 1, 180, 440)
    pump(app)
    assert window.view.selected_markup is not None
    return window.view._transformer


def test_resize_selected_box_by_corner(window, app):
    v = window.view
    t = _add_and_select_box(window, app, BoxStyle(2, (1, 0, 0), (1, 1, 0)))
    assert t is not None and not t.rotatable
    # Bottom-right corner, dragged freely (no fixed proportions for a box).
    _drag(v, _page_pos(v, 1, 260, 480), _page_pos(v, 1, 300, 560))
    pump(app)
    (box,) = window.doc.markups(1)
    assert tuple(box.bbox) == pytest.approx((100, 400, 300, 560), abs=1.5)
    assert window.a_undo.text() == "Undo Resize box"
    assert v.selected_markup is not None and v._transformer is not None
    # Dragging the selected box itself moves it without changing its size.
    _drag(v, _page_pos(v, 1, 200, 480), _page_pos(v, 1, 220, 500))
    pump(app)
    (box,) = window.doc.markups(1)
    assert tuple(box.bbox) == pytest.approx((120, 420, 320, 580), abs=1.5)
    assert box.style == BoxStyle(2, pytest.approx((1, 0, 0)), pytest.approx((1, 1, 0)))
    assert not window.errors


def test_restyle_selected_box_in_inspector(window, app):
    v, insp = window.view, window.inspector
    QTest.mouseClick(v.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(5, 5))
    remembered = insp.box_style()
    _add_and_select_box(window, app, BoxStyle(5, (0, 0, 0), (1, 1, 1)))
    # The controls show the selected box, not the style for new boxes.
    assert insp.box_box.isVisibleTo(insp)
    assert insp.box_width.value() == pytest.approx(5)
    assert insp.box_fill.color() == pytest.approx((1, 1, 1))
    assert v.box_style == remembered
    steps = len(window.doc._undo)
    QTest.mouseClick(insp.box_color.buttons[5], Qt.MouseButton.LeftButton)  # blue border
    QTest.mouseClick(insp.box_color.buttons[5], Qt.MouseButton.LeftButton)  # again: no change
    QTest.mouseClick(insp.box_fill.buttons[0], Qt.MouseButton.LeftButton)  # transparent
    pump(app)
    (box,) = window.doc.markups(1)
    assert box.color == pytest.approx(insp.box_color.color(), abs=0.01) and box.color[2] > 0.8
    assert box.fill is None and box.width == pytest.approx(5)
    assert len(window.doc._undo) == steps + 2
    # Typing a width: applied once on Enter, and Backspace edits the number
    # instead of deleting the selected box.
    field = insp.box_width.lineEdit()
    QTest.mouseClick(field, Qt.MouseButton.LeftButton)
    field.selectAll()
    QTest.keyClicks(field, "13")
    QTest.keyClick(field, Qt.Key.Key_Backspace)
    QTest.keyClicks(field, "2")
    QTest.keyClick(field, Qt.Key.Key_Return)
    pump(app)
    (box,) = window.doc.markups(1)
    assert box.width == pytest.approx(12)
    assert tuple(box.bbox) == pytest.approx((100, 400, 260, 480))
    assert len(window.doc._undo) == steps + 3
    assert v.selected_markup is not None
    # The edited style is the one new boxes get, also next time.
    assert v.box_style == insp.box_style()
    assert window.settings.value("box_fill") == "none"
    assert float(window.settings.value("box_width")) == pytest.approx(12)
    # Another box keeps its own look; deselecting shows the remembered style again.
    window.doc.add_box(2, fitz.Rect(100, 400, 260, 480), BoxStyle(1, (0, 0, 0), (1, 1, 1)))
    v.scroll_to_page(2)
    pump(app)
    click_page(window, 2, 180, 440)
    pump(app)
    assert insp.box_width.value() == pytest.approx(1)
    assert v.box_style.width == pytest.approx(12)
    QTest.keyClick(v, Qt.Key.Key_Escape)
    pump(app)
    assert v.selected is None and insp.box_width.value() == pytest.approx(12)
    assert not window.errors


def test_recolour_selected_highlight(window, app):
    v, insp = window.view, window.inspector
    body = window.doc.text_lines(0)[1]
    window.doc.add_highlight(0, [body.bbox], (1, 0.5, 0))
    window.set_tool(Tool.SELECT)
    click_page(window, 0, body.bbox.x0 + 5, (body.bbox.y0 + body.bbox.y1) / 2)
    pump(app)
    assert insp.highlight_box.isVisibleTo(insp)
    assert insp.highlight_color.color() == pytest.approx((1, 0.5, 0), abs=0.01)
    QTest.mouseClick(insp.highlight_color.buttons[2], Qt.MouseButton.LeftButton)  # blue
    pump(app)
    (mark,) = window.doc.markups(0)
    assert mark.color == pytest.approx(insp.highlight_color.color(), abs=0.01)
    assert mark.color[2] > mark.color[0] and v.selected_markup is not None


def test_size_and_width_step_through_common_values(window, app):
    insp = window.inspector
    window.set_tool(Tool.ADD_TEXT)
    assert insp.size.value() == pytest.approx(12)
    QTest.mouseClick(insp.size.plus, Qt.MouseButton.LeftButton)
    assert insp.size.value() == pytest.approx(14)
    assert window.add_text_style.size == pytest.approx(14)  # applied like a typed size
    insp.size.setValue(13)  # a typed in-between size steps to its neighbours
    QTest.mouseClick(insp.size.minus, Qt.MouseButton.LeftButton)
    assert insp.size.value() == pytest.approx(12)
    QTest.mouseClick(insp.size.minus, Qt.MouseButton.LeftButton)
    assert insp.size.value() == pytest.approx(11)
    QTest.keyClick(insp.size.lineEdit(), Qt.Key.Key_Up)
    assert insp.size.value() == pytest.approx(12)
    # Border width: steps for new boxes and for the selected one.
    _add_and_select_box(window, app, BoxStyle(2, (1, 0, 0), None))
    QTest.mouseClick(insp.box_width.plus, Qt.MouseButton.LeftButton)
    pump(app)
    assert window.doc.markups(1)[0].width == pytest.approx(3)
    for _ in range(6):
        QTest.mouseClick(insp.box_width.minus, Qt.MouseButton.LeftButton)
    pump(app)
    assert insp.box_width.value() == 0  # stops at "No border"
    # The border is gone, also from a box without a fill; a hint says why nothing shows.
    assert window.doc.markups(1)[0].style == BoxStyle(0, BoxStyle().color, None)
    assert "invisible" in window.statusBar().currentMessage()
    QTest.mouseClick(insp.box_fill.buttons[2], Qt.MouseButton.LeftButton)
    pump(app)
    assert window.doc.markups(1)[0].fill is not None
    assert window.view.selected_markup is not None and not window.errors


def test_text_typed_on_a_box_is_on_top_and_selectable(window, app):
    v = window.view
    window.doc.add_box(1, fitz.Rect(100, 400, 300, 480), BoxStyle(1, (0, 0, 0), (1, 1, 0)))
    window.set_tool(Tool.ADD_TEXT)
    click_page(window, 1, 120, 430)
    pump(app)
    QTest.keyClicks(v._editor, "On the box")
    QTest.keyClick(v._editor, Qt.Key.Key_Return)
    pump(app)
    line = next(ln for ln in window.doc.text_lines(1) if ln.text == "On the box")
    image = window.doc.doc[1].get_pixmap(clip=line.bbox)
    assert any(sum(image.pixel(x, y)) < 150 for x in range(image.width)
               for y in range(image.height))  # dark glyphs show on the yellow fill
    window.set_tool(Tool.SELECT)
    click_page(window, 1, 280, 470)  # the box, away from the text
    pump(app)
    assert v.selected_markup is not None
    middle = line.bbox.tl + (line.bbox.br - line.bbox.tl) * 0.5
    click_page(window, 1, middle.x, middle.y)  # the text, although the box is selected
    pump(app)
    assert v.selected_text is not None and v.selected_text.text == "On the box"
    assert not window.errors


# ------------------------------------------------------------------ printing
def test_print_to_pdf(window, app, tmp_path, monkeypatch):
    from PySide6.QtGui import QKeySequence
    from PySide6.QtPrintSupport import QPrinter

    from pixa.ui import printing

    assert window.a_print.shortcuts()[0] == QKeySequence(QKeySequence.StandardKey.Print)
    window.doc.rotate_pages([1], 90)  # a landscape page is turned to fill the paper
    out = tmp_path / "printed.pdf"

    def choose(printer):
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(str(out))
        printer.setResolution(72)
        return [0, 1], printing.Layout()

    monkeypatch.setattr(window, "_print_choice", choose)
    assert window.print_document()
    printed = fitz.open(str(out))
    assert printed.page_count == 2
    assert printed[0].get_images() and not printed[0].get_text().strip()  # pages as pictures
    pix = printed[1].get_pixmap()
    assert pix.width < pix.height  # still portrait paper


def test_page_ranges_and_scaling():
    from pixa.ui.printing import Layout, Sizing, page_scale, parse_pages

    assert parse_pages("1-3, 5", 6) == [0, 1, 2, 4]
    assert parse_pages(" -2 , 5- ", 6) == [0, 1, 4, 5]
    assert parse_pages("4", 6) == [3]
    for bad in ("", "0", "7", "3-2", "a", "-", "1-3,x"):
        with pytest.raises(ValueError):
            parse_pages(bad, 6)
    page, small_area, big_area = (600, 800), (300, 400), (1200, 1600)
    assert page_scale(Layout(), page, small_area, 1) == 0.5  # fitted, down
    assert page_scale(Layout(), page, big_area, 1) == 2  # and up
    assert page_scale(Layout(Sizing.ACTUAL), page, small_area, 1) == 1
    assert page_scale(Layout(Sizing.SHRINK), page, small_area, 1) == 0.5
    assert page_scale(Layout(Sizing.SHRINK), page, big_area, 1) == 1
    assert page_scale(Layout(Sizing.CUSTOM, scale=150), page, big_area, 2) == 3


def test_windows_driver_settings_round_trip():
    from pixa.ui import winprint

    dm = winprint.DEVMODEW()
    chosen = winprint.DriverSettings(paper=9, landscape=True, copies=3, collate=False,
                                     duplex=winprint.DMDUP_HORIZONTAL, color=False)
    winprint.write_devmode(dm, chosen)
    assert winprint.read_devmode(dm, winprint.DriverSettings()) == chosen
    # Fields the driver doesn't set keep what the dialog had.
    dm.dmFields = winprint.DM_COPIES
    dm.dmCopies = 2
    kept = winprint.read_devmode(dm, winprint.DriverSettings(paper=1, duplex=2))
    assert (kept.copies, kept.paper, kept.duplex, kept.landscape) == (2, 1, 2, False)


def test_print_dialog(window, app, tmp_path, monkeypatch):
    from PySide6.QtGui import QPageLayout, QPageSize
    from PySide6.QtPrintSupport import QPrinter

    from pixa.ui import printing, winprint
    from pixa.ui.print_dialog import PrintDialog
    from pixa.ui.printing import Sizing

    window.doc.rotate_pages([2], 90)
    dialog = PrintDialog(window.doc, 1, [0, 2], window)
    dialog.show()
    pump(app, 40)
    assert dialog.selection.isChecked() and dialog.pages() == [0, 2]
    assert dialog.page_count() == 2 and dialog.page_label.text() == "Page 1 of 2"
    dialog.next.click()
    assert dialog.page_label.text() == "Page 2 of 2" and not dialog.next.isEnabled()
    assert dialog.doc_size.text() == "Document: 297.0 × 209.9 mm"  # the turned page
    dialog.current.setChecked(True)
    assert dialog.pages() == [1]
    dialog.all_pages.setChecked(True)
    assert dialog.pages() == [0, 1, 2]
    dialog.range_text.setText("x")
    dialog.range_text.textEdited.emit("x")
    assert dialog.range.isChecked() and dialog.pages() == []
    assert not dialog.print_button.isEnabled() and "between 1 and 3" in dialog.range_hint.text()
    dialog.range_text.setText("3")
    assert dialog.pages() == [2] and dialog.print_button.isEnabled()
    # Auto orientation follows the first page printed.
    assert dialog.orientation() == QPageLayout.Orientation.Landscape
    dialog.portrait.setChecked(True)
    assert dialog.orientation() == QPageLayout.Orientation.Portrait
    assert not dialog.print_layout().auto_rotate
    dialog.scale.setValue(80)
    assert dialog.custom.isChecked() and dialog.print_layout().scale == 80
    dialog.scale.plus.click()  # the − / + buttons beside the number boxes step them
    dialog.copies.plus.click()
    assert dialog.scale.value() == 85 and dialog.copies.value() == 2
    assert dialog.collate.isEnabled()
    dialog.scale.minus.click()
    dialog.copies.minus.click()
    assert dialog.scale.value() == 80 and dialog.copies.value() == 1
    pump(app, 40)
    assert dialog.page_count() == 1

    # Settings from the printer's own Properties window come back to the dialog.
    dialog.set_driver_settings(winprint.DriverSettings(
        paper=QPageSize.windowsId(QPageSize.PageSizeId.A3), landscape=True, copies=2,
        collate=False, color=False))
    assert dialog.page_size().id() == QPageSize.PageSizeId.A3
    assert dialog.landscape.isChecked() and dialog.copies.value() == 2
    assert not dialog.collate.isChecked() and dialog.grayscale.isChecked()

    # Save as PDF: actual size, in grayscale, on A4.
    dialog.printer_combo.setCurrentIndex(dialog.printer_combo.findData(""))
    dialog.all_pages.setChecked(True)
    dialog.auto.setChecked(True)
    dialog.actual.setChecked(True)
    dialog.copies.setValue(1)
    dialog._select_paper(QPageSize(QPageSize.PageSizeId.A4))
    out = tmp_path / "out.pdf"
    monkeypatch.setattr(dialog, "ask_pdf_path", lambda: str(out))
    dialog.print_button.click()
    assert dialog.result() == PrintDialog.DialogCode.Accepted
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    dialog.apply_to(printer)
    printer.setResolution(72)
    layout = dialog.print_layout()
    assert layout.sizing is Sizing.ACTUAL and layout.grayscale
    printing.print_pages(window.doc, printer, [0], layout=layout)
    printed = fitz.open(str(out))
    assert printed[0].rect.width < printed[0].rect.height  # A4 portrait
    pix = printed[0].get_pixmap()
    pixels = [pix.pixel(x, y) for x in range(0, pix.width, 2) for y in range(0, pix.height, 2)]
    square = [p for p in pixels if p[0] < 200]
    assert all(r == g == b for r, g, b in square)  # the red square printed gray
    xs = [x for x in range(0, pix.width, 2) for y in range(200, 500, 2)  # below the text
          if pix.pixel(x, y)[0] < 150]
    assert 95 <= max(xs) - min(xs) <= 101  # 100 pt wide: true size, not fitted


# ------------------------------------------------------------- drag and drop
def drop_on(widget, pos, mime):
    from PySide6.QtGui import QDropEvent

    event = QDropEvent(QPointF(pos), Qt.DropAction.CopyAction | Qt.DropAction.MoveAction, mime,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    widget.dropEvent(event)
    return event


def file_mime(*paths):
    from PySide6.QtCore import QMimeData, QUrl

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    return mime


def page_pos(window, page, x, y):
    v = window.view
    return v.mapFromScene(v.pages[page].pos() + QPointF(x * v.zoom, y * v.zoom))


def test_drop_pdf_on_a_page_inserts_it_next_to_that_page(window, app, sample_pdf):
    mime = file_mime(sample_pdf)
    assert drop_on(window.view, page_pos(window, 0, 300, 700), mime).isAccepted()
    pump(app)
    assert window.doc.page_count == 6
    titles = [window.doc.doc[i].get_text().splitlines()[0] for i in range(6)]
    assert titles[:3] == ["Page 1 title", "Page 1 title", "Page 2 title"]
    assert window.thumbs.selected_pages() == [1, 2, 3]
    window.undo()  # one step
    pump(app)
    assert window.doc.page_count == 3
    # On the top half of a page: before it.
    drop_on(window.view, page_pos(window, 1, 300, 100), mime)
    pump(app)
    titles = [window.doc.doc[i].get_text().splitlines()[0] for i in range(6)]
    assert titles[:3] == ["Page 1 title", "Page 1 title", "Page 2 title"]
    assert window.thumbs.selected_pages() == [1, 2, 3]


def test_drop_image_on_a_page_places_it_there(window, app, tmp_path, png_bytes):
    img = tmp_path / "pic.png"
    img.write_bytes(png_bytes)
    drop_on(window.view, page_pos(window, 1, 200, 300), file_mime(img))
    pump(app)
    (image,) = window.doc.images(1)
    center = image.bbox.tl + (image.bbox.br - image.bbox.tl) * 0.5
    assert (center.x, center.y) == pytest.approx((200, 300), abs=0.5)
    assert image.bbox.width == pytest.approx(40)  # a pixel per point
    assert window.view.selected_image is not None  # ready to be adjusted
    assert window.doc.undo_label == "Add image"


def test_paste_image_from_clipboard(window, app, tmp_path, png_bytes):
    from PySide6.QtGui import QImage

    window.view.scroll_to_page(1)
    pump(app)
    QApplication.clipboard().setImage(QImage.fromData(png_bytes))
    QTest.keySequence(window.view, QKeySequence.StandardKey.Paste)
    pump(app)
    (image,) = window.doc.images(1)
    assert image.bbox.width == pytest.approx(40)  # a pixel per point, like a drop
    assert window.view.selected_image is not None
    assert window.doc.undo_label == "Add image"
    # Copied image files are pasted too.
    img = tmp_path / "pic.png"
    img.write_bytes(png_bytes)
    QApplication.clipboard().setMimeData(file_mime(img))
    window.a_paste.trigger()
    pump(app)
    assert len(window.doc.images(1)) == 2


def test_paste_while_typing_pastes_text(window, app, png_bytes):
    window.set_tool(Tool.ADD_TEXT)
    click_page(window, 1, 100, 400)
    pump(app)
    QApplication.clipboard().setText("Pasted")
    QTest.keySequence(window.view._editor, QKeySequence.StandardKey.Paste)
    pump(app)
    assert window.view._editor.toPlainText() == "Pasted"
    assert not window.doc.images(1)
    QTest.keyClick(window.view._editor, Qt.Key.Key_Escape)  # nothing left to save on close


def test_drop_on_sidebar_inserts_pages_and_images(window, app, sample_pdf, tmp_path, png_bytes):
    from pixa.ui import dnd

    other = window.doc.pages_pdf([2])  # as dragged from another Pixa window
    thumbs = window.thumbs
    top = thumbs.visualItemRect(thumbs.item(0)).topLeft() + QPoint(20, 5)
    assert drop_on(thumbs, top, dnd.pages_mime(other, "another window")).isAccepted()
    pump(app)
    assert window.doc.page_count == 4
    assert window.doc.doc[0].get_text().startswith("Page 3 title")
    img = tmp_path / "pic.png"
    img.write_bytes(png_bytes)
    # Images aren't for the sidebar's own drop handling: the window places them.
    assert not drop_on(thumbs, top, file_mime(img)).isAccepted()
    pump(app)
    assert window.doc.page_count == 4


def test_drag_pages_in_sidebar_reorders_them(window, app):
    from pixa.ui import dnd

    thumbs = window.thumbs
    thumbs.clearSelection()
    thumbs.item(0).setSelected(True)
    last = thumbs.visualItemRect(thumbs.item(2))
    mime = dnd.pages_mime(window.doc.pages_pdf([0]), thumbs.source_id)
    # Dropping its own pages on the page view does nothing.
    assert not drop_on(window.view, page_pos(window, 0, 300, 300), mime).isAccepted()
    drop_on(thumbs, last.bottomLeft() - QPoint(-20, 5), mime)
    pump(app)
    titles = [window.doc.doc[i].get_text().splitlines()[0] for i in range(3)]
    assert titles == ["Page 2 title", "Page 3 title", "Page 1 title"]
    assert thumbs.selected_pages() == [2]


def test_drop_without_document_opens_or_makes_one(window, app, sample_pdf, tmp_path,
                                                  png_bytes):
    window.close_document()
    pump(app)
    assert window.doc is None
    img = tmp_path / "pic.png"
    img.write_bytes(png_bytes)
    drop_on(window, QPoint(50, 50), file_mime(img, img))
    pump(app)
    assert window.doc is not None and window.doc.page_count == 2 and window.doc.path is None
    assert "Untitled" in window.windowTitle() and window.doc.dirty
    window.doc.dirty = False
    window.close_document()
    drop_on(window, QPoint(50, 50), file_mime(sample_pdf, img))
    pump(app)
    assert window.doc.path == sample_pdf
    assert window.doc.page_count == 4  # and the image as a page after it


# ------------------------------------------------------------------- layers
def _dark_in(window, page, rect):
    pix = window.doc.doc[page].get_pixmap(clip=rect, alpha=False)
    return sum(1 for x in range(pix.width) for y in range(pix.height)
               if sum(pix.pixel(x, y)) < 200)


def test_arrange_selected_image(window, app, monkeypatch):
    from pixa.document import TextStyle

    words = fitz.Rect(305, 320, 395, 345)
    window.doc.add_text(0, fitz.Point(305, 320), "Over", TextStyle(size=20))
    pump(app)
    assert _dark_in(window, 0, words) > 30  # the text was placed on the picture
    window.set_tool(Tool.SELECT)
    click_page(window, 0, 390, 395)
    pump(app)
    assert window.view.selected_image is not None
    assert window.arrange_actions["front"].isEnabled()
    assert window.inspector.arrange_box.isVisibleTo(window.inspector)
    window.arrange_actions["front"].trigger()
    pump(app)
    assert _dark_in(window, 0, words) == 0
    assert window.view.selected_image is not None  # still selected
    window.inspector.action.emit("arrange_backward")
    pump(app)
    assert _dark_in(window, 0, words) > 30
    messages = []
    window.view.message.connect(messages.append)
    window.inspector.action.emit("arrange_back")
    pump(app)
    assert "already" in messages[-1]
    # Right click: the layer actions for what is under the mouse.
    from PySide6.QtWidgets import QMenu

    from pixa.ui import main_window

    shown = []

    class Menu(QMenu):
        def exec(self, *args):  # noqa: A003
            shown.append([x.text() for x in self.actions()])

    monkeypatch.setattr(main_window, "QMenu", Menu)
    window.view.clear_selection()
    from PySide6.QtGui import QContextMenuEvent

    pos = page_pos(window, 0, 390, 395)
    window.view.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse, pos,
                                                   window.view.mapToGlobal(pos)))
    pump(app)
    assert window.view.selected_image is not None
    assert shown and shown[0][:4] == ["Bring to front", "Bring forward", "Send backward",
                                      "Send to back"]


def test_print_preview_shows_every_page(window, app, monkeypatch):
    window.doc.rotate_pages([1], 90)
    window.view.scroll_to_page(1)
    dialog = window.print_preview()
    assert dialog is not None
    pump(app, 60)
    assert dialog.page_count() == 3 and not window.errors
    assert window.a_preview.shortcut().toString() == "Ctrl+Shift+P"
    assert dialog.page_label.text() == "Page 1 of 3"
    dialog.actions_by_name["next"].trigger()
    assert dialog.page_label.text() == "Page 2 of 3"
    dialog.actions_by_name["landscape"].trigger()  # paper turned: drawn again
    pump(app, 40)
    assert dialog.page_count() == 3
    dialog.all_pages.trigger()
    pump(app, 20)
    # Print… closes the preview and goes on to the normal print flow.
    printed = []
    monkeypatch.setattr(window, "print_document", lambda: printed.append(True))
    dialog.printRequested.disconnect()
    dialog.printRequested.connect(window.print_document)
    closed = []
    dialog.finished.connect(closed.append)
    dialog.print_button.click()
    pump(app)
    assert printed == [True] and closed == [QDialog.DialogCode.Accepted]



def test_formats_pymupdf_cant_read_are_converted(app, tmp_path):
    from PySide6.QtGui import QColor, QImage

    from pixa.document import PdfError
    from pixa.ui import imagefiles

    assert {".png", ".svg", ".svgz", ".ico", ".webp"} <= set(imagefiles.extensions())
    assert ".pdf" not in imagefiles.extensions()
    assert "*.ico" in imagefiles.file_filter()
    image = QImage(30, 20, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 255, 128))
    for ext, fmt in ((".ico", "ICO"), (".webp", "WEBP")):
        path = tmp_path / f"pic{ext}"
        assert image.save(str(path), fmt)
        data = imagefiles.source(str(path))
        assert isinstance(data, bytes) and data.startswith(b"\x89PNG")
        assert fitz.Pixmap(data).width == 30
    assert imagefiles.source(str(tmp_path / "pic.png")) == str(tmp_path / "pic.png")
    (tmp_path / "bad.ico").write_bytes(b"nope")
    with pytest.raises(PdfError):
        imagefiles.source(str(tmp_path / "bad.ico"))


def test_drop_icon_and_svg_on_a_page(window, app, tmp_path):
    from PySide6.QtCore import QMimeData, QUrl
    from PySide6.QtGui import QColor, QImage

    icon = tmp_path / "icon.ico"
    image = QImage(32, 32, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 128, 0))
    assert image.save(str(icon), "ICO")
    svg = tmp_path / "logo.svg"
    svg.write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg" width="60" height="30">'
                    b'<rect width="60" height="30" fill="red"/></svg>')
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(icon)), QUrl.fromLocalFile(str(svg))])
    drop_on(window.view, page_pos(window, 1, 200, 300), mime)
    pump(app)
    assert window.errors == []
    raster, vector = sorted(window.doc.images(1), key=lambda im: im.vector)
    assert not raster.vector and raster.bbox.width == pytest.approx(32)
    assert vector.vector and vector.bbox.width == pytest.approx(60)
    assert window.view.selected_image is not None  # the SVG, with its handles
    assert window.view.selected_image.vector


def test_place_svg_from_the_file_dialog(window, app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    svg = tmp_path / "logo.svg"
    svg.write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg" width="60" height="30">'
                    b'<rect width="60" height="30" fill="red"/></svg>')
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: (str(svg), ""))
    window.choose_image()
    assert window.view.is_placing
    QTest.keyClick(window.view, Qt.Key.Key_Return)
    pump(app)
    images = [im for im in window.doc.images(window.view.current_page) if im.vector]
    assert len(images) == 1


def test_paste_copied_icon_and_svg_files(window, app, tmp_path):
    from PySide6.QtGui import QColor, QImage

    icon = tmp_path / "icon.ico"
    image = QImage(32, 32, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 128, 0))
    assert image.save(str(icon), "ICO")
    svg = tmp_path / "logo.svg"
    svg.write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg" width="60" height="30">'
                    b'<rect width="60" height="30" fill="red"/></svg>')
    window.view.scroll_to_page(1)
    pump(app)
    QApplication.clipboard().setMimeData(file_mime(icon, svg))
    window.a_paste.trigger()
    pump(app)
    assert window.errors == []
    raster, vector = sorted(window.doc.images(1), key=lambda im: im.vector)
    assert not raster.vector and raster.bbox.width == pytest.approx(32)
    assert vector.vector and vector.bbox.width == pytest.approx(60)
    assert window.doc.undo_label == "Add images"  # one step


def test_check_for_updates(window, app, monkeypatch):
    from pixa import updates
    from pixa.ui import updater

    release = updates.Release(version="99.0", notes="- Better", page_url="https://example.com")
    monkeypatch.setattr(updates, "fetch_latest", lambda: release)
    shown = []

    def answer(dialog):
        shown.append(dialog.install_button.text())
        return updater.UpdateDialog.SKIP

    monkeypatch.setattr(updater.UpdateDialog, "exec", answer)
    window.a_check_update.trigger()
    for _ in range(100):
        pump(app, 1)
        if shown:
            break
    assert shown == ["Download…"]  # not an installed Windows copy, so no in-place install
    assert window.settings.value("skipped_version") == "99.0"

    # A skipped version isn't offered again by the automatic check, only when asked.
    window.updater.check(manual=False)
    for _ in range(50):
        pump(app, 1)
        if not window.updater.checking:
            break
    assert shown == ["Download…"]

    window.a_auto_update.trigger()
    assert window.settings.value("check_updates") == "false"
