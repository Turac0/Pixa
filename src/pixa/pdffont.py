"""Write new text with a font that's already in the PDF, using its own glyph codes.

Embedded fonts are usually *subsets* with no Unicode character map, so they
can't simply be re-inserted as fonts. But the PDF's ``/ToUnicode`` table says
which code draws which character, and (for TrueType programs) the ``loca``
table says which glyphs really exist. With both we can write text in the
original font object, so an edit using available characters looks identical
and adds nothing to the file.
"""

from __future__ import annotations

import re
import struct

import pymupdf as fitz

from pixa.fonts import normalize

_HEX = rb"<([0-9A-Fa-f]+)>"


def _ints(text: str) -> list:
    """Parse a PDF array like "[ 3 [ 600 0 ] 11 12 390 ]" into nested Python lists."""
    tokens = re.findall(r"\[|\]|-?\d+(?:\.\d+)?", text)
    stack: list[list] = [[]]
    for tok in tokens:
        if tok == "[":
            stack.append([])
        elif tok == "]":
            done = stack.pop()
            stack[-1].append(done)
        else:
            stack[-1].append(float(tok))
    return stack[0][0] if stack[0] and isinstance(stack[0][0], list) else stack[0]


def _resolve(doc: fitz.Document, xref: int, key: str) -> tuple[str, str]:
    kind, value = doc.xref_get_key(xref, key)
    return kind, value


def _ref(value: str) -> int | None:
    m = re.match(r"(\d+) 0 R", value.strip())
    return int(m.group(1)) if m else None


