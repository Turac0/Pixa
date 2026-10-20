"""Main application window."""

from __future__ import annotations

import dataclasses
import os

import pymupdf as fitz
from PySide6.QtCore import QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QColor, QKeySequence
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from pixa import __version__, i18n
from pixa.document import LAYER_MOVES, BoxStyle, PdfDocument, PdfError, TextStyle
from pixa.i18n import N_, ntr, tr
from pixa.ui import dnd, icons, imagefiles, printing, theme, widgets
from pixa.ui.inspector import Inspector
from pixa.ui.page_view import PageView, Tool
from pixa.ui.print_dialog import PrintDialog
from pixa.ui.print_preview import PrintPreview
from pixa.ui.thumbnails import ThumbnailList
from pixa.ui.updater import Updater

PDF_FILTER = N_("PDF documents (*.pdf)")
MAX_RECENT = 8
THEME_NAMES = {"system": N_("system"), "light": N_("light"), "dark": N_("dark")}
# Windows made by switching the language, kept alive here (see MainWindow.set_language).
_windows: list[MainWindow] = []


class Welcome(QWidget):
    def __init__(self, on_open, on_recent) -> None:
        super().__init__()
        self.setObjectName("Welcome")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.on_recent = on_recent
        outer = QVBoxLayout(self)
        outer.addStretch(1)
        zone = QFrame()
        zone.setObjectName("DropZone")
        zone.setFixedWidth(460)
        zl = QVBoxLayout(zone)
        zl.setContentsMargins(36, 40, 36, 36)
        zl.setSpacing(12)
        self.logo = QLabel()
        self.logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel("Pixa")
        title.setObjectName("WelcomeTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text = QLabel(tr("Open a PDF or drop it here to start editing. Dropped images "
                         "become a new PDF."))
        text.setWordWrap(True)
        text.setObjectName("WelcomeText")
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        button = QPushButton(tr("Open PDF…"))
        button.setProperty("primary", True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(on_open)
        button.setFixedWidth(180)
        self.recent_box = QVBoxLayout()
        self.recent_box.setSpacing(2)
        zl.addWidget(self.logo)
        zl.addWidget(title)
        zl.addWidget(text)
        zl.addSpacing(8)
        zl.addWidget(button, 0, Qt.AlignmentFlag.AlignHCenter)
        zl.addSpacing(8)
        zl.addLayout(self.recent_box)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(zone)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(2)

    def set_logo(self, color: str) -> None:
        self.logo.setPixmap(icons.pixmap("file", color, 56))

    def set_recent(self, paths: list[str]) -> None:
        while self.recent_box.count():
            w = self.recent_box.takeAt(0).widget()
            if w:
                w.deleteLater()
        existing = [p for p in paths if os.path.exists(p)][:5]
        if not existing:
            return
        label = QLabel(tr("Recent").upper())
        label.setProperty("role", "heading")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.recent_box.addWidget(label)
        for path in existing:
            btn = QPushButton(os.path.basename(path))
            btn.setToolTip(path)
            btn.setFlat(True)
            btn.setObjectName("RecentLink")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, p=path: self.on_recent(p))
            self.recent_box.addWidget(btn)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        # Spelled out so QSettings.setDefaultFormat() is honoured (the short
        # constructor always uses the native store, also in the tests).
        self.settings = QSettings(QSettings.defaultFormat(), QSettings.Scope.UserScope,
                                  "Pixa", "Pixa")
        self.doc: PdfDocument | None = None
        self._last_revision = -1
        self._last_count = -1
        self.add_text_style = TextStyle()
        self._overwrite_confirmed = False
        self.setAcceptDrops(True)
        self.resize(1280, 860)
        self.setMinimumSize(QSize(820, 560))

        mode = self.settings.value("theme", "system")
        self.theme_mode = mode if mode in ("system", "light", "dark") else "system"
        self.theme = self._resolve_theme()

        # ---- widgets
        self.view = PageView()
        self.thumbs = ThumbnailList()
        self.inspector = Inspector()
        self.welcome = Welcome(self.open_dialog, self.open_path)
        editor = QWidget()
        el = QHBoxLayout(editor)
        el.setContentsMargins(0, 0, 0, 0)
        el.setSpacing(0)
        el.addWidget(self.thumbs)
        el.addWidget(self.view, 1)
        el.addWidget(self.inspector)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.welcome)
        self.stack.addWidget(editor)
        self.setCentralWidget(self.stack)

        self.page_status = QLabel()
        self.statusBar().addPermanentWidget(self.page_status)
        self.statusBar().setSizeGripEnabled(False)

        self.updater = Updater(self)
        self._create_actions()
        self.a_confirm_overwrite.setChecked(self.confirm_overwrite)
        self.a_auto_update.setChecked(self.updater.automatic)
        self._create_toolbar()
        self._create_menus()
        self._connect()
        self._restore_markup_styles()
        self.apply_theme()
        self._update_ui()
        self.welcome.set_recent(self.recent_files())

    # ------------------------------------------------------------------ setup
    def _act(self, text, slot=None, shortcut=None, icon_name=None, checkable=False, tip=None):
        action = QAction(text, self)
        if shortcut:
            action.setShortcuts(shortcut if isinstance(shortcut, list) else [shortcut])
        if slot:
            action.triggered.connect(slot)
        action.setCheckable(checkable)
        action.setData(icon_name)
        tip = tip or text.replace("…", "")
        if action.shortcut().toString():
            tip += f"  ({action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)})"
        action.setToolTip(tip)
        return action

    def _create_actions(self) -> None:
        K = QKeySequence.StandardKey  # noqa: N806
        self.a_open = self._act(tr("Open…"), self.open_dialog, K.Open, "open")
        self.a_save = self._act(tr("Save"), self.save, K.Save, "save")
        self.a_save_as = self._act(tr("Save As…"), self.save_as, K.SaveAs)
        self.a_confirm_overwrite = self._act(
            tr("Ask Before Overwriting Originals"), self.set_confirm_overwrite, checkable=True
        )
        self.a_print = self._act(tr("Print…"), self.print_document, K.Print, "print")
        self.a_preview = self._act(tr("Print Preview…"), self.print_preview, "Ctrl+Shift+P",
                                   "preview", tip=tr("See the pages as they will print"))
        self.a_close = self._act(tr("Close Document"), self.close_document, K.Close)
        self.a_quit = self._act(tr("Quit"), self.close, K.Quit)
        self.a_quit.setMenuRole(QAction.MenuRole.QuitRole)
        self.a_undo = self._act(tr("Undo"), self.undo, K.Undo, "undo")
        self.a_redo = self._act(tr("Redo"), self.redo, [QKeySequence(K.Redo),
                                                   QKeySequence("Ctrl+Y")], "redo")
        self.a_paste = self._act(tr("Paste"), self.paste, K.Paste,
                                 tip=tr("Paste an image from the clipboard"))
        self.a_delete = self._act(tr("Delete"), self.delete_selection,
                                  [QKeySequence(Qt.Key.Key_Delete),
                                   QKeySequence(Qt.Key.Key_Backspace)])
        self.a_delete.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)

        self.tool_group = QActionGroup(self)
        self.tool_actions: dict[Tool, QAction] = {}
        for tool, label, key, icon_name in (
            (Tool.SELECT, N_("Select"), "V", "select"),
            (Tool.EDIT_TEXT, N_("Edit text"), "E", "edit-text"),
            (Tool.ADD_TEXT, N_("Add text"), "T", "add-text"),
            (Tool.ADD_IMAGE, N_("Add image"), "I", "image"),
            (Tool.HIGHLIGHT, N_("Highlight"), "H", "highlight"),
            (Tool.ADD_BOX, N_("Add box"), "B", "box"),
        ):
            action = self._act(tr(label), lambda _=False, t=tool: self.set_tool(t), key, icon_name,
                               checkable=True)
            self.tool_group.addAction(action)
            self.tool_actions[tool] = action
        self.tool_actions[Tool.SELECT].setChecked(True)

        self.a_rot_l = self._act(tr("Rotate Left"), lambda: self.rotate(-90), "Ctrl+[",
                                 "rotate-left", tip=tr("Rotate page left"))
        self.a_rot_r = self._act(tr("Rotate Right"), lambda: self.rotate(90), "Ctrl+]",
                                 "rotate-right", tip=tr("Rotate page right"))
        self.a_del_page = self._act(tr("Delete Page"), self.delete_pages, "Ctrl+Shift+D", "delete",
                                    tip=tr("Delete selected page(s)"))
        self.a_move_up = self._act(tr("Move Page Up"), lambda: self.move_pages(-1), "Ctrl+Shift+Up")
        self.a_move_down = self._act(tr("Move Page Down"), lambda: self.move_pages(1),
                                     "Ctrl+Shift+Down")
        self.a_blank = self._act(tr("Insert Blank Page"), self.insert_blank, None, "blank-page")
        self.a_insert_pdf = self._act(tr("Insert Pages from PDF…"), self.insert_pdf, None,
                                      "insert-pdf", tip=tr("Insert pages from another PDF"))

        # Layers. Page Up/Down rather than brackets: those need AltGr on many keyboards.
        self.arrange_actions: dict[str, QAction] = {}
        for how, keys in (("front", "Ctrl+Shift+PgUp"), ("forward", "Ctrl+PgUp"),
                          ("backward", "Ctrl+PgDown"), ("back", "Ctrl+Shift+PgDown")):
            self.arrange_actions[how] = self._act(
                tr(LAYER_MOVES[how]), lambda _=False, h=how: self.view.arrange_selected(h), keys,
                tip=tr("{action} (the selected text box, image or box)",
                       action=tr(LAYER_MOVES[how])))

        self.a_zoom_in = self._act(tr("Zoom In"), self.view.zoom_in, [QKeySequence(K.ZoomIn),
                                   QKeySequence("Ctrl+=")], "zoom-in")
        self.a_zoom_out = self._act(tr("Zoom Out"), self.view.zoom_out, K.ZoomOut, "zoom-out")
        self.a_fit = self._act(tr("Fit Width"), self.view.zoom_fit, "Ctrl+0", "fit")
        self.a_theme = self._act(tr("Toggle Theme"), self.cycle_theme, None, "theme",
                                 tip=tr("Theme: system / light / dark"))

        self.a_check_update = self._act(tr("Check for Updates…"), self.updater.check)
        self.a_auto_update = self._act(tr("Check for Updates Automatically"),
                                       self.updater.set_automatic, checkable=True)

        for a in (self.a_delete,):
            self.addAction(a)

    def _create_toolbar(self) -> None:
        tb = QToolBar("Main")
        tb.setObjectName("MainToolbar")
        tb.setMovable(False)
        tb.setIconSize(QSize(20, 20))
        tb.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)
        self.doc_title = QLabel()
        self.doc_title.setObjectName("DocTitle")
        tb.addActions([self.a_open, self.a_save, self.a_print])
        tb.addSeparator()
        tb.addActions([self.a_undo, self.a_redo])
        tb.addSeparator()
        tb.addActions(list(self.tool_actions.values()))
        tb.addSeparator()
        tb.addActions([self.a_rot_l, self.a_rot_r, self.a_del_page, self.a_insert_pdf])
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)
        tb.addWidget(self.doc_title)
        spacer2 = QWidget()
        spacer2.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer2)
        tb.addAction(self.a_zoom_out)
        self.zoom_label = QLabel("100%")
        self.zoom_label.setObjectName("ZoomLabel")
        tb.addWidget(self.zoom_label)
        tb.addActions([self.a_zoom_in, self.a_fit])
        tb.addSeparator()
        tb.addAction(self.a_theme)
        self.toolbar = tb

    def _create_menus(self) -> None:
        mb = self.menuBar()
        m = mb.addMenu(tr("&File"))
        m.addAction(self.a_open)
        self.recent_menu = m.addMenu(tr("Open Recent"))
        m.addSeparator()
        m.addActions([self.a_save, self.a_save_as])
        m.addAction(self.a_confirm_overwrite)
        m.addSeparator()
        m.addAction(self.a_insert_pdf)
        m.addSeparator()
        m.addActions([self.a_preview, self.a_print])
        m.addSeparator()
        m.addActions([self.a_close, self.a_quit])
        m = mb.addMenu(tr("&Edit"))
        m.addActions([self.a_undo, self.a_redo])
        m.addSeparator()
        m.addAction(self.a_paste)
        m.addSeparator()
        m.addActions(list(self.tool_actions.values()))
        m.addSeparator()
        self.arrange_menu = m.addMenu(tr("Arrange"))
        self.arrange_menu.addActions(list(self.arrange_actions.values()))
        m.addAction(self.a_delete)
        m = mb.addMenu(tr("&Page"))
        m.addActions([self.a_rot_l, self.a_rot_r])
        m.addSeparator()
        m.addActions([self.a_move_up, self.a_move_down])
        m.addSeparator()
        m.addActions([self.a_blank, self.a_insert_pdf])
        m.addSeparator()
        m.addAction(self.a_del_page)
        m = mb.addMenu(tr("&View"))
        m.addActions([self.a_zoom_in, self.a_zoom_out, self.a_fit])
        m.addSeparator()
        m.addAction(self.a_theme)
        self.language_menu = m.addMenu(tr("Language"))
        self._fill_language_menu()
        m = mb.addMenu(tr("&Help"))
        m.addActions([self.a_check_update, self.a_auto_update])
        m.addSeparator()
        about = m.addAction(tr("About Pixa"), self.about)
        about.setMenuRole(QAction.MenuRole.AboutRole)
        self._refresh_recent_menu()

    def _connect(self) -> None:
        v = self.view
        v.currentPageChanged.connect(self._page_changed)
        v.zoomChanged.connect(lambda z: self.zoom_label.setText(f"{round(z * 100)}%"))
        v.selectionChanged.connect(lambda _img: self._update_image_state())
        v.placementChanged.connect(lambda _p: self._update_image_state())
        v.editingChanged.connect(self._editing_changed)
        v.message.connect(lambda m: self.statusBar().showMessage(m, 5000))
        v.error.connect(self.show_error)
        v.dropped.connect(self._dropped_on_page)
        v.contextMenuWanted.connect(self._page_menu)
        v.own_pages_source = self.thumbs.source_id
        self.thumbs.pageActivated.connect(self.view.scroll_to_page)
        self.thumbs.orderChanged.connect(self._reorder)
        self.thumbs.contextAction.connect(self._page_action)
        self.thumbs.dropped.connect(self._dropped_on_sidebar)
        self.inspector.styleChanged.connect(self._style_changed)
        self.inspector.highlightChanged.connect(self._highlight_changed)
        self.inspector.boxChanged.connect(self._box_changed)
        self.inspector.action.connect(self._inspector_action)
        self.inspector.returnToEditor.connect(self.view.focus_editor)

    # ------------------------------------------------------------------ theme
    def _resolve_theme(self) -> theme.Theme:
        if self.theme_mode == "light":
            return theme.LIGHT
        if self.theme_mode == "dark":
            return theme.DARK
        return theme.DARK if theme.system_prefers_dark() else theme.LIGHT

    def apply_theme(self) -> None:
        self.theme = self._resolve_theme()
        theme.apply(QApplication.instance(), self.theme)
        icons.clear_cache()
        for action in self.findChildren(QAction):
            name = action.data()
            if name:
                action.setIcon(icons.icon(name, self.theme.text, self.theme.accent))
        widgets.retint(self)
        self.view.set_accent(self.theme.accent)
        self.thumbs.set_accent(self.theme.accent)
        self.welcome.set_logo(self.theme.accent)
        self.a_theme.setToolTip(tr("Theme: {mode} (click to change)",
                                   mode=tr(THEME_NAMES[self.theme_mode])))

    def cycle_theme(self) -> None:
        order = ["system", "light", "dark"]
        self.theme_mode = order[(order.index(self.theme_mode) + 1) % 3]
        self.settings.setValue("theme", self.theme_mode)
        self.apply_theme()
        self.statusBar().showMessage(tr("Theme: {mode}", mode=tr(THEME_NAMES[self.theme_mode])),
                                     2000)

    # --------------------------------------------------------------- language
    def _fill_language_menu(self) -> None:
        """View → Language: the system's language, or one chosen here."""
        setting = str(self.settings.value("language", i18n.SYSTEM))
        group = QActionGroup(self)
        system = i18n.LANGUAGES[i18n.system_language()]
        choices = [(i18n.SYSTEM, tr("Same as System ({language})", language=system))]
        choices += list(i18n.LANGUAGES.items())
        self.language_actions: dict[str, QAction] = {}
        for code, name in choices:
            action = self.language_menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(code == setting or (code == i18n.SYSTEM
                                                  and setting not in i18n.LANGUAGES))
            action.triggered.connect(lambda _=False, c=code: self.set_language(c))
            group.addAction(action)
            self.language_actions[code] = action
            if code == i18n.SYSTEM:
                self.language_menu.addSeparator()

    def set_language(self, setting: str) -> MainWindow:
        """Switch to a language code, or ``i18n.SYSTEM``. The window is made again in
        the new language, with the open document and its undo history kept.
        Returns the window showing the document from now on."""
        self.settings.setValue("language", setting)
        code = i18n.resolve(setting)
        if code == i18n.language():
            return self
        i18n.set_language(code)
        i18n.install_qt_translations(QApplication.instance())
        self.view.cancel_interactions(commit=True)
        window = MainWindow()
        window.setGeometry(self.geometry())
        if self.isMaximized():
            window.showMaximized()
        elif self.isVisible():
            window.show()
        doc, page = self.doc, self.view.current_page
        if doc is not None:
            doc.listeners.remove(self._document_changed)
            self.doc = None  # handed over: closing this window mustn't ask to save it
            window.set_document(doc)
            window._overwrite_confirmed = self._overwrite_confirmed
            QTimer.singleShot(0, lambda: window.view.scroll_to_page(page))
        _windows.append(window)
        if self in _windows:
            _windows.remove(self)
        self.close()
        self.deleteLater()
        window.statusBar().showMessage(tr("Language: {language}",
                                          language=i18n.LANGUAGES[code]), 3000)
        return window

    # ---------------------------------------------------- highlight and box
    def _restore_markup_styles(self) -> None:
        """Highlight colour and box style are remembered between sessions."""
        def color(key: str):
            c = QColor(str(self.settings.value(key, "")))
            return (c.redF(), c.greenF(), c.blueF()) if c.isValid() else None

        highlight = color("highlight_color")
        if highlight is not None:
            self.inspector.set_highlight_color(highlight)
        box = BoxStyle()
        try:
            box.width = min(24.0, max(0.0, float(self.settings.value("box_width", box.width))))
        except (TypeError, ValueError):
            pass
        box.color = color("box_color") or box.color
        if self.settings.contains("box_fill"):
            box.fill = color("box_fill")  # "none" is transparent
        self.inspector.set_box_style(box)
        self.view.highlight_color = self.inspector.highlight_color.color()
        self.view.box_style = self.inspector.box_style()

    def _highlight_changed(self, color) -> None:
        self.view.highlight_color = color
        self.settings.setValue("highlight_color", QColor.fromRgbF(*color).name())
        self.view.restyle_selected_markup()

    def _box_changed(self, style: BoxStyle) -> None:
        self.view.box_style = style
        self.settings.setValue("box_width", style.width)
        self.settings.setValue("box_color", QColor.fromRgbF(*style.color).name())
        self.settings.setValue(
            "box_fill", QColor.fromRgbF(*style.fill).name() if style.fill else "none")
        self.view.restyle_selected_markup()

    def _sync_markup_controls(self) -> None:
        """Show the selected highlight's or box's own style, else the one for new ones."""
        markup = self.view.selected_markup
        box = markup is not None and markup.kind == "box"
        self.inspector.set_box_style(markup.style if box else self.view.box_style)
        own = markup.color if markup is not None and markup.kind == "highlight" else None
        self.inspector.set_highlight_color(own or self.view.highlight_color)

    # ------------------------------------------------------------------ files
    def recent_files(self) -> list[str]:
        value = self.settings.value("recent", [])
        if isinstance(value, str):
            value = [value]
        return [str(p) for p in value or []]

    def _add_recent(self, path: str) -> None:
        path = os.path.abspath(path)
        files = [p for p in self.recent_files() if p != path]
        files.insert(0, path)
        self.settings.setValue("recent", files[:MAX_RECENT])
        self._refresh_recent_menu()
        self.welcome.set_recent(self.recent_files())

    def _refresh_recent_menu(self) -> None:
        self.recent_menu.clear()
        files = [p for p in self.recent_files() if os.path.exists(p)]
        for path in files:
            self.recent_menu.addAction(os.path.basename(path), lambda p=path: self.open_path(p))
        self.recent_menu.setEnabled(bool(files))

    def open_dialog(self) -> None:
        if not self.maybe_save():
            return
        start = os.path.dirname(self.doc.path) if self.doc and self.doc.path else ""
        path, _ = QFileDialog.getOpenFileName(self, tr("Open PDF"), start, tr(PDF_FILTER))
        if path:
            self.open_path(path, ask_save=False)

    def open_path(self, path: str, ask_save: bool = True) -> bool:
        if ask_save and not self.maybe_save():
            return False
        password = None
        if PdfDocument.needs_password(path):
            password, ok = QInputDialog.getText(
                self, tr("Password required"),
                tr("“{name}” is protected. Enter the password:", name=os.path.basename(path)),
                QLineEdit.EchoMode.Password,
            )
            if not ok:
                return False
        try:
            doc = PdfDocument.open(path, password)
        except PdfError as exc:
            msg = tr("Incorrect password.") if str(exc) == "password" else str(exc)
            self.show_error(msg)
            return False
        self.set_document(doc)
        self._add_recent(path)
        return True

    def set_document(self, doc: PdfDocument | None) -> None:
        self.doc = doc
        self._overwrite_confirmed = False
        if doc is not None:
            doc.listeners.append(self._document_changed)
        self.stack.setCurrentIndex(1 if doc else 0)
        self.inspector.set_document_fonts(doc.document_fonts() if doc else [])
        self._last_revision = doc.revision if doc else -1
        self._last_count = doc.page_count if doc else -1
        # Defer so the view has its final size for fit-to-width.
        QTimer.singleShot(0, lambda: self.view.set_document(doc))
        self.thumbs.set_document(doc)
        self._update_ui()

    def close_document(self) -> None:
        if self.doc and self.maybe_save():
            self.set_document(None)

    def save(self) -> bool:
        if not self.doc:
            return False
        if not self.doc.path:
            return self.save_as()
        self.view.cancel_interactions(commit=True)
        if not self._overwrite_confirmed and self.confirm_overwrite:
            choice = self._ask_overwrite(os.path.basename(self.doc.path))
            if choice == "copy":
                return self.save_as()
            if choice != "overwrite":
                return False
        self._overwrite_confirmed = True  # don't ask again for this document
        try:
            self.doc.save()
        except PdfError as exc:
            self.show_error(str(exc))
            return False
        self.statusBar().showMessage(tr("Saved {name}", name=os.path.basename(self.doc.path)),
                                     3000)
        return True

    def save_as(self) -> bool:
        if not self.doc:
            return False
        self.view.cancel_interactions(commit=True)
        if self.doc.path and not self._overwrite_confirmed:
            # Suggest a new name so the original isn't replaced by accident.
            stem, ext = os.path.splitext(self.doc.path)
            suggested = tr("{name} (edited)", name=stem) + (ext or ".pdf")
        else:
            suggested = self.doc.path or tr("document") + ".pdf"
        path, _ = QFileDialog.getSaveFileName(self, tr("Save PDF As"), suggested,
                                              tr(PDF_FILTER))
        if not path:
            return False
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            self.doc.save(path)
        except PdfError as exc:
            self.show_error(str(exc))
            return False
        # The file dialog already confirmed any overwrite, and later saves go to
        # the copy the user just chose.
        self._overwrite_confirmed = True
        self._add_recent(path)
        self.statusBar().showMessage(tr("Saved {name}", name=os.path.basename(path)), 3000)
        return True

    def _ask_overwrite(self, name: str) -> str:
        """Ask before replacing the opened file. Returns "overwrite", "copy" or "cancel"."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(tr("Overwrite original?"))
        box.setText(tr("Replace “{name}” with your edited version?", name=name))
        box.setInformativeText(
            tr("The original file will be overwritten and can't be recovered. "
               "Choose “Save as Copy…” to keep it unchanged.")
        )
        overwrite = box.addButton(tr("Overwrite"), QMessageBox.ButtonRole.DestructiveRole)
        copy = box.addButton(tr("Save as Copy…"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(copy)
        dont_ask = QCheckBox(tr("Don't ask again"))
        box.setCheckBox(dont_ask)
        box.exec()
        clicked = box.clickedButton()
        choice = "overwrite" if clicked is overwrite else "copy" if clicked is copy else "cancel"
        if choice == "overwrite" and dont_ask.isChecked():
            self.set_confirm_overwrite(False)
        return choice

    @property
    def confirm_overwrite(self) -> bool:
        return str(self.settings.value("confirm_overwrite", "true")).lower() != "false"

    def set_confirm_overwrite(self, enabled: bool) -> None:
        self.settings.setValue("confirm_overwrite", "true" if enabled else "false")
        self.a_confirm_overwrite.setChecked(enabled)

    def maybe_save(self) -> bool:
        if not self.doc:
            return True
        self.view.cancel_interactions(commit=True)
        if not self.doc.dirty:
            return True
        name = os.path.basename(self.doc.path) if self.doc.path else tr("Untitled")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(tr("Unsaved changes"))
        box.setText(tr("Save changes to “{name}” before closing?", name=name))
        box.setInformativeText(tr("Your changes will be lost if you don't save them."))
        box.setStandardButtons(QMessageBox.StandardButton.Save
                               | QMessageBox.StandardButton.Discard
                               | QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Save)
        answer = box.exec()
        if answer == QMessageBox.StandardButton.Save:
            return self.save()
        return answer == QMessageBox.StandardButton.Discard

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self.maybe_save():
            event.accept()
        else:
            event.ignore()

    # ---------------------------------------------------------- drag and drop
    # PDFs dropped on an open document are inserted (on the pages: next to the
    # page they land on; in the sidebar: where they land); without a document
    # the first one is opened. Images are placed where they land on a page,
    # become pages of their own in the sidebar, or a new PDF without a
    # document. Pages dragged from another Pixa window's sidebar are copied in
    # like a PDF.
    def _wanted(self, event) -> dnd.Dropped | None:
        data = dnd.read(event.mimeData())
        if not data or (self.doc is not None and data.from_list(self.thumbs.source_id)):
            return None
        return data

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._wanted(event) is not None:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        self.dragEnterEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        data = self._wanted(event)
        if data is None:
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        # Deferred: dialogs must not open while the system is still in the drag.
        QTimer.singleShot(0, lambda: self.drop(data))

    def _readable(self, data: dnd.Dropped) -> dnd.Dropped | None:
        """The drop with its images in a form the document reads (None on an error)."""
        try:
            images = imagefiles.sources(data.images)
        except PdfError as exc:
            self.show_error(str(exc))
            return None
        return dataclasses.replace(data, images=images)

    def drop(self, data: dnd.Dropped) -> None:
        """Files or pages dropped outside the pages and the sidebar."""
        data = self._readable(data)
        if data is None:
            return
        if self.doc is None:
            self._open_dropped(data)
            return
        at = self._pages()[-1] + 1
        if self._insert_dropped(data, at, images_as_pages=False) is not None and data.images:
            index = self.view.current_page
            w, h = self.doc.page_size(index)
            self.view.place_images(index, self._visible_center(index, w, h), data.images)

    def paste(self) -> None:
        """Place the clipboard's image (or copied image files) in the middle of what
        is visible of the current page, like a drop there."""
        if self.doc is None:
            return
        try:
            images = dnd.pasted_images(QApplication.clipboard().mimeData())
        except PdfError as exc:
            self.show_error(str(exc))
            return
        if not images:
            self.statusBar().showMessage(tr("There is no image on the clipboard to paste."), 5000)
            return
        if isinstance(images[0], str):  # copied files: read as if they were dropped
            data = self._readable(dnd.Dropped(images=images))
            if data is None:
                return
            images = data.images
        index = self.view.current_page
        w, h = self.doc.page_size(index)
        self.view.place_images(index, self._visible_center(index, w, h), images)

    def _visible_center(self, index: int, w: float, h: float) -> fitz.Point:
        """The middle of what is visible of a page (display point)."""
        view = self.view
        visible = view.mapToScene(view.viewport().rect()).boundingRect()
        page = view.pages[index]
        local = visible.center() - page.pos()
        return fitz.Point(min(max(local.x() / view.zoom, 0), w),
                          min(max(local.y() / view.zoom, 0), h))

    def _dropped_on_page(self, data: dnd.Dropped, index: int, point: fitz.Point) -> None:
        """PDFs and pages go before the page they land on (its top half) or after it;
        images are placed where they land."""
        data = self._readable(data) if self.doc is not None else None
        if data is None:
            return
        _, height = self.doc.page_size(index)
        at = index if point.y < height / 2 else index + 1
        count = self._insert_dropped(data, at, images_as_pages=False)
        if data.images and count is not None:
            if at <= index:  # the page moved down past the inserted ones
                index += count
            self.view.place_images(index, point, data.images)

    def _dropped_on_sidebar(self, data: dnd.Dropped, at: int) -> None:
        data = self._readable(data) if self.doc is not None else None
        if data is not None:
            self._insert_dropped(data, at, images_as_pages=True)

    def _insert_dropped(self, data: dnd.Dropped, at: int, images_as_pages: bool) -> int | None:
        """Insert dropped PDFs and pages (and images, as pages of their own) before
        page ``at``. Returns how many pages were inserted (None on an error)."""
        self._finish_editing()
        sources: list[str | bytes] = ([data.pages] if data.pages else []) + data.pdfs
        try:
            count = self.doc.insert_pdfs(sources, at) if sources else 0
            if images_as_pages and data.images:
                count += self.doc.insert_image_pages(data.images, at + count)
        except PdfError as exc:
            self.show_error(str(exc))
            return None
        if count:
            self._select_pages(list(range(at, at + count)))
            self.statusBar().showMessage(
                ntr("Inserted {n} page. Undo removes it again.",
                    "Inserted {n} pages. Undo removes them again.", count), 4000)
        return count

    def _open_dropped(self, data: dnd.Dropped) -> None:
        """Without a document: open the first PDF (or the dropped pages, or the images
        as a new PDF) and insert the rest."""
        rest = dnd.Dropped(list(data.pdfs), list(data.images), data.pages)
        if rest.pdfs:
            if not self.open_path(rest.pdfs.pop(0)):
                return
        else:
            try:
                if rest.pages:
                    doc, rest.pages = PdfDocument.from_bytes(rest.pages), None
                else:
                    doc, rest.images = PdfDocument.from_images(rest.images), []
            except PdfError as exc:
                self.show_error(str(exc))
                return
            self.set_document(doc)
        if rest:
            self._insert_dropped(rest, self.doc.page_count, images_as_pages=True)

    # --------------------------------------------------------------- changes
    def _document_changed(self) -> None:
        doc = self.doc
        if doc is None:
            return
        if doc.revision != self._last_revision:
            if doc.page_count != self._last_count or self._layout_changed():
                self.view.rebuild()
                self.thumbs.rebuild(keep_row=min(self.view.current_page, doc.page_count - 1))
            else:
                self.view.refresh_pages()
                self.thumbs.refresh_all()
            self._last_revision = doc.revision
            self._last_count = doc.page_count
            self.inspector.set_document_fonts(doc.document_fonts())
        self._update_ui()

    def _layout_changed(self) -> bool:
        # Rotation changes page sizes; compare with what is currently laid out.
        sizes = [(round(p.size.width()), round(p.size.height())) for p in self.view.pages]
        z = self.view.zoom
        now = [(round(w * z), round(h * z)) for w, h in
               (self.doc.page_size(i) for i in range(self.doc.page_count))]
        return sizes != now

    def _update_ui(self) -> None:
        has = self.doc is not None
        for a in (self.a_save, self.a_save_as, self.a_print, self.a_preview, self.a_close,
                  self.a_rot_l, self.a_rot_r, self.a_del_page, self.a_move_up, self.a_move_down,
                  self.a_blank, self.a_insert_pdf, self.a_paste, self.a_zoom_in, self.a_zoom_out,
                  self.a_fit,
                  *self.tool_actions.values()):
            a.setEnabled(has)
        self.a_undo.setEnabled(has and self.doc.can_undo)
        self.a_redo.setEnabled(has and self.doc.can_redo)
        self.a_undo.setText(tr("Undo {action}", action=tr(self.doc.undo_label, "undo"))
                            if has and self.doc.can_undo else tr("Undo"))
        self.a_redo.setText(tr("Redo {action}", action=tr(self.doc.redo_label, "undo"))
                            if has and self.doc.can_redo else tr("Redo"))
        self.a_del_page.setEnabled(has and self.doc.page_count > 1)
        name = (os.path.basename(self.doc.path) if self.doc.path else tr("Untitled")) if has else ""
        dirty = has and self.doc.dirty
        self.doc_title.setText(f"{name}{'  •' if dirty else ''}")
        self.setWindowTitle(f"{name}{' •' if dirty else ''} — Pixa" if has else "Pixa")
        self._page_changed(self.view.current_page)
        self._update_image_state()

    def _page_changed(self, index: int) -> None:
        total = self.doc.page_count if self.doc else 0
        self.page_status.setText(tr("Page {page} of {count}", page=index + 1, count=total)
                                 if total else "")
        self.inspector.set_page_info(index, total)
        self.thumbs.set_current_page(index)

    def _update_image_state(self) -> None:
        selected = self.view.selected
        if selected is None:
            kind = None
        elif self.view.selected_markup is not None:
            kind = self.view.selected_markup.kind
        else:
            kind = "text" if self.view.selected_text else "image"
        self.inspector.set_selection_state(self.view.is_placing, kind)
        layered = kind in ("text", "image", "box") and not self.view.is_placing
        for action in self.arrange_actions.values():
            action.setEnabled(layered)
        self.arrange_menu.setEnabled(layered)
        self._sync_markup_controls()

    def _style_changed(self, style: TextStyle) -> None:
        if self.view.tool == Tool.ADD_TEXT:
            self.add_text_style = TextStyle(**vars(style))
        self.view.update_editor_style(style)

    def _editing_changed(self, style) -> None:
        if style is not None:
            self.inspector.set_style(style)

    # --------------------------------------------------------------- actions
    def set_tool(self, tool: Tool) -> None:
        self.tool_actions[tool].setChecked(True)
        self.view.set_tool(tool)
        self.inspector.set_tool(tool)
        if tool == Tool.ADD_TEXT:
            # New text has its own remembered style, separate from edited lines.
            self.inspector.set_style(self.add_text_style)
            self.view.text_style = TextStyle(**vars(self.add_text_style))
        self._update_image_state()
        if tool == Tool.ADD_IMAGE and not self.view.is_placing:
            self.choose_image()

    def choose_image(self) -> None:
        if not self.doc:
            return
        start = self.settings.value("image_dir", "")
        path, _ = QFileDialog.getOpenFileName(self, tr("Choose image"), start,
                                              imagefiles.file_filter())
        if path:
            self.settings.setValue("image_dir", os.path.dirname(path))
            try:
                self.view.begin_image_placement(imagefiles.source(path))
            except PdfError as exc:
                self.show_error(str(exc))
        self._update_image_state()

    def undo(self) -> None:
        if self.view.is_editing:
            return  # the inline editor handles its own undo
        if self.doc:
            self.view.cancel_interactions()
            self.doc.undo()

    def redo(self) -> None:
        if self.view.is_editing:
            return
        if self.doc:
            self.view.cancel_interactions()
            self.doc.redo()

    def _finish_editing(self) -> None:
        """Commit any text being typed before the pages change underneath it."""
        self.view.cancel_interactions(commit=True)

    def _pages(self) -> list[int]:
        pages = self.thumbs.selected_pages()
        return pages or [self.view.current_page]

    def rotate(self, degrees: int) -> None:
        if self.doc:
            self._finish_editing()
            self.doc.rotate_pages(self._pages(), degrees)

    def delete_pages(self) -> None:
        if not self.doc:
            return
        self._finish_editing()
        pages = self._pages()
        try:
            self.doc.delete_pages(pages)
        except PdfError as exc:
            self.show_error(str(exc))
            return
        self.statusBar().showMessage(
            ntr("Deleted {n} page. Undo to restore.", "Deleted {n} pages. Undo to restore.",
                len(pages)), 4000
        )

    def move_pages(self, delta: int) -> None:
        if not self.doc:
            return
        self._finish_editing()
        pages = self._pages()
        order = list(range(self.doc.page_count))
        if (delta < 0 and pages[0] == 0) or (delta > 0 and pages[-1] == len(order) - 1):
            return
        for p in pages if delta < 0 else reversed(pages):
            order[p], order[p + delta] = order[p + delta], order[p]
        self.doc.reorder_pages(order)
        self._select_pages([p + delta for p in pages])

    def _select_pages(self, pages: list[int]) -> None:
        self.thumbs.clearSelection()
        for p in pages:
            if 0 <= p < self.thumbs.count():
                self.thumbs.item(p).setSelected(True)
        if pages:
            self.view.scroll_to_page(pages[0])

    def _reorder(self, order: list[int]) -> None:
        if self.doc:
            self._finish_editing()
            moved = self.thumbs.selected_pages()
            self.doc.reorder_pages(order)
            self._select_pages(sorted(order.index(p) for p in moved if p in order))

    def insert_blank(self) -> None:
        if self.doc:
            self._finish_editing()
            at = self._pages()[-1] + 1
            self.doc.insert_blank_page(at)
            self._select_pages([at])

    def insert_pdf(self) -> None:
        if not self.doc:
            return
        start = os.path.dirname(self.doc.path) if self.doc.path else ""
        path, _ = QFileDialog.getOpenFileName(self, tr("Insert pages from PDF"), start,
                                              tr(PDF_FILTER))
        if path:
            self._insert_pdf_file(path)

    def _insert_pdf_file(self, path: str) -> None:
        self._finish_editing()
        at = self._pages()[-1] + 1
        try:
            count = self.doc.insert_pdf(path, at)
        except PdfError as exc:
            self.show_error(str(exc))
            return
        self._select_pages(list(range(at, at + count)))
        self.statusBar().showMessage(
            ntr("Inserted {n} page from {name}", "Inserted {n} pages from {name}", count,
                name=os.path.basename(path)), 4000)

    def delete_selection(self) -> None:
        if not self.doc:
            return
        if self.view.delete_selected():
            return
        if self.thumbs.hasFocus():
            self.delete_pages()

    def _page_action(self, key: str) -> None:
        {
            "rotate_left": lambda: self.rotate(-90),
            "rotate_right": lambda: self.rotate(90),
            "move_up": lambda: self.move_pages(-1),
            "move_down": lambda: self.move_pages(1),
            "insert_blank": self.insert_blank,
            "insert_pdf": self.insert_pdf,
            "delete": self.delete_pages,
        }[key]()

    def _inspector_action(self, key: str) -> None:
        if key == "choose_image":
            self.choose_image()
        elif key == "place_image":
            self.view.commit_placement()
        elif key == "cancel_image":
            self.view.cancel_placement()
        elif key == "delete_selection":
            self.view.delete_selected()
        elif key == "rotate_image_left":
            self.view.rotate_selected_image(-90)
        elif key == "rotate_image_right":
            self.view.rotate_selected_image(90)
        elif key.startswith("arrange_"):
            self.view.arrange_selected(key.removeprefix("arrange_"))
        else:
            self._page_action(key)

    def _page_menu(self, pos) -> None:
        """Right click on a page with the Select tool: layers and delete."""
        menu = QMenu(self)
        menu.addActions(list(self.arrange_actions.values()))
        menu.addSeparator()
        delete = menu.addAction(tr("Delete"), self.view.delete_selected)
        delete.setEnabled(self.view.selected is not None)
        if self.view.selected_image is not None:
            menu.addSeparator()
            menu.addAction(tr("Rotate image left"), lambda: self.view.rotate_selected_image(-90))
            menu.addAction(tr("Rotate image right"), lambda: self.view.rotate_selected_image(90))
        menu.exec(pos)

    # ----------------------------------------------------------------- print
    def print_document(self) -> bool:
        if not self.doc:
            return False
        self._finish_editing()
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setDocName(os.path.basename(self.doc.path or tr("Untitled") + ".pdf"))
        choice = self._print_choice(printer)
        if choice is None:
            return False
        pages, layout = choice
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            printing.print_pages(
                self.doc, printer, printing.copies(pages, printer),
                lambda n, total: self.statusBar().showMessage(
                    tr("Printing page {page} of {count}…", page=n + 1, count=total)),
                layout=layout)
        except PdfError as exc:
            self.show_error(str(exc))
            return False
        finally:
            QApplication.restoreOverrideCursor()
        self.statusBar().showMessage(
            ntr("Sent {n} page to the printer.", "Sent {n} pages to the printer.", len(pages)),
            4000)
        return True

    def print_preview(self) -> PrintPreview | None:
        """Show the pages as they will print; its Print button goes on to printing."""
        if not self.doc:
            return None
        self._finish_editing()
        dialog = PrintPreview(self._paint_preview, self)
        dialog.printRequested.connect(self.print_document)
        dialog.finished.connect(dialog.deleteLater)
        dialog.open()
        return dialog

    def _paint_preview(self, printer: QPrinter) -> None:
        """Draw every page for the preview, at screen quality."""
        if not self.doc:
            return
        try:
            printing.print_pages(self.doc, printer,
                                 printing.copies(self._pages_to_print(printer), printer),
                                 dpi=printing.PREVIEW_DPI)
        except PdfError as exc:
            self.show_error(str(exc))

    def _print_choice(self, printer: QPrinter) -> tuple[list[int], printing.Layout] | None:
        """Ask which printer, pages and layout, and set ``printer`` up; None if cancelled."""
        selected = self.thumbs.selected_pages() if len(self.thumbs.selectedItems()) > 1 else []
        dialog = PrintDialog(self.doc, self.view.current_page, selected, self)
        if dialog.exec() != PrintDialog.DialogCode.Accepted:
            return None
        dialog.apply_to(printer)
        return dialog.pages(), dialog.print_layout()

    def _pages_to_print(self, printer: QPrinter) -> list[int]:
        count = self.doc.page_count
        mode = printer.printRange()
        if mode == QPrinter.PrintRange.CurrentPage:
            return [self.view.current_page]
        if mode == QPrinter.PrintRange.Selection:
            return self.thumbs.selected_pages()
        if mode == QPrinter.PrintRange.PageRange and printer.fromPage() > 0:
            first = max(1, printer.fromPage())
            last = min(count, printer.toPage() or count)
            return list(range(first - 1, last))
        return list(range(count))

    def show_error(self, message: str) -> None:
        QMessageBox.warning(self, "Pixa", message)

    def about(self) -> None:
        QMessageBox.about(
            self, tr("About Pixa"),
            f"<h3>Pixa {__version__}</h3><p>{tr('A clean, local PDF editor.')}</p>"
            f"<p>{tr('Built with PySide6 and PyMuPDF.')}</p>",
        )
