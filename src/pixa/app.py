"""Application entry point."""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtWidgets import QApplication

from pixa import __version__, i18n
from pixa.document import system_fonts
from pixa.ui import icons
from pixa.ui.main_window import MainWindow


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(argv)
    app.setApplicationName("Pixa")
    app.setOrganizationName("Pixa")
    app.setApplicationVersion(__version__)
    app.setWindowIcon(icons.app_icon())
    # The language chosen under View → Language, else the system's (English if Pixa
    # doesn't have it).
    settings = QSettings(QSettings.defaultFormat(), QSettings.Scope.UserScope, "Pixa", "Pixa")
    i18n.set_language(i18n.resolve(settings.value("language", i18n.SYSTEM)))
    i18n.install_qt_translations(app)
    # Index installed fonts in the background, so the first text edit is instant.
    system_fonts().warm()
    window = MainWindow()
    window.show()
    files = [a for a in argv[1:] if a.lower().endswith(".pdf")]
    if files:
        window.open_path(files[0], ask_save=False)
    if "--smoke-test" not in argv:
        window.updater.check_on_startup()
    else:
        # Used by CI to check a packaged build starts: render, optionally screenshot, quit.
        def finish() -> None:
            shot = os.environ.get("PIXA_SMOKE_SCREENSHOT")
            if shot:
                window.grab().save(shot)
            print(f"smoke-test ok: {window.doc.page_count if window.doc else 0} page(s)")
            app.quit()

        QTimer.singleShot(1500, finish)
    return app.exec()
