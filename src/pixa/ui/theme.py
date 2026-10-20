"""Light and dark themes: a Fusion palette plus a stylesheet."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

from pixa.ui import icons


@dataclass(frozen=True)
class Theme:
    name: str
    bg: str  # window background
    surface: str  # panels, toolbar
    canvas: str  # area behind pages
    border: str
    text: str
    muted: str
    accent: str
    accent_text: str
    hover: str
    selection: str  # translucent overlay colour for hover boxes, rgba()


LIGHT = Theme(
    name="light",
    bg="#f4f5f7",
    surface="#ffffff",
    canvas="#e9ebef",
    border="#dfe2e7",
    text="#1d2330",
    muted="#6b7280",
    accent="#4f6bed",
    accent_text="#ffffff",
    hover="#eef1f6",
    selection="rgba(79, 107, 237, 0.16)",
)

DARK = Theme(
    name="dark",
    bg="#16181d",
    surface="#1f2228",
    canvas="#121418",
    border="#2d313a",
    text="#e6e8ec",
    muted="#9aa1ad",
    accent="#7b8cff",
    accent_text="#0e1014",
    hover="#2a2e37",
    selection="rgba(123, 140, 255, 0.22)",
)


def system_prefers_dark() -> bool:
    hints = QGuiApplication.styleHints()
    try:
        return hints.colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:  # Qt < 6.5
        return QGuiApplication.palette().window().color().lightness() < 128


_current: Theme = LIGHT


def current() -> Theme:
    """The theme applied last."""
    return _current


def _image(name: str, color: str, opacity: float = 1.0) -> str:
    """Path of an icon as a PNG file, for the stylesheet (which can only point at files)."""
    folder = Path(tempfile.gettempdir()) / "pixa-theme"
    folder.mkdir(exist_ok=True)
    path = folder / f"{name}-{color.lstrip('#')}-{round(opacity * 100)}.png"
    icons.pixmap(name, color, 32, opacity).save(str(path), "PNG")
    return path.as_posix()


def stylesheet(t: Theme) -> str:
    return f"""
QMainWindow, QDialog {{ background: {t.bg}; color: {t.text}; }}
QWidget {{ color: {t.text}; }}
QToolTip {{
    background: {t.surface}; color: {t.text}; border: 1px solid {t.border};
    padding: 4px 8px; border-radius: 6px;
}}

QToolBar#MainToolbar {{
    background: {t.surface}; border: none; border-bottom: 1px solid {t.border};
    padding: 6px 10px; spacing: 2px;
}}
QToolBar#MainToolbar QToolButton {{
    background: transparent; border: none; border-radius: 8px;
    padding: 6px; margin: 0 1px;
}}
QToolBar#MainToolbar QToolButton:hover {{ background: {t.hover}; }}
QToolBar#MainToolbar QToolButton:checked {{ background: {t.selection}; }}
QToolBar#MainToolbar QToolButton:disabled {{ background: transparent; }}
QToolBar::separator {{ background: {t.border}; width: 1px; margin: 6px 8px; }}
QLabel#ZoomLabel {{ color: {t.muted}; min-width: 48px; qproperty-alignment: AlignCenter; }}
QLabel#DocTitle {{ font-weight: 600; padding: 0 8px; }}

QListWidget#Thumbnails {{
    background: {t.surface}; border: none; border-right: 1px solid {t.border};
    padding: 8px 4px; outline: none;
}}
QListWidget#Thumbnails::item {{
    border-radius: 8px; padding: 6px; margin: 2px 6px; color: {t.muted};
}}
QListWidget#Thumbnails::item:hover {{ background: {t.hover}; }}
QListWidget#Thumbnails::item:selected {{ background: {t.selection}; color: {t.text}; }}

QGraphicsView#PageView {{ background: {t.canvas}; border: none; }}

