"""Translations: every text in the app is translated, and the language can be switched."""

import ast
import os
import pathlib
import re

import pytest

from pixa import i18n
from pixa.document import LAYER_MOVES
from pixa.locales import CATALOGS

SRC = pathlib.Path(__file__).resolve().parent.parent / "src" / "pixa"
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _strings(node: ast.AST) -> list[str]:
    """The text constants in ``node``, leaving out ones compared with (``kind == "box"``)."""
    compared = {id(c) for n in ast.walk(node) if isinstance(n, ast.Compare)
                for c in ast.walk(n)}
    return [n.value for n in ast.walk(node) if isinstance(n, ast.Constant)
            and isinstance(n.value, str) and id(n) not in compared]


def _name(func: ast.AST) -> str:
    return func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")


def source_texts() -> dict[str, bool]:
    """Every text the code marks for translation, as a catalog key ("context|text"
    with a context), mapped to whether it has plural forms."""
    found: dict[str, bool] = {}
    for path in SRC.rglob("*.py"):
        if "locales" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            name, args = _name(node.func), node.args
            literal = [a.value if isinstance(a, ast.Constant) and isinstance(a.value, str)
                       else None for a in args]
            if name in ("tr", "N_") and literal and literal[0] is not None:
                context = literal[1] if len(literal) > 1 and literal[1] else ""
                found[f"{context}|{literal[0]}" if context else literal[0]] = False
            elif name == "ntr" and len(literal) >= 2 and literal[0] is not None:
                found[literal[0]] = True
            elif name == "_edit":  # undo labels, shown as "Undo <label>"
                for text in _strings(node):
                    found[f"undo|{text}"] = False
    for label in LAYER_MOVES.values():  # also undo labels: _edit(LAYER_MOVES[how])
        found[f"undo|{label}"] = False
    return found


def _english(key: str) -> str:
    return key.split("|", 1)[1] if "|" in key else key


@pytest.fixture(autouse=True)
def english_afterwards():
    yield
    i18n.set_language(i18n.DEFAULT)


@pytest.mark.parametrize("code", sorted(CATALOGS))
def test_every_text_is_translated(code):
    messages = CATALOGS[code].MESSAGES
    missing = sorted(key for key in source_texts() if key not in messages)
    assert not missing, f"{code}: no translation for {missing}"


@pytest.mark.parametrize("code", sorted(CATALOGS))
def test_no_unused_translations(code):
    unused = sorted(set(CATALOGS[code].MESSAGES) - set(source_texts()))
    assert not unused, f"{code}: translations of texts the app doesn't use: {unused}"


@pytest.mark.parametrize("code", sorted(CATALOGS))
def test_translations_keep_placeholders_and_plurals(code):
    module = CATALOGS[code]
    plural_counts = {module.plural(n) for n in range(200)}
    for key, plural in source_texts().items():
        value = module.MESSAGES.get(key)
        if value is None:
            continue
        expected = set(PLACEHOLDER.findall(_english(key)))
        if plural:
            expected.add("n")
            assert isinstance(value, tuple) and len(value) == len(plural_counts), key
            forms = value
        else:
            assert isinstance(value, str), key
            forms = (value,)
        for form in forms:
            # Every value is filled in; a form may leave out {n} (like "one page").
            assert set(PLACEHOLDER.findall(form)) <= expected, (key, form)
            assert expected - {"n"} <= set(PLACEHOLDER.findall(form)), (key, form)


def test_tr_and_ntr():
    i18n.set_language("sv")
    assert i18n.tr("Save") == "Spara"
    assert i18n.tr("Saved {name}", name="a.pdf") == "Sparade a.pdf"
    assert i18n.tr("Rotate page", "undo") == "rotera sida"
    assert i18n.tr("Text nobody translated") == "Text nobody translated"
    assert i18n.ntr("Deleted {n} page. Undo to restore.",
                    "Deleted {n} pages. Undo to restore.", 3).startswith("Tog bort 3 sidor")
    i18n.set_language("xx")  # a language Pixa doesn't have
    assert i18n.language() == "en" and i18n.tr("Save") == "Save"
    assert i18n.ntr("Deleted {n} page. Undo to restore.",
                    "Deleted {n} pages. Undo to restore.", 1) == "Deleted 1 page. Undo to restore."


