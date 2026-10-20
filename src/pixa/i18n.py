"""Translations of Pixa's user interface.

Text is written in English in the code and wrapped in :func:`tr`, or :func:`ntr`
when it depends on a number. Every other language is a module in
``pixa.locales`` whose ``MESSAGES`` map the English text to the translation (see
``pixa/locales/sv.py``). Text that has no translation is shown in English.

Values go into the text by name, so a translation can put them where its
grammar wants them: ``tr("Saved {name}", name=...)``. A ``context`` tells apart
the same English text used in two ways; its translation is looked up as
``"context|text"`` first, then as plain ``"text"``.

This module doesn't need Qt, so the document model can use it too.
"""

from __future__ import annotations

import sys
from collections.abc import Callable

from pixa.locales import CATALOGS

DEFAULT = "en"
# Every language Pixa speaks, by code, each named in its own language.
LANGUAGES = {DEFAULT: "English", **{code: module.NAME for code, module in CATALOGS.items()}}
SYSTEM = "system"  # the language setting that follows the operating system


def _english_plural(n: int) -> int:
    return 0 if n == 1 else 1


_language = DEFAULT
_messages: dict[str, str | tuple[str, ...]] = {}
_plural: Callable[[int], int] = _english_plural
_qt_translators: list = []


def N_(text: str, context: str = "") -> str:  # noqa: N802 - the usual gettext name
    """Mark ``text`` for translation where it is defined; :func:`tr` translates it
    where it is shown (for text kept in constants)."""
    return text


def tr(text: str, context: str = "", **values) -> str:
    """``text`` in the current language, with ``values`` filled in."""
    found = _messages.get(f"{context}|{text}") if context else None
    if found is None:
        found = _messages.get(text, text)
    if isinstance(found, tuple):  # a plural entry used for a single form
        found = found[0]
    return found.format(**values) if values else found


def ntr(singular: str, plural: str, n: int, **values) -> str:
    """The form of a text for the number ``n``, which is filled in as ``{n}``.

    A translation gives every form its language has, as a tuple, in the order of
    its ``plural(n)`` function (one, then other, for Swedish as for English).
    """
    forms = _messages.get(singular)
    if isinstance(forms, tuple) and forms:
        text = forms[min(max(_plural(n), 0), len(forms) - 1)]
    else:
        text = singular if _english_plural(n) == 0 else plural
    return text.format(n=n, **values)


# ------------------------------------------------------------------ choosing
def language() -> str:
    """The code of the language in use."""
    return _language


def _mac_languages() -> list[str]:
    """The languages chosen in macOS's Language & Region settings, most preferred first.

    Asked of the system directly: Qt goes by the LANG variable instead, which is
    unset for apps opened from the Finder and often "C.UTF-8" in a terminal.
    """
    import ctypes

    cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    cf.CFLocaleCopyPreferredLanguages.restype = ctypes.c_void_p
    cf.CFArrayGetCount.argtypes = [ctypes.c_void_p]
    cf.CFArrayGetCount.restype = ctypes.c_long
    cf.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]
    cf.CFArrayGetValueAtIndex.restype = ctypes.c_void_p
    cf.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long,
                                      ctypes.c_uint32]
    cf.CFStringGetCString.restype = ctypes.c_bool
    cf.CFRelease.argtypes = [ctypes.c_void_p]
    utf8 = 0x08000100  # kCFStringEncodingUTF8
    languages = cf.CFLocaleCopyPreferredLanguages()
    if not languages:
        return []
    try:
        found = []
        buffer = ctypes.create_string_buffer(128)
        for i in range(cf.CFArrayGetCount(languages)):
            item = cf.CFArrayGetValueAtIndex(languages, i)
            if cf.CFStringGetCString(item, buffer, len(buffer), utf8):
                found.append(buffer.value.decode())
        return found
    finally:
        cf.CFRelease(languages)


def preferred_languages() -> list[str]:
    """The system's preferred languages ("sv-SE", "en", ...), most preferred first."""
    from PySide6.QtCore import QLocale

    found = []
    if sys.platform == "darwin":
        try:
            found += _mac_languages()
        except (OSError, AttributeError):
            pass  # fall back on Qt's answer
    # "C" and "POSIX" mean no language was set, not a language.
    found += [name for name in QLocale.system().uiLanguages() if name not in ("C", "POSIX")]
    return found


def system_language() -> str:
    """The first of the system's preferred languages that Pixa has, else English."""
    for name in preferred_languages():
        code = name.replace("_", "-").split("-")[0].lower()
        if code in LANGUAGES:
            return code
    return DEFAULT


def resolve(setting: str | None) -> str:
    """The language for a setting: a language code, or anything else for the system's."""
    return setting if setting in LANGUAGES else system_language()


def set_language(code: str) -> None:
    """Show text in ``code`` from now on (English for a language Pixa doesn't have)."""
    global _language, _messages, _plural
    module = CATALOGS.get(code)
    _language = code if module is not None else DEFAULT
    _messages = dict(module.MESSAGES) if module is not None else {}
    _plural = getattr(module, "plural", _english_plural)


def install_qt_translations(app) -> None:
    """Load Qt's own translations of its standard dialogs and buttons for the
    current language (Cancel, Save, the colour and file dialogs, ...)."""
    from PySide6.QtCore import QLibraryInfo, QTranslator

    for translator in _qt_translators:
        app.removeTranslator(translator)
    _qt_translators.clear()
    if _language == DEFAULT:
        return
    folder = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    translator = QTranslator(app)
    if translator.load(f"qtbase_{_language}", folder):
        app.installTranslator(translator)
        _qt_translators.append(translator)