QWidget#Inspector {{ background: {t.surface}; border-left: 1px solid {t.border}; }}
QScrollArea#InspectorScroll, QWidget#InspectorContent {{ background: transparent; }}
QLabel[role="heading"] {{
    color: {t.muted}; font-size: 11px; font-weight: 700; letter-spacing: 0.6px;
    padding-top: 10px;
}}
QLabel[role="hint"] {{ color: {t.muted}; }}

QPushButton, QComboBox, QDoubleSpinBox, QSpinBox, QLineEdit {{
    background: {t.bg}; border: 1px solid {t.border}; border-radius: 8px;
    padding: 6px 10px; min-height: 18px;
}}
QPushButton:hover, QComboBox:hover, QDoubleSpinBox:hover, QSpinBox:hover, QLineEdit:hover {{
    background: {t.hover};
}}
QPushButton:pressed {{ background: {t.selection}; }}
QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus, QLineEdit:focus {{
    border-color: {t.accent};
}}
QPushButton:checked {{ background: {t.selection}; border-color: {t.accent}; }}
QPushButton:disabled, QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
    color: {t.muted};
}}
QPushButton[iconButton="true"] {{ padding: 6px; }}
QPushButton[primary="true"] {{
    background: {t.accent}; color: {t.accent_text}; border: none; font-weight: 600;
    padding: 6px 18px;
}}
QPushButton[primary="true"]:hover {{ background: {t.accent}; }}
QPushButton[primary="true"]:disabled {{ background: {t.border}; color: {t.muted}; }}
QDialog QPushButton {{ min-width: 64px; }}
QDialog QPushButton[iconButton="true"] {{ min-width: 0; }}
QComboBox {{ padding-right: 4px; }}
QComboBox::drop-down {{
    subcontrol-origin: padding; subcontrol-position: center right; width: 26px;
    border: none; border-left: 1px solid {t.border};
}}
QComboBox::down-arrow {{ image: url({_image("chevron", t.text)}); width: 12px; height: 12px; }}
QComboBox:disabled {{ color: {t.muted}; }}
QComboBox QAbstractItemView {{
    background: {t.surface}; border: 1px solid {t.border}; selection-background-color:
    {t.selection}; selection-color: {t.text}; outline: none;
}}

QSpinBox, QDoubleSpinBox {{ padding-right: 24px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border; width: 22px; border: none; border-left: 1px solid {t.border};
    background: transparent;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-position: top right; border-top-right-radius: 8px;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-position: bottom right; border-bottom-right-radius: 8px;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{ background: {t.selection}; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: url({_image("chevron-up", t.text)}); width: 10px; height: 10px;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: url({_image("chevron", t.text)}); width: 10px; height: 10px;
}}
QSpinBox::up-arrow:disabled, QDoubleSpinBox::up-arrow:disabled,
QSpinBox::up-arrow:off, QDoubleSpinBox::up-arrow:off {{
    image: url({_image("chevron-up", t.text, 0.3)});
}}
QSpinBox::down-arrow:disabled, QDoubleSpinBox::down-arrow:disabled,
QSpinBox::down-arrow:off, QDoubleSpinBox::down-arrow:off {{
    image: url({_image("chevron", t.text, 0.3)});
}}
QSpinBox[stepped="true"], QDoubleSpinBox[stepped="true"] {{ padding: 6px 6px; }}
QSpinBox[stepped="true"]::up-button, QDoubleSpinBox[stepped="true"]::up-button,
QSpinBox[stepped="true"]::down-button, QDoubleSpinBox[stepped="true"]::down-button {{
    width: 0; height: 0; border: none; border-radius: 0; background: transparent;
}}
QSpinBox[stepped="true"]::up-arrow, QDoubleSpinBox[stepped="true"]::up-arrow,
QSpinBox[stepped="true"]::down-arrow, QDoubleSpinBox[stepped="true"]::down-arrow {{
    image: none; width: 0; height: 0;
}}

QCheckBox, QRadioButton {{ spacing: 8px; background: transparent; }}
QCheckBox:disabled, QRadioButton:disabled {{ color: {t.muted}; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px; height: 16px; background: {t.bg}; border: 1.5px solid {t.muted};
}}
QCheckBox::indicator {{ border-radius: 5px; }}
QRadioButton::indicator {{ border-radius: 9px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {t.accent}; }}
QCheckBox::indicator:checked {{
    background: {t.accent}; border-color: {t.accent};
    image: url({_image("check", t.accent_text)});
}}
QRadioButton::indicator:checked {{
    background: {t.accent}; border-color: {t.accent};
    image: url({_image("dot", t.accent_text)});
}}
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{
    background: {t.hover}; border-color: {t.border};
}}
QCheckBox::indicator:checked:disabled, QRadioButton::indicator:checked:disabled {{
    background: {t.border}; border-color: {t.border};
}}