def test_resolve_follows_the_system_and_falls_back_to_english(monkeypatch):
    assert i18n.resolve("sv") == "sv" and i18n.resolve("en") == "en"
    for languages, expected in ((["sv-SE", "en-US"], "sv"), (["de-DE", "sv-SE"], "sv"),
                                (["de-DE", "fr-FR"], "en"), (["en-GB"], "en"), ([], "en")):
        monkeypatch.setattr(i18n, "preferred_languages", lambda langs=languages: langs)
        assert i18n.resolve(i18n.SYSTEM) == expected
        assert i18n.resolve(None) == expected


def test_preferred_languages_skip_c_and_ask_macos(monkeypatch):
    """With LANG unset or "C.UTF-8" (apps opened from the Finder, many terminals)
    Qt answers "C"; on macOS the system's own list is used."""
    from PySide6.QtCore import QLocale

    class Locale:
        def uiLanguages(self):  # noqa: N802
            return ["C"]

    monkeypatch.setattr(QLocale, "system", staticmethod(Locale))
    monkeypatch.setattr(i18n.sys, "platform", "darwin")
    monkeypatch.setattr(i18n, "_mac_languages", lambda: ["sv-SE", "en-US"])
    assert i18n.preferred_languages() == ["sv-SE", "en-US"]
    assert i18n.system_language() == "sv"
    monkeypatch.setattr(i18n.sys, "platform", "linux")
    assert i18n.preferred_languages() == [] and i18n.system_language() == "en"


@pytest.mark.skipif(i18n.sys.platform != "darwin", reason="macOS only")
def test_mac_languages_reads_the_system_list():
    languages = i18n._mac_languages()
    assert languages and all(isinstance(x, str) and x for x in languages)


# ------------------------------------------------------------------ the window
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def window(tmp_path, sample_pdf):
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from pixa.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    w = MainWindow()
    w.show()
    assert w.open_path(sample_pdf, ask_save=False)
    app.processEvents()
    windows = [w]
    yield windows
    from shiboken6 import isValid

    for w in windows:
        if not isValid(w):  # replaced by a language switch, and deleted since
            continue
        if w.doc:
            w.doc.dirty = False
        w.close()
    i18n.install_qt_translations(app)


def test_switching_language_keeps_the_document(window):
    from pixa.ui.main_window import _windows

    old = window[0]
    assert old.a_save.text() == "Save"
    old.doc.rotate_pages([0], 90)
    doc = old.doc
    new = old.set_language("sv")
    window.append(new)
    assert new is not old and new in _windows and not old.isVisible()
    assert new.doc is doc and doc.dirty and new.a_save.text() == "Spara"
    assert new.a_undo.text() == "Ångra rotera sida"
    assert old._document_changed not in doc.listeners
    assert new.settings.value("language") == "sv"
    assert new.language_actions["sv"].isChecked()
    # Choosing the language already in use changes nothing.
    assert new.set_language("sv") is new
    back = new.set_language("en")
    window.append(back)
    assert back.doc is doc and back.a_undo.text() == "Undo Rotate page"
    _windows.clear()


def _fits(window, app) -> None:
    """Every tool and selection: the panel's contents fit beside its scroll bar."""
    from PySide6.QtTest import QTest

    from pixa.ui.page_view import Tool

    insp = window.inspector
    widths = set()
    for tool in Tool:
        for selected in (None, "image", "text", "box", "highlight"):
            insp.set_tool(tool)
            insp.set_selection_state(False, selected)
            QTest.qWait(20)
            room = (insp._scroll.viewport().width()
                    - (0 if insp._scroll.verticalScrollBar().isVisible()
                       else insp._scroll.verticalScrollBar().sizeHint().width()))
            assert insp._content.minimumSizeHint().width() <= room, (tool, selected)
            widths.add(insp.width())
    return widths


def test_side_panel_fits_longer_translations(window):
    """Swedish buttons are longer than English ones: the panel widens instead of cutting
    them off, keeps one width whatever the tool, and stays as it was in English."""
    from PySide6.QtWidgets import QApplication

    from pixa.document import DocFace
    from pixa.ui import inspector
    from pixa.ui.main_window import _windows

    app = QApplication.instance()
    assert _fits(window[0], app) == {inspector.WIDTH}
    sv = window[0].set_language("sv")
    window.append(sv)
    # A long font name in the document is cut short instead of widening the panel.
    sv.inspector.set_document_fonts([DocFace("SourceSansPro-SemiboldItalicExtended Condensed",
                                             "SourceSansPro", 600, True, "helv", "x")])
    widths = _fits(sv, app)
    assert len(widths) == 1 and widths.pop() > inspector.WIDTH
    _windows.clear()
