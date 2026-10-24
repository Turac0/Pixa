# Pixa

A clean, modern PDF editor that runs entirely on your machine. It works on macOS, Windows and Linux and ships as a single executable.

## Features

- **Edit existing text**: hover a line to highlight it, click it, type, and click outside the text when you're done (or press Ctrl+Enter). Enter starts a new line. Pixa keeps the original font whenever it can (see below), and you can change the font, size, bold/italic/underline and colour in the right pane without leaving the text.
- **Move text**: with the Select tool, click a line of text (the same lines the Edit text tool picks) and drag it. Arrow keys nudge it by 1 pt, or 10 pt with Shift. Delete removes it. Mixed fonts and colours inside the line are kept.
- **Select several things**: Shift-click (or Ctrl-click) to add text, images, highlights and boxes to the selection, or drag across an empty spot of a page to select everything the rectangle touches. Drag any of them or use the arrow keys to move them all together, and Delete removes them, each as one undo step.
- **Add text** anywhere on a page, with a font family, size, bold/italic and colour. Enter starts a new line; click outside the text to place it.
- **Images**: add PNG, JPG, WebP, SVG (kept as sharp vector graphics), icons and more (HEIC and AVIF where your system's Qt can read them), or select any image already on a page. Drag to move it, drag a corner to resize (Shift for free aspect), and drag the round handle to rotate (snaps to 15°, Shift for free). Arrow keys nudge it, the right pane rotates it by 90°, and Delete removes it. Moving an image keeps its quality and its place in front of or behind other content.
- **Highlight**: drag across text like with a marker, in any colour. Going over text again replaces the earlier highlight instead of darkening it. The highlight snaps to whole words and follows the text over several lines; where there is no text (a scan, a picture) the dragged area is highlighted. Highlights are standard PDF annotations, so other viewers show them too.
- **Boxes**: drag to draw a rectangle with the border width, border colour and fill you choose (or no fill). Boxes are drawn on the page like text and images, so whatever you place last is on top: a white box hides what is under it, and text added afterwards sits on the box. Click a box with the Select tool to change it: drag it to move it, drag a corner to resize it (Shift keeps the proportions), nudge it with the arrow keys, change its border and fill in the right pane, or delete it. A selected highlight can be recoloured the same way. Your highlight colour and box style are remembered between sessions.
- **Sizes in steps**: the − and + buttons beside the font size and border width jump through the common sizes (…, 10, 11, 12, 14, 16, 18, 24, …); any other value can still be typed.
- **Layers**: whatever is placed last lies on top, and you can change that. Select a text box, image or box and choose **Bring to front**, **Bring forward**, **Send backward** or **Send to back** (right-click it, use Edit → Arrange, the buttons in the right pane, or the shortcuts below). Forward and backward pass the nearest thing it overlaps, so you can put a picture behind a paragraph but keep it in front of a coloured box. Highlights are annotations and always lie on top.
- **Pages**: rotate, delete, move up/down, drag & drop to reorder in the sidebar, insert blank pages, and insert or merge pages from other PDFs. Multi-select works with Ctrl/Shift-click.
- **Drag & drop**: drop PDFs and images from your file manager. With no document open, a dropped PDF opens (and dropped images become a new PDF). With a document open, a PDF dropped on a page is inserted after it (or before it, on its top half), and in the sidebar exactly where you drop it. An image dropped on a page is placed where you drop it, selected so you can adjust it right away; dropped in the sidebar it becomes a page of its own. Drag pages from the sidebar of one Pixa window to another (also between separate Pixa windows) to copy them there.
- **Print** (Ctrl+P): Pixa's own print dialog, with a live preview. Choose the printer (or save as a PDF file), copies, grayscale, all pages, ranges like `1-3, 5`, the current page or the pages selected in the sidebar; fit to paper, actual size, shrink oversized pages or a custom scale; paper size, two-sided printing and orientation (Auto turns landscape pages to suit the paper). On Windows, **Properties…** opens the printer's own settings. **Print Preview** (Ctrl+Shift+P, File menu) shows the pages as they will print, with zoom, page, orientation and all-pages controls, and its Print button goes on to the print dialog.
- Unlimited-feeling **undo/redo** (last 50 steps), continuous scrolling, zoom and fit-to-width.
- **Safe saving**: the first time you press Save on a file you opened, Pixa asks whether to overwrite the original or save a copy. You can turn this off with "Don't ask again" and back on under File → Ask Before Overwriting Originals.
- Light and dark themes (by default it follows the OS), recent files, and support for password-protected PDFs.
- **Automatic updates**: Pixa checks for a new version when it starts and shows what's new. On Windows, **Install and Restart** downloads the installer, verifies its checksum and installs it. **Help → Check for Updates…** looks right away, and **Help → Check for Updates Automatically** turns the check off.
- **English and Swedish.** Pixa uses your system's language when it has it, and English otherwise. Choose another under **View → Language**; the window switches right away and keeps your document and its undo history.

## Keyboard shortcuts

| Action | Shortcut |
| --- | --- |
| Open / Save / Save As | Ctrl+O / Ctrl+S / Ctrl+Shift+S |
| Print / Print preview | Ctrl+P / Ctrl+Shift+P |
| Undo / Redo | Ctrl+Z / Ctrl+Shift+Z (or Ctrl+Y) |
| Tools: Select / Edit text / Add text / Add image / Highlight / Add box | V / E / T / I / H / B |
| Rotate page left / right | Ctrl+[ / Ctrl+] |
| Move page up / down | Ctrl+Shift+↑ / Ctrl+Shift+↓ |
| Delete page | Ctrl+Shift+D (or Delete in the sidebar) |
| Add to the selection | Shift-click (or Ctrl-click) |
| Delete selected image, text, highlight or box | Delete |
| Nudge selected image, text or box | Arrow keys (Shift = 10 pt) |
| Finish editing text | Click outside it (or Ctrl+Enter) |
| Bring forward / Send backward | Ctrl+Page Up / Ctrl+Page Down |
| Bring to front / Send to back | Ctrl+Shift+Page Up / Ctrl+Shift+Page Down |
| Zoom in / out / fit width | Ctrl++ / Ctrl+- / Ctrl+0 (or Ctrl+scroll, or pinch on a touchpad) |

On macOS, use ⌘ instead of Ctrl.

## Run from source

Requires Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m pixa                     # or: pixa path/to/file.pdf
```

## Translations

Text in the code is written in English and wrapped in `tr()` (or `ntr()` when it depends on a number) from `pixa.i18n`. Each other language is one file in `src/pixa/locales/` that maps the English text to its translation. To add a language:

1. Copy `src/pixa/locales/sv.py` to `<code>.py`, using the two-letter ISO 639-1 code (for example `de.py`), set `NAME` to the language's own name, adapt `plural()` to its plural forms, and translate `MESSAGES`.
2. Add it to `CATALOGS` in `src/pixa/locales/__init__.py` and to `CFBundleLocalizations` in `packaging/pixa.spec`.

`tests/test_i18n.py` fails when a text in the app has no translation in some language, when a translation is no longer used, or when a translation drops a `{placeholder}`, so run the tests after changing text. Qt's own dialogs and buttons (Cancel, the colour picker, …) use the translations that ship with Qt.

## Build a standalone executable

```bash
pip install -e ".[dev]"
pyinstaller --noconfirm packaging/pixa.spec
```

| OS | Output |
| --- | --- |
| Windows | `dist/Pixa/` (folder with `Pixa.exe`) |
| Linux | `dist/Pixa` (single file) |
| macOS | `dist/Pixa.app` |

PyInstaller can't cross-compile, so build on each OS. The GitHub Actions workflow in `.github/workflows/build.yml` does this for you. When you push a `v*` tag (or start it manually from the Actions tab) it builds a Windows installer named after the version in `pyproject.toml` (for example `Pixa-windows-x86_64-0.5.3-setup.exe`). You can download it from the run's **Artifacts**, whose zip files carry the version too. A tag also attaches it to a GitHub release. The macOS disk image (`Pixa-macos-arm64-<version>.dmg`) and Linux tarball jobs are in the workflow but commented out; uncomment them in the build matrix to build those too.

The workflow builds with a read-only token. Only the final release job can write to the repository, and it runs no installed packages. Every action is pinned to a commit, and Dependabot (`.github/dependabot.yml`) proposes updates to those pins.

### Publishing an update

Installed copies of Pixa look for new versions in this repository's [latest release](https://github.com/Turac0/Pixa/releases/latest). To release:

1. Bump the version (`pyproject.toml`, `src/pixa/__init__.py`, `packaging/pixa.spec`) and describe the changes under `## <version>` in `CHANGELOG.md`.
2. Merge to `main`, then tag it: `git tag v0.6.0 && git push origin v0.6.0`. The tag must match the version.

CI then publishes the Windows installer, its `.sha256` checksum and that changelog section as a GitHub release. Pixa shows the notes in its update dialog and checks the download against the checksum before installing.

The Windows build is a folder rather than a single self-extracting `.exe`, because those trip antivirus tools. To build the installer yourself, install [Inno Setup](https://jrsoftware.org/isinfo.php) and run `iscc /DAppVersion=0.1.0 packaging\pixa.iss` after PyInstaller.

> **macOS:** open the `.dmg` and drag Pixa to Applications. The app isn't code-signed, so the first time you open it, right-click → **Open** (or run `xattr -dr com.apple.quarantine /Applications/Pixa.app`).
>
> **Windows:** the installer isn't code-signed either, so SmartScreen may show "Windows protected your PC"; choose **More info → Run anyway**.
>
> **Linux:** the binary needs the usual desktop libraries (X11/Wayland, fontconfig, EGL). Every desktop distribution already has them.

Do the build in a clean virtualenv. Packages like numpy or Pillow sitting in your environment can bloat the executable; the spec excludes the common ones.

## Development

```bash
ruff check src tests packaging
QT_QPA_PLATFORM=offscreen pytest
python packaging/make_icons.py     # regenerate app icons
```

Project layout:

```
src/pixa/
  document.py          PDF model: every edit lives here, Qt-free, unit tested
  layers.py            reads a page's drawing order (for bringing things to front/back)
  app.py               QApplication entry point
  ui/main_window.py    window, toolbar, menus, file handling
  ui/page_view.py      page canvas, zoom, inline text editor, image placement
  ui/thumbnails.py     sidebar thumbnails with drag & drop reordering
  ui/inspector.py      right panel: text style, image, layer and page actions
  ui/dnd.py            what can be dropped: PDF/image files and pages from Pixa
  ui/printing.py       printing pages at printer resolution
  ui/print_dialog.py   print dialog with live preview
  ui/winprint.py       the printer's Properties window (Windows)
  ui/print_preview.py  print preview dialog
  ui/theme.py          light/dark palettes and stylesheet
  ui/icons.py          inline SVG icons and the app icon
packaging/             PyInstaller spec, launcher, icons
tests/                 model tests + headless GUI tests
```

Undo works by snapshot. Before each change, `PdfDocument` serializes the document in memory, and undo restores that snapshot. This makes every operation reliably undoable, including redactions that can't be reversed in place.

## How text editing works, and its limits

PDFs don't store paragraphs. They store positioned runs of glyphs. To edit a line, Pixa removes the original glyphs with a narrow redaction band, which leaves images, vector graphics and neighbouring lines untouched. It then writes the new text at the same baseline.

**Keeping the font.** PDFs usually embed only the characters a document originally used (a font "subset"). For the new text, Pixa picks the first option that works:

1. **The PDF's own font, using its existing glyphs.** If every character you typed is already in the subset, the edit looks identical and adds nothing to the file. This covers typo fixes, changed numbers and dates, and rearranged words.
2. **The same font installed on your computer**, e.g. Arial, Calibri or Garamond. Pixa embeds it and keeps only the used glyphs when saving. If the exact font isn't installed, a font with identical character widths is used when available (Liberation Sans for Arial, Carlito for Calibri, …).
3. **Only for characters nothing else can draw**: if the document's font has some of the characters you typed but neither it nor your computer has the rest, only the missing characters use a similar standard font (sans/serif/mono and weight matched), and the rest of the line keeps the original font. The status bar names those characters.

**The font picker** lists the font faces used in the open document, with their real weights (e.g. "Inter", "Inter SemiBold"), each previewed in its own typeface when it's installed, followed by the standard Helvetica, Times and Courier. When you start editing a line, its face is selected automatically and the text box previews it in that exact face and weight, so you always see what you're working with. **B** and **I** switch to the document's bold/italic face of the same family.

Changing only the size, colour or underline keeps the original font. Picking another document font, or toggling **B**/**I**, uses that font's matching face from the document, by the same rules as above.

**Underline and strikethrough** are separate lines in a PDF. Pixa detects them, stretches or shrinks them to the new text, moves them with a text box, and lets you toggle underline with the **U** button.

**Limits:**
- Editing works one line at a time; paragraphs don't reflow.
- Scanned (image-only) PDFs contain no text to edit, and OCR isn't included.
- A few images can't be moved: images stored inline in the page or inside form objects. Pixa says so when that happens. The same goes for changing their layer.
- Changing the layer of a text box redraws its text, the same way moving it does. Editing or moving a text box later puts it on top again.

## License

Pixa is free software under the [GNU Affero General Public License v3.0 or later](LICENSE). It is built on [PyMuPDF](https://pymupdf.readthedocs.io/) (AGPL-3.0) and Qt for Python ([PySide6](https://doc.qt.io/qtforpython-6/), LGPL-3.0).
