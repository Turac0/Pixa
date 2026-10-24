import os

import pymupdf as fitz
import pytest

from pixa.document import BoxStyle, ImageGeometry, PdfDocument, PdfError, TextStyle
from pixa.fonts import SystemFonts


def geo(rect, angle=0.0):
    r = fitz.Rect(rect)
    return ImageGeometry(fitz.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2), r.width, r.height,
                         angle)


def page_titles(doc: PdfDocument):
    return [doc.doc[i].get_text().splitlines()[0] for i in range(doc.page_count)]


def test_open_and_lines(sample_pdf):
    doc = PdfDocument.open(sample_pdf)
    assert doc.page_count == 3
    lines = doc.text_lines(0)
    assert [ln.text for ln in lines] == ["Page 1 title", "The quick brown fox"]
    assert lines[0].style.bold and lines[0].style.family == "helv"
    assert lines[1].style.family == "tiro"
    assert lines[0].style.size == pytest.approx(20)


def test_open_invalid(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")
    with pytest.raises(PdfError):
        PdfDocument.open(str(bad))


def test_rotate_and_undo_redo(sample_pdf):
    doc = PdfDocument.open(sample_pdf)
    doc.rotate_pages([0, 2], 90)
    assert [doc.doc[i].rotation for i in range(3)] == [90, 0, 90]
    doc.rotate_pages([0], -90)
    assert doc.doc[0].rotation == 0
    doc.undo()
    assert doc.doc[0].rotation == 90
    doc.undo()
    assert doc.doc[0].rotation == 0
    assert not doc.can_undo
    doc.redo()
    assert doc.doc[2].rotation == 90


def test_delete_pages(sample_pdf):
    doc = PdfDocument.open(sample_pdf)
    doc.delete_pages([1])
    assert page_titles(doc) == ["Page 1 title", "Page 3 title"]
    with pytest.raises(PdfError):
        doc.delete_pages([0, 1])
    assert doc.page_count == 2


def test_reorder_and_move(sample_pdf):
    doc = PdfDocument.open(sample_pdf)
    doc.reorder_pages([2, 0, 1])
    assert page_titles(doc) == ["Page 3 title", "Page 1 title", "Page 2 title"]
    doc.move_page(0, 2)
    assert page_titles(doc) == ["Page 1 title", "Page 2 title", "Page 3 title"]
    with pytest.raises(ValueError):
        doc.reorder_pages([0, 0, 1])


def test_insert_pdf_and_blank(sample_pdf, tmp_path):
    doc = PdfDocument.open(sample_pdf)
    assert doc.insert_pdf(sample_pdf, 1) == 3
    assert doc.page_count == 6
    assert page_titles(doc)[:2] == ["Page 1 title", "Page 1 title"]
    doc.insert_blank_page(0)
    assert doc.page_count == 7
    assert doc.doc[0].get_text() == ""


def test_replace_text_keeps_neighbours(sample_pdf):
    doc = PdfDocument.open(sample_pdf)
    title = doc.text_lines(0)[0]
    doc.replace_text(title, "Brand new heading")
    text = doc.doc[0].get_text()
    assert "Brand new heading" in text
    assert "Page 1 title" not in text
    assert "The quick brown fox" in text
    new = next(ln for ln in doc.text_lines(0) if ln.text == "Brand new heading")
    assert tuple(new.origin) == pytest.approx(tuple(title.origin), abs=0.5)
    assert new.style.size == pytest.approx(20)


def test_replace_text_with_new_style(sample_pdf):
    doc = PdfDocument.open(sample_pdf)
    body = doc.text_lines(0)[1]
    style = TextStyle(family="cour", size=16, color=(1, 0, 0))
    doc.replace_text(body, "Edited", style)
    edited = [ln for ln in doc.text_lines(0) if ln.text == "Edited"][0]
    assert edited.style.family == "cour"
    assert edited.style.color == pytest.approx((1, 0, 0))


def test_replace_text_with_empty_deletes(sample_pdf):
    doc = PdfDocument.open(sample_pdf)
    doc.replace_text(doc.text_lines(0)[1], "")
    assert [ln.text for ln in doc.text_lines(0)] == ["Page 1 title"]


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_add_text_reads_upright(sample_pdf, rotation):
    doc = PdfDocument.open(sample_pdf)
    doc.rotate_pages([1], rotation)
    top_left = doc.from_display(1, fitz.Point(50, 50))
    doc.add_text(1, top_left, "Hello\nWorld", TextStyle(size=14))
    added = [ln for ln in doc.text_lines(1) if ln.text in ("Hello", "World")]
    assert len(added) == 2
    # In display space the first line must be near the click and run left to right.
    box = doc.to_display(1, added[0].bbox)
    assert box.x0 == pytest.approx(50, abs=3)
    assert 45 < box.y0 < 60
    assert box.width > box.height


def test_images_add_and_delete(sample_pdf, png_bytes):
    doc = PdfDocument.open(sample_pdf)
    assert len(doc.images(0)) == 1
    doc.add_image(1, geo((100, 200, 200, 250)), data=png_bytes)
    imgs = doc.images(1)
    assert len(imgs) == 1
    assert tuple(imgs[0].bbox) == pytest.approx((100, 200, 200, 250), abs=0.5)
    doc.delete_image(doc.images(0)[0])
    assert doc.images(0) == []
    # text is untouched
    assert "Page 1 title" in doc.doc[0].get_text()


def test_delete_shared_image_only_on_one_page(tmp_path, png_bytes):
    doc = fitz.open()
    for _ in range(2):
        doc.new_page()
    xref = doc[0].insert_image(fitz.Rect(50, 50, 150, 150), stream=png_bytes)
    doc[1].insert_image(fitz.Rect(50, 50, 150, 150), xref=xref)
    path = tmp_path / "shared.pdf"
    doc.save(path)
    pdf = PdfDocument.open(str(path))
    pdf.delete_image(pdf.images(0)[0])
    assert pdf.images(0) == []
    assert len(pdf.images(1)) == 1


def test_save_roundtrip(sample_pdf, tmp_path):
    doc = PdfDocument.open(sample_pdf)
    doc.rotate_pages([0], 90)
    doc.replace_text(doc.text_lines(1)[0], "Saved text")
    assert doc.dirty
    doc.save()  # overwrite the file that is open
    assert not doc.dirty
    again = PdfDocument.open(sample_pdf)
    assert again.doc[0].rotation == 90
    assert "Saved text" in again.doc[1].get_text()
    out = tmp_path / "copy.pdf"
    again.save(str(out))
    assert PdfDocument.open(str(out)).page_count == 3


def test_password_protected(tmp_path):
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "secret")
    path = tmp_path / "locked.pdf"
    doc.save(path, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="pw")
    assert PdfDocument.needs_password(str(path))
    with pytest.raises(PdfError):
        PdfDocument.open(str(path))
    assert PdfDocument.open(str(path), "pw").page_count == 1


def test_listener_and_history_limit(sample_pdf):
    doc = PdfDocument.open(sample_pdf)
    calls = []
    doc.listeners.append(lambda: calls.append(1))
    for _ in range(60):
        doc.rotate_pages([0], 90)
    assert len(calls) == 60
    assert len(doc._undo) == 50


def test_edit_reuses_embedded_font(tmp_path):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_font(fontname="emb", fontbuffer=fitz.Font("tiro").buffer)
    page.insert_text((72, 100), "Embedded font line", fontname="emb", fontsize=16)
    path = tmp_path / "embedded.pdf"
    doc.save(path)
    pdf = PdfDocument.open(str(path))
    line = pdf.text_lines(0)[0]
    pdf.replace_text(line, "Still the same font")
    edited = pdf.text_lines(0)[0]
    assert edited.text == "Still the same font"
    assert edited.font == line.font
    assert any(ext != "n/a" for _, ext, *_ in pdf.doc[0].get_fonts())


