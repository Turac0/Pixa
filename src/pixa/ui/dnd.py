"""What can be dropped on Pixa: PDF and image files, and pages dragged from Pixa.

Pages dragged out of the sidebar travel as a small PDF of their own, so they
can be dropped into another Pixa window, also one of another Pixa process.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field

from PySide6.QtCore import QMimeData
from PySide6.QtGui import QImage

from pixa.ui import imagefiles

PAGES_MIME = "application/x-pixa-pages"  # a PDF with the dragged pages
SOURCE_MIME = "application/x-pixa-source"  # which page list they came from


def new_source_id() -> str:
    return uuid.uuid4().hex


def pages_mime(pdf: bytes, source: str) -> QMimeData:
    mime = QMimeData()
    mime.setData(PAGES_MIME, pdf)
    mime.setData(SOURCE_MIME, source.encode())
    return mime


@dataclass
class Dropped:
    """The usable parts of a drag."""

    pdfs: list[str] = field(default_factory=list)
    images: list[str | bytes] = field(default_factory=list)  # paths, or contents
    pages: bytes | None = None  # pages dragged from Pixa, as a PDF
    source: str = ""  # the page list they came from

    def __bool__(self) -> bool:
        return bool(self.pdfs or self.images or self.pages)

    def from_list(self, source: str) -> bool:
        """True for pages dragged from the page list ``source`` itself."""
        return self.pages is not None and self.source == source


def read(mime: QMimeData) -> Dropped:
    out = Dropped()
    if mime.hasFormat(PAGES_MIME):
        out.pages = bytes(mime.data(PAGES_MIME).data()) or None
        out.source = bytes(mime.data(SOURCE_MIME).data()).decode(errors="ignore")
    for url in mime.urls() if mime.hasUrls() else []:
        path = url.toLocalFile()
        if not path or not os.path.isfile(path):
            continue
        if os.path.splitext(path)[1].lower() == ".pdf":
            out.pdfs.append(path)
        elif imagefiles.is_image(path):
            out.images.append(path)
    return out


def pasted_images(mime: QMimeData | None) -> list[str | bytes]:
    """The images on the clipboard: copied image files (paths, as for a drop),
    else copied pixels (as PNG file contents). Files win: file managers also
    offer the file's icon as an image."""
    if mime is None:
        return []
    files = read(mime).images
    if files or not mime.hasImage():
        return files
    image = mime.imageData()
    if not isinstance(image, QImage) or image.isNull():
        return []
    return [imagefiles.png_bytes(image)]
