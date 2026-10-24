"""PDF document model.

Every mutation of a PDF goes through :class:`PdfDocument`. The module has no Qt
dependency so it can be unit tested in isolation.

Coordinate conventions
----------------------
PyMuPDF reports text and image positions in *unrotated* page space and also
expects unrotated coordinates for insertions and redactions. Rendered pixmaps,
however, show the page *with* its rotation applied. Methods here take and
return unrotated coordinates; use :meth:`PdfDocument.to_display` and
:meth:`PdfDocument.from_display` to convert for the UI.
"""

from __future__ import annotations

import gzip
import math
import os
import re
import tempfile
import zlib
from collections.abc import Callable, Iterable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field

import pymupdf as fitz

from pixa import layers
from pixa.fonts import (
    SystemFonts,
    face_bytes,
    family_name,
    normalize,
    read_faces_from,
    style_of,
    weight_from_name,
    weight_label,
)
from pixa.i18n import N_, ntr, tr
from pixa.pdffont import PdfFontEncoder, find_encoder, write_text

MAX_HISTORY = 50

# Flips the image unit square between PDF (y up) and PyMuPDF (y down) conventions.
_IMAGE_FLIP = fitz.Matrix(1, 0, 0, -1, 0, 1)
# Marks the form XObjects that hold an inserted SVG, so they are treated as images.
_VECTOR_KEY = "PixaVector"

_FONT_LABELS = {"helv": "Helvetica", "tiro": "Times", "cour": "Courier"}

_shared_system_fonts: SystemFonts | None = None


def system_fonts() -> SystemFonts:
    """The process-wide installed-font index (built lazily)."""
    global _shared_system_fonts
    if _shared_system_fonts is None:
        _shared_system_fonts = SystemFonts()
    return _shared_system_fonts

# Base-14 font codes keyed by (family, bold, italic).
_BASE14 = {
    ("helv", False, False): "helv",
    ("helv", True, False): "hebo",
    ("helv", False, True): "heit",
    ("helv", True, True): "hebi",
    ("tiro", False, False): "tiro",
    ("tiro", True, False): "tibo",
    ("tiro", False, True): "tiit",
    ("tiro", True, True): "tibi",
    ("cour", False, False): "cour",
    ("cour", True, False): "cobo",
    ("cour", False, True): "coit",
    ("cour", True, True): "cobi",
}

# Standard fonts offered in the font picker, by Base-14 family code.
# The labels are translated where they are shown.
FONT_FAMILIES = {N_("Helvetica (standard)"): "helv", N_("Times (standard)"): "tiro",
                 N_("Courier (standard)"): "cour"}


def fallback_family(font_name: str) -> str:
    """The standard family (helv/tiro/cour) closest to a font, judged by its name."""
    name = font_name.lower()
    if any(w in name for w in ("mono", "courier", "consol", "code")):
        return "cour"
    if "sans" in name or any(w in name for w in ("arial", "helvetica", "calibri", "verdana")):
        return "helv"
    if any(w in name for w in ("serif", "times", "roman", "georgia", "garamond", "cambria",
                                "book", "minion", "palatino")):
        return "tiro"
    return "helv"

# span["flags"] bits as documented by PyMuPDF
_FLAG_ITALIC = 1 << 1
_FLAG_SERIF = 1 << 2
_FLAG_MONO = 1 << 3
_FLAG_BOLD = 1 << 4


class PdfError(Exception):
    """Raised for user-facing errors (bad file, wrong password, ...)."""


@dataclass
class TextStyle:
    family: str = "helv"  # one of FONT_FAMILIES values
    size: float = 12.0
    color: tuple[float, float, float] = (0.0, 0.0, 0.0)
    bold: bool = False
    italic: bool = False
    underline: bool = False
    # A font face used in the document, by its label ("Inter SemiBold"), or
    # None for the standard font picked by ``family`` (Helvetica/Times/Courier).
    font: str | None = None
    typeface: str | None = None  # that face's family ("Inter"), for previews
    weight: int = 400  # 100 (thin) .. 900 (black); "bold" is the B toggle

    @property
    def base14(self) -> str:
        return _BASE14[(self.family, self.bold, self.italic)]

    def same_face(self, other: TextStyle) -> bool:
        """Same typeface (size, colour and underline may differ)."""
        return (self.font, self.weight, self.bold, self.italic, self.family) == (
            other.font, other.weight, other.bold, other.italic, other.family
        )


@dataclass
class DocFace:
    """A font face used in the document."""

    label: str  # what the font picker shows: "Inter SemiBold", "Inter", "Inter Italic"
    family: str  # "Inter"
    weight: int
    italic: bool
    fallback: str  # closest standard family: "helv" | "tiro" | "cour"
    pdf_name: str  # the font's name in the PDF (BaseFont)

    @staticmethod
    def make(family: str, weight: int, italic: bool, serif: bool | None, mono: bool,
             pdf_name: str) -> DocFace:
        style = " ".join(w for w in (weight_label(weight), "Italic" if italic else "") if w)
        if mono:
            fallback = "cour"
        elif serif is not None:
            fallback = "tiro" if serif else "helv"
        else:
            fallback = fallback_family(family)
        return DocFace(f"{family} {style}".strip(), family, weight, italic, fallback, pdf_name)

    def apply(self, style: TextStyle) -> None:
        """Make ``style`` use this face."""
        style.font, style.typeface = self.label, self.family
        style.weight, style.italic, style.family = self.weight, self.italic, self.fallback
        style.bold = self.weight >= 600


@dataclass
class Decoration:
    """An underline or strikethrough: in PDFs these are separate vector lines.

    Positions are relative to the text line: ``start``/``end`` along the
    reading direction from the line's origin, ``offset`` across it (positive
    is below the baseline).
    """

    kind: str  # "underline" | "strike"
    start: float
    end: float
    offset: float
    thickness: float
    color: tuple[float, float, float]
    area: fitz.Rect  # unrotated bounding box of the drawing, for removal


@dataclass
class TextLine:
    """One line of text on a page, as extracted from the PDF."""

    page: int
    bbox: fitz.Rect  # unrotated page coordinates
    origin: fitz.Point  # baseline start of the first span
    text: str
    font: str  # PDF font name of the first span
    style: TextStyle
    direction: tuple[float, float]
    spans: list[TextSpan] = field(default_factory=list)
    decorations: list[Decoration] = field(default_factory=list)

    @property
    def length(self) -> float:
        """Extent of the glyphs along the reading direction, from the origin."""
        dx, dy = self.direction
        corners = (self.bbox.tl, self.bbox.tr, self.bbox.bl, self.bbox.br)
        return max((c.x - self.origin.x) * dx + (c.y - self.origin.y) * dy for c in corners)

    @property
    def horizontal(self) -> bool:
        return abs(self.direction[1]) < 1e-3


@dataclass
class TextSpan:
    """A run of text with one font and style (part of a line)."""

    text: str
    origin: fitz.Point  # unrotated page coordinates
    font: str
    style: TextStyle


@dataclass
class TextBlock:
    """A text box: the lines PDF text extraction groups together (e.g. a paragraph)."""

    page: int
    bbox: fitz.Rect  # unrotated page coordinates
    lines: list[TextLine]

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)


@dataclass
class ImageInfo:
    page: int
    bbox: fitz.Rect  # unrotated page coordinates
    xref: int  # 0 for inline images
    # Maps the image's unit square (y down) onto the unrotated page.
    transform: fitz.Matrix = field(default_factory=fitz.Matrix)
    name: str | None = None  # resource name used by "/name Do" on the page, if unique
    vector: bool = False  # an inserted SVG (a form XObject), not pixels

    def contains(self, point: fitz.Point) -> bool:
        """Hit test against the real (possibly rotated) image, not its bbox."""
        if abs(self.transform.a * self.transform.d - self.transform.b * self.transform.c) < 1e-9:
            return point in self.bbox
        p = fitz.Point(point) * ~self.transform
        return -0.001 <= p.x <= 1.001 and -0.001 <= p.y <= 1.001


@dataclass
class _VectorForms:
    drawn: dict[str, int]  # resource name -> xref of the SVGs the page draws itself
    inner: set[int]  # those and every form XObject they use


@dataclass
class ImageGeometry:
    """Placement of an image as seen on screen (page rotation applied)."""

    center: fitz.Point
    width: float
    height: float
    angle: float  # degrees, clockwise on screen
    flipped: bool = False  # mirrored images keep their mirroring when transformed


@dataclass
class BoxStyle:
    """How a new box is drawn: border width (0 for none), border colour and fill."""

    width: float = 1.5
    color: tuple[float, float, float] = (0.851, 0.188, 0.145)
    fill: tuple[float, float, float] | None = None  # None is transparent


@dataclass
class Markup:
    """A highlight (an annotation on top of the page) or a box (drawn on the page)."""

    page: int
    xref: int  # of the annotation; 0 for a box drawn on the page, which has a ``tag``
    kind: str  # "highlight" | "box"
    bbox: fitz.Rect  # unrotated page coordinates
    rects: list[fitz.Rect]  # the highlighted areas (for a box: its outer edge)
    color: tuple[float, float, float] | None = None  # highlight / border colour
    fill: tuple[float, float, float] | None = None
    width: float = 0.0  # border width of a box
    tag: int = 0  # number of a box in the page's content

    @property
    def style(self) -> BoxStyle:
        """A box's border and fill, as the box tool describes them."""
        return BoxStyle(self.width if self.color else 0.0, self.color or BoxStyle().color,
                        self.fill)

    def contains(self, point: fitz.Point) -> bool:
        return any(point in r for r in self.rects)

    def covers(self, point: fitz.Point) -> bool:
        """True where the markup lies over the page content: anywhere on a
        highlight or a filled box, but only on the border of a hollow box."""
        if not self.contains(point):
            return False
        if self.kind == "highlight" or self.fill is not None:
            return True
        reach = max(3.0, self.width)
        return point not in self.bbox + (reach, reach, -reach, -reach)


def _int_to_rgb(color: int) -> tuple[float, float, float]:
    return (((color >> 16) & 255) / 255, ((color >> 8) & 255) / 255, (color & 255) / 255)


def _rgb(color: Sequence[float] | None) -> tuple[float, float, float] | None:
    """An annotation colour as RGB (they may also be grey; None for no colour)."""
    if not color:
        return None
    if len(color) == 3:
        return tuple(color)
    return (color[0],) * 3 if len(color) == 1 else None


_BOX_CODE = re.compile(rb"/PixaBox\s*<<(.*?)>>\s*BDC.*?EMC", re.S)


def _box_fix(code: bytes) -> fitz.Matrix | None:
    """The coordinate fix a box's drawing code starts with, if any (see ``_box_code``)."""
    m = re.search(rb"BDC\s*q\s+((?:[-+\d.]+\s+){6})cm", code)
    return fitz.Matrix(*(float(v) for v in m.group(1).split())) if m else None


