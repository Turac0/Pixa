"""Image files Pixa can insert, and turning them into something PyMuPDF reads.

PyMuPDF decodes the common raster formats itself, and SVGs are inserted as
vector graphics by the document model. Every other format Qt has a reader for
(icons, TGA, WebP, and HEIC or AVIF where the installed Qt plugins handle
them) is decoded by Qt and handed over as PNG, as are images from elsewhere
in Qt (such as the clipboard), through :func:`png_bytes`.
"""

from __future__ import annotations

import functools
import os

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage, QImageReader

from pixa.document import PdfError
from pixa.i18n import tr

# Formats PyMuPDF reads itself (it can't read WebP, so Qt does that one).
NATIVE = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".pnm", ".pbm",
          ".pgm", ".ppm", ".pam", ".psd", ".jxr", ".jpx", ".jp2")
VECTOR = (".svg", ".svgz")
_NOT_IMAGES = {".pdf"}  # Qt may have a reader for these, but they are documents


@functools.cache
def extensions() -> tuple[str, ...]:
    """Every file extension that can be inserted as an image (lower case, with dot)."""
    qt = sorted(f".{bytes(fmt).decode().lower()}" for fmt in QImageReader.supportedImageFormats())
    found = list(NATIVE + VECTOR)
    found += [ext for ext in qt if ext not in found and ext not in _NOT_IMAGES]
    return tuple(found)


def is_image(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in extensions()


def file_filter() -> str:
    """A file dialog filter for the images that can be inserted."""
    patterns = " ".join(f"*{ext}" for ext in extensions())
    return tr("Images ({patterns})", patterns=patterns) + ";;" + tr("All files (*)")


def png_bytes(image: QImage) -> bytes:
    data = QBuffer()
    data.open(QIODevice.OpenModeFlag.WriteOnly)
    if image.isNull() or not image.save(data, "PNG"):
        raise PdfError(tr("The image could not be converted."))
    return bytes(data.data())


def source(path: str) -> str | bytes:
    """What to hand the document for an image file: the path when PyMuPDF reads it
    (or it is an SVG), otherwise the image decoded by Qt as PNG."""
    ext = os.path.splitext(path)[1].lower()
    if ext in NATIVE or ext in VECTOR:
        return path
    reader = QImageReader(path)
    reader.setAutoTransform(True)  # photos keep the orientation they were taken in
    image = reader.read()
    if image.isNull():
        raise PdfError(tr("{name} could not be read as an image.", name=os.path.basename(path)))
    return png_bytes(image)


def sources(paths: list[str]) -> list[str | bytes]:
    return [source(path) for path in paths]