def _block(doc, page, text):
    return next(b for b in doc.text_blocks(page) if b.text.startswith(text))


def test_text_blocks_group_lines(sample_pdf):
    doc = PdfDocument.open(sample_pdf)
    doc.add_text(1, fitz.Point(300, 400), "First line\nSecond line", TextStyle(size=14))
    block = _block(doc, 1, "First line")
    assert [ln.text for ln in block.lines] == ["First line", "Second line"]
    assert block.bbox.contains(block.lines[1].bbox)


def test_move_text_block(sample_pdf):
    doc = PdfDocument.open(sample_pdf)
    doc.add_text(1, fitz.Point(300, 400), "Move me\nand me", TextStyle(size=14, color=(1, 0, 0)))
    before = _block(doc, 1, "Move me")
    doc.move_text_block(before, -150, 100)
    after = _block(doc, 1, "Move me")
    assert [ln.text for ln in after.lines] == ["Move me", "and me"]
    assert after.bbox.x0 == pytest.approx(before.bbox.x0 - 150, abs=0.5)
    assert after.bbox.y0 == pytest.approx(before.bbox.y0 + 100, abs=0.5)
    assert after.lines[0].style.color == pytest.approx((1, 0, 0))
    assert after.lines[0].style.size == pytest.approx(14)
    # the rest of the page is untouched
    assert "Page 2 title" in doc.doc[1].get_text()
    assert "The quick brown fox" in doc.doc[1].get_text()
    doc.undo()
    assert _block(doc, 1, "Move me").bbox.x0 == pytest.approx(before.bbox.x0, abs=0.5)


def test_move_keeps_mixed_styles(tmp_path):
    doc = fitz.open()
    page = doc.new_page()
    # One line made of two spans with different fonts and colours.
    tw = fitz.TextWriter(page.rect)
    tw.append((72, 100), "Bold part ", font=fitz.Font("hebo"), fontsize=12)
    tw.append(tw.last_point, "normal part", font=fitz.Font("helv"), fontsize=12)
    tw.write_text(page)
    path = tmp_path / "mixed.pdf"
    doc.save(path)
    pdf = PdfDocument.open(str(path))
    pdf.move_text_block(pdf.text_blocks(0)[0], 0, 50)
    spans = pdf.text_blocks(0)[0].lines[0].spans
    assert [s.style.bold for s in spans] == [True, False]
    assert spans[0].origin.y == pytest.approx(150, abs=0.5)


@pytest.mark.parametrize("rotation", [90])
def test_move_on_rotated_page_follows_display(sample_pdf, rotation):
    doc = PdfDocument.open(sample_pdf)
    doc.rotate_pages([0], rotation)
    block = _block(doc, 0, "The quick")
    shown = doc.to_display(0, block.bbox)
    doc.move_text_block(block, 40, 25)  # right and down, as seen on screen
    # Look up the line: moved text may merge into a neighbouring block.
    line = next(ln for ln in doc.text_lines(0) if ln.text.startswith("The quick"))
    moved = doc.to_display(0, line.bbox)
    assert moved.x0 == pytest.approx(shown.x0 + 40, abs=1)
    assert moved.y0 == pytest.approx(shown.y0 + 25, abs=1)


def test_delete_text_block(sample_pdf):
    doc = PdfDocument.open(sample_pdf)
    doc.delete_text_block(_block(doc, 0, "The quick"))
    text = doc.doc[0].get_text()
    assert "The quick brown fox" not in text and "Page 1 title" in text


# ----------------------------------------------------------------- images: transform
def _stripe_png() -> bytes:
    """40x20 red image with a blue stripe on its left edge (shows orientation)."""
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 20), False)
    pix.set_rect(pix.irect, (255, 0, 0))
    pix.set_rect(fitz.IRect(0, 0, 8, 20), (0, 0, 255))
    return pix.tobytes("png")


def _pixel(doc, page, point):
    pm = doc.doc[page].get_pixmap()
    return pm.pixel(int(point.x), int(point.y))


@pytest.mark.parametrize("rotation", [0, 90])
@pytest.mark.parametrize("angle", [0, 30])
def test_transform_image(sample_pdf, rotation, angle):
    doc = PdfDocument.open(sample_pdf)
    doc.rotate_pages([1], rotation)
    doc.add_image(1, geo((100, 100, 200, 150)), data=_stripe_png())
    image = doc.images(1)[0]
    xref = image.xref
    target = ImageGeometry(fitz.Point(250, 300), 160, 80, angle)
    doc.transform_image(image, target)
    moved = doc.images(1)[0]
    got = doc.image_geometry(moved)
    assert moved.xref == xref  # same image object: no re-encoding or duplication
    assert (got.center.x, got.center.y) == pytest.approx((250, 300), abs=0.5)
    assert (got.width, got.height) == pytest.approx((160, 80), abs=0.5)
    assert got.angle % 360 == pytest.approx(angle, abs=0.5)
    # Orientation on screen: blue stripe at the image's left end, red at the right.
    left = fitz.Point(0.05, 0.5) * (moved.transform * doc.doc[1].rotation_matrix)
    right = fitz.Point(0.9, 0.5) * (moved.transform * doc.doc[1].rotation_matrix)
    assert _pixel(doc, 1, left) == (0, 0, 255)
    assert _pixel(doc, 1, right) == (255, 0, 0)
    assert moved.contains(doc.from_display(1, fitz.Point(250, 300)))


def test_transform_keeps_z_order(tmp_path):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_image(fitz.Rect(50, 50, 250, 150), stream=_stripe_png())
    page.draw_rect(fitz.Rect(140, 190, 160, 210), color=None, fill=(0, 1, 0))  # drawn after
    path = tmp_path / "z.pdf"
    doc.save(path)
    pdf = PdfDocument.open(str(path))
    pdf.transform_image(pdf.images(0)[0], ImageGeometry(fitz.Point(150, 200), 200, 100, 0))
    assert _pixel(pdf, 0, fitz.Point(150, 200)) == (0, 255, 0)  # green square still on top
    assert _pixel(pdf, 0, fitz.Point(80, 200)) != (255, 255, 255)  # image moved under it


def test_delete_image_removes_only_its_do(tmp_path, png_bytes):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_image(fitz.Rect(0, 0, 400, 400), stream=_stripe_png())  # background
    page.insert_image(fitz.Rect(100, 100, 150, 150), stream=png_bytes)
    path = tmp_path / "two.pdf"
    doc.save(path)
    pdf = PdfDocument.open(str(path))
    big, small = sorted(pdf.images(0), key=lambda im: -im.bbox.get_area())
    pdf.delete_image(small)
    assert [im.bbox for im in pdf.images(0)] == [big.bbox]


# ------------------------------------------------------------------ installed fonts
DEJAVU_DIR = "/usr/share/fonts/truetype/dejavu"
needs_dejavu = pytest.mark.skipif(
    not os.path.exists(os.path.join(DEJAVU_DIR, "DejaVuSans.ttf")),
    reason="DejaVu fonts not installed",
)