def _rect_minus(rect: fitz.Rect, cut: fitz.Rect) -> list[fitz.Rect]:
    """What is left of ``rect`` after ``cut`` is taken out of it (up to four pieces).

    Made for highlights, which are as tall as their line of text: a mere touch
    (the boxes of neighbouring lines overlap a little) leaves ``rect`` whole,
    and slivers are dropped.
    """
    both = fitz.Rect(max(rect.x0, cut.x0), max(rect.y0, cut.y0),
                     min(rect.x1, cut.x1), min(rect.y1, cut.y1))
    least = 0.3 * min(rect.width, rect.height, cut.width, cut.height)
    if both.width < least or both.height < least or both.width <= 0 or both.height <= 0:
        return [rect]
    pieces = [
        fitz.Rect(rect.x0, rect.y0, rect.x1, both.y0),  # above
        fitz.Rect(rect.x0, both.y1, rect.x1, rect.y1),  # below
        fitz.Rect(rect.x0, both.y0, both.x0, both.y1),  # left
        fitz.Rect(both.x1, both.y0, rect.x1, both.y1),  # right
    ]
    return [p for p in pieces if p.width >= least and p.height >= least]


def _open_other(source: str | bytes) -> fitz.Document:
    """Another PDF to take pages from: a file path or a file's contents."""
    name = os.path.basename(source) if isinstance(source, str) else tr("The dropped pages")
    try:
        if isinstance(source, str):
            doc = fitz.open(source)
        else:
            doc = fitz.open(stream=source, filetype="pdf")
    except Exception as exc:  # pymupdf raises various error types
        raise PdfError(tr("Could not open {name}: {error}", name=name, error=exc)) from exc
    if not doc.is_pdf:
        doc.close()
        raise PdfError(tr("{name} is not a PDF.", name=name))
    if doc.needs_pass:
        doc.close()
        raise PdfError(tr("{name} is password protected.", name=name))
    return doc


def _image_source(source: str | bytes) -> dict:
    """``insert_image`` arguments for an image file path or an image file's contents."""
    return {"filename": source} if isinstance(source, str) else {"stream": source}


def _svg_data(source: str | bytes) -> bytes | None:
    """The markup of an SVG image (``.svg``/``.svgz`` path or file contents), else None."""
    if isinstance(source, str):
        if not source.lower().endswith((".svg", ".svgz")):
            return None
        try:
            with open(source, "rb") as fh:
                data = fh.read()
        except OSError as exc:
            raise PdfError(tr("{name} could not be read.",
                              name=os.path.basename(source))) from exc
    else:
        data = source
    if data[:2] == b"\x1f\x8b":  # svgz
        try:
            data = gzip.decompress(data)
        except (OSError, EOFError):
            return None
    if isinstance(source, str):
        return data
    head = data[:4096].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    return data if head.startswith(b"<") and b"<svg" in head else None


def _svg_page(data: bytes, name: str) -> fitz.Document:
    """An SVG converted to a one-page PDF (its drawing stays vector graphics)."""
    try:
        svg = fitz.open(stream=data, filetype="svg")
        pdf = fitz.open("pdf", svg.convert_to_pdf())
    except Exception as exc:
        raise PdfError(tr("{name} could not be read as an SVG image.", name=name)) from exc
    if not pdf.page_count or pdf[0].rect.is_empty:
        raise PdfError(tr("{name} is an empty SVG image.", name=name))
    return pdf


def _source_name(source: str | bytes) -> str:
    return os.path.basename(source) if isinstance(source, str) else tr("The image")


def image_size(source: str | bytes) -> tuple[float, float]:
    """Width and height in pixels of an image file (path or contents); SVGs in points."""
    svg = _svg_data(source)
    if svg is not None:
        rect = _svg_page(svg, _source_name(source))[0].rect
        return max(1.0, rect.width), max(1.0, rect.height)
    try:
        pix = fitz.Pixmap(source)
    except Exception as exc:
        raise PdfError(tr("{name} could not be read as an image.",
                          name=_source_name(source))) from exc
    return max(1, pix.width), max(1, pix.height)


def _style_from_span(span: dict) -> TextStyle:
    flags = span.get("flags", 0)
    name = span.get("font", "")
    font = name.lower()
    # The family class comes from the name: MuPDF's serif flag is often wrong
    # (it marks Inter as serif, which made every fallback Times).
    family = "cour" if flags & _FLAG_MONO else fallback_family(name)
    weight = weight_from_name(name)
    bold = bool(flags & _FLAG_BOLD) or weight >= 600 or "bold" in font or "black" in font
    if bold and weight < 600:
        weight = 700
    italic = bool(flags & _FLAG_ITALIC) or "italic" in font or "oblique" in font
    return TextStyle(
        family=family,
        size=round(span.get("size", 12.0), 2),
        color=_int_to_rgb(span.get("color", 0)),
        bold=bold,
        italic=italic,
        weight=weight,
    )


# Also the undo labels of the moves; both are translated where they are shown.
LAYER_MOVES = {"front": N_("Bring to front"), "forward": N_("Bring forward"),
               "backward": N_("Send backward"), "back": N_("Send to back")}


@dataclass
class _Layer:
    """Where an element is drawn in a page's content (see ``PdfDocument.arrange``)."""

    item: ImageInfo | TextBlock | Markup
    bbox: fitz.Rect
    ops: list[int]  # the operators drawing it, in order (none for a box)
    first: int  # where its drawing starts in the content
    span: tuple[int, int] | None = None  # a box: where its code is

    def before(self, ops: list[layers.Op], final: fitz.Matrix) -> layers.Spot:
        if self.span is not None:
            return layers.Spot(self.span[0], layers.ctm_at(ops, final, self.span[0]))
        return layers.before(ops, self.ops[0])

    def after(self, ops: list[layers.Op], final: fitz.Matrix) -> layers.Spot:
        if self.span is not None:
            # A box's code leaves the coordinate system as it found it.
            return layers.Spot(self.span[1], layers.ctm_at(ops, final, self.span[0]))
        return layers.after(ops, self.ops[-1], final)


def _same_element(a: ImageInfo | TextBlock | Markup, b: ImageInfo | TextBlock | Markup) -> bool:
    def close(r: fitz.Rect, s: fitz.Rect) -> bool:
        return all(abs(x - y) < 0.5 for x, y in zip(r, s, strict=True))

    # Redacting text (to redraw it) renames the page's image resources, so
    # images are told apart by what they show and where.
    if isinstance(a, ImageInfo):
        return isinstance(b, ImageInfo) and a.xref == b.xref and close(a.bbox, b.bbox)
    if isinstance(a, Markup):
        return isinstance(b, Markup) and (a.kind, a.xref, a.tag) == (b.kind, b.xref, b.tag)
    return isinstance(b, TextBlock) and close(a.bbox, b.bbox)


