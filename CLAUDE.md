# Pixa

A local PDF editor: PySide6 (Qt) UI on top of PyMuPDF. Python 3.10+, packaged with PyInstaller for macOS, Windows and Linux. The user-facing feature list and keyboard shortcuts are in README.md.

## Commands

```bash
.venv/bin/ruff check src tests                      # lint (line length 100)
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -p no:cacheprovider \
  --deselect tests/test_gui.py::test_editor_survives_style_changes_in_inspector
.venv/bin/python -m pixa [file.pdf]                 # run from source
.venv/bin/python -m pixa file.pdf --smoke-test      # start, render, quit (used by CI)
pyinstaller --noconfirm packaging/pixa.spec         # standalone build
```

Known test problems that predate current work, so don't chase them as regressions:
- `test_editor_survives_style_changes_in_inspector` hangs forever under the offscreen platform on macOS (the combo popup). Always deselect it, or the whole run hangs with no output.
- `tests/test_gui.py` crashes when the process exits (exit code 139) even though every test passes. Read the pass/fail summary, not the exit code.
- Some font tests skip unless the DejaVu or Inter fonts are installed.

## Layout

- `src/pixa/document.py`: the document model (`PdfDocument`). It has no Qt dependency. Every change goes through `with self._edit("<label>")`, which takes an undo snapshot. The label is shown as "Undo <label>".
- `src/pixa/ui/main_window.py`: menus, actions, file handling, drag and drop, and the language switch.
- `src/pixa/ui/page_view.py`: the page canvas (editing, selection, tools). `inspector.py` is the right-hand panel, `thumbnails.py` the page sidebar.
- `src/pixa/ui/print_dialog.py`, `print_preview.py`, `printing.py`: Pixa's own print dialog and preview. `winprint.py` opens the Windows printer Properties dialog through ctypes.
- `src/pixa/updates.py` (network, no Qt) and `src/pixa/ui/updater.py` (UI): update checks against this repo's latest GitHub release.
- `src/pixa/fonts.py`, `pdffont.py`, `layers.py`: font matching, encoding text into existing PDF fonts, and content-stream layer order.

## Translations (i18n)

All user-visible text is written in English and wrapped with helpers from `pixa.i18n`:
- `tr("Saved {name}", name=...)`: named placeholders only, never f-strings, so translators can reorder words.
- `ntr(singular, plural, n, ...)`: text that depends on a number; `{n}` is filled in.
- `N_("...")`: marks text stored in constants or dicts; call `tr()` on it where it is displayed.
- `tr(text, "context")`: separates the same English text used in two senses. The catalog key is `"context|text"`. Examples: `"noun|Highlight"`, and `"undo|..."` for undo labels (lower-case in Swedish, shown after "Ångra").
- Build whole sentences per case (one string each for image, text box and box) instead of inserting nouns into a template. Swedish noun genders break templates.

Catalogs live in `src/pixa/locales/<code>.py` (`NAME`, `MESSAGES`, `plural()`), are registered in `locales/__init__.py` (`CATALOGS`), and are listed in `CFBundleLocalizations` in `packaging/pixa.spec`. Whenever you add or change English text, update `sv.py` in the same change. `tests/test_i18n.py` reads the source's AST and fails on missing, unused or placeholder-mismatched translations. It finds literals in `tr`, `ntr`, `N_` and `_edit(...)` calls, so pass literals there, not variables.

Module-level constants must not call `tr()`, because they are evaluated at import time before the language is set. Use `N_()` for them. Switching the language rebuilds `MainWindow` (see `MainWindow.set_language`), so text only needs to be translated when the widget is built. No live retranslation is needed.

Tests construct `MainWindow` without calling `i18n.set_language`, so they run in English whatever the OS language is. Keep it that way: string assertions in the tests depend on it.

## Conventions

- Settings: `QSettings(QSettings.defaultFormat(), QSettings.Scope.UserScope, "Pixa", "Pixa")`, spelled out so the tests' INI redirect works.
- Errors meant for the user are raised as `PdfError(tr(...))` and shown with `MainWindow.show_error`. The tests replace that method with a list to record them.
- The code uses British spelling ("colour") in identifiers and English UI text.
- Comments explain why, briefly. Docstrings are plain sentences.

## Branches and releases

- Where the work is committed depends on where Claude runs (cloud sessions have the environment variable `CLAUDE_CODE_REMOTE` set; local ones don't):
  - **Local:** commit straight to the branch that is checked out. Don't create branches or open PRs unless asked.
  - **Cloud:** work on a new branch and open a pull request **into `dev`**, never into `main` and never straight onto `dev`. If `gh` isn't available, give the user the compare link (https://github.com/Turac0/Pixa/compare/dev...<branch>).
- `dev` is merged into `main` for releases (see below), by the user. Don't merge it yourself. The `gh` CLI isn't installed on the user's Mac.
- Release: bump the version in `pyproject.toml`, `src/pixa/__init__.py` and `packaging/pixa.spec`, and add a `## <version>` section to `CHANGELOG.md`. CI copies that section into the release notes. Merge to `main`, then push the tag `v<version>`. CI publishes the Windows installer, its checksum and the notes as a GitHub release here.
- Changelog entries are written for users: a bold lead-in, then what changed and where to find it.
