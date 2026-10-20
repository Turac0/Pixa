"""Find fonts installed on this computer by the names PDFs use for them.

PDFs usually embed only the glyphs a document originally used (a "subset"), so
an edit that types new characters can't reuse the embedded font. If the same
font is installed locally we can embed that instead and keep the text's look.

Scanning opens every font file, so instead of loading fonts with PyMuPDF
(~10 ms each) we read just the OpenType ``name`` and ``OS/2`` tables, which
takes well under a millisecond per file.
"""

from __future__ import annotations

import os
import re
import struct
import sys
import threading
from dataclasses import dataclass

FONT_EXTENSIONS = (".ttf", ".otf", ".ttc", ".otc")

# When a font isn't installed, an installed font with identical character widths
# keeps the line layout intact (e.g. Liberation Sans on Linux instead of Arial).
METRIC_ALIASES = {
    "arial": ["liberationsans", "arimo", "helvetica", "helveticaneue"],
    "helvetica": ["arial", "liberationsans", "arimo", "helveticaneue"],
    "timesnewroman": ["liberationserif", "tinos", "times"],
    "times": ["timesnewroman", "liberationserif", "tinos"],
    "couriernew": ["liberationmono", "cousine", "courier"],
    "courier": ["couriernew", "liberationmono", "cousine"],
    "calibri": ["carlito"],
    "cambria": ["caladea"],
    "liberationsans": ["arial", "arimo", "helvetica"],
    "liberationserif": ["timesnewroman", "tinos", "times"],
    "liberationmono": ["couriernew", "cousine", "courier"],
}
_STYLE_SUFFIX = re.compile(r"(bold|italic|oblique|semibold|demibold|light|medium|black)+$")


@dataclass(frozen=True)
class FontFace:
    path: str
    index: int  # face index inside a .ttc collection, else 0
    family: str
    subfamily: str
    full_name: str
    postscript_name: str
    bold: bool
    italic: bool
    weight: int = 400  # 100 (thin) .. 900 (black)
    serif: bool | None = None  # None when the font doesn't say
    mono: bool = False


_WEIGHT_WORDS = [  # longest first, so "semibold" wins over "bold"
    ("extralight", 200), ("ultralight", 200), ("extrabold", 800), ("ultrabold", 800),
    ("semibold", 600), ("demibold", 600), ("hairline", 100), ("thin", 100), ("light", 300),
    ("regular", 400), ("normal", 400), ("book", 400), ("roman", 400), ("medium", 500),
    ("bold", 700), ("heavy", 900), ("black", 900),
]


def weight_from_name(name: str) -> int:
    """Weight class guessed from a font/style name ("Inter-SemiBold" -> 600)."""
    text = re.sub(r"[^a-z]", "", name.split("+", 1)[-1].lower())
    for word, weight in _WEIGHT_WORDS:
        if word in text:
            return weight
    return 400


def weight_label(weight: int) -> str:
    return {100: "Thin", 200: "ExtraLight", 300: "Light", 400: "", 500: "Medium",
            600: "SemiBold", 700: "Bold", 800: "ExtraBold", 900: "Black"}.get(
        min(900, max(100, round(weight / 100) * 100)), "")


def normalize(name: str) -> str:
    """Normalize a font name for matching.

    "ABCDEF+Arial-BoldMT", "Arial,Bold" and "Arial Bold" all become "arialbold";
    "TimesNewRomanPSMT" and "Times New Roman" both become "timesnewroman".
    """
    name = name.split("+", 1)[-1].lower()
    name = re.sub(r"[^a-z0-9]", "", name)
    for suffix in ("psmt", "mt", "ps"):
        if name.endswith(suffix) and len(name) > len(suffix) + 2:
            name = name[: -len(suffix)]
            break
    for style in ("regular", "book", "normal"):
        if name.endswith(style) and len(name) > len(style):
            return name[: -len(style)]
    return name


def default_font_dirs() -> list[str]:
    home = os.path.expanduser("~")
    if sys.platform.startswith("win"):
        windir = os.environ.get("WINDIR", r"C:\Windows")
        local = os.environ.get("LOCALAPPDATA", os.path.join(home, "AppData", "Local"))
        return [os.path.join(windir, "Fonts"), os.path.join(local, "Microsoft", "Windows", "Fonts")]
    if sys.platform == "darwin":
        return ["/System/Library/Fonts", "/Library/Fonts", os.path.join(home, "Library", "Fonts")]
    return [
        "/usr/share/fonts",
        "/usr/local/share/fonts",
        os.path.join(home, ".local", "share", "fonts"),
        os.path.join(home, ".fonts"),
    ]