class PdfDocument:
    """A PDF opened for editing, with snapshot-based undo/redo."""

    def __init__(self) -> None:
        self.doc: fitz.Document = fitz.open()
        self.path: str | None = None
        self.revision = 0
        self.dirty = False
        self._undo: list[tuple[str, bytes]] = []
        self._redo: list[tuple[str, bytes]] = []
        self.listeners: list[Callable[[], None]] = []
        self.fonts: SystemFonts = system_fonts()
        self._embedded_installed_fonts = False  # subset fonts when saving
        self._fonts_cache: tuple[int, list[DocFace]] | None = None
        self._identity_cache: dict[tuple[int, str], DocFace] = {}
        self._face_by_font: dict[str, DocFace] = {}
        self._word_rows: tuple[tuple[int, int], list[tuple[int, list[fitz.Rect]]]] | None = None
        self._editing = False  # inside an _edit, whose snapshot covers nested ones

    # ------------------------------------------------------------------ files
    @classmethod
    def open(cls, path: str, password: str | None = None) -> PdfDocument:
        try:
            with open(path, "rb") as fh:
                data = fh.read()
            # Opening from memory means the file on disk is never locked, so
            # we can save back to it (important on Windows).
            doc = fitz.open(stream=data, filetype="pdf")
        except Exception as exc:  # pymupdf raises various error types
            raise PdfError(tr("Could not open {name}: {error}",
                              name=os.path.basename(path), error=exc)) from exc
        if doc.needs_pass and not doc.authenticate(password or ""):
            doc.close()
            raise PdfError("password")
        self = cls()
        self.doc = doc
        self.path = path
        return self

    @staticmethod
    def needs_password(path: str) -> bool:
        try:
            with fitz.open(path) as doc:
                return bool(doc.needs_pass)
        except Exception:
            return False

    def save(self, path: str | None = None) -> None:
        path = path or self.path
        if not path:
            raise PdfError(tr("No file name given"))
        directory = os.path.dirname(os.path.abspath(path))
        fd, tmp = tempfile.mkstemp(suffix=".pdf", dir=directory)
        os.close(fd)
        try:
            out = self.doc
            if self._embedded_installed_fonts:
                # Installed fonts are embedded whole while editing (so later
                # edits can use any glyph); keep only the used glyphs on disk.
                out = fitz.open(stream=self.doc.tobytes(), filetype="pdf")
                try:
                    out.subset_fonts()
                except Exception:
                    pass  # an unsubsetted file is still a correct file
            out.save(tmp, garbage=3, deflate=True, clean=False)
            if out is not self.doc:
                out.close()
            os.replace(tmp, path)
        except Exception as exc:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise PdfError(tr("Could not save: {error}", error=exc)) from exc
        self.path = path
        self.dirty = False
        self._notify()

    @property
    def page_count(self) -> int:
        return self.doc.page_count

    def page_size(self, index: int) -> tuple[float, float]:
        """Display size (rotation applied) of a page in points."""
        r = self.doc[index].rect
        return r.width, r.height

    def render(self, index: int, zoom: float) -> fitz.Pixmap:
        page = self.doc[index]
        return page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False, annots=True)

    # ------------------------------------------------------------ coordinates
    def to_display(self, index: int, rect: fitz.Rect) -> fitz.Rect:
        return fitz.Rect(rect) * self.doc[index].rotation_matrix

    def from_display(self, index: int, point: fitz.Point) -> fitz.Point:
        return fitz.Point(point) * self.doc[index].derotation_matrix

    def from_display_rect(self, index: int, rect: fitz.Rect) -> fitz.Rect:
        return fitz.Rect(rect) * self.doc[index].derotation_matrix

    # ---------------------------------------------------------------- history
    def _notify(self) -> None:
        for fn in list(self.listeners):
            fn()

    @contextmanager
    def _edit(self, label: str):
        if self._editing:  # part of a bigger change: that one is the undo step
            yield
            return
        snapshot = self.doc.tobytes()
        self._editing = True
        try:
            yield
        except Exception:
            self._restore(snapshot)
            raise
        finally:
            self._editing = False
        self._undo.append((label, snapshot))
        del self._undo[:-MAX_HISTORY]
        self._redo.clear()
        self.revision += 1
        self.dirty = True
        self._notify()

    def _restore(self, data: bytes) -> None:
        self.doc.close()
        self.doc = fitz.open(stream=data, filetype="pdf")

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def undo_label(self) -> str:
        return self._undo[-1][0] if self._undo else ""

    @property
    def redo_label(self) -> str:
        return self._redo[-1][0] if self._redo else ""

    def undo(self) -> None:
        if not self._undo:
            return
        label, data = self._undo.pop()
        self._redo.append((label, self.doc.tobytes()))
        self._restore(data)
        self.revision += 1
        self.dirty = True
        self._notify()

    def redo(self) -> None:
        if not self._redo:
            return
        label, data = self._redo.pop()
        self._undo.append((label, self.doc.tobytes()))
        self._restore(data)
        self.revision += 1
        self.dirty = True
        self._notify()

    # ----------------------------------------------------------------- pages
    def rotate_pages(self, pages: Iterable[int], degrees: int) -> None:
        pages = sorted(set(pages))
        if not pages:
            return
        with self._edit("Rotate page" if len(pages) == 1 else "Rotate pages"):
            for i in pages:
                page = self.doc[i]
                page.set_rotation((page.rotation + degrees) % 360)

    def delete_pages(self, pages: Iterable[int]) -> None:
        pages = sorted(set(pages))
        if not pages:
            return
        if len(pages) >= self.page_count:
            raise PdfError(tr("A PDF must keep at least one page."))
        with self._edit("Delete page" if len(pages) == 1 else "Delete pages"):
            self.doc.delete_pages(pages)

    def reorder_pages(self, order: Sequence[int]) -> None:
        """Reorder pages. ``order[i]`` is the old index of the new page ``i``."""
        order = list(order)
        if sorted(order) != list(range(self.page_count)):
            raise ValueError("order must be a permutation of all page indices")
        if order == list(range(self.page_count)):
            return
        with self._edit("Reorder pages"):
            self.doc.select(order)

    def move_page(self, src: int, dst: int) -> None:
        order = list(range(self.page_count))
        order.insert(dst, order.pop(src))
        self.reorder_pages(order)

    def insert_pdf(self, path: str, at: int) -> int:
        """Insert all pages of another PDF before index ``at``; returns the count."""
        return self.insert_pdfs([path], at)

    def insert_pdfs(self, sources: Sequence[str | bytes], at: int) -> int:
        """Insert all pages of other PDFs (file paths or file contents) before index
        ``at``, as one undo step; returns the number of pages inserted."""
        others: list[fitz.Document] = []
        try:
            for source in sources:
                others.append(_open_other(source))
            count = sum(other.page_count for other in others)
            if count:
                with self._edit("Insert pages" if count > 1 else "Insert page"):
                    for other in others:
                        self.doc.insert_pdf(other, start_at=at)
                        at += other.page_count
        finally:
            for other in others:
                other.close()
        return count

    def pages_pdf(self, pages: Iterable[int]) -> bytes:
        """The given pages as a PDF file of their own (e.g. to drag them elsewhere)."""
        out = fitz.open()
        try:
            for i in sorted(set(pages)):
                out.insert_pdf(self.doc, from_page=i, to_page=i)
            return out.tobytes(garbage=3, deflate=True)
        finally:
            out.close()

    @classmethod
    def from_bytes(cls, data: bytes) -> PdfDocument:
        """A new, unsaved document with the pages of a PDF file's contents."""
        self = cls()
        self.doc.close()
        self.doc = _open_other(data)
        self.dirty = True
        return self

    @classmethod
    def from_images(cls, sources: Sequence[str | bytes]) -> PdfDocument:
        """A new, unsaved document with one page per image."""
        self = cls()
        for i, source in enumerate(sources):
            self._image_page(i, source)
        self.dirty = True
        return self

    def insert_image_pages(self, sources: Sequence[str | bytes], at: int) -> int:
        """Insert one page per image (file path or contents) before index ``at``."""
        if not sources:
            return 0
        with self._edit("Insert pages" if len(sources) > 1 else "Insert page"):
            for i, source in enumerate(sources):
                self._image_page(at + i, source)
        return len(sources)

    def _image_page(self, at: int, source: str | bytes) -> None:
        """A page as big as the image fits on A4 (turned to suit it), showing it whole."""
        width, height = image_size(source)
        short, long = fitz.paper_size("a4")
        bound_w, bound_h = (long, short) if width > height else (short, long)
        scale = min(bound_w / width, bound_h / height)
        page = self.doc.new_page(at, width=width * scale, height=height * scale)
        w, h = page.rect.width, page.rect.height
        self._insert_placed(page, ImageGeometry(fitz.Point(w / 2, h / 2), w, h, 0.0), source)

    def insert_blank_page(self, at: int) -> None:
        ref = self.doc[min(max(at - 1, 0), self.page_count - 1)] if self.page_count else None
        width, height = (ref.rect.width, ref.rect.height) if ref else fitz.paper_size("a4")
        with self._edit("Insert blank page"):
            self.doc.new_page(at, width=width, height=height)

    # ------------------------------------------------------------------ text
    def document_fonts(self) -> list[DocFace]:
        """Font faces used anywhere in the document (standard fonts excluded)."""
        if self._fonts_cache and self._fonts_cache[0] == self.revision:
            return self._fonts_cache[1]
        faces: dict[str, DocFace] = {}
        self._face_by_font = {}
        for page in self.doc:
            for xref, ext, _type, basefont, *_ in page.get_fonts():
                if not basefont or _is_standard_font(basefont):
                    continue
                face = self._font_identity(xref, ext, basefont)
                face = faces.setdefault(face.label.lower(), face)
                self._face_by_font.setdefault(normalize(basefont), face)
        result = sorted(faces.values(), key=lambda f: (f.family.lower(), f.italic, f.weight))
        self._fonts_cache = (self.revision, result)
        return result

    def _font_identity(self, xref: int, ext: str, basefont: str) -> DocFace:
        """Who a PDF font really is: family, weight, italic, serif/sans.

        Best: the embedded font program's own name and OS/2 tables ("Inter",
        600), even when the PDF calls it "ABCDEF+Inter-SemiBold". Then the
        matching installed font. Last: a guess from the PDF name.
        """
        key = (xref, basefont)
        if key in self._identity_cache:
            return self._identity_cache[key]
        face = None
        if ext in ("ttf", "otf"):
            try:
                found = read_faces_from(self.doc.extract_font(xref)[3] or b"")
                if found and found[0].family:
                    f = found[0]
                    face = DocFace.make(f.family, f.weight, f.italic, f.serif, f.mono, basefont)
            except Exception:
                face = None
        if face is None:
            bold, italic = style_of(basefont)
            guess = family_name(basefont)
            installed = self.fonts.find(basefont, bold, italic)
            if installed is not None and normalize(installed.family) == normalize(guess):
                face = DocFace.make(installed.family, installed.weight, installed.italic,
                                    installed.serif, installed.mono, basefont)
            else:
                lower = basefont.lower()
                face = DocFace.make(guess, weight_from_name(basefont), italic, None,
                                    "mono" in lower or "courier" in lower, basefont)
        self._identity_cache[key] = face
        return face

    def face_for(self, pdf_font_name: str) -> DocFace | None:
        """The document face for a font name (None for standard fonts)."""
        if not pdf_font_name or _is_standard_font(pdf_font_name):
            return None
        self.document_fonts()
        face = self._face_by_font.get(normalize(pdf_font_name))
        if face is None:  # e.g. used only inside a form XObject
            lower = pdf_font_name.lower()
            face = DocFace.make(family_name(pdf_font_name), weight_from_name(pdf_font_name),
                                style_of(pdf_font_name)[1], None,
                                "mono" in lower or "courier" in lower, pdf_font_name)
        return face

    def doc_face(self, label: str) -> DocFace | None:
        return next((f for f in self.document_fonts() if f.label.lower() == label.lower()), None)

    def nearest_face(self, family: str, weight: int, italic: bool) -> DocFace | None:
        """The document's face of a family closest to a weight/italic (exact italic only)."""
        faces = [f for f in self.document_fonts()
                 if f.family.lower() == family.lower() and f.italic == italic]
        return min(faces, key=lambda f: abs(f.weight - weight)) if faces else None

    def preview_font_data(self, label: str) -> bytes | None:
        """The embedded program of a face, if it can preview typing (has a cmap)."""
        face = self.doc_face(label)
        if face is None:
            return None
        for page in self.doc:
            for xref, ext, _type, basefont, *_ in page.get_fonts():
                if basefont != face.pdf_name or ext not in ("ttf", "otf"):
                    continue
                try:
                    buf = self.doc.extract_font(xref)[3]
                    if buf and fitz.Font(fontbuffer=buf).has_glyph(ord("e")):
                        return buf
                except Exception:
                    return None
        return None

    def text_blocks(self, index: int) -> list[TextBlock]:
        page = self.doc[index]
        blocks: list[TextBlock] = []
        segments = self._line_segments(page)
        data = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        for block in data["blocks"]:
            if block.get("type") != 0:
                continue
            lines: list[TextLine] = []
            for line in block["lines"]:
                spans = [s for s in line["spans"] if s["text"]]
                text = "".join(s["text"] for s in spans)
                if not text.strip():
                    continue
                first = spans[0]
                lines.append(
                    TextLine(
                        page=index,
                        bbox=fitz.Rect(line["bbox"]),
                        origin=fitz.Point(first["origin"]),
                        text=text,
                        font=first["font"],
                        style=_style_from_span(first),
                        direction=tuple(line["dir"]),
                        spans=[
                            TextSpan(s["text"], fitz.Point(s["origin"]), s["font"],
                                     _style_from_span(s))
                            for s in spans
                        ],
                    )
                )
            for ln in lines:
                self._attach_decorations(ln, segments)
                for style, font in ((ln.style, ln.font),
                                    *((span.style, span.font) for span in ln.spans)):
                    face = self.face_for(font)
                    if face is not None:
                        flag_bold = style.bold
                        face.apply(style)
                        style.bold = style.bold or flag_bold  # synthetic bold
            if lines:
                bbox = fitz.Rect(lines[0].bbox)
                for line in lines[1:]:
                    bbox |= line.bbox
                blocks.append(TextBlock(page=index, bbox=bbox, lines=lines))
        return blocks

    def text_lines(self, index: int) -> list[TextLine]:
        return [line for block in self.text_blocks(index) for line in block.lines]

    def line_blocks(self, index: int) -> list[TextBlock]:
        """Each text line as a text box of its own, the way the Select tool picks text."""
        return [TextBlock(index, fitz.Rect(line.bbox), [line]) for line in self.text_lines(index)]

    def block_at(self, index: int, point: fitz.Point) -> TextBlock | None:
        """Text block at an unrotated page point (smallest match wins)."""
        hits = [b for b in self.text_blocks(index) if point in b.bbox]
        return min(hits, key=lambda b: b.bbox.get_area()) if hits else None

    def text_at(self, index: int, point: fitz.Point) -> TextLine | None:
        """Text line at an unrotated page point (smallest match wins)."""
        hits = [ln for ln in self.text_lines(index) if point in ln.bbox]
        return min(hits, key=lambda ln: ln.bbox.get_area()) if hits else None

    @staticmethod
    def _redaction_band(line: TextLine) -> fitz.Rect:
        """A thin band through the middle of a line's glyphs.

        Redacting the full line bbox also removes glyphs of tightly spaced
        neighbouring lines whose boxes overlap it, so we only redact a band
        around the x-height which neighbours don't touch.
        """
        b, o, s = line.bbox, line.origin, line.style.size
        dx, dy = line.direction
        if abs(dy) < 1e-3:  # left-to-right / right-to-left
            sign = 1 if dx > 0 else -1
            return fitz.Rect(b.x0, o.y - sign * 0.55 * s, b.x1, o.y - sign * 0.25 * s).normalize()
        sign = 1 if dy < 0 else -1  # text running upwards / downwards
        return fitz.Rect(o.x - sign * 0.55 * s, b.y0, o.x - sign * 0.25 * s, b.y1).normalize()

    @staticmethod
    def _rotate_for(direction: tuple[float, float]) -> int:
        dx, dy = direction
        if abs(dy) < 1e-3:
            return 0 if dx > 0 else 180
        return 90 if dy < 0 else 270

    # ------------------------------------------------------------ decorations
    @staticmethod
    def _line_segments(page: fitz.Page) -> list[dict]:
        """Thin straight vector lines on a page: candidate underlines/strikethroughs."""
        segments = []
        for drawing in page.get_drawings():
            for item in drawing["items"]:
                if item[0] == "l" and drawing.get("color") is not None:
                    p1, p2 = fitz.Point(item[1]), fitz.Point(item[2])
                    thickness = drawing.get("width") or 1.0
                    color = drawing["color"]
                elif item[0] == "re" and drawing.get("fill") is not None:
                    r = fitz.Rect(item[1])
                    if r.width >= r.height:
                        p1 = fitz.Point(r.x0, (r.y0 + r.y1) / 2)
                        p2 = fitz.Point(r.x1, p1.y)
                        thickness = r.height
                    else:
                        p1 = fitz.Point((r.x0 + r.x1) / 2, r.y0)
                        p2 = fitz.Point(p1.x, r.y1)
                        thickness = r.width
                    color = drawing["fill"]
                else:
                    continue
                segments.append({
                    "p1": p1, "p2": p2, "thickness": thickness,
                    "color": tuple(color[:3]), "area": fitz.Rect(drawing["rect"]),
                })
        return segments

    @staticmethod
    def _attach_decorations(line: TextLine, segments: list[dict]) -> None:
        """Move segments that underline or strike through ``line`` onto it."""
        size = line.style.size
        if size <= 0 or not segments:
            return
        dx, dy = line.direction
        o = line.origin
        length = line.length
        for seg in list(segments):
            # Coordinates in the line's frame: along the text, and across (down = +).
            a1 = (seg["p1"].x - o.x) * dx + (seg["p1"].y - o.y) * dy
            a2 = (seg["p2"].x - o.x) * dx + (seg["p2"].y - o.y) * dy
            c1 = -(seg["p1"].x - o.x) * dy + (seg["p1"].y - o.y) * dx
            c2 = -(seg["p2"].x - o.x) * dy + (seg["p2"].y - o.y) * dx
            if abs(c1 - c2) > 0.1 * size or seg["thickness"] > 0.2 * size:
                continue  # not parallel to the text, or too thick to be a rule
            start, end = min(a1, a2), max(a1, a2)
            overlap = min(end, length) - max(start, 0.0)
            if overlap < 0.6 * min(end - start, length):
                continue
            across = (c1 + c2) / 2
            if -0.05 * size <= across <= 0.4 * size:
                kind = "underline"
            elif -0.45 * size <= across <= -0.15 * size:
                kind = "strike"
            else:
                continue
            line.decorations.append(Decoration(kind, start, end, across, seg["thickness"],
                                               seg["color"], seg["area"]))
            segments.remove(seg)
        if any(d.kind == "underline" for d in line.decorations):
            line.style.underline = True
            for span in line.spans:
                span.style.underline = True

    def _remove_decorations(self, page: fitz.Page, decorations: list[Decoration]) -> None:
        if not decorations:
            return
        for deco in decorations:
            pad = deco.thickness / 2 + 0.75
            page.add_redact_annot(deco.area + (-pad, -pad, pad, pad))
        # Separate pass: only line art fully inside these thin boxes goes; text
        # and images (e.g. descenders of the next line) are left alone.
        page.apply_redactions(
            images=fitz.PDF_REDACT_IMAGE_NONE,
            graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
            text=fitz.PDF_REDACT_TEXT_NONE,
        )

    @staticmethod
    def _draw_decoration(page: fitz.Page, origin: fitz.Point, direction: tuple[float, float],
                         start: float, end: float, offset: float, thickness: float,
                         color: tuple[float, float, float]) -> None:
        dx, dy = direction
        def at(along: float) -> fitz.Point:
            return fitz.Point(origin.x + along * dx - offset * dy,
                              origin.y + along * dy + offset * dx)
        page.draw_line(at(start), at(end), color=color, width=thickness)

    # ------------------------------------------------------------------ fonts
    def _embedded_font(self, page: fitz.Page, name: str, text: str) -> tuple[bytes, int] | None:
        """Return (buffer, xref) of the embedded font ``name`` if it can render ``text``."""
        # "ABCDEF+DejaVuSans" (the resource) and "DejaVu Sans Book" (what text
        # extraction reports) name the same font.
        wanted = normalize(name)
        entries = [*page.get_fonts(), *(e for p in self.doc for e in p.get_fonts())]
        for xref, ext, _type, basefont, *_ in entries:
            if normalize(basefont) != wanted or ext in ("n/a", ""):
                continue
            try:
                _, _, _, buf = self.doc.extract_font(xref)
                if not buf:
                    return None
                font = fitz.Font(fontbuffer=buf)
                if all(ch.isspace() or font.has_glyph(ord(ch)) for ch in text):
                    return buf, xref
            except Exception:
                return None
        return None

    def _font_writer(self, page: fitz.Page) -> _FontWriter:
        return _FontWriter(self, page)

    # ------------------------------------------------------------------- text
    def replace_text(self, line: TextLine, new_text: str,
                     style: TextStyle | None = None) -> str | None:
        """Replace an existing text line, keeping its position.

        Returns a note for the user when the original font couldn't be kept.
        """
        style = style or line.style
        page = self.doc[line.page]
        note = None
        rows = new_text.split("\n")
        with self._edit("Edit text"):
            writer = self._font_writer(page)
            font = None
            if new_text.strip():
                # Resolve before redacting, which may drop the font from the page.
                font = writer.prepare(line.font, line.style, style, "".join(rows))
            page.add_redact_annot(self._redaction_band(line))
            page.apply_redactions(
                images=fitz.PDF_REDACT_IMAGE_NONE,
                graphics=fitz.PDF_REDACT_LINE_ART_NONE,
            )
            self._remove_decorations(page, line.decorations)
            if font is None:
                return None
            writer.flush()
            note = font.note
            # Further rows go below the first, across the reading direction.
            dx, dy = line.direction
            down = fitz.Point(-dy, dx) * (1.25 * style.size)
            for i, row in enumerate(rows):
                if not row.strip():
                    continue
                origin = line.origin + down * i
                font.write(page, origin, row, style.size, style.color, line.direction,
                           self._rotate_for(line.direction))
                length = font.text_length(row, style.size)
                if i == 0:
                    self._redraw_decorations(page, line, style, length)
                elif style.underline:
                    self._draw_decoration(page, origin, line.direction, 0, length,
                                          0.12 * style.size, max(0.5, 0.06 * style.size),
                                          style.color)
        return note

    def _redraw_decorations(self, page: fitz.Page, line: TextLine, style: TextStyle,
                            new_length: float) -> None:
        """Underlines/strikethroughs follow the new text length (keeping any overhang)."""
        kept_underline = False
        for deco in line.decorations:
            if deco.kind == "underline" and not style.underline:
                continue  # switched off in the inspector
            kept_underline |= deco.kind == "underline"
            end = deco.end - line.length + new_length
            color = style.color if deco.color == line.style.color else deco.color
            self._draw_decoration(page, line.origin, line.direction, deco.start, end,
                                  deco.offset, deco.thickness, color)
        if style.underline and not kept_underline:
            self._draw_decoration(page, line.origin, line.direction, 0, new_length,
                                  0.12 * style.size, max(0.5, 0.06 * style.size), style.color)

    def add_text(self, index: int, point: fitz.Point, text: str,
                 style: TextStyle) -> str | None:
        """Insert new text whose top-left corner is at an unrotated page point.

        Returns a note for the user if the chosen font couldn't be used.
        """
        if not text.strip():
            return None
        page = self.doc[index]
        rows = text.split("\n")
        with self._edit("Add text"):
            writer = self._font_writer(page)
            choice = writer.prepare(None, style, style, "".join(rows))
            writer.flush()
            # Write in the page's visual orientation so text reads upright on screen.
            m = page.derotation_matrix
            right = fitz.Point(1, 0) * m - fitz.Point(0, 0) * m
            down = fitz.Point(0, 1) * m - fitz.Point(0, 0) * m
            origin = self._baseline_from_top_left(page, point, style.size)
            for i, row in enumerate(rows):
                if not row.strip():
                    continue
                base = origin + down * (i * 1.25 * style.size)
                choice.write(page, base, row, style.size, style.color, (right.x, right.y),
                             page.rotation)
                if style.underline:
                    self._draw_decoration(page, base, (right.x, right.y), 0,
                                          choice.text_length(row, style.size),
                                          0.12 * style.size, max(0.5, 0.06 * style.size),
                                          style.color)
        return choice.note

    @staticmethod
    def _baseline_from_top_left(page: fitz.Page, point: fitz.Point, size: float) -> fitz.Point:
        # Move "down" by the ascender in display space, then map back.
        display = fitz.Point(point) * page.rotation_matrix
        display.y += size * 0.85
        return display * page.derotation_matrix

    def move_text_block(self, block: TextBlock, dx: float, dy: float) -> None:
        """Move a text block by (dx, dy) points in *display* space (rotation applied)."""
        page = self.doc[block.page]
        # A display-space offset expressed in unrotated page space (no translation).
        m = page.derotation_matrix
        delta = fitz.Point(dx, dy) * m - fitz.Point(0, 0) * m
        with self._edit("Move text"):
            self._carry_highlights(page, block, delta)
            self._rewrite_block(page, block, delta)

    def _carry_highlights(self, page: fitz.Page, block: TextBlock, delta: fitz.Point) -> None:
        """Move the parts of highlights that lie on a block's lines along with it
        (``delta`` in unrotated page space)."""
        def on_text(rect: fitz.Rect) -> bool:
            area = rect.get_area()
            return area > 0 and any(
                (fitz.Rect(rect) & line.bbox).get_area() > area / 2 for line in block.lines)

        for mark in self.markups(page.number):
            if mark.kind != "highlight":
                continue
            moved = [on_text(r) for r in mark.rects]
            if not any(moved):
                continue
            rects = [r + (delta.x, delta.y, delta.x, delta.y) if m else r
                     for r, m in zip(mark.rects, moved, strict=True)]
            page.delete_annot(page.load_annot(mark.xref))
            self._highlight(page, rects, mark.color or (1.0, 0.92, 0.3))

    def delete_text_block(self, block: TextBlock) -> None:
        with self._edit("Delete text"):
            self._rewrite_block(self.doc[block.page], block, None)

    def move_items(self, items: Sequence[ImageInfo | TextBlock | Markup],
                   dx: float, dy: float) -> None:
        """Move images, text boxes and boxes together by (dx, dy) display points,
        as one undo step. Highlights on the text go along with it; selected or
        not, they aren't moved on their own."""
        with self._edit("Move items"):
            # Images first: redacting text (to redraw it) renames their resources.
            for image in (i for i in items if isinstance(i, ImageInfo)):
                geo = self.image_geometry(image)
                geo.center = fitz.Point(geo.center.x + dx, geo.center.y + dy)
                self.transform_image(image, geo)
            for box in (i for i in items if isinstance(i, Markup) and i.kind == "box"):
                self.move_markup(box, dx, dy)
            for block in self._text_per_page(items):
                page = self.doc[block.page]
                m = page.derotation_matrix
                # All of a page's text at once, so text moved onto another
                # selected line isn't erased when that one is taken away.
                delta = fitz.Point(dx, dy) * m - fitz.Point(0, 0) * m
                self._carry_highlights(page, block, delta)
                self._rewrite_block(page, block, delta)

    def delete_items(self, items: Sequence[ImageInfo | TextBlock | Markup]) -> None:
        """Delete several images, text boxes, highlights and boxes as one undo step."""
        with self._edit("Delete items"):
            for image in (i for i in items if isinstance(i, ImageInfo)):
                self.delete_image(image)
            for markup in (i for i in items if isinstance(i, Markup)):
                self.delete_markup(markup)
            for block in self._text_per_page(items):
                self._rewrite_block(self.doc[block.page], block, None)

    @staticmethod
    def _text_per_page(items: Sequence[ImageInfo | TextBlock | Markup]) -> list[TextBlock]:
        """The text boxes among ``items`` combined into one per page."""
        pages: dict[int, TextBlock] = {}
        for block in (i for i in items if isinstance(i, TextBlock)):
            whole = pages.setdefault(block.page, TextBlock(block.page, fitz.Rect(block.bbox), []))
            whole.bbox |= block.bbox
            whole.lines += [ln for ln in block.lines if ln not in whole.lines]
        return list(pages.values())

    def _rewrite_block(self, page: fitz.Page, block: TextBlock, delta: fitz.Point | None,
                       capture: bool = False) -> bytes | None:
        """Remove a block's glyphs and, unless ``delta`` is None, redraw them shifted.

        Every span is re-inserted with its own size, colour and font (the
        embedded one, else the installed one), and underlines move along, so a
        paragraph with mixed styling survives the move.

        With ``capture`` the redrawn text isn't added to the page: its drawing
        code (for the default coordinate system) is returned instead.
        """
        spans = [(line, span) for line in block.lines for span in line.spans]
        writer = self._font_writer(page)
        resolved = {}
        if delta is not None:
            for font in {span.font for _, span in spans}:
                mine = [s for _, s in spans if s.font == font]
                text = "".join(s.text for s in mine)
                resolved[font] = writer.prepare(font, mine[0].style, mine[0].style, text)
        for line in block.lines:
            page.add_redact_annot(self._redaction_band(line))
        page.apply_redactions(
            images=fitz.PDF_REDACT_IMAGE_NONE,
            graphics=fitz.PDF_REDACT_LINE_ART_NONE,
        )
        self._remove_decorations(page, [d for line in block.lines for d in line.decorations])
        if delta is None:
            return None
        if capture:
            if not page.is_wrapped:
                page.wrap_contents()
            kept = page.get_contents()
        writer.flush()
        for line, span in spans:
            resolved[span.font].write(page, span.origin + delta, span.text, span.style.size,
                                      span.style.color, line.direction,
                                      self._rotate_for(line.direction))
        for line in block.lines:
            for deco in line.decorations:
                self._draw_decoration(page, line.origin + delta, line.direction, deco.start,
                                      deco.end, deco.offset, deco.thickness, deco.color)
        if not capture:
            return None
        # Writing text only appends content streams: take them off again.
        added = [x for x in page.get_contents() if x not in kept]
        self._set_contents(page, kept)
        return b"\n".join(self.doc.xref_stream(x) or b"" for x in added)

    def _set_contents(self, page: fitz.Page, xrefs: Sequence[int]) -> None:
        self.doc.xref_set_key(page.xref, "Contents",
                              "[" + " ".join(f"{x} 0 R" for x in xrefs) + "]")

    # ---------------------------------------------------------------- images
    def images(self, index: int) -> list[ImageInfo]:
        page = self.doc[index]
        # Resource names of images drawn directly by the page (not via forms).
        names: dict[int, list[str]] = {}
        for entry in page.get_images(full=True):
            if entry[9] == 0:
                names.setdefault(entry[0], []).append(entry[7])
        vectors = self._vector_forms(page)
        # Pixels drawn by an inserted SVG are part of it, not images of their own.
        inside = {entry[0] for entry in page.get_images(full=True)
                  if entry[9] in vectors.inner} - set(names)
        out = []
        for info in page.get_image_info(xrefs=True):
            bbox = fitz.Rect(info["bbox"])
            if bbox.is_empty or bbox.is_infinite:
                continue
            if info.get("width", 2) <= 1 and info.get("height", 2) <= 1:
                continue  # placeholder left behind by a deleted image
            xref = info.get("xref", 0)
            if xref in inside:
                continue
            candidates = names.get(xref, [])
            out.append(ImageInfo(
                page=index, bbox=bbox, xref=xref,
                transform=fitz.Matrix(info.get("transform", (1, 0, 0, 1, 0, 0))),
                name=candidates[0] if len(candidates) == 1 else None,
            ))
        if vectors.drawn:
            out.extend(self._vector_images(page, vectors.drawn))
        return out

    def render_vector(self, image: ImageInfo, scale: float) -> fitz.Pixmap:
        """An inserted SVG drawn on its own, on transparency, ``scale`` pixels per point
        of its size on the page (upright and unmirrored, like an image's pixels)."""
        if not image.vector or not image.name:
            raise PdfError(tr("Not an SVG image."))
        geo = self.image_geometry(image)
        w, h = max(1.0, geo.width * scale), max(1.0, geo.height * scale)
        tmp = fitz.open()
        tmp.insert_pdf(self.doc, from_page=image.page, to_page=image.page, annots=False)
        page = tmp[0]
        page.set_rotation(0)
        page.set_mediabox(fitz.Rect(0, 0, w, h))
        xref = tmp.get_new_xref()
        tmp.update_object(xref, "<<>>")
        cm = layers.matrix_code(fitz.Matrix(w, 0, 0, h, 0, 0))
        tmp.update_stream(xref, b"q " + cm + b" cm /" + image.name.encode() + b" Do Q")
        tmp.xref_set_key(page.xref, "Contents", f"{xref} 0 R")
        return tmp[0].get_pixmap(alpha=True, annots=False)

    def _vector_forms(self, page: fitz.Page) -> _VectorForms:
        """The inserted SVGs the page draws directly, and every form inside them."""
        xobjects = page.get_xobjects()
        drawn = {name: xref for xref, name, invoker, _ in xobjects
                 if invoker == 0 and self.doc.xref_get_key(xref, _VECTOR_KEY)[1] == "true"}
        inner = set(drawn.values())
        grew = True
        while grew:
            more = {xref for xref, _, invoker, _ in xobjects if invoker in inner} - inner
            inner |= more
            grew = bool(more)
        return _VectorForms(drawn, inner)

    def _vector_images(self, page: fitz.Page, drawn: dict[str, int]) -> list[ImageInfo]:
        """Where the page's content paints its inserted SVGs."""
        ops, _ = layers.scan(self._content(page))
        painted: dict[str, list[fitz.Matrix]] = {}
        for op in ops:
            if op.name == b"Do" and op.operand:
                name = op.operand.decode(errors="replace")
                if name in drawn:
                    painted.setdefault(name, []).append(op.ctm)
        out = []
        for name, ctms in painted.items():
            for ctm in ctms:
                transform = _IMAGE_FLIP * ctm * page.transformation_matrix
                bbox = fitz.Rect(0, 0, 1, 1) * transform
                if bbox.is_empty or bbox.is_infinite:
                    continue
                out.append(ImageInfo(page=page.number, bbox=bbox, xref=drawn[name],
                                     transform=transform,
                                     name=name if len(ctms) == 1 else None, vector=True))
        return out

    def image_at(self, index: int, point: fitz.Point) -> ImageInfo | None:
        hits = [im for im in self.images(index) if im.contains(point)]
        return min(hits, key=lambda im: im.bbox.get_area()) if hits else None

    def image_geometry(self, image: ImageInfo) -> ImageGeometry:
        m = image.transform * self.doc[image.page].rotation_matrix
        width = math.hypot(m.a, m.b)
        height = math.hypot(m.c, m.d)
        flipped = m.a * m.d - m.b * m.c < 0
        return ImageGeometry(
            center=fitz.Point(0.5, 0.5) * m,
            width=width,
            height=height,
            angle=math.degrees(math.atan2(m.b, m.a)),
            flipped=flipped,
        )

    def _placement_matrix(self, page: fitz.Page, geo: ImageGeometry) -> fitz.Matrix:
        """Unit-square-to-page matrix (unrotated space) for an on-screen placement."""
        h = -geo.height if geo.flipped else geo.height
        m = fitz.Matrix(geo.width, 0, 0, h, -geo.width / 2, -h / 2)
        m = m * fitz.Matrix(geo.angle) * fitz.Matrix(1, 0, 0, 1, geo.center.x, geo.center.y)
        return m * page.derotation_matrix

    def _do_matches(self, page: fitz.Page, name: str):
        pattern = re.compile(rb"/" + re.escape(name.encode()) + rb"\s+Do(?![A-Za-z0-9_])")
        found = []
        for xref in page.get_contents():
            data = self.doc.xref_stream(xref) or b""
            found.extend((xref, m) for m in pattern.finditer(data))
        return found

    def _rewrite_do(self, page: fitz.Page, name: str, replacement: bytes) -> bool:
        """Replace the single "/name Do" in the page's content with ``replacement``."""
        matches = self._do_matches(page, name)
        if len(matches) != 1:
            return False
        xref, match = matches[0]
        data = self.doc.xref_stream(xref)
        self.doc.update_stream(xref, data[: match.start()] + replacement + data[match.end():])
        return True

    def _set_image_matrix(self, page: fitz.Page, name: str, current: fitz.Matrix,
                          target: fitz.Matrix) -> bool:
        # The image keeps its place in the content stream (z-order) and its
        # xref (no re-encoding): we only prepend a correcting "cm" to its Do.
        fix = _IMAGE_FLIP * target * ~current * _IMAGE_FLIP
        cm = " ".join(f"{v:.6f}".rstrip("0").rstrip(".") or "0" for v in fix).encode()
        do = b"/" + name.encode() + b" Do"
        return self._rewrite_do(page, name, b"q " + cm + b" cm " + do + b" Q")

    def transform_image(self, image: ImageInfo, geometry: ImageGeometry) -> None:
        """Move/resize/rotate an image to an on-screen placement."""
        page = self.doc[image.page]
        if not image.name or len(self._do_matches(page, image.name)) != 1:
            raise PdfError(tr("This image can't be moved: it's embedded in a way Pixa "
                              "can't edit yet (inline or inside a form)."))
        if geometry.width < 1 or geometry.height < 1:
            raise PdfError(tr("An image can't be smaller than 1 point."))
        with self._edit("Transform image"):
            target = self._placement_matrix(page, geometry)
            if not self._set_image_matrix(page, image.name, image.transform, target):
                raise PdfError(tr("Could not update the image."))
            self.doc.reload_page(page)

    def rotate_image(self, image: ImageInfo, degrees: float) -> None:
        geo = self.image_geometry(image)
        geo.angle = (geo.angle + degrees) % 360
        self.transform_image(image, geo)

    def add_image(self, index: int, geometry: ImageGeometry, path: str | None = None,
                  data: bytes | None = None) -> str:
        """Place an image at an on-screen placement (centre, size, rotation).

        Returns the name the page knows the image by."""
        return self.add_images(index, [(geometry, path if data is None else data)])[0]

    def add_images(self, index: int,
                   images: Sequence[tuple[ImageGeometry, str | bytes]]) -> list[str]:
        """Place images (file paths or contents) on a page as one undo step.

        Returns the names the page knows them by, in the same order."""
        page = self.doc[index]
        names = []
        with self._edit("Add image" if len(images) == 1 else "Add images"):
            for geometry, source in images:
                page, name = self._insert_placed(page, geometry, source)
                names.append(name)
        return names

    def _insert_placed(self, page: fitz.Page, geometry: ImageGeometry,
                       source: str | bytes) -> tuple[fitz.Page, str]:
        """Draw an image (file path or contents) at an on-screen placement, on top
        of the page. SVGs stay vector graphics: a form XObject made to fill the
        unit square like an image does, so it is moved and layered like one.

        Returns the reloaded page and the name the page knows the image by."""
        svg = _svg_data(source)
        try:
            if svg is None:
                before = {entry[7] for entry in page.get_images(full=True)}
                rect = fitz.Rect(0, 0, geometry.width, geometry.height)
                page.insert_image(rect, keep_proportion=False, **_image_source(source))
                page = self.doc.reload_page(page)
                new = [e[7] for e in page.get_images(full=True) if e[7] not in before]
                current = fitz.Matrix(rect.width, 0, 0, rect.height, rect.x0, rect.y0)
            else:
                drawing = _svg_page(svg, _source_name(source))
                before = {entry[1] for entry in page.get_xobjects()}
                page.show_pdf_page(drawing[0].rect, drawing, 0)
                page = self.doc.reload_page(page)
                forms = [(x, name) for x, name, invoker, _ in page.get_xobjects()
                         if invoker == 0 and name not in before]
                for xref, _ in forms[:1]:
                    self._make_unit_form(xref)
                new = [name for _, name in forms]
                # Drawn with the page's own coordinate system, filling the unit square.
                current = _IMAGE_FLIP * page.transformation_matrix
        except PdfError:
            raise
        except Exception as exc:
            raise PdfError(tr("Could not insert image: {error}", error=exc)) from exc
        if not new or not self._set_image_matrix(page, new[0], current,
                                                 self._placement_matrix(page, geometry)):
            raise PdfError(tr("Could not insert image."))
        return self.doc.reload_page(page), new[0]

    def _make_unit_form(self, xref: int) -> None:
        """Have a form XObject draw its bounding box onto the unit square, as an
        image does, and mark it as an inserted SVG."""
        x0, y0, x1, y1 = (float(v) for v in
                          self.doc.xref_get_key(xref, "BBox")[1].strip("[] ").split())
        w, h = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
        matrix = " ".join(layers.number(v) for v in (1 / w, 0, 0, 1 / h, -x0 / w, -y0 / h))
        self.doc.xref_set_key(xref, "Matrix", f"[{matrix}]")
        self.doc.xref_set_key(xref, _VECTOR_KEY, "true")

    def _xref_uses(self, xref: int) -> int:
        """How many times an image xref is drawn across the whole document."""
        return sum(
            1
            for page in self.doc
            for info in page.get_image_info(xrefs=True)
            if info.get("xref") == xref
        )

    def delete_image(self, image: ImageInfo) -> None:
        page = self.doc[image.page]
        with self._edit("Delete image"):
            # Best: drop this one "Do" from the page; other pages sharing the
            # image (a logo on every page) keep it.
            if image.name and self._rewrite_do(page, image.name, b""):
                self.doc.reload_page(page)
                return
            if image.vector:
                raise PdfError(tr("Could not delete the image."))
            if image.xref and self._xref_uses(image.xref) == 1:
                # Only drawn here: swap the image for an empty one.
                page.delete_image(image.xref)
                return
            # Shared or inline image: redact only this occurrence, leaving
            # text and vector graphics alone.
            area = fitz.Rect(image.bbox)
            inset = min(area.width, area.height) * 0.25
            page.add_redact_annot(area + (inset, inset, -inset, -inset))
            page.apply_redactions(
                images=fitz.PDF_REDACT_IMAGE_REMOVE,
                graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                text=fitz.PDF_REDACT_TEXT_NONE,
            )

    # ---------------------------------------------------------------- markup
    # Highlights are standard PDF annotations, so other viewers show them
    # too and they can be selected and removed again later.
    def _rows_of_words(self, index: int) -> list[tuple[int, list[fitz.Rect]]]:
        """Each text line as (block number, word boxes), in *display* coordinates."""
        key = (index, self.revision)
        if self._word_rows is None or self._word_rows[0] != key:
            page = self.doc[index]
            rows: dict[tuple[int, int], list[fitz.Rect]] = {}
            for x0, y0, x1, y1, _word, block, line, _n in page.get_text("words"):
                rows.setdefault((block, line), []).append(
                    fitz.Rect(x0, y0, x1, y1) * page.rotation_matrix)
            self._word_rows = (key, [(block, words) for (block, _), words in rows.items()])
        return self._word_rows[1]

    def highlight_rects(self, index: int, start: fitz.Point, stop: fitz.Point) -> list[fitz.Rect]:
        """What dragging a marker between two unrotated page points covers.

        Like selecting text: from ``start`` to the end of its line, whole lines
        in between, and the last line up to ``stop``, snapped to whole words.
        Only text boxes the drag passes over take part, so a neighbouring
        column stays clean. Where there is no text (a scan, a picture) the
        dragged area itself is returned.
        """
        page = self.doc[index]
        a = fitz.Point(start) * page.rotation_matrix
        b = fitz.Point(stop) * page.rotation_matrix
        if a.y > b.y:
            a, b = b, a
        left, right = min(a.x, b.x), max(a.x, b.x)

        def union(rects: list[fitz.Rect]) -> fitz.Rect:
            box = fitz.Rect(rects[0])
            for r in rects[1:]:
                box |= r
            return box

        rows = self._rows_of_words(index)
        blocks: dict[int, fitz.Rect] = {}
        for block, words in rows:
            blocks[block] = union([*words, *([blocks[block]] if block in blocks else [])])
        out = []
        for block, words in rows:
            row, box = union(words), blocks[block]
            if row.y1 < a.y or row.y0 > b.y or box.x1 < left or box.x0 > right:
                continue
            lo, hi = -math.inf, math.inf
            first, last = row.y0 <= a.y, row.y1 >= b.y
            if first and last:  # dragged along a single line
                lo, hi = left, right
            elif first:
                lo = a.x
            elif last:
                hi = b.x
            picked = [w for w in words if w.x1 > lo and w.x0 < hi]
            if picked:
                span = union(picked)
                out.append(fitz.Rect(span.x0, row.y0, span.x1, row.y1))
        if not out and right - left >= 4 and b.y - a.y >= 4:
            out = [fitz.Rect(left, a.y, right, b.y)]
        return [(r * page.derotation_matrix).normalize() for r in out]

    def add_highlight(self, index: int, rects: Sequence[fitz.Rect],
                      color: tuple[float, float, float]) -> None:
        """Highlight areas of a page (unrotated coordinates) as one highlight.

        It replaces what earlier highlights marked in the same places, so
        going over text twice doesn't make it darker.
        """
        rects = [fitz.Rect(r).normalize() for r in rects]
        if not rects:
            return
        page = self.doc[index]
        with self._edit("Highlight"):
            for old in [m for m in self.markups(index) if m.kind == "highlight"]:
                left = old.rects
                for new in rects:
                    left = [part for r in left for part in _rect_minus(r, new)]
                if left == old.rects:
                    continue
                page.delete_annot(page.load_annot(old.xref))
                if left:
                    self._highlight(page, left, old.color or color)
            self._highlight(page, rects, color)

    @staticmethod
    def _highlight(page: fitz.Page, rects: Sequence[fitz.Rect],
                   color: tuple[float, float, float]) -> None:
        annot = page.add_highlight_annot(quads=[fitz.Rect(r).quad for r in rects])
        annot.set_colors(stroke=color)
        annot.update()

    def set_highlight_color(self, markup: Markup, color: tuple[float, float, float]) -> None:
        page = self.doc[markup.page]
        with self._edit("Change highlight"):
            annot = page.load_annot(markup.xref)
            annot.set_colors(stroke=color)
            annot.update()

    # Boxes are drawn into the page itself, like text and images, so whatever
    # is placed last lies on top. Each one is wrapped in marked content that
    # records what it is ("/PixaBox <<...>> BDC ... EMC"); that is how it is
    # found again to move, resize, restyle or delete it.
    def _box_code(self, page: fitz.Page, tag: int, rect: fitz.Rect, style: BoxStyle,
                  fix: fitz.Matrix | None = None) -> bytes:
        """The drawing code of a box. ``fix`` undoes the coordinate system in
        effect where the code goes (when layering put it among other content)."""
        def nums(*values: float) -> str:
            return " ".join(f"{v:.4f}".rstrip("0").rstrip(".") or "0" for v in values)

        r = (fitz.Rect(rect).normalize() * ~page.transformation_matrix).normalize()
        width = max(0.0, style.width)
        props, ops = f"/Id {tag} /R [{nums(*r)}] /W {nums(width)}", "q"
        if fix is not None and not layers.is_identity(fix):
            ops += f" {layers.matrix_code(fix).decode()} cm"
        if width > 0:
            props += f" /C [{nums(*style.color)}]"
            ops += f" {nums(width)} w {nums(*style.color)} RG"
        if style.fill is not None:
            props += f" /F [{nums(*style.fill)}]"
            ops += f" {nums(*style.fill)} rg"
        paint = {(True, True): "B", (True, False): "S", (False, True): "f"}.get(
            (width > 0, style.fill is not None), "n")
        ops += f" {nums(r.x0, r.y0, r.width, r.height)} re {paint} Q"
        return f"\n/PixaBox <<{props}>> BDC\n{ops}\nEMC\n".encode()

    def _drawn_boxes(self, page: fitz.Page) -> list[tuple[int, re.Match, Markup]]:
        """The boxes in a page's content as (stream xref, where it is, what it is)."""
        def numbers(props: bytes, key: bytes) -> list[float] | None:
            m = re.search(rb"/" + key + rb"\s*\[([^\]]*)\]", props)
            return [float(v) for v in m.group(1).split()] if m else None

        found = []
        for xref in page.get_contents():
            for match in _BOX_CODE.finditer(self.doc.xref_stream(xref) or b""):
                props = match.group(1)
                tag = re.search(rb"/Id\s*(\d+)", props)
                width = re.search(rb"/W\s*([\d.]+)", props)
                r = numbers(props, b"R")
                if not (tag and width and r and len(r) == 4):
                    continue
                bbox = (fitz.Rect(r) * page.transformation_matrix).normalize()
                stroke, fill = numbers(props, b"C"), numbers(props, b"F")
                half = float(width.group(1)) / 2 if stroke else 0.0
                found.append((xref, match, Markup(
                    page.number, 0, "box", bbox, [bbox + (-half, -half, half, half)],
                    tuple(stroke) if stroke else None, tuple(fill) if fill else None,
                    float(width.group(1)) if stroke else 0.0, int(tag.group(1)))))
        return found

    def _draw_box(self, page: fitz.Page, rect: fitz.Rect, style: BoxStyle) -> int:
        """Draw a new box on top of the page's content; returns its tag."""
        tag = max((m.tag for _, _, m in self._drawn_boxes(page)), default=0) + 1
        if not page.is_wrapped:
            page.wrap_contents()
        xref = self.doc.get_new_xref()
        self.doc.update_object(xref, "<<>>")
        self.doc.update_stream(xref, self._box_code(page, tag, rect, style))
        self._set_contents(page, page.get_contents() + [xref])
        return tag

    def _redraw_box(self, markup: Markup, rect: fitz.Rect | None,
                    style: BoxStyle | None) -> Markup | None:
        """Give a box a new place and look; with neither, remove it.

        A drawn box is replaced where it is in the page's content, so it stays
        in front of or behind the same things. A box that is an annotation
        (from another program) becomes a drawn one.
        """
        page = self.doc[markup.page]
        tag = markup.tag
        if markup.xref:
            page.delete_annot(page.load_annot(markup.xref))
            if rect is None:
                return None
            tag = self._draw_box(page, rect, style)
        else:
            xref, match, _ = next(b for b in self._drawn_boxes(page) if b[2].tag == tag)
            code = b"" if rect is None else self._box_code(
                page, tag, rect, style, _box_fix(match.group())).strip()
            data = self.doc.xref_stream(xref)
            self.doc.update_stream(xref, data[: match.start()] + code + data[match.end():])
        return next((m for m in self.markups(markup.page) if m.tag == tag and not m.xref), None)

    def add_box(self, index: int, rect: fitz.Rect, style: BoxStyle) -> None:
        """Draw a box; the border is centred on ``rect`` (unrotated coordinates)."""
        if style.width <= 0 and style.fill is None:
            raise PdfError(tr("A box needs a border or a fill colour."))
        page = self.doc[index]
        with self._edit("Add box"):
            self._draw_box(page, rect, style)

    def set_box_style(self, markup: Markup, style: BoxStyle) -> Markup | None:
        """Change the border and fill of a box; returns the box as it is now."""
        with self._edit("Change box"):
            return self._redraw_box(markup, fitz.Rect(markup.bbox), style)

    def set_box_rect(self, markup: Markup, rect: fitz.Rect) -> Markup | None:
        """Move or resize a box to ``rect`` (unrotated coordinates); returns it as it is now."""
        if markup.kind != "box":
            raise PdfError(tr("Only boxes can be moved."))
        rect = fitz.Rect(rect).normalize()
        resized = (abs(rect.width - markup.bbox.width) > 0.01
                   or abs(rect.height - markup.bbox.height) > 0.01)
        with self._edit("Resize box" if resized else "Move box"):
            return self._redraw_box(markup, rect, markup.style)

    def move_markup(self, markup: Markup, dx: float, dy: float) -> Markup | None:
        """Move a box by (dx, dy) points in *display* space (rotation applied)."""
        m = self.doc[markup.page].derotation_matrix
        delta = fitz.Point(dx, dy) * m - fitz.Point(0, 0) * m
        return self.set_box_rect(markup, markup.bbox + (delta.x, delta.y, delta.x, delta.y))

    def markups(self, index: int) -> list[Markup]:
        """Highlights and boxes on a page, each kind oldest first."""
        page = self.doc[index]
        out = []
        for annot in page.annots(types=(fitz.PDF_ANNOT_HIGHLIGHT, fitz.PDF_ANNOT_SQUARE)):
            colors = annot.colors
            stroke, fill = _rgb(colors.get("stroke")), _rgb(colors.get("fill"))
            if annot.type[0] == fitz.PDF_ANNOT_HIGHLIGHT:
                points = annot.vertices or []
                rects = [fitz.Quad(points[i:i + 4]).rect for i in range(0, len(points) - 3, 4)]
                rects = rects or [fitz.Rect(annot.rect)]
                bbox = fitz.Rect(rects[0])
                for r in rects[1:]:
                    bbox |= r
                out.append(Markup(index, annot.xref, "highlight", bbox, rects, stroke))
            else:
                # A box annotation: its border runs inside its rectangle, by /RD.
                width = float(annot.border.get("width") or 0)
                half = width / 2
                kind, value = self.doc.xref_get_key(annot.xref, "RD")
                inset = [float(v) for v in value.strip("[]").split()] if kind == "array" else []
                left, bottom, right, top = inset if len(inset) == 4 else [half] * 4
                bbox = fitz.Rect(annot.rect) + (left, top, -right, -bottom)
                out.append(Markup(index, annot.xref, "box", bbox,
                                  [bbox + (-half, -half, half, half)], stroke, fill, width))
        return out + [m for _, _, m in self._drawn_boxes(page)]

    def markup_at(self, index: int, point: fitz.Point) -> Markup | None:
        hits = [m for m in self.markups(index) if m.contains(point)]
        return min(hits, key=lambda m: m.bbox.get_area()) if hits else None

    def delete_markup(self, markup: Markup) -> None:
        page = self.doc[markup.page]
        with self._edit("Delete box" if markup.kind == "box" else "Delete highlight"):
            if markup.kind == "box":
                self._redraw_box(markup, None, None)
            else:
                page.delete_annot(page.load_annot(markup.xref))

    # ---------------------------------------------------------------- layers
    # Whatever a page's content draws later lies on top. Changing the layer of
    # a text box, image or box takes its drawing code out of the content and
    # puts it back elsewhere: at the very end (front), the very start (back),
    # or just past the nearest element it overlaps (forward / backward).
    # Text is redrawn the way moving a text box redraws it. Highlights are
    # annotations, which always lie on top of the page.
    def arrange(self, item: ImageInfo | TextBlock | Markup, how: str) -> bool:
        """Bring an element to the front, forward, backward or to the back.

        Forward and backward pass the nearest element it overlaps. Returns
        False when there is nothing to pass (nothing changes then).
        """
        if how not in LAYER_MOVES:
            raise ValueError(f"unknown layer move: {how}")
        if isinstance(item, Markup) and item.kind == "highlight":
            raise PdfError(tr("Highlights always lie on top of the page."))
        page = self.doc[item.page]
        # A line picked out of a paragraph is layered on its own.
        lines = isinstance(item, TextBlock) and not any(
            _same_element(b, item) for b in self.text_blocks(item.page))
        found = self._page_layers(page, self._content(page), lines)[2]
        me = next((layer for layer in found if _same_element(layer.item, item)), None)
        if me is None and not (isinstance(item, Markup) and item.xref):
            raise PdfError(tr({
                ImageInfo: N_("The layer of this image can't be changed: it's drawn in a way "
                              "Pixa can't edit yet (e.g. inside a form)."),
                TextBlock: N_("The layer of this text can't be changed: it's drawn in a way "
                              "Pixa can't edit yet (e.g. inside a form)."),
            }.get(type(item), N_("The layer of this box can't be changed: it's drawn in a way "
                                 "Pixa can't edit yet (e.g. inside a form)."))))
        # A box that is an annotation lies on top of all the page's content.
        first = me.first if me is not None else math.inf
        others = [layer for layer in found
                  if layer is not me and layer.bbox.intersects(item.bbox)]
        above = sorted((x for x in others if x.first > first), key=lambda x: x.first)
        below = sorted((x for x in others if x.first < first), key=lambda x: x.first)
        if not (above if how in ("front", "forward") else below):
            return False
        anchor = above[0] if how == "forward" else below[-1] if how == "backward" else None
        with self._edit(LAYER_MOVES[how]):
            draw = self._lift(page, item)
            page = self.doc.reload_page(page)
            xref, data = self._merge_contents(page)
            page = self.doc.reload_page(page)
            ops, final, found = self._page_layers(page, data, lines)
            if anchor is None:
                spot = layers.Spot(len(data), final) if how == "front" else \
                    layers.Spot(0, fitz.Identity)
            else:
                again = next((x for x in found if _same_element(x.item, anchor.item)), None)
                if again is None:
                    raise PdfError(tr("Could not change the layer."))
                spot = again.after(ops, final) if how == "forward" else again.before(ops, final)
            self.doc.update_stream(xref, data[: spot.pos] + draw(spot) + data[spot.pos:])
            self.doc.reload_page(page)
        return True

    def _content(self, page: fitz.Page) -> bytes:
        """A page's content streams as one (they are drawn one after another)."""
        return b"\n".join(self.doc.xref_stream(x) or b"" for x in page.get_contents())

    def _merge_contents(self, page: fitz.Page) -> tuple[int, bytes]:
        """Make the page's content a single stream (in a new object, as streams may
        be shared with other pages); returns its xref and data."""
        if not page.is_wrapped:
            page.wrap_contents()
        data = self._content(page)
        xref = self.doc.get_new_xref()
        self.doc.update_object(xref, "<<>>")
        self.doc.update_stream(xref, data)
        self._set_contents(page, [xref])
        return xref, data

    def _page_layers(self, page: fitz.Page, data: bytes, lines: bool = False
                     ) -> tuple[list[layers.Op], fitz.Matrix, list[_Layer]]:
        """The content's operators and where the page's text boxes (with ``lines``:
        text lines), images and boxes are drawn in it (each element whose drawing
        code can be found)."""
        ops, final = layers.scan(data)
        index = page.number
        found: list[_Layer] = []
        painted: dict[bytes, list[int]] = {}
        for i, op in enumerate(ops):
            if op.name == b"Do" and op.operand:
                painted.setdefault(op.operand, []).append(i)
        for image in self.images(index):
            hits = painted.get(image.name.encode(), []) if image.name else []
            if len(hits) == 1:
                found.append(_Layer(image, image.bbox, hits, ops[hits[0]].start))
        boxes = {m.tag: m for m in self.markups(index) if m.kind == "box" and not m.xref}
        for match in _BOX_CODE.finditer(data):
            tag = re.search(rb"/Id\s*(\d+)", match.group(1))
            box = boxes.get(int(tag.group(1))) if tag else None
            if box is not None:
                found.append(_Layer(box, box.bbox, [], match.start(),
                                    (match.start(), match.end())))
        blocks = self.line_blocks(index) if lines else self.text_blocks(index)
        shown: dict[int, list[int]] = {}
        to_page = page.transformation_matrix
        for i, op in enumerate(ops):
            if op.origin is None:
                continue
            p = op.origin * to_page
            hits = [k for k, b in enumerate(blocks) if p in b.bbox + (-1, -1, 1, 1)]
            if hits:
                k = min(hits, key=lambda k: blocks[k].bbox.get_area())
                shown.setdefault(k, []).append(i)
        for k, shows in shown.items():
            found.append(_Layer(blocks[k], blocks[k].bbox, shows, ops[shows[0]].start))
        return ops, final, found

    def _lift(self, page: fitz.Page, item: ImageInfo | TextBlock | Markup
              ) -> Callable[[layers.Spot], bytes]:
        """Take an element out of the page's content; returns what draws it again
        at a given place."""
        if isinstance(item, TextBlock):
            code = self._rewrite_block(page, item, fitz.Point(0, 0), capture=True) or b""
            return lambda spot: layers.place(code, spot)
        if isinstance(item, ImageInfo):
            if not item.name or not self._rewrite_do(page, item.name, b""):
                raise PdfError(tr("Could not change the layer of the image."))
            # The image's own coordinate system, in the page's default one.
            own = _IMAGE_FLIP * item.transform * ~page.transformation_matrix
            code = b"q " + layers.matrix_code(own) + b" cm /" + item.name.encode() + b" Do Q"
            return lambda spot: layers.place(code, spot)
        if item.xref:  # a box annotation becomes a box drawn on the page
            page.delete_annot(page.load_annot(item.xref))
            tag = max((m.tag for _, _, m in self._drawn_boxes(page)), default=0) + 1
        else:
            tag = item.tag
            xref, match, _ = next(b for b in self._drawn_boxes(page) if b[2].tag == tag)
            data = self.doc.xref_stream(xref)
            self.doc.update_stream(xref, data[: match.start()] + data[match.end():])
        rect, style, index = fitz.Rect(item.bbox), item.style, page.number
        return lambda spot: layers.place(
            self._box_code(self.doc[index], tag, rect, style, ~spot.ctm), spot, adjust=False)


