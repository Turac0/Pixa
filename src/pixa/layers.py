"""Reading the drawing order of a page's content stream, for layering.

A PDF page is painted in the order its content stream lists the operators:
whatever comes later lies on top. :func:`scan` walks the operators and keeps
just enough graphics and text state to say, for every operator, where it
sits in the stream, what coordinate system is in effect (the CTM), whether it
is inside a text object, and where a text-showing operator starts on the page.

That is what layering needs: finding the operators that draw an element
(an image's ``Do``, the text of a paragraph), and places before or after
them where a self-contained piece of drawing code can be put. Inside a text
object (``BT`` … ``ET``) such code can't go directly, so the text object is
split there: ``ET`` <code> ``BT`` <line matrix> ``Tm`` (text state such as the
font and spacing is part of the graphics state and survives the split).

The module is Qt-free and only depends on PyMuPDF's matrices.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pymupdf as fitz

_REGULAR = rb"[^\x00\t\n\x0c\r ()<>\[\]{}/%]"
_TOKEN = re.compile(
    rb"(?P<ws>[\x00\t\n\x0c\r ]+)"
    rb"|(?P<comment>%[^\r\n]*)"
    rb"|(?P<num>[+-]?(?:\d+\.?\d*|\.\d+)(?!" + _REGULAR + rb"))"
    rb"|(?P<name>/" + _REGULAR + rb"*)"
    rb"|(?P<dict><<|>>)"
    rb"|(?P<hex><[^<>]*>)"
    rb"|(?P<bracket>[\[\]{}])"
    rb"|(?P<string>\()"
    rb"|(?P<op>" + _REGULAR + rb"+)"
)
_STRING_PART = re.compile(rb"[^()\\]+|\\.?|[()]", re.S)
_INLINE_END = re.compile(rb"[\x00\t\n\x0c\r ]EI(?=[\x00\t\n\x0c\r ]|$)")

SHOW_TEXT = {b"Tj", b"TJ", b"'", b'"'}
# Operators after which the text position is the start of a line again.
_NEW_LINE = {b"Td", b"TD", b"T*", b"Tm"}


@dataclass
class Op:
    """One operator of a content stream, with the state it runs in."""

    name: bytes
    start: int  # first byte of its operands (or of the operator itself)
    end: int  # just after the operator
    ctm: fitz.Matrix  # in effect when it runs (for "cm": before it)
    in_text: bool  # inside BT … ET
    # Inside text: the text position is where its line starts (nothing has
    # been shown since BT or the last line move), so the text object can be
    # split right before this operator.
    line_start: bool
    line_matrix: fitz.Matrix | None  # the text line matrix before it runs
    origin: fitz.Point | None = None  # text-showing operators: where they start (PDF space)
    operand: bytes | None = None  # Do: the name of what it paints


def _skip_string(data: bytes, i: int) -> int:
    """End of the literal string starting at ``data[i] == '('``."""
    depth = 0
    for m in _STRING_PART.finditer(data, i):
        part = m.group()
        if part == b"(":
            depth += 1
        elif part == b")":
            depth -= 1
            if depth == 0:
                return m.end()
    return len(data)


def scan(data: bytes) -> tuple[list[Op], fitz.Matrix]:
    """The operators of a content stream, and the CTM in effect at its end.

    Coordinates are PDF user space of the page (the CTM starts as identity).
    """
    ops: list[Op] = []
    ctm = fitz.Identity
    leading = 0.0
    stack: list[tuple[fitz.Matrix, float]] = []
    in_text = False
    tm = tlm = fitz.Identity
    line_start = True
    nums: list[float] = []
    last_name: bytes | None = None
    start = -1
    i, n = 0, len(data)
    while i < n:
        m = _TOKEN.match(data, i)
        if m is None:  # a stray ')' or '>': not part of anything we track
            i += 1
            continue
        kind = m.lastgroup
        if kind in ("ws", "comment"):
            i = m.end()
            continue
        if start < 0:
            start = m.start()
        if kind == "string":
            i = _skip_string(data, i)
            continue
        i = m.end()
        if kind == "num":
            nums.append(float(m.group()))
            continue
        if kind == "name":
            last_name = m.group()[1:]
            continue
        if kind != "op":
            continue
        name = m.group()
        if name == b"ID":  # inline image data: skip to its "EI"
            end = _INLINE_END.search(data, i)
            i = end.end() if end else n
        op = Op(name, start, i, ctm, in_text, line_start, tlm if in_text else None)
        ops.append(op)
        if name == b"q":
            stack.append((ctm, leading))
        elif name == b"Q":
            if stack:
                ctm, leading = stack.pop()
        elif name == b"cm" and len(nums) >= 6:
            ctm = fitz.Matrix(*nums[-6:]) * ctm
        elif name == b"BT":
            in_text, tm, tlm, line_start = True, fitz.Identity, fitz.Identity, True
        elif name == b"ET":
            in_text = False
        elif name == b"Do":
            op.operand = last_name
        elif in_text:
            if name == b"TL" and nums:
                leading = nums[-1]
            elif name in (b"Td", b"TD") and len(nums) >= 2:
                if name == b"TD":
                    leading = -nums[-1]
                tlm = tm = fitz.Matrix(1, 0, 0, 1, nums[-2], nums[-1]) * tlm
                line_start = True
            elif name == b"Tm" and len(nums) >= 6:
                tlm = tm = fitz.Matrix(*nums[-6:])
                line_start = True
            elif name in (b"T*", b"'", b'"'):
                tlm = tm = fitz.Matrix(1, 0, 0, 1, 0, -leading) * tlm
                line_start = True
            if name in SHOW_TEXT:
                op.origin = fitz.Point(0, 0) * tm * ctm
                # The glyph advance isn't tracked: the position is now unknown
                # until the next line move.
                line_start = False
        nums = []
        last_name = None
        start = -1
    return ops, ctm


def ctm_at(ops: list[Op], final: fitz.Matrix, pos: int) -> fitz.Matrix:
    """The CTM in effect at byte ``pos`` (between operators)."""
    for op in ops:
        if op.start >= pos:
            return op.ctm
    return final


@dataclass
class Spot:
    """A place in a content stream where drawing code can be inserted."""

    pos: int
    ctm: fitz.Matrix
    # Set when the place is inside a text object, which is split there; the
    # text continues from this line matrix.
    line_matrix: fitz.Matrix | None = None


def before(ops: list[Op], index: int) -> Spot:
    """A place just before operator ``index``, below what it draws."""
    k = index
    while ops[k].in_text and not ops[k].line_start:
        k -= 1  # the line continues text shown before: go back to its start
    op = ops[k]
    if op.in_text and ops[k - 1].name == b"BT":
        op = ops[k - 1]  # the start of the text object: no need to split it
    if op.in_text:
        return Spot(op.start, op.ctm, op.line_matrix)
    return Spot(op.start, op.ctm)


def after(ops: list[Op], index: int, final: fitz.Matrix) -> Spot:
    """A place just after operator ``index``, on top of what it draws."""
    op = ops[index]
    if not op.in_text or op.name == b"ET":
        return Spot(op.end, op.ctm)
    for nxt in ops[index + 1:]:
        if nxt.name == b"ET":
            return Spot(nxt.end, nxt.ctm)
        if nxt.name in _NEW_LINE or nxt.name in (b"'", b'"'):
            # The text after this point is placed from the line matrix.
            return Spot(nxt.start, nxt.ctm, nxt.line_matrix)
    return Spot(ops[-1].end, final)


def number(v: float) -> str:
    return f"{v:.10f}".rstrip("0").rstrip(".") or "0"


def matrix_code(m: fitz.Matrix) -> bytes:
    return " ".join(number(v) for v in m).encode()


def is_identity(m: fitz.Matrix) -> bool:
    return all(abs(a - b) < 1e-6 for a, b in zip(m, fitz.Identity, strict=True))


def place(code: bytes, spot: Spot, adjust: bool = True) -> bytes:
    """``code`` (drawing at the default CTM) wrapped to go at ``spot``.

    Without ``adjust`` the code is taken as already made for the CTM there.
    """
    if adjust:
        fix = b"" if is_identity(spot.ctm) else matrix_code(~spot.ctm) + b" cm\n"
        wrapped = b"q\n" + fix + code.strip() + b"\nQ"
    else:
        wrapped = code.strip()
    if spot.line_matrix is None:
        return b"\n" + wrapped + b"\n"
    return b"\nET\n" + wrapped + b"\nBT " + matrix_code(spot.line_matrix) + b" Tm\n"
