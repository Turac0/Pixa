"""Help → Check for Updates, and the quiet check when Pixa starts."""

from __future__ import annotations

import os
import subprocess
import sys
import threading

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from pixa import __version__, updates
from pixa.i18n import tr

STARTUP_DELAY_MS = 3000


class UpdateDialog(QDialog):
    """"Pixa X is available", its release notes, and what to do about it."""

    INSTALL, DOWNLOAD, SKIP = 1, 2, 3

    def __init__(self, release: updates.Release, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Update Available"))
        self.resize(520, 420)
        layout = QVBoxLayout(self)
        title = QLabel("<h3>" + tr("Pixa {version} is available", version=release.version)
                       + "</h3><p>" + tr("You have version {version}.", version=__version__)
                       + "</p>")
        layout.addWidget(title)
        notes = QTextBrowser()
        notes.setOpenExternalLinks(True)
        notes.setMarkdown(release.notes or tr("No release notes."))
        layout.addWidget(notes, 1)

        buttons = QHBoxLayout()
        skip = QPushButton(tr("Skip This Version"))
        skip.clicked.connect(lambda: self.done(self.SKIP))
        later = QPushButton(tr("Later"))
        later.clicked.connect(self.reject)
        if updates.can_install() and release.installer_url:
            go = QPushButton(tr("Install and Restart"))
            go.clicked.connect(lambda: self.done(self.INSTALL))
        else:
            go = QPushButton(tr("Download…"))
            go.clicked.connect(lambda: self.done(self.DOWNLOAD))
        go.setProperty("primary", True)
        go.setDefault(True)
        self.install_button = go
        buttons.addWidget(skip)
        buttons.addStretch(1)
        buttons.addWidget(later)
        buttons.addWidget(go)
        layout.addLayout(buttons)


class Updater(QObject):
    """Checks for, downloads and starts installing updates for ``window``.

    Network work runs on a plain thread; the signals bring results back to the GUI thread.
    """

    _checked = Signal(object, bool)  # Release, manual
    _check_failed = Signal(str, bool)
    _progress = Signal(int, int)
    _downloaded = Signal(str)
    _download_failed = Signal(str)

    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.settings = window.settings
        self.checking = False
        self._cancel = False
        self._progress_dialog: QProgressDialog | None = None
        self._checked.connect(self._on_checked)
        self._check_failed.connect(self._on_check_failed)
        self._progress.connect(self._on_progress)
        self._downloaded.connect(self._on_downloaded)
        self._download_failed.connect(self._on_download_failed)

    # ------------------------------------------------------------ settings
    @property
    def automatic(self) -> bool:
        return str(self.settings.value("check_updates", "true")).lower() != "false"

    def set_automatic(self, enabled: bool) -> None:
        self.settings.setValue("check_updates", "true" if enabled else "false")

    # -------------------------------------------------------------- checking
    def check_on_startup(self) -> None:
        """Look for an update shortly after start, in installed copies only."""
        if self.automatic and getattr(sys, "frozen", False) \
                and not os.environ.get("PIXA_NO_UPDATE_CHECK"):
            QTimer.singleShot(STARTUP_DELAY_MS, lambda: self.check(manual=False))

    def check(self, manual: bool = True) -> None:
        if self.checking:
            return
        self.checking = True
        if manual:
            self.window.statusBar().showMessage(tr("Checking for updates…"), 5000)

        def run() -> None:
            try:
                self._checked.emit(updates.fetch_latest(), manual)
            except updates.UpdateError as exc:
                self._check_failed.emit(str(exc), manual)

        threading.Thread(target=run, daemon=True).start()

    def _on_check_failed(self, message: str, manual: bool) -> None:
        self.checking = False
        if manual:
            self.window.show_error(message)

    def _on_checked(self, release: updates.Release, manual: bool) -> None:
        self.checking = False
        if not updates.is_newer(release.version):
            if manual:
                QMessageBox.information(
                    self.window, "Pixa",
                    tr("You have the latest version of Pixa ({version}).", version=__version__))
            return
        if not manual and self.settings.value("skipped_version") == release.version:
            return
        self.offer(release)

    def offer(self, release: updates.Release) -> None:
        answer = UpdateDialog(release, self.window).exec()
        if answer == UpdateDialog.SKIP:
            self.settings.setValue("skipped_version", release.version)
        elif answer == UpdateDialog.DOWNLOAD:
            QDesktopServices.openUrl(QUrl(release.page_url))
        elif answer == UpdateDialog.INSTALL:
            self.install(release)

    # ------------------------------------------------------------ installing
    def install(self, release: updates.Release) -> None:
        if not self.window.maybe_save():
            return
        self._cancel = False
        dialog = QProgressDialog(tr("Downloading Pixa {version}…", version=release.version),
                                 tr("Cancel"), 0, 0, self.window)
        dialog.setWindowTitle(tr("Updating Pixa"))
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.canceled.connect(self._on_cancel)
        dialog.show()
        self._progress_dialog = dialog

        def run() -> None:
            def progress(done: int, total: int) -> bool:
                self._progress.emit(done, total)
                return not self._cancel

            try:
                self._downloaded.emit(updates.download_installer(release, progress))
            except updates.UpdateError as exc:
                self._download_failed.emit("" if self._cancel else str(exc))

        threading.Thread(target=run, daemon=True).start()

    def _on_cancel(self) -> None:
        self._cancel = True

    def _on_progress(self, done: int, total: int) -> None:
        if self._progress_dialog and total:
            # In KiB, so sizes over 2 GiB can't overflow the dialog's int range.
            self._progress_dialog.setMaximum(total // 1024)
            self._progress_dialog.setValue(done // 1024)

    def _close_progress(self) -> None:
        if self._progress_dialog:
            self._progress_dialog.canceled.disconnect(self._on_cancel)
            self._progress_dialog.close()
            self._progress_dialog = None

    def _on_download_failed(self, message: str) -> None:
        self._close_progress()
        if message:
            self.window.show_error(message)

    def _on_downloaded(self, path: str) -> None:
        self._close_progress()
        if self._cancel:
            return
        try:
            flags = getattr(subprocess, "DETACHED_PROCESS", 0) \
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            subprocess.Popen(updates.installer_command(path), creationflags=flags,
                             close_fds=True)
        except OSError as exc:
            self.window.show_error(tr("Couldn't start the installer: {error}", error=exc))
            return
        # The user already chose to save or discard their changes in install().
        if self.window.doc:
            self.window.doc.dirty = False
        self.window.close()
