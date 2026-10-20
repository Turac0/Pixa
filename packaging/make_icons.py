"""Render the app icon to PNG/ICO/ICNS. Run: python packaging/make_icons.py"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6.QtGui import QGuiApplication  # noqa: E402

from pixa.ui.icons import app_icon_image  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def main() -> None:
    QGuiApplication([])
    app_icon_image(512).save(os.path.join(HERE, "icon.png"))
    app_icon_image(256).save(os.path.join(HERE, "icon.ico"))
    app_icon_image(1024).save(os.path.join(HERE, "icon.icns"))
    print("icons written to", HERE)


if __name__ == "__main__":
    main()