_STANDARD_FONTS = {
    "helvetica", "helveticabold", "helveticaoblique", "helveticaboldoblique",
    "timesroman", "timesbold", "timesitalic", "timesbolditalic",
    "courier", "courierbold", "courieroblique", "courierboldoblique",
}


def _is_standard_font(name: str) -> bool:
    return re.sub(r"[^a-z]", "", name.split("+", 1)[-1].lower()) in _STANDARD_FONTS


def _base14_label(style: TextStyle) -> str:
    bold = style.bold or style.weight >= 600
    variant = " ".join(w for w, on in (("Bold", bold), ("Italic", style.italic)) if on)
    return f"{_FONT_LABELS[style.family]} {variant}".strip()


def _covers(font: fitz.Font, text: str) -> bool:
    return all(ch.isspace() or font.has_glyph(ord(ch)) for ch in text)


class _FontChoice:
    """How a piece of text will be drawn, and how to measure it.

    ``fallback`` draws the characters in ``missing`` (ones the main font
    lacks), so only those change typeface instead of the whole line.
    """

    def __init__(self, name: str | None = None, font: fitz.Font | None = None,
                 encoder: PdfFontEncoder | None = None, note: str | None = None,
                 fallback: _FontChoice | None = None, missing: set[str] | None = None,
                 label: str = "") -> None:
        self.name, self.font, self.encoder, self.note = name, font, encoder, note
        self.fallback, self.missing, self.label = fallback, missing or set(), label

    def _runs(self, text: str) -> list[tuple[_FontChoice, str]]:
        if not self.missing or self.fallback is None:
            return [(self, text)]
        runs: list[tuple[_FontChoice, str]] = []
        for ch in text:
            choice = self.fallback if ch in self.missing else self
            if runs and runs[-1][0] is choice:
                runs[-1] = (choice, runs[-1][1] + ch)
            else:
                runs.append((choice, ch))
        return runs

    def _write_one(self, page, origin, text, size, color, direction, rotate) -> None:
        if self.encoder is not None:
            write_text(page, self.encoder, origin, text, size, color, direction)
        else:
            page.insert_text(origin, text, fontsize=size, color=color, fontname=self.name,
                             rotate=rotate)

    def _length_one(self, text: str, size: float) -> float:
        if self.encoder is not None:
            return self.encoder.text_length(text, size)
        return self.font.text_length(text, fontsize=size)

    def write(self, page: fitz.Page, origin: fitz.Point, text: str, size: float,
              color: tuple[float, float, float], direction: tuple[float, float],
              rotate: int) -> None:
        dx, dy = direction
        norm = math.hypot(dx, dy) or 1.0
        pos = fitz.Point(origin)
        for choice, run in self._runs(text):
            choice._write_one(page, pos, run, size, color, direction, rotate)
            advance = choice._length_one(run, size)
            pos = pos + fitz.Point(dx / norm * advance, dy / norm * advance)

    def text_length(self, text: str, size: float) -> float:
        return sum(choice._length_one(run, size) for choice, run in self._runs(text))