def _parse_tounicode(data: bytes) -> tuple[dict[str, int], int]:
    """char -> code, and the code length in bytes."""
    code_len = 1
    m = re.search(rb"begincodespacerange\s*" + _HEX, data)
    if m:
        code_len = max(1, len(m.group(1)) // 2)
    mapping: dict[str, int] = {}

    def add(code: int, uni_hex: bytes) -> None:
        try:
            text = bytes.fromhex(uni_hex.decode()).decode("utf-16-be")
        except (ValueError, UnicodeDecodeError):
            return
        if len(text) == 1:
            mapping.setdefault(text, code)

    for block in re.findall(rb"beginbfchar(.*?)endbfchar", data, re.S):
        for src, dst in re.findall(_HEX + rb"\s*" + _HEX, block):
            add(int(src, 16), dst)
    for block in re.findall(rb"beginbfrange(.*?)endbfrange", data, re.S):
        for lo, hi, rest in re.findall(_HEX + rb"\s*" + _HEX + rb"\s*(\[[^\]]*\]|<[0-9A-Fa-f]+>)",
                                       block):
            lo_i, hi_i = int(lo, 16), int(hi, 16)
            if rest.startswith(b"["):
                for i, dst in enumerate(re.findall(_HEX, rest)):
                    add(lo_i + i, dst)
            else:
                start = int(rest[1:-1], 16)
                width = len(rest) - 2
                for i in range(min(hi_i - lo_i + 1, 0x10000)):
                    add(lo_i + i, f"{start + i:0{width}x}".encode())
    return mapping, code_len


def _truetype_glyphs(buf: bytes) -> set[int] | None:
    """Glyph ids that have outlines in a TrueType program (None if not TrueType)."""
    try:
        if buf[:4] not in (b"\x00\x01\x00\x00", b"true"):
            return None
        (num,) = struct.unpack(">H", buf[4:6])
        tables = {}
        for i in range(num):
            tag, _cs, off, length = struct.unpack(">4sIII", buf[12 + 16 * i : 28 + 16 * i])
            tables[tag] = (off, length)
        if b"loca" not in tables or b"head" not in tables:
            return None
        head = tables[b"head"][0]
        (long_fmt,) = struct.unpack(">h", buf[head + 50 : head + 52])
        off, length = tables[b"loca"]
        size = 4 if long_fmt else 2
        count = length // size
        loca = struct.unpack(f">{count}{'I' if long_fmt else 'H'}", buf[off : off + count * size])
        return {g for g in range(count - 1) if loca[g + 1] > loca[g]}
    except (struct.error, IndexError):
        return None


class PdfFontEncoder:
    """Encodes text into one existing PDF font resource's character codes."""

    def __init__(self, doc: fitz.Document, xref: int, refname: str) -> None:
        self.doc = doc
        self.xref = xref
        self.refname = refname
        self.codes: dict[str, int] = {}
        self.code_len = 1
        self.widths: dict[int, float] = {}
        self.default_width = 0.0
        self._glyphs: set[int] | None = None
        self._identity = False
        self._load()

    def _load(self) -> None:
        doc, xref = self.doc, self.xref
        kind, value = _resolve(doc, xref, "ToUnicode")
        tu = _ref(value) if kind == "xref" else None
        if tu is None:
            return
        self.codes, self.code_len = _parse_tounicode(doc.xref_stream(tu) or b"")
        subtype = _resolve(doc, xref, "Subtype")[1]
        if subtype == "/Type0":
            kind, value = _resolve(doc, xref, "DescendantFonts")
            refs = re.findall(r"(\d+) 0 R", value)
            if not refs:
                self.codes = {}
                return
            desc = int(refs[0])
            encoding = _resolve(doc, xref, "Encoding")[1]
            self._identity = encoding in ("/Identity-H", "/Identity-V")
            self.code_len = 2
            gid_map = _resolve(doc, desc, "CIDToGIDMap")
            identity_gids = gid_map[0] == "null" or gid_map[1] == "/Identity"
            dw = _resolve(doc, desc, "DW")
            self.default_width = float(dw[1]) if dw[0] in ("int", "float") else 1000.0
            kind, value = _resolve(doc, desc, "W")
            if kind == "xref":
                value = doc.xref_object(_ref(value) or 0)
            if kind in ("array", "xref"):
                self._read_cid_widths(_ints(value))
            if self._identity and identity_gids:
                try:
                    _, _, _, buf = doc.extract_font(xref)
                    self._glyphs = _truetype_glyphs(buf) if buf else None
                except Exception:
                    self._glyphs = None
        else:
            # Simple fonts always use one-byte codes, whatever codespace the
            # ToUnicode CMap declares (some producers write <0000> <FFFF>).
            self.code_len = 1
            self.codes = {ch: code for ch, code in self.codes.items() if code < 256}
            first = _resolve(doc, xref, "FirstChar")
            kind, value = _resolve(doc, xref, "Widths")
            if kind == "xref":
                value = doc.xref_object(_ref(value) or 0)
            if first[0] == "int" and kind in ("array", "xref"):
                start = int(first[1])
                for i, w in enumerate(_ints(value)):
                    if isinstance(w, float):
                        self.widths[start + i] = w

    def _read_cid_widths(self, arr: list) -> None:
        i = 0
        while i < len(arr):
            first = arr[i]
            if i + 1 < len(arr) and isinstance(arr[i + 1], list):
                for j, w in enumerate(arr[i + 1]):
                    self.widths[int(first) + j] = w
                i += 2
            elif i + 2 < len(arr):
                for c in range(int(first), int(arr[i + 1]) + 1):
                    self.widths[c] = arr[i + 2]
                i += 3
            else:
                break

    def can_encode(self, text: str) -> bool:
        for ch in text:
            code = self.codes.get(ch)
            if code is None:
                return False
            if self._glyphs is not None and code not in self._glyphs and not ch.isspace():
                return False  # listed in ToUnicode, but the subset dropped the glyph
            if self.code_len == 1 and self.widths and code not in self.widths:
                return False
        return bool(text)

    def encode(self, text: str) -> str:
        return "".join(f"{self.codes[ch]:0{2 * self.code_len}x}" for ch in text)

    def text_length(self, text: str, fontsize: float) -> float:
        total = sum(self.widths.get(self.codes[ch], self.default_width) for ch in text)
        return total * fontsize / 1000


def find_encoder(page: fitz.Page, font_name: str) -> PdfFontEncoder | None:
    """A font object with this name in the document (this page first) that can encode text."""
    wanted = normalize(font_name)
    doc = page.parent
    seen: set[int] = set()
    for p in [page, *doc]:
        for entry in p.get_fonts(full=True):
            xref, _ext, _type, basefont, refname = entry[:5]
            if xref in seen or normalize(basefont) != wanted:
                continue
            seen.add(xref)
            encoder = PdfFontEncoder(doc, xref, refname)
            if encoder.codes:
                return encoder
    return None


def _add_font_resource(doc: fitz.Document, page: fitz.Page, refname: str, xref: int) -> None:
    """Add "/refname xref 0 R" to the page's font resources.

    /Resources and its /Font dictionary may each be inline or separate
    objects; PyMuPDF's key paths can't cross the latter, so walk them.
    """
    holder, path = page.xref, "Resources"
    kind, value = doc.xref_get_key(holder, path)
    if kind == "xref":
        holder, path = _ref(value), ""
    elif kind == "null":
        doc.xref_set_key(holder, path, "<<>>")
    font_key = f"{path}/Font" if path else "Font"
    kind, value = doc.xref_get_key(holder, font_key)
    if kind == "xref":
        doc.xref_set_key(_ref(value), refname, f"{xref} 0 R")
        return
    if kind == "null":
        doc.xref_set_key(holder, font_key, "<<>>")
    doc.xref_set_key(holder, f"{font_key}/{refname}", f"{xref} 0 R")


def write_text(page: fitz.Page, encoder: PdfFontEncoder, origin: fitz.Point, text: str,
               fontsize: float, color: tuple[float, float, float],
               direction: tuple[float, float]) -> None:
    """Append text drawn with an existing font resource to the page."""
    doc = page.parent
    # The font may come from another page, or redactions may have dropped it
    # from this one: make sure this page lists it under a name of its own.
    on_page = {entry[4]: entry[0] for entry in page.get_fonts(full=True)}
    refname = encoder.refname
    if on_page.get(refname, encoder.xref) != encoder.xref:
        refname = f"PXR{encoder.xref}"  # that name means another font here
    if on_page.get(refname) != encoder.xref:
        _add_font_resource(doc, page, refname, encoder.xref)
    if not page.is_wrapped:
        page.wrap_contents()
    to_pdf = ~page.transformation_matrix
    o = fitz.Point(origin) * to_pdf
    d = (fitz.Point(*direction) * to_pdf) - (fitz.Point(0, 0) * to_pdf)
    length = (d.x ** 2 + d.y ** 2) ** 0.5 or 1.0
    cx, cy = d.x / length, d.y / length

    def num(v: float) -> str:
        return f"{v:.4f}".rstrip("0").rstrip(".") or "0"

    stream = (
        f"q {num(color[0])} {num(color[1])} {num(color[2])} rg BT "
        f"/{refname} {num(fontsize)} Tf "
        f"{num(cx)} {num(cy)} {num(-cy)} {num(cx)} {num(o.x)} {num(o.y)} Tm "
        f"<{encoder.encode(text)}> Tj ET Q"
    ).encode()
    xref = doc.get_new_xref()
    doc.update_object(xref, "<<>>")
    doc.update_stream(xref, stream)
    contents = page.get_contents() + [xref]
    doc.xref_set_key(page.xref, "Contents", "[" + " ".join(f"{x} 0 R" for x in contents) + "]")