def _subset_pdf(tmp_path, text="Hello"):
    """A PDF whose DejaVu Sans font is subset to just the glyphs of ``text``."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_font(fontname="dv", fontfile=os.path.join(DEJAVU_DIR, "DejaVuSans.ttf"))
    page.insert_text((72, 100), text, fontname="dv", fontsize=16)
    doc.subset_fonts()
    path = tmp_path / "subset.pdf"
    doc.save(path, garbage=3, deflate=True)
    return str(path)


@needs_dejavu
def test_edit_uses_installed_font_when_subset_lacks_glyphs(tmp_path):
    pdf = PdfDocument.open(_subset_pdf(tmp_path))
    pdf.fonts = SystemFonts([DEJAVU_DIR])
    line = pdf.text_lines(0)[0]
    note = pdf.replace_text(line, "Quizzical jumps")  # letters the subset doesn't have
    assert note is None
    edited = pdf.text_lines(0)[0]
    assert edited.text == "Quizzical jumps"
    assert "DejaVu" in edited.font
    out = tmp_path / "out.pdf"
    pdf.save(str(out))
    # Saved file carries only a subset of the installed font, not all 750 KB of it.
    assert os.path.getsize(out) < 200_000
    assert PdfDocument.open(str(out)).text_lines(0)[0].text == "Quizzical jumps"


@needs_dejavu
def test_missing_font_falls_back_with_note(tmp_path):
    pdf = PdfDocument.open(_subset_pdf(tmp_path))
    pdf.fonts = SystemFonts([])
    note = pdf.replace_text(pdf.text_lines(0)[0], "Quizzical")
    # Only the characters the subset lacks change font; "l" keeps DejaVu Sans.
    assert note and "DejaVu Sans" in note and "“Q”" in note and "“l”" not in note
    fonts = {span.text: span.font for span in pdf.text_lines(0)[0].spans}
    assert any("DejaVu" in f for f in fonts.values())
    assert "Helvetica" in fonts.values()
    assert "".join(fonts) == "Quizzical"


# ----------------------------------------------------------------------- underline
def _underlined_pdf(tmp_path):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Short", fontsize=14)
    width = fitz.get_text_length("Short", fontsize=14)
    page.draw_line((72, 102), (72 + width, 102), color=(0, 0, 0), width=0.8)
    page.draw_line((72, 160), (300, 160), color=(0, 0, 1), width=0.8)  # unrelated rule
    page.insert_text((72, 130), "Next line", fontsize=14)
    path = tmp_path / "u.pdf"
    doc.save(path)
    return str(path)


def _rules(pdf, page=0):
    return sorted(
        (round(d["rect"].x0), round(d["rect"].x1), round(d["rect"].y0))
        for d in pdf.doc[page].get_drawings()
    )


def test_underline_detected_and_follows_new_length(tmp_path):
    pdf = PdfDocument.open(_underlined_pdf(tmp_path))
    line = pdf.text_lines(0)[0]
    assert line.style.underline and len(line.decorations) == 1
    assert not pdf.text_lines(0)[1].style.underline  # "Next line" isn't underlined
    pdf.replace_text(line, "A much longer underlined text")
    width = fitz.get_text_length("A much longer underlined text", fontsize=14)
    assert _rules(pdf) == [(72, round(72 + width), 102), (72, 300, 160)]
    assert "Next line" in pdf.doc[0].get_text()


def test_underline_toggle(tmp_path):
    pdf = PdfDocument.open(_underlined_pdf(tmp_path))
    line = pdf.text_lines(0)[0]
    off = TextStyle(**vars(line.style))
    off.underline = False
    pdf.replace_text(line, "Short", off)
    assert _rules(pdf) == [(72, 300, 160)]
    plain = next(ln for ln in pdf.text_lines(0) if ln.text == "Next line")
    on = TextStyle(**vars(plain.style))
    on.underline = True
    pdf.replace_text(plain, "Next line", on)
    assert next(ln for ln in pdf.text_lines(0) if ln.text == "Next line").style.underline


def test_underline_moves_with_block(tmp_path):
    pdf = PdfDocument.open(_underlined_pdf(tmp_path))
    block = next(b for b in pdf.text_blocks(0) if b.text.startswith("Short"))
    pdf.move_text_block(block, 100, 300)
    assert (172, 172 + round(fitz.get_text_length("Short", fontsize=14)), 402) in _rules(pdf)
    moved = next(ln for ln in pdf.text_lines(0) if ln.text == "Short")
    assert moved.style.underline


@needs_dejavu
@pytest.mark.parametrize("rotation", [0, 90])
def test_edit_reuses_subset_glyphs_without_new_font(tmp_path, rotation):
    pdf = PdfDocument.open(_subset_pdf(tmp_path, "Invoice 2024"))
    pdf.fonts = SystemFonts([])
    pdf.rotate_pages([0], rotation)
    fonts_before = len(pdf.doc[0].get_fonts())
    line = pdf.text_lines(0)[0]
    assert pdf.replace_text(line, "Invoice 2042") is None  # digits already in the subset
    edited = pdf.text_lines(0)[0]
    assert edited.text == "Invoice 2042" and "DejaVu" in edited.font
    assert tuple(edited.origin) == pytest.approx(tuple(line.origin), abs=0.5)
    assert len(pdf.doc[0].get_fonts()) == fonts_before  # same font object, nothing added
    pdf.undo()
    assert pdf.text_lines(0)[0].text == "Invoice 2024"


# ------------------------------------------------------------------ document fonts
from pixa.fonts import family_name  # noqa: E402


@pytest.mark.parametrize("name, family", [
    ("ABCDEF+TimesNewRomanPS-BoldMT", "Times New Roman"),
    ("Arial-BoldMT", "Arial"),
    ("ArialMT", "Arial"),
    ("Arial,Bold", "Arial"),
    ("ABCDEF+DejaVu Sans Book", "DejaVu Sans"),
    ("Calibri-Light", "Calibri"),
    ("TimesNewRomanPS-ItalicMT", "Times New Roman"),
    ("NotoSans-Regular", "Noto Sans"),
])
def test_family_name(name, family):
    assert family_name(name) == family


def _two_font_pdf(tmp_path):
    """Page 1: DejaVu Sans text; page 2: DejaVu Sans Bold and a Helvetica line."""
    doc = fitz.open()
    doc.new_page()
    doc.new_page()
    p1, p2 = doc[0], doc[1]
    p1.insert_font(fontname="dv", fontfile=os.path.join(DEJAVU_DIR, "DejaVuSans.ttf"))
    p1.insert_text((72, 100), "Regular words here", fontname="dv", fontsize=14)
    p2.insert_font(fontname="dvb", fontfile=os.path.join(DEJAVU_DIR, "DejaVuSans-Bold.ttf"))
    p2.insert_text((72, 100), "Bold words here", fontname="dvb", fontsize=14)
    p2.insert_text((72, 140), "Helvetica line", fontname="helv", fontsize=14)
    doc.subset_fonts()
    path = tmp_path / "two.pdf"
    doc.save(path, garbage=3, deflate=True)
    return str(path)


@needs_dejavu
def test_document_fonts_lists_families_and_faces(tmp_path):
    pdf = PdfDocument.open(_two_font_pdf(tmp_path))
    fonts = pdf.document_fonts()
    # Faces, labelled as the user would name them; Helvetica is a standard font.
    assert [f.label for f in fonts] == ["DejaVu Sans", "DejaVu Sans Bold"]
    assert [(f.family, f.weight) for f in fonts] == [("DejaVu Sans", 400), ("DejaVu Sans", 700)]
    line = pdf.text_lines(0)[0]
    assert line.style.font == "DejaVu Sans" and not line.style.bold
    helv = next(ln for ln in pdf.text_lines(1) if ln.text == "Helvetica line")
    assert helv.style.font is None and helv.style.family == "helv"


@needs_dejavu
def test_switch_line_to_font_from_another_page(tmp_path):
    pdf = PdfDocument.open(_two_font_pdf(tmp_path))
    pdf.fonts = SystemFonts([])  # must come from the document itself
    xrefs_before = {x for p in pdf.doc for x, *_ in p.get_fonts()}
    helv = next(ln for ln in pdf.text_lines(1) if ln.text == "Helvetica line")
    style = TextStyle(**vars(helv.style))
    style.font = "DejaVu Sans"  # regular face lives on page 1 only
    assert pdf.replace_text(helv, "Regular here", style) is None  # glyphs exist in that subset
    edited = next(ln for ln in pdf.text_lines(1) if ln.text == "Regular here")
    assert edited.style.font == "DejaVu Sans" and not edited.style.bold
    assert {x for p in pdf.doc for x, *_ in p.get_fonts()} <= xrefs_before  # reused, not added
    # Bold face via the B toggle: the bold subset (page 2) has these glyphs.
    style.bold, style.weight = True, 700
    assert pdf.replace_text(edited, "Bold here", style) is None
    bold = next(ln for ln in pdf.text_lines(1) if ln.text == "Bold here")
    assert bold.style.bold and bold.style.font == "DejaVu Sans Bold"


@needs_dejavu
def test_add_text_in_document_font(tmp_path):
    pdf = PdfDocument.open(_two_font_pdf(tmp_path))
    pdf.fonts = SystemFonts([])
    style = TextStyle(size=12, font="DejaVu Sans")
    assert pdf.add_text(1, fitz.Point(72, 300), "words\nhere", style) is None
    added = [ln for ln in pdf.text_lines(1) if ln.text in ("words", "here")]
    assert len(added) == 2 and all(ln.style.font == "DejaVu Sans" for ln in added)
    # Characters the subsets don't have: falls back to installed, then standard, with a note.
    note = pdf.add_text(1, fitz.Point(72, 400), "Quiz", style)
    assert note and "DejaVu Sans" in note


# ------------------------------------------------------------------ Inter (weights)
INTER_DIR = "/usr/share/fonts/opentype/inter"
needs_inter = pytest.mark.skipif(not os.path.exists(os.path.join(INTER_DIR, "Inter-SemiBold.otf")),
                                 reason="Inter fonts not installed")


def _real_world_subset(doc):
    """Make /ToUnicode list only the glyphs the text uses, like PDFs from other tools.

    MuPDF's own subsetting keeps the full map, which would hide missing glyphs.
    """
    import re as _re

    used: dict[int, set[int]] = {}
    for page in doc:
        for xref, *_ in page.get_fonts():
            used.setdefault(xref, set())
        for xref in page.get_contents():
            for hexes in _re.findall(rb"<([0-9a-fA-F]+)>", doc.xref_stream(xref)):
                for i in range(0, len(hexes), 4):
                    for f in used:
                        used[f].add(int(hexes[i:i + 4], 16))
    for font_xref, codes in used.items():
        kind, value = doc.xref_get_key(font_xref, "ToUnicode")
        if kind != "xref":
            continue
        tu = int(value.split()[0])
        from pixa.pdffont import _parse_tounicode

        mapping, _ = _parse_tounicode(doc.xref_stream(tu))
        pairs = sorted((code, ch) for ch, code in mapping.items() if code in codes)
        body = "".join(f"<{c:04x}> <{ord(ch):04x}>\n" for c, ch in pairs)
        cmap = ("/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n"
                "1 begincodespacerange <0000> <FFFF> endcodespacerange\n"
                f"{len(pairs)} beginbfchar\n{body}endbfchar\nendcmap end end\n")
        doc.update_stream(tu, cmap.encode())


def _inter_pdf(tmp_path, regular_too=False):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_font(fontname="isb", fontfile=os.path.join(INTER_DIR, "Inter-SemiBold.otf"))
    page.insert_text((72, 100), "Heading text", fontname="isb", fontsize=20)
    if regular_too:
        page.insert_font(fontname="ir", fontfile=os.path.join(INTER_DIR, "Inter-Regular.otf"))
        page.insert_text((72, 140), "Heading text body", fontname="ir", fontsize=12)
    doc.subset_fonts()
    doc = fitz.open(stream=doc.tobytes(garbage=3, deflate=True), filetype="pdf")
    _real_world_subset(doc)
    path = tmp_path / "inter.pdf"
    doc.save(path)
    return str(path)


@needs_inter
def test_inter_semibold_identity(tmp_path):
    pdf = PdfDocument.open(_inter_pdf(tmp_path))
    line = pdf.text_lines(0)[0]
    assert line.style.font == "Inter SemiBold"
    assert line.style.typeface == "Inter" and line.style.weight == 600
    assert line.style.family == "helv"  # a sans: falls back to Helvetica, never Times
    assert line.style.bold
    assert [f.label for f in pdf.document_fonts()] == ["Inter SemiBold"]


@needs_inter
def test_inter_edit_keeps_font_for_available_characters(tmp_path):
    pdf = PdfDocument.open(_inter_pdf(tmp_path))
    pdf.fonts = SystemFonts([])  # Inter not installed
    # Real subsets drop unused glyphs; MuPDF's keep them in the program, so
    # pretend the embedded program can't draw new characters either.
    pdf._embedded_font = lambda page, name, text: None
    line = pdf.text_lines(0)[0]
    note = pdf.replace_text(line, "Heading textQ")  # "Q" isn't in the subset
    spans = pdf.text_lines(0)[0].spans
    assert [s.text for s in spans] == ["Heading text", "Q"]
    assert spans[0].style.font == "Inter SemiBold"
    assert spans[1].font == "Helvetica-Bold"  # sans + bold: not Times
    assert note and "“Q”" in note


@needs_inter
def test_bold_off_picks_regular_face(tmp_path):
    pdf = PdfDocument.open(_inter_pdf(tmp_path, regular_too=True))
    pdf.fonts = SystemFonts([])
    line = pdf.text_lines(0)[0]
    style = TextStyle(**vars(line.style))
    style.bold, style.weight = False, 400  # what the B toggle does
    assert pdf.replace_text(line, "Heading text", style) is None
    edited = next(ln for ln in pdf.text_lines(0) if ln.origin.y == pytest.approx(100))
    assert edited.style.font == "Inter" and edited.style.weight == 400


def _zoomed_pixel(doc, index, x, y, zoom=4):
    pix = doc.render(index, zoom)
    return pix.pixel(round(x * zoom), round(y * zoom))


def test_highlight_follows_text_and_can_be_deleted(sample_pdf):
    doc = PdfDocument.open(sample_pdf)
    title, body = doc.text_lines(0)
    middle = (body.bbox.y0 + body.bbox.y1) / 2
    # Dragging along one line picks the words the drag touches, at full line height.
    words = doc.doc[0].get_text("words")
    quick = next(fitz.Rect(w[:4]) for w in words if w[4] == "quick")
    brown = next(fitz.Rect(w[:4]) for w in words if w[4] == "brown")
    rects = doc.highlight_rects(0, fitz.Point(brown.x1 - 2, middle),
                                fitz.Point(quick.x0 + 2, middle))
    assert len(rects) == 1
    assert rects[0].x0 == pytest.approx(quick.x0) and rects[0].x1 == pytest.approx(brown.x1)
    assert rects[0].y0 == pytest.approx(body.bbox.y0) and rects[0].y1 == pytest.approx(body.bbox.y1)
    # Dragging down from the title: the rest of the title, then the body up to the end point.
    flow = doc.highlight_rects(0, fitz.Point(title.bbox.x1 - 5, title.bbox.y0 + 5),
                               fitz.Point(quick.x1 - 1, middle))
    assert len(flow) == 2
    assert flow[0].x1 == pytest.approx(title.bbox.x1, abs=1) and flow[0].x0 > title.bbox.x0
    assert flow[1].x0 == pytest.approx(body.bbox.x0, abs=1)
    assert flow[1].x1 == pytest.approx(quick.x1)

    doc.add_highlight(0, rects, (1, 1, 0))
    assert doc.undo_label == "Highlight"
    (mark,) = doc.markups(0)
    assert mark.kind == "highlight" and mark.color == pytest.approx((1, 1, 0))
    assert mark.bbox.x0 == pytest.approx(quick.x0) and mark.bbox.x1 == pytest.approx(brown.x1)
    r, g, b = _zoomed_pixel(doc, 0, quick.x0 + 1, body.bbox.y0 + 1)
    assert r > 200 and g > 200 and b < 100  # yellow behind the text
    assert "The quick brown fox" in doc.doc[0].get_text()
    assert doc.markup_at(0, fitz.Point(quick.x0 + 3, middle)) == mark
    assert doc.markup_at(0, fitz.Point(body.bbox.x0 + 1, middle)) is None  # "The" isn't marked
    doc.delete_markup(mark)
    assert doc.markups(0) == []
    doc.undo()
    assert len(doc.markups(0)) == 1


def test_highlight_without_text_marks_the_dragged_area(sample_pdf):
    doc = PdfDocument.open(sample_pdf)
    rects = doc.highlight_rects(1, fitz.Point(400, 620), fitz.Point(300, 600))
    assert [tuple(r) for r in rects] == [(300, 600, 400, 620)]
    assert doc.highlight_rects(1, fitz.Point(300, 600), fitz.Point(301, 600)) == []  # a click


def test_highlight_survives_text_edit_and_save(sample_pdf, tmp_path):
    doc = PdfDocument.open(sample_pdf)
    body = doc.text_lines(0)[1]
    doc.add_highlight(0, [body.bbox], (0.5, 1, 0.5))
    doc.replace_text(body, "Edited under the marker")
    assert len(doc.markups(0)) == 1
    out = str(tmp_path / "out.pdf")
    doc.save(out)
    (mark,) = PdfDocument.open(out).markups(0)
    assert mark.kind == "highlight" and mark.color == pytest.approx((0.5, 1, 0.5))


def test_box_border_and_fill(sample_pdf):
    doc = PdfDocument.open(sample_pdf)
    rect = fitz.Rect(100, 300, 200, 360)
    doc.add_box(1, rect, BoxStyle(width=4, color=(1, 0, 0), fill=(0, 0, 1)))
    (box,) = doc.markups(1)
    assert box.kind == "box" and box.width == pytest.approx(4)
    assert box.color == pytest.approx((1, 0, 0)) and box.fill == pytest.approx((0, 0, 1))
    assert tuple(box.bbox) == pytest.approx(tuple(rect))
    # The border is centred on the rectangle: 2 pt outside it and 2 pt inside.
    assert _zoomed_pixel(doc, 1, 97, 330) == (255, 255, 255)
    assert _zoomed_pixel(doc, 1, 99, 330) == (255, 0, 0)
    assert _zoomed_pixel(doc, 1, 101, 330) == (255, 0, 0)
    assert _zoomed_pixel(doc, 1, 103, 330) == (0, 0, 255)
    assert _zoomed_pixel(doc, 1, 150, 330) == (0, 0, 255)


def test_box_transparent_or_borderless(sample_pdf):
    doc = PdfDocument.open(sample_pdf)
    doc.add_box(1, fitz.Rect(100, 300, 200, 360), BoxStyle(width=2, color=(0, 0, 0), fill=None))
    assert doc.markups(1)[0].fill is None
    assert _zoomed_pixel(doc, 1, 150, 330) == (255, 255, 255)
    assert _zoomed_pixel(doc, 1, 100, 330) == (0, 0, 0)
    # A hollow box is picked by its border, so what's inside it stays reachable.
    hollow = doc.markups(1)[0]
    assert hollow.covers(fitz.Point(100.5, 330)) and not hollow.covers(fitz.Point(150, 330))
    assert hollow.contains(fitz.Point(150, 330))
    doc.add_box(1, fitz.Rect(300, 300, 400, 360), BoxStyle(width=0, fill=(0, 1, 0)))
    borderless = doc.markups(1)[1]
    assert borderless.color is None
    assert tuple(borderless.bbox) == pytest.approx((300, 300, 400, 360))
    assert _zoomed_pixel(doc, 1, 300.5, 330) == (0, 255, 0)
    assert _zoomed_pixel(doc, 1, 299, 330) == (255, 255, 255)
    with pytest.raises(PdfError):
        doc.add_box(1, fitz.Rect(10, 10, 50, 50), BoxStyle(width=0, fill=None))
    assert len(doc.markups(1)) == 2


def test_move_and_delete_box_on_rotated_page(sample_pdf):
    doc = PdfDocument.open(sample_pdf)
    doc.rotate_pages([1], 90)
    shown = fitz.Rect(100, 200, 180, 240)  # as seen on screen
    doc.add_box(1, doc.from_display_rect(1, shown), BoxStyle(width=3, color=(1, 0, 0),
                                                              fill=(0, 1, 0)))
    (box,) = doc.markups(1)
    assert tuple(doc.to_display(1, box.bbox)) == pytest.approx(tuple(shown))
    assert _zoomed_pixel(doc, 1, 140, 220) == (0, 255, 0)
    doc.move_markup(box, 50, 100)
    (moved,) = doc.markups(1)
    assert tuple(doc.to_display(1, moved.bbox)) == pytest.approx((150, 300, 230, 340))
    assert (moved.width, moved.color, moved.fill) == (box.width, box.color, box.fill)
    assert _zoomed_pixel(doc, 1, 190, 320) == (0, 255, 0)
    assert _zoomed_pixel(doc, 1, 110, 220) == (255, 255, 255)
    doc.delete_markup(moved)
    assert doc.markups(1) == []
    assert doc.undo_label == "Delete box"


def test_resize_and_restyle_box(sample_pdf):
    doc = PdfDocument.open(sample_pdf)
    doc.add_box(1, fitz.Rect(100, 300, 200, 360), BoxStyle(width=2, color=(1, 0, 0), fill=None))
    (box,) = doc.markups(1)
    doc.set_box_rect(box, fitz.Rect(100, 300, 260, 400))
    assert doc.undo_label == "Resize box"
    (box,) = doc.markups(1)
    assert tuple(box.bbox) == pytest.approx((100, 300, 260, 400))
    assert box.style == BoxStyle(2, pytest.approx((1, 0, 0)), None)
    # A wider border in another colour, with a fill: the box stays where it is.
    doc.set_box_style(box, BoxStyle(width=6, color=(0, 0, 1), fill=(0, 1, 0)))
    (box,) = doc.markups(1)
    assert tuple(box.bbox) == pytest.approx((100, 300, 260, 400))
    assert box.width == pytest.approx(6) and box.color == pytest.approx((0, 0, 1))
    assert _zoomed_pixel(doc, 1, 98, 350) == (0, 0, 255)
    assert _zoomed_pixel(doc, 1, 102, 350) == (0, 0, 255)
    assert _zoomed_pixel(doc, 1, 96, 350) == (255, 255, 255)
    assert _zoomed_pixel(doc, 1, 180, 350) == (0, 255, 0)
    # Back to no border and, separately, no fill.
    doc.set_box_style(box, BoxStyle(width=0, fill=(0, 1, 0)))
    (box,) = doc.markups(1)
    assert box.color is None and box.style.width == 0
    assert _zoomed_pixel(doc, 1, 99, 350) == (255, 255, 255)
    assert _zoomed_pixel(doc, 1, 100.5, 350) == (0, 255, 0)
    doc.set_box_style(box, BoxStyle(width=1, color=(0, 0, 0), fill=None))
    assert doc.markups(1)[0].fill is None
    assert _zoomed_pixel(doc, 1, 180, 350) == (255, 255, 255)
    # The border can be removed from a hollow box too: it is still there (and can be
    # given a border or fill again), just not visible.
    bare = doc.set_box_style(doc.markups(1)[0], BoxStyle(width=0, fill=None))
    assert bare.color is None and bare.fill is None and bare.style.width == 0
    assert tuple(bare.bbox) == pytest.approx((100, 300, 260, 400))
    assert _zoomed_pixel(doc, 1, 100, 350) == (255, 255, 255)
    again = doc.set_box_style(bare, BoxStyle(width=2, color=(1, 0, 0), fill=None))
    assert _zoomed_pixel(doc, 1, 100, 350) == (255, 0, 0) and again.tag == bare.tag
    doc.undo()
    doc.undo()
    doc.undo()
    assert doc.markups(1)[0].fill == pytest.approx((0, 1, 0))


def test_last_placed_is_on_top(sample_pdf):
    doc = PdfDocument.open(sample_pdf)
    body = doc.text_lines(0)[1]
    cover = body.bbox + (-5, -5, 5, 5)

    def dark_pixels():
        pix = doc.doc[0].get_pixmap(clip=body.bbox)
        return sum(1 for x in range(pix.width) for y in range(pix.height)
                   if sum(pix.pixel(x, y)) < 200)

    assert dark_pixels() > 50
    doc.add_box(0, cover, BoxStyle(width=0, fill=(1, 1, 1)))  # placed after the text: hides it
    assert dark_pixels() == 0
    doc.add_text(0, fitz.Point(body.bbox.x0, body.bbox.y0), "Typed on the box", TextStyle())
    assert dark_pixels() > 50  # placed after the box: on top of it
    # Restyling or moving the box doesn't bring it to the front.
    box = doc.set_box_style(doc.markups(0)[0], BoxStyle(width=1, color=(1, 0, 0), fill=(1, 1, 0)))
    box = doc.move_markup(box, 2, 0)
    assert dark_pixels() > 50
    assert "Typed on the box" in doc.doc[0].get_text()
    # Editing text on the page keeps the box, and it can still be changed afterwards.
    doc.replace_text(doc.text_lines(0)[0], "New title")
    (box,) = doc.markups(0)
    assert box.fill == pytest.approx((1, 1, 0)) and box.width == pytest.approx(1)
    doc.delete_markup(box)
    assert doc.markups(0) == []
    pix = doc.doc[0].get_pixmap()
    assert pix.pixel(round(cover.x1 - 2), round(cover.y1 - 2)) == (255, 255, 255)


def test_box_made_as_annotation_is_converted_when_changed(sample_pdf):
    doc = PdfDocument.open(sample_pdf)
    page = doc.doc[1]
    annot = page.add_rect_annot(fitz.Rect(100, 300, 200, 360))
    for width in (6, 2):  # as older versions of Pixa left them: thinner, with a wide inset
        annot.set_border(width=width)
        annot.set_colors(stroke=(0, 0, 1), fill=(0, 1, 0))
        annot.update()
        annot.set_rect(fitz.Rect(100, 300, 200, 360))
        annot.update()
    (old,) = doc.markups(1)
    assert old.xref and tuple(old.bbox) == pytest.approx((100, 300, 200, 360))
    new = doc.set_box_style(old, BoxStyle(width=4, color=(0, 0, 1), fill=(0, 1, 0)))
    assert not list(doc.doc[1].annots())
    assert new.tag and tuple(new.bbox) == pytest.approx((100, 300, 200, 360))
    assert doc.markups(1) == [new]
    assert _zoomed_pixel(doc, 1, 99, 330) == (0, 0, 255)
    assert _zoomed_pixel(doc, 1, 97, 330) == (255, 255, 255)


def test_highlighting_again_replaces_the_old_highlight(sample_pdf):
    doc = PdfDocument.open(sample_pdf)
    title, body = doc.text_lines(0)
    words = {w[4]: fitz.Rect(w[:4]) for w in doc.doc[0].get_text("words")}
    row = lambda x0, x1: fitz.Rect(x0, body.bbox.y0, x1, body.bbox.y1)  # noqa: E731
    doc.add_highlight(0, [title.bbox, body.bbox], (1, 1, 0))
    once = _zoomed_pixel(doc, 0, body.bbox.x0 + 1, body.bbox.y0 + 1)
    # The same again: one highlight, no darker.
    doc.add_highlight(0, [title.bbox, body.bbox], (1, 1, 0))
    assert len(doc.markups(0)) == 1
    assert _zoomed_pixel(doc, 0, body.bbox.x0 + 1, body.bbox.y0 + 1) == once
    # Another colour over two words in the middle: the old one keeps the rest.
    doc.add_highlight(0, [row(words["quick"].x0, words["brown"].x1)], (0, 1, 1))
    old, new = doc.markups(0)
    assert new.color == pytest.approx((0, 1, 1)) and old.color == pytest.approx((1, 1, 0))
    kept = sorted(tuple(round(v) for v in r) for r in old.rects)
    assert kept == sorted(tuple(round(v) for v in r) for r in (
        title.bbox, row(body.bbox.x0, words["quick"].x0), row(words["brown"].x1, body.bbox.x1)))
    r, g, b = _zoomed_pixel(doc, 0, words["quick"].x0 + 1, body.bbox.y0 + 1)
    assert r < 100 and g > 200 and b > 200  # pure cyan, not mixed with the yellow
    assert doc.undo_label == "Highlight"
    doc.undo()
    assert len(doc.markups(0)) == 1 and len(doc.markups(0)[0].rects) == 2


# ---------------------------------------------------------------- layers
def _dark(doc, index, rect):
    """How many dark pixels a page shows in an (unrotated) area."""
    pix = doc.doc[index].get_pixmap(clip=doc.to_display(index, rect), alpha=False)
    return sum(1 for x in range(pix.width) for y in range(pix.height)
               if sum(pix.pixel(x, y)) < 200)


def _text_under_image(rotation=0):
    """A page with a bold word and, drawn after it, a red picture covering it."""
    from conftest import _png_bytes

    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 140), "Hello", fontsize=40, fontname="hebo")
    page.insert_image(fitz.Rect(60, 90, 260, 160), stream=_png_bytes(),
                      keep_proportion=False)
    page.set_rotation(rotation)
    return PdfDocument.from_bytes(pdf.tobytes()), fitz.Rect(60, 90, 260, 160)


@pytest.mark.parametrize("rotation", [0, 90])
def test_send_image_behind_text_and_back(rotation):
    doc, area = _text_under_image(rotation)
    assert _dark(doc, 0, area) == 0  # the picture hides the word
    (image,) = doc.images(0)
    assert doc.arrange(image, "forward") is False  # nothing above it
    assert doc.arrange(image, "front") is False
    assert not doc.can_undo
    assert doc.arrange(image, "backward") is True
    assert doc.undo_label == "Send backward"
    assert _dark(doc, 0, area) > 200  # the word shows on the picture
    (moved,) = doc.images(0)
    assert moved.bbox == image.bbox and moved.xref == image.xref
    assert doc.arrange(moved, "back") is False  # already behind all it overlaps
    assert doc.arrange(moved, "front") is True
    assert _dark(doc, 0, area) == 0
    doc.undo()
    assert _dark(doc, 0, area) > 200
    # It can still be moved and resized where it now lies.
    (image,) = doc.images(0)
    geometry = doc.image_geometry(image)
    geometry.center = fitz.Point(geometry.center.x + 10, geometry.center.y)
    doc.transform_image(image, geometry)
    assert _dark(doc, 0, area) > 200


def test_bring_text_in_front_of_image():
    doc, area = _text_under_image()
    (block,) = doc.text_blocks(0)
    assert doc.arrange(block, "front") is True
    assert _dark(doc, 0, area) > 200
    (again,) = doc.text_blocks(0)
    assert again.text == "Hello"
    assert tuple(again.bbox) == pytest.approx(tuple(block.bbox), abs=0.1)
    assert doc.arrange(again, "back") is True
    assert _dark(doc, 0, area) == 0
    assert doc.text_blocks(0)[0].text == "Hello"


def test_layering_splits_text_shared_by_several_paragraphs():
    """Producers often draw all text of a page in one text object, under a scaling."""
    from conftest import _png_bytes

    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((10, 10), "x", fontsize=1)  # just for a font resource
    font = page.get_fonts(full=True)[0][4]
    pdf.update_stream(page.get_contents()[0], (
        f"2 0 0 2 0 0 cm BT /{font} 10 Tf 36 350 Td (Top line here) Tj "
        "0 -150 Td (Bottom line) Tj ( more) Tj ET").encode())
    page = pdf.reload_page(page)
    page.insert_image(fitz.Rect(60, 420, 300, 560), stream=_png_bytes(), keep_proportion=False)
    doc = PdfDocument.from_bytes(pdf.tobytes())
    top, bottom = doc.text_blocks(0)
    words = doc.doc[0].get_text("words")
    assert _dark(doc, 0, bottom.bbox) == 0
    dark_top = _dark(doc, 0, top.bbox)
    (image,) = doc.images(0)
    assert doc.arrange(image, "backward") is True
    # Only the bottom paragraph overlaps the picture; both stay where they were.
    assert _dark(doc, 0, bottom.bbox) > 100
    assert _dark(doc, 0, top.bbox) == dark_top
    assert doc.doc[0].get_text("words") == words
    # And the text can go back behind it.
    assert doc.arrange(doc.text_blocks(0)[1], "backward") is True
    assert _dark(doc, 0, bottom.bbox) == 0
    assert [b.text for b in doc.text_blocks(0)] == ["Top line here", "Bottom line more"]
    assert tuple(doc.text_blocks(0)[1].bbox) == pytest.approx(tuple(bottom.bbox), abs=0.1)


def test_layer_boxes_and_change_them_afterwards():
    doc, area = _text_under_image()
    doc.add_box(0, fitz.Rect(50, 80, 120, 200), BoxStyle(2, (0, 0, 1), (0, 1, 0)))
    (box,) = doc.markups(0)
    green = fitz.Rect(100, 170, 110, 190)  # only the box is there
    assert doc.arrange(box, "back") is True
    (box,) = doc.markups(0)
    assert doc.arrange(box, "forward") is True  # past the word, still under the picture
    (box,) = doc.markups(0)
    assert doc.arrange(box, "forward") is True  # past the picture: on top
    (box,) = doc.markups(0)
    assert doc.arrange(box, "forward") is False
    assert _zoomed_pixel(doc, 0, 105, 180) == (0, 255, 0)
    doc.undo()
    (box,) = doc.markups(0)
    # Moving and restyling keep working where layering put the box.
    box = doc.move_markup(box, 5, 0)
    box = doc.set_box_style(box, BoxStyle(0, (0, 0, 0), (1, 1, 0)))
    assert tuple(box.bbox) == pytest.approx((55, 80, 125, 200))
    assert _zoomed_pixel(doc, 0, 122, 180) == (255, 255, 0)
    assert _dark(doc, 0, green) == 0
    doc.delete_markup(box)
    assert doc.markups(0) == []


def test_layer_box_annotation_and_highlights():
    doc, area = _text_under_image()
    annot = doc.doc[0].add_rect_annot(fitz.Rect(40, 100, 300, 150))
    annot.set_colors(stroke=(0, 0, 1), fill=(0, 1, 0))
    annot.update()
    del annot  # it holds on to the page, which layering reloads
    (box,) = doc.markups(0)
    assert box.xref
    assert doc.arrange(box, "front") is False  # annotations lie on top of everything
    assert doc.arrange(box, "back") is True
    assert not list(doc.doc[0].annots())
    (box,) = doc.markups(0)
    assert box.tag and not box.xref
    doc.add_highlight(0, [fitz.Rect(72, 100, 150, 150)], (1, 1, 0))
    highlight = next(m for m in doc.markups(0) if m.kind == "highlight")
    with pytest.raises(PdfError):
        doc.arrange(highlight, "back")


def test_scan_content_stream():
    from pixa import layers

    data = (b"q 1 0 0 1 10 20 cm BI /W 2 /H 1 /BPC 8 /CS /G ID \x00EI\xff EI Q "
            b"% a comment (with a paren\n"
            b"BT /F1 12 Tf 100 200 Td (a \\) (nested) string) Tj T* [(x) 5 (y)] TJ ET "
            b"/Im0 Do")
    ops, final = layers.scan(data)
    names = [op.name for op in ops]
    assert names == [b"q", b"cm", b"BI", b"ID", b"Q", b"BT", b"Tf", b"Td", b"Tj", b"T*",
                     b"TJ", b"ET", b"Do"]
    tj = ops[names.index(b"Tj")]
    assert tj.in_text and tj.line_start and tj.origin == fitz.Point(100, 200)
    assert not ops[names.index(b"T*")].line_start
    assert ops[names.index(b"TJ")].line_start
    assert ops[-1].operand == b"Im0"
    assert ops[names.index(b"Q")].ctm == fitz.Matrix(1, 0, 0, 1, 10, 20)
    assert final == fitz.Identity
    # A spot inside the text object splits it, continuing from the line matrix.
    spot = layers.after(ops, names.index(b"Tj"), final)
    assert spot.pos == ops[names.index(b"T*")].start
    assert spot.line_matrix == fitz.Matrix(1, 0, 0, 1, 100, 200)
    assert layers.place(b"X", spot) == b"\nET\nq\nX\nQ\nBT 1 0 0 1 100 200 Tm\n"


# ---------------------------------------------------- pages from elsewhere
def test_insert_pdfs_from_files_and_dragged_pages(sample_pdf):
    doc = PdfDocument.open(sample_pdf)
    other = PdfDocument.open(sample_pdf)
    other.replace_text(other.text_lines(1)[0], "Dragged page")
    dragged = other.pages_pdf([1])
    assert fitz.open(stream=dragged).page_count == 1
    assert doc.insert_pdfs([dragged, sample_pdf], 1) == 4
    assert doc.page_count == 7
    texts = [doc.doc[i].get_text() for i in range(doc.page_count)]
    assert "Dragged page" in texts[1] and "Page 2 title" not in texts[1]
    assert [t.splitlines()[0] for t in texts[2:5]] == [f"Page {i} title" for i in (1, 2, 3)]
    doc.undo()  # one step
    assert doc.page_count == 3
    with pytest.raises(PdfError):
        doc.insert_pdfs([b"not a pdf"], 0)
    assert doc.page_count == 3


def test_documents_and_pages_from_images(tmp_path, png_bytes):
    path = tmp_path / "pic.png"
    path.write_bytes(png_bytes)
    doc = PdfDocument.from_images([str(path), png_bytes])
    assert doc.page_count == 2 and doc.dirty and doc.path is None
    w, h = doc.page_size(0)
    assert w == pytest.approx(h) and w == pytest.approx(fitz.paper_size("a4")[0])
    assert len(doc.images(0)) == 1
    assert doc.images(0)[0].bbox == doc.doc[0].rect
    assert doc.insert_image_pages([str(path)], 1) == 1
    assert doc.page_count == 3 and doc.undo_label == "Insert page"
    from conftest import _png_bytes

    names = doc.add_images(1, [(geo((10, 10, 60, 60)), _png_bytes((0, 255, 0))),
                               (geo((70, 10, 90, 30)), _png_bytes((0, 0, 255)))])
    assert len(names) == 2 and doc.undo_label == "Add images"
    assert {im.name for im in doc.images(1)} >= set(names)
    with pytest.raises(PdfError):
        PdfDocument.from_images([b"nope"])


SVG = (b'<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100">'
       b'<rect width="100" height="100" fill="red"/>'
       b'<circle cx="150" cy="50" r="40" fill="blue"/></svg>')


def test_svg_is_inserted_as_vector_graphics(tmp_path):
    import gzip

    path = tmp_path / "logo.svgz"
    path.write_bytes(gzip.compress(SVG))
    doc = PdfDocument.from_images([SVG, str(path)])
    for index in range(2):
        page = doc.doc[index]
        assert page.get_images() == [] and len(page.get_drawings()) == 2
        (image,) = doc.images(index)
        assert image.vector and image.bbox == page.rect
    # Its colours land where the SVG put them, not mirrored or turned.
    pix = doc.doc[0].get_pixmap()
    assert pix.pixel(10, pix.height // 2) == (255, 0, 0)
    assert pix.pixel(pix.width * 3 // 4, pix.height // 2) == (0, 0, 255)
    with pytest.raises(PdfError):
        PdfDocument.from_images([b"<svg xmlns='http://www.w3.org/2000/svg'><broken"])


@pytest.mark.parametrize("rotation", [0, 90])
def test_svg_moves_layers_and_deletes_like_an_image(sample_pdf, rotation):
    doc = PdfDocument.open(sample_pdf)
    doc.rotate_pages([1], rotation)
    name = doc.add_image(1, geo((100, 200, 300, 300), angle=30), data=SVG)
    (image,) = doc.images(1)
    assert image.vector and image.name == name
    placed = doc.image_geometry(image)
    assert (placed.center.x, placed.center.y) == pytest.approx((200, 250), abs=0.01)
    assert (placed.width, placed.height, placed.angle) == pytest.approx((200, 100, 30), abs=0.01)
    doc.transform_image(image, geo((50, 50, 150, 100)))
    (image,) = doc.images(1)
    assert tuple(doc.to_display(1, image.bbox)) == pytest.approx((50, 50, 150, 100), abs=0.01)
    pix = doc.render_vector(image, 2)
    assert (pix.width, pix.height, pix.alpha) == (200, 100, 1)
    doc.arrange(image, "back")
    assert doc.images(1)[0].vector
    doc.replace_text(doc.text_lines(1)[0], "New title")
    assert doc.images(1)[0].vector  # untouched by editing text around it
    doc.delete_image(doc.images(1)[0])
    assert doc.images(1) == [] and doc.doc[1].get_drawings() == []
    doc.undo()
    assert len(doc.images(1)) == 1


def test_pixels_inside_an_svg_are_not_images_of_their_own(png_bytes):
    import base64

    svg = (b'<svg xmlns="http://www.w3.org/2000/svg" '
           b'xmlns:xlink="http://www.w3.org/1999/xlink" width="80" height="40">'
           b'<image width="40" height="40" xlink:href="data:image/png;base64,'
           + base64.b64encode(png_bytes) + b'"/></svg>')
    doc = PdfDocument.from_images([svg])
    (image,) = doc.images(0)
    assert image.vector


def test_simple_font_with_two_byte_tounicode_survives_edits(tmp_path):
    """A one-byte (Type1) font whose /ToUnicode declares <0000> <FFFF>, as some
    producers write it: text drawn in it again must still use one-byte codes."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Scope", fontname="helv", fontsize=14)
    font_xref = page.get_fonts()[0][0]
    pairs = "".join(f"<{ord(ch):02X}> <{ord(ch):04X}>\n" for ch in "Scope")
    cmap = ("/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n"
            "1 begincodespacerange <0000> <FFFF> endcodespacerange\n"
            f"5 beginbfchar\n{pairs}endbfchar\nendcmap end end\n")
    tu = doc.get_new_xref()
    doc.update_object(tu, "<<>>")
    doc.update_stream(tu, cmap.encode())
    doc.xref_set_key(font_xref, "ToUnicode", f"{tu} 0 R")
    # Not a standard font name, so Pixa reuses the PDF's own font object.
    doc.xref_set_key(font_xref, "BaseFont", "/XWKEFT+UniversS-CondensedBold")
    path = tmp_path / "simple.pdf"
    doc.save(path)

    pdf = PdfDocument.open(str(path))
    pdf.fonts = SystemFonts([])
    for _ in range(2):
        pdf.move_text_block(pdf.text_blocks(0)[0], 5, 0)
        assert pdf.replace_text(pdf.text_lines(0)[0], "Scope") is None
        assert [ln.text for ln in pdf.text_lines(0)] == ["Scope"]
    line = pdf.text_lines(0)[0]
    assert line.font.endswith("UniversS-CondensedBold")
    assert line.spans[0].origin.x == pytest.approx(82, abs=0.5)