class _FontWriter:
    """Chooses and embeds the font for re-inserted text on one page.

    For the target face, in order of preference:
    1. the PDF's own font object, if its (subset) glyphs cover the text;
    2. the embedded font program, if it has a usable character map;
    3. the same face installed on this computer (embedded, subset on save);
    4. if the PDF's font has *some* of the characters: that font, with only
       the missing characters drawn in the best fallback;
    5. otherwise the best fallback: the family installed in another weight,
       or the closest standard font. Each fallback comes with a note.
    """

    def __init__(self, pdf: PdfDocument, page: fitz.Page) -> None:
        self.pdf = pdf
        self.page = page
        self._inserted: set[str] = set()
        self._pending: dict[str, bytes] = {}

    def prepare(self, pdf_font: str | None, original: TextStyle, style: TextStyle,
                text: str) -> _FontChoice:
        """Pick the font for ``text`` in ``style``.

        ``pdf_font`` is the font the text currently has (None for new text);
        it's kept when the style still names the same face.
        """
        base14 = self._base14(style)
        if style.font is None:
            return base14  # a standard font: built into every PDF viewer
        face = self.pdf.doc_face(style.font) or (self.pdf.face_for(pdf_font) if pdf_font
                                                 else None)
        family = style.typeface or (face.family if face else family_name(style.font))
        if pdf_font and style.same_face(original):
            target = pdf_font
        else:
            # Picked in the font list, or B/I toggled: the document's closest face.
            if face is None or (face.weight, face.italic) != (style.weight, style.italic):
                face = self.pdf.nearest_face(family, style.weight, style.italic)
                if face is not None and abs(face.weight - style.weight) > 100:
                    face = None  # e.g. Regular is not a stand-in for Bold
            target = face.pdf_name if face else None
        label = style.font
        if target:
            choice = self._whole(target, style, text)
            if choice is not None:
                return choice
        installed = self.pdf.fonts.find_family(family, style.weight, style.italic)
        exact = installed is not None and abs(installed.weight - style.weight) <= 50
        if exact and (choice := self._installed(installed, text)) is not None:
            return choice
        # Nothing has every character. Keep the PDF's font for those it has.
        fallback = (self._installed(installed, text) if installed is not None else None) \
            or base14
        fallback.label = fallback.label or _base14_label(style)
        encoder = find_encoder(self.page, target) if target else None
        if encoder is not None:
            missing = {ch for ch in set(text) if not encoder.can_encode(ch)}
            if missing != set(text) - {" "} and len(missing) < len(set(text)):
                chars = [f"“{ch}”" for ch in sorted(missing) if not ch.isspace()]
                return _FontChoice(
                    encoder=encoder, fallback=fallback, missing=missing, label=label,
                    note=ntr("“{font}” isn't installed on this computer and the document "
                             "only contains some of its characters, so {chars} uses "
                             "{fallback}.",
                             "“{font}” isn't installed on this computer and the document "
                             "only contains some of its characters, so {chars} use "
                             "{fallback}.",
                             len(chars), font=label, chars=", ".join(chars),
                             fallback=fallback.label),
                )
        fallback.note = tr("“{font}” isn't available for these characters in this document "
                           "or on this computer, so the text uses {fallback}.",
                           font=label, fallback=fallback.label)
        return fallback

    def _base14(self, style: TextStyle) -> _FontChoice:
        bold = style.bold or style.weight >= 600
        code = _BASE14[(style.family, bold, style.italic)]
        return _FontChoice(name=code, font=fitz.Font(code), label=_base14_label(style))

    def _whole(self, target: str, style: TextStyle, text: str) -> _FontChoice | None:
        """A font for ``target`` that has every character of ``text``, if any."""
        encoder = find_encoder(self.page, target)
        if encoder is not None and encoder.can_encode(text):
            return _FontChoice(encoder=encoder, label=style.font or "")
        found = self.pdf._embedded_font(self.page, target, text)
        if found:
            return _FontChoice(name=self._insert(f"PXF{found[1]}", found[0]),
                               font=fitz.Font(fontbuffer=found[0]), label=style.font or "")
        return self._installed(self.pdf.fonts.find(target, style.bold, style.italic), text)

    def _installed(self, face, text: str) -> _FontChoice | None:
        if face is None:
            return None
        try:
            buf = face_bytes(face)
            font = fitz.Font(fontbuffer=buf)
        except Exception:
            return None
        if not _covers(font, text):
            return None
        digest = zlib.crc32(f"{face.path}#{face.index}".encode())
        self.pdf._embedded_installed_fonts = True
        return _FontChoice(name=self._insert(f"PXS{digest:08x}", buf), font=font,
                           label=face.full_name)

    def _insert(self, name: str, buf: bytes) -> str:
        # Embedded later by flush(): redactions run in between and would drop
        # a font that no text uses yet.
        self._pending[name] = buf
        return name

    def flush(self) -> None:
        """Embed the chosen fonts; call after redacting, before inserting text."""
        for name, buf in self._pending.items():
            if name not in self._inserted:
                self.page.insert_font(fontname=name, fontbuffer=buf)
                self._inserted.add(name)
        self._pending.clear()