# ------------------------------------------------------------- sfnt parsing
def _face_offsets(data: bytes) -> list[int]:
    if data[:4] == b"ttcf":
        (count,) = struct.unpack(">I", data[8:12])
        return list(struct.unpack(f">{count}I", data[12 : 12 + 4 * count]))
    return [0]


def _tables(data: bytes, offset: int) -> dict[bytes, tuple[int, int]]:
    (num,) = struct.unpack(">H", data[offset + 4 : offset + 6])
    tables = {}
    for i in range(num):
        rec = offset + 12 + 16 * i
        tag, _checksum, start, length = struct.unpack(">4sIII", data[rec : rec + 16])
        tables[tag] = (start, length)
    return tables


def _names(data: bytes, start: int) -> dict[int, str]:
    _fmt, count, string_offset = struct.unpack(">HHH", data[start : start + 6])
    found: dict[int, tuple[int, str]] = {}
    for i in range(count):
        rec = start + 6 + 12 * i
        platform, encoding, language, name_id, length, offset = struct.unpack(
            ">HHHHHH", data[rec : rec + 12]
        )
        if name_id not in (1, 2, 4, 6, 16, 17):
            continue
        raw = data[start + string_offset + offset : start + string_offset + offset + length]
        if platform == 3 or platform == 0:  # Windows / Unicode: UTF-16BE
            text = raw.decode("utf-16-be", "ignore")
            # Prefer US English Windows names, then any Unicode name.
            rank = 0 if (platform == 3 and language == 0x409) else 1
        elif platform == 1 and encoding == 0:  # Mac Roman
            text, rank = raw.decode("mac_roman", "ignore"), 2
        else:
            continue
        if text and (name_id not in found or rank < found[name_id][0]):
            found[name_id] = (rank, text)
    return {k: v for k, (_, v) in found.items()}


def read_faces(path: str) -> list[FontFace]:
    with open(path, "rb") as fh:
        return read_faces_from(fh.read(), path)


def read_faces_from(data: bytes, path: str = "") -> list[FontFace]:
    """Faces described by an OpenType/TrueType font file's name tables."""
    if data[:4] not in (b"\x00\x01\x00\x00", b"true", b"OTTO", b"ttcf"):
        return []
    faces = []
    for index, offset in enumerate(_face_offsets(data)):
        tables = _tables(data, offset)
        if b"name" not in tables:
            continue
        names = _names(data, tables[b"name"][0])
        subfamily = names.get(17) or names.get(2, "Regular")
        if 16 in names:
            family = names[16]  # typographic family: "Inter"
        else:
            # Legacy family names carry non-RIBBI weights: "Inter SemiBold" + "Regular".
            words = names.get(1, "").split()
            while len(words) > 1 and words[-1].lower() in dict(_WEIGHT_WORDS):
                subfamily = words.pop() + ("" if subfamily.lower() == "regular" else
                                           " " + subfamily)
            family = " ".join(words)
        bold = italic = False
        weight = weight_from_name(subfamily)
        serif: bool | None = None
        mono = False
        if b"OS/2" in tables:
            start = tables[b"OS/2"][0]
            (weight_class,) = struct.unpack(">H", data[start + 4 : start + 6])
            if 100 <= weight_class <= 950:
                weight = weight_class
            family_type, serif_style = data[start + 32], data[start + 33]
            if family_type == 2 and 2 <= serif_style <= 13:  # PANOSE "Latin text"
                serif = serif_style <= 10
            (fs_selection,) = struct.unpack(">H", data[start + 62 : start + 64])
            italic = bool(fs_selection & 0x01)
            bold = bool(fs_selection & 0x20)
        if b"post" in tables:
            start = tables[b"post"][0]
            mono = struct.unpack(">I", data[start + 12 : start + 16])[0] != 0
        sub = subfamily.lower()
        bold = bold or weight >= 600 or "bold" in sub or "black" in sub
        italic = italic or "italic" in sub or "oblique" in sub
        faces.append(
            FontFace(
                path=path,
                index=index,
                family=family,
                subfamily=subfamily,
                full_name=names.get(4, f"{family} {subfamily}"),
                postscript_name=names.get(6, ""),
                bold=bold,
                italic=italic,
                weight=weight,
                serif=serif,
                mono=mono,
            )
        )
    return faces


def face_bytes(face: FontFace) -> bytes:
    """The font file for one face; a face inside a collection becomes a standalone font."""
    with open(face.path, "rb") as fh:
        data = fh.read()
    if data[:4] != b"ttcf":
        return data
    offset = _face_offsets(data)[face.index]
    tables = _tables(data, offset)
    header = bytearray(data[offset : offset + 12])
    directory = bytearray()
    body = bytearray()
    start = 12 + 16 * len(tables)
    for tag, (table_start, length) in sorted(tables.items()):
        rec = offset + 12 + 16 * list(tables).index(tag)
        checksum = struct.unpack(">I", data[rec + 4 : rec + 8])[0]
        directory += struct.pack(">4sIII", tag, checksum, start + len(body), length)
        body += data[table_start : table_start + length]
        body += b"\0" * (-len(body) % 4)  # tables are 4-byte aligned
    return bytes(header + directory + body)


