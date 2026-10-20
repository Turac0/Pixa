import pymupdf as fitz
import pytest


def _png_bytes(color=(255, 0, 0), size=40) -> bytes:
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, size, size), False)
    pix.set_rect(pix.irect, color)
    return pix.tobytes("png")


@pytest.fixture
def png_bytes():
    return _png_bytes()


@pytest.fixture
def sample_pdf(tmp_path):
    """A 3-page PDF; each page has a title line, a body line and page 0 has an image."""
    doc = fitz.open()
    for i in range(3):
        page = doc.new_page()
        page.insert_text((72, 100), f"Page {i + 1} title", fontsize=20, fontname="hebo")
        page.insert_text((72, 130), "The quick brown fox", fontsize=12, fontname="tiro")
    doc[0].insert_image(fitz.Rect(300, 300, 400, 400), stream=_png_bytes())
    path = tmp_path / "sample.pdf"
    doc.save(path)
    return str(path)
