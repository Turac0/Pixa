"""The printer driver's own settings window (Windows only).

Qt has no public way to open a printer's "Properties" dialog, so it is called
through winspool directly. The settings Qt understands (paper, orientation,
copies, two-sided, colour) are read back from the driver's DEVMODE and applied
to the QPrinter; settings only the driver knows about stay in that window.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from dataclasses import dataclass

# DEVMODE.dmFields bits
DM_ORIENTATION = 0x1
DM_PAPERSIZE = 0x2
DM_COPIES = 0x100
DM_COLOR = 0x800
DM_DUPLEX = 0x1000
DM_COLLATE = 0x8000
# DocumentProperties modes
DM_OUT_BUFFER = 2
DM_IN_PROMPT = 4
DM_IN_BUFFER = 8
IDOK = 1

DMORIENT_PORTRAIT, DMORIENT_LANDSCAPE = 1, 2
DMCOLOR_MONOCHROME, DMCOLOR_COLOR = 1, 2
DMDUP_SIMPLEX, DMDUP_VERTICAL, DMDUP_HORIZONTAL = 1, 2, 3  # vertical = long edge


class DEVMODEW(ctypes.Structure):
    """The start of DEVMODEW, up to dmCollate (printer variant of the union).
    The driver's buffer is bigger; only these fields are read or written."""

    _fields_ = [
        ("dmDeviceName", ctypes.c_wchar * 32),
        ("dmSpecVersion", wintypes.WORD),
        ("dmDriverVersion", wintypes.WORD),
        ("dmSize", wintypes.WORD),
        ("dmDriverExtra", wintypes.WORD),
        ("dmFields", wintypes.DWORD),
        ("dmOrientation", ctypes.c_short),
        ("dmPaperSize", ctypes.c_short),
        ("dmPaperLength", ctypes.c_short),
        ("dmPaperWidth", ctypes.c_short),
        ("dmScale", ctypes.c_short),
        ("dmCopies", ctypes.c_short),
        ("dmDefaultSource", ctypes.c_short),
        ("dmPrintQuality", ctypes.c_short),
        ("dmColor", ctypes.c_short),
        ("dmDuplex", ctypes.c_short),
        ("dmYResolution", ctypes.c_short),
        ("dmTTOption", ctypes.c_short),
        ("dmCollate", ctypes.c_short),
    ]


@dataclass
class DriverSettings:
    """What the print dialog shows, in the terms the driver uses."""

    paper: int | None = None  # Windows paper id (DMPAPER_*), None to leave as is
    landscape: bool = False
    copies: int = 1
    collate: bool = True
    duplex: int = DMDUP_SIMPLEX
    color: bool = True


def available() -> bool:
    return sys.platform == "win32"


def write_devmode(dm: DEVMODEW, s: DriverSettings) -> None:
    """Put the settings into a DEVMODE, marking which fields are set."""
    fields = DM_ORIENTATION | DM_COPIES | DM_COLLATE | DM_DUPLEX | DM_COLOR
    dm.dmOrientation = DMORIENT_LANDSCAPE if s.landscape else DMORIENT_PORTRAIT
    dm.dmCopies = max(1, s.copies)
    dm.dmCollate = 1 if s.collate else 0
    dm.dmDuplex = s.duplex
    dm.dmColor = DMCOLOR_COLOR if s.color else DMCOLOR_MONOCHROME
    if s.paper:
        dm.dmPaperSize = s.paper
        fields |= DM_PAPERSIZE
    dm.dmFields |= fields


def read_devmode(dm: DEVMODEW, s: DriverSettings) -> DriverSettings:
    """The settings from a DEVMODE; fields the driver didn't set keep ``s``'s value."""
    f = dm.dmFields
    return DriverSettings(
        paper=dm.dmPaperSize if f & DM_PAPERSIZE and dm.dmPaperSize > 0 else s.paper,
        landscape=dm.dmOrientation == DMORIENT_LANDSCAPE if f & DM_ORIENTATION else s.landscape,
        copies=max(1, dm.dmCopies) if f & DM_COPIES else s.copies,
        collate=bool(dm.dmCollate) if f & DM_COLLATE else s.collate,
        duplex=dm.dmDuplex if f & DM_DUPLEX and dm.dmDuplex in (1, 2, 3) else s.duplex,
        color=dm.dmColor != DMCOLOR_MONOCHROME if f & DM_COLOR else s.color,
    )


def show_properties(hwnd: int, printer: str, settings: DriverSettings) -> DriverSettings | None:
    """Open the driver's Properties window for ``printer``, starting from
    ``settings``. Returns the settings chosen there, or None if cancelled or
    the window couldn't be opened."""
    if not available():
        return None
    winspool = ctypes.WinDLL("winspool.drv")
    open_printer = winspool.OpenPrinterW
    open_printer.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.HANDLE), ctypes.c_void_p]
    open_printer.restype = wintypes.BOOL
    close_printer = winspool.ClosePrinter
    close_printer.argtypes = [wintypes.HANDLE]
    document_properties = winspool.DocumentPropertiesW
    document_properties.argtypes = [wintypes.HWND, wintypes.HANDLE, wintypes.LPWSTR,
                                    ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD]
    document_properties.restype = ctypes.c_long

    handle = wintypes.HANDLE()
    if not open_printer(printer, ctypes.byref(handle), None):
        return None
    try:
        size = document_properties(hwnd, handle, printer, None, None, 0)
        if size < ctypes.sizeof(DEVMODEW):
            return None
        buffer = ctypes.create_string_buffer(size)
        if document_properties(hwnd, handle, printer, buffer, None, DM_OUT_BUFFER) < 0:
            return None
        write_devmode(DEVMODEW.from_buffer(buffer), settings)
        chosen = ctypes.create_string_buffer(size)
        result = document_properties(hwnd, handle, printer, chosen, buffer,
                                     DM_IN_BUFFER | DM_OUT_BUFFER | DM_IN_PROMPT)
        if result != IDOK:
            return None
        return read_devmode(DEVMODEW.from_buffer(chosen), settings)
    finally:
        close_printer(handle)