QGroupBox {{
    background: {t.surface}; border: 1px solid {t.border}; border-radius: 10px;
    margin-top: 24px; padding: 12px 12px 10px 12px;
}}
QGroupBox::title {{
    subcontrol-origin: margin; subcontrol-position: top left; left: 2px; padding: 0 0 6px 0;
    color: {t.muted}; font-size: 11px; font-weight: 700; letter-spacing: 0.6px;
}}

QDialog QToolBar {{
    background: {t.surface}; border: none; border-bottom: 1px solid {t.border};
    padding: 6px 10px; spacing: 2px;
}}
QDialog QToolBar QToolButton {{
    background: transparent; border: none; border-radius: 8px; padding: 5px 8px;
}}
QDialog QToolBar QToolButton:hover {{ background: {t.hover}; }}
QDialog QToolBar QToolButton:checked {{ background: {t.selection}; color: {t.text}; }}
QDialog QToolBar QToolButton:disabled {{ color: {t.muted}; }}
QFrame#PreviewFrame {{
    background: {t.canvas}; border: 1px solid {t.border}; border-radius: 10px;
}}
QLabel#PreviewInfo {{ color: {t.muted}; }}

QWidget#Welcome {{ background: {t.canvas}; }}
QLabel#WelcomeTitle {{ font-size: 26px; font-weight: 700; }}
QLabel#WelcomeText {{ color: {t.muted}; font-size: 14px; }}
QPushButton#RecentLink {{
    border: none; background: transparent; color: {t.accent}; padding: 2px 6px;
}}
QPushButton#RecentLink:hover {{ text-decoration: underline; }}
QFrame#DropZone {{
    border: 2px dashed {t.border}; border-radius: 16px; background: {t.surface};
}}

QStatusBar {{ background: {t.surface}; border-top: 1px solid {t.border}; color: {t.muted}; }}
QStatusBar::item {{ border: none; }}

QMenuBar {{ background: {t.surface}; }}
QMenuBar::item:selected {{ background: {t.hover}; border-radius: 4px; }}
QMenu {{
    background: {t.surface}; border: 1px solid {t.border}; border-radius: 8px; padding: 4px;
}}
QMenu::item {{ padding: 6px 24px 6px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {t.selection}; }}
QMenu::separator {{ height: 1px; background: {t.border}; margin: 4px 8px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle {{ background: {t.border}; border-radius: 4px; min-height: 30px;
    min-width: 30px; }}
QScrollBar::handle:hover {{ background: {t.muted}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QSplitter::handle {{ background: {t.border}; }}
"""


def apply(app: QApplication, t: Theme) -> None:
    global _current
    _current = t
    app.setStyle("Fusion")
    font = app.font()
    font.setPixelSize(13)
    app.setFont(font)
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(t.bg))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(t.text))
    pal.setColor(QPalette.ColorRole.Base, QColor(t.surface))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(t.hover))
    pal.setColor(QPalette.ColorRole.Text, QColor(t.text))
    pal.setColor(QPalette.ColorRole.Button, QColor(t.surface))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(t.text))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(t.accent))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(t.accent_text))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(t.surface))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor(t.text))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(t.muted))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText,
                 QPalette.ColorRole.WindowText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor(t.muted))
    app.setPalette(pal)
    app.setStyleSheet(stylesheet(t))