# ------------------------------------------------------------------ index
class SystemFonts:
    """Lazily built index of installed fonts. Thread-safe; build it early with :meth:`warm`."""

    def __init__(self, dirs: list[str] | None = None) -> None:
        self.dirs = dirs if dirs is not None else default_font_dirs()
        self._by_name: dict[str, FontFace] | None = None
        self._by_family: dict[tuple[str, bool, bool], FontFace] = {}
        self._faces: dict[str, list[FontFace]] = {}  # normalized family -> faces
        self._lock = threading.Lock()

    def warm(self) -> None:
        threading.Thread(target=self._index, daemon=True).start()

    def _index(self) -> dict[str, FontFace]:
        with self._lock:
            if self._by_name is not None:
                return self._by_name
            by_name: dict[str, FontFace] = {}
            for directory in self.dirs:
                for root, _dirs, files in os.walk(directory):
                    for file in files:
                        if not file.lower().endswith(FONT_EXTENSIONS):
                            continue
                        try:
                            faces = read_faces(os.path.join(root, file))
                        except (OSError, struct.error, IndexError, UnicodeDecodeError):
                            continue
                        for face in faces:
                            for key in (face.postscript_name, face.full_name,
                                        f"{face.family} {face.subfamily}"):
                                by_name.setdefault(normalize(key), face)
                            self._by_family.setdefault(
                                (normalize(face.family), face.bold, face.italic), face
                            )
                            self._faces.setdefault(normalize(face.family), []).append(face)
            self._by_name = by_name
            return by_name

    def find(self, pdf_font_name: str, bold: bool = False, italic: bool = False) -> FontFace | None:
        """The installed font a PDF font name refers to, if any."""
        by_name = self._index()
        key = normalize(pdf_font_name)
        if not key:
            return None
        if key in by_name:
            return by_name[key]
        # "Calibri-SemiboldItalic" etc.: fall back to the family plus the span's style.
        family = _STYLE_SUFFIX.sub("", key) or key
        family = re.sub(r"(psmt|mt|ps)$", "", family) or family  # "TimesNewRomanPS-Italic"
        weight = weight_from_name(pdf_font_name)
        if bold and weight < 600:
            weight = 700
        return self.find_family(family, weight, italic)

    def find_family(self, family: str, weight: int = 400,
                    italic: bool = False) -> FontFace | None:
        """The installed face of a family closest to a weight ("Inter", 600 -> SemiBold)."""
        self._index()
        key = normalize(family)
        for candidate in [key, *METRIC_ALIASES.get(key, [])]:
            faces = self._faces.get(candidate)
            if faces:
                return min(faces, key=lambda f: (f.italic != italic, abs(f.weight - weight),
                                                 -f.weight))
        return None

    def families(self) -> set[str]:
        """Normalized names of installed families."""
        self._index()
        return {family for family, _bold, _italic in self._by_family}

    def __len__(self) -> int:
        return len(self._index())


_STYLE_WORDS = (
    "bolditalic", "boldoblique", "semibold", "demibold", "extrabold", "ultrabold", "bold",
    "black", "heavy", "italic", "oblique", "regular", "book", "normal", "roman", "medium",
    "light", "thin",
)
_BOLD_WORDS = ("bold", "black", "heavy")
_ITALIC_WORDS = ("italic", "oblique")


def family_name(pdf_font_name: str) -> str:
    """A readable family name from a PDF font name.

    "ABCDEF+TimesNewRomanPS-BoldMT" -> "Times New Roman", "Arial,Bold" -> "Arial",
    "DejaVu Sans Book" -> "DejaVu Sans", "Calibri-Light" -> "Calibri".
    """
    name = pdf_font_name.split("+", 1)[-1]
    name = re.split(r"[,-]", name, maxsplit=1)[0] if re.search(r"[,-]", name) else name
    name = re.sub(r"(PSMT|MT|PS)$", "", name)
    words = name.split()
    while len(words) > 1 and words[-1].lower() in _STYLE_WORDS:
        words.pop()
    name = " ".join(words)
    if " " not in name:
        # "TimesNewRoman" -> "Times New Roman", but keep acronyms like "PT Sans".
        name = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)
    return name.strip() or pdf_font_name


def style_of(pdf_font_name: str) -> tuple[bool, bool]:
    """(bold, italic) as far as the font's name tells."""
    rest = pdf_font_name.split("+", 1)[-1].lower()
    return any(w in rest for w in _BOLD_WORDS), any(w in rest for w in _ITALIC_WORDS)