def test_highlights_move_with_their_text(sample_pdf):
    doc = PdfDocument.open(sample_pdf)
    title, body = doc.text_lines(0)[:2]
    # One highlight over both lines: only the part on the moved line goes along.
    doc.add_highlight(0, [fitz.Rect(title.bbox), fitz.Rect(body.bbox)], (0, 1, 0))
    (line,) = [b for b in doc.line_blocks(0) if b.text == "The quick brown fox"]
    doc.move_text_block(line, 30, 40)
    (mark,) = doc.markups(0)
    assert mark.color == pytest.approx((0, 1, 0))
    top, bottom = sorted(mark.rects, key=lambda r: r.y0)
    assert tuple(top) == pytest.approx(tuple(title.bbox), abs=0.5)
    assert tuple(bottom) == pytest.approx(tuple(body.bbox + (30, 40, 30, 40)), abs=0.5)
    doc.undo()  # one step for both
    (mark,) = doc.markups(0)
    assert max(r.y1 for r in mark.rects) == pytest.approx(body.bbox.y1, abs=0.5)


def test_moving_several_items_carries_highlights(sample_pdf):
    doc = PdfDocument.open(sample_pdf)
    body = doc.text_lines(0)[1]
    doc.add_highlight(0, [fitz.Rect(body.bbox)], (1, 1, 0))
    (mark,) = doc.markups(0)
    (line,) = [b for b in doc.line_blocks(0) if b.text == "The quick brown fox"]
    doc.move_items([line, mark], 0, 50)  # the highlight is selected too: moved once
    (moved,) = doc.markups(0)
    assert moved.bbox.y0 == pytest.approx(body.bbox.y0 + 50, abs=0.5)
