# PyInstaller spec for Pixa.  Build with:  pyinstaller packaging/pixa.spec
# Produces dist/Pixa.app on macOS, the folder dist/Pixa/ on Windows and the single file
# dist/Pixa on Linux.
import os
import sys

HERE = os.path.dirname(os.path.abspath(SPEC))  # noqa: F821 (injected by PyInstaller)
ROOT = os.path.dirname(HERE)

# Qt modules Pixa doesn't use; excluding them keeps the executable small.
EXCLUDES = [
    # Optional extras PyMuPDF imports when present; Pixa doesn't need them.
    "tkinter", "numpy", "PIL", "lxml", "matplotlib", "pandas", "fontTools", "IPython",
    # PyMuPDF 2 installs its layout analysis (an ONNX model) and pymupdf4llm and tries to
    # import them; they add well over 100 MB and Pixa never uses them.
    "pymupdf.layout", "pymupdf4llm", "onnxruntime", "networkx",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel", "PySide6.QtWebSockets", "PySide6.QtQml", "PySide6.QtQuick",
    "PySide6.QtQuickWidgets", "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.QtNetwork", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtPdf",
    "PySide6.QtPdfWidgets", "PySide6.QtPositioning", "PySide6.QtSql", "PySide6.QtTest",
    "PySide6.QtBluetooth", "PySide6.QtSerialPort", "PySide6.QtSensors", "PySide6.QtDesigner",
    "PySide6.QtHelp", "PySide6.QtUiTools", "PySide6.QtXml", "PySide6.QtSpatialAudio",
]

a = Analysis(  # noqa: F821
    [os.path.join(HERE, "launcher.py")],
    pathex=[os.path.join(ROOT, "src")],
    hiddenimports=["PySide6.QtSvg"],
    excludes=EXCLUDES,
    noarchive=False,
)
# Qt libraries that get dragged in by plugins we don't need (QML, PDF image plugin, ...).
DROP_BINARIES = ("Qt6Quick", "Qt6Qml", "Qt6Pdf", "Qt6WebEngine", "Qt6VirtualKeyboard",
                 "Qt6OpenGL", "Qt6Network", "imageformats/libqpdf", "imageformats/qpdf",
                 "Qt63D", "Qt6Multimedia", "Qt6Charts")
a.binaries = [b for b in a.binaries if not any(d in b[0].replace(os.sep, "/") for d in DROP_BINARIES)]

pyz = PYZ(a.pure)  # noqa: F821

icon = os.path.join(HERE, "icon.icns" if sys.platform == "darwin" else "icon.ico")

if sys.platform in ("darwin", "win32"):
    # One-folder builds.  On macOS that is what an .app bundle is.  On Windows a one-file
    # executable unpacks itself to a temp folder on every start, which antivirus tools
    # flag; a plain folder (shipped by the installer, see pixa.iss) doesn't, and starts faster.
    exe = EXE(  # noqa: F821
        pyz, a.scripts, [], exclude_binaries=True, name="Pixa", console=False,
        icon=icon, upx=False,
    )
    coll = COLLECT(exe, a.binaries, a.datas, name="Pixa", upx=False)  # noqa: F821
if sys.platform == "darwin":
    app = BUNDLE(  # noqa: F821
        coll,
        name="Pixa.app",
        icon=icon,
        bundle_identifier="app.pixa.editor",
        info_plist={
            "CFBundleShortVersionString": "0.5.4",
            "NSHighResolutionCapable": True,
            # Pixa's languages (pixa/locales), so macOS shows its own dialogs in them too.
            "CFBundleLocalizations": ["en", "sv"],
            "CFBundleDocumentTypes": [{
                "CFBundleTypeName": "PDF Document",
                "CFBundleTypeRole": "Editor",
                "LSItemContentTypes": ["com.adobe.pdf"],
            }],
        },
    )
elif sys.platform != "win32":
    exe = EXE(  # noqa: F821
        pyz, a.scripts, a.binaries, a.datas, [],
        name="Pixa", console=False, icon=icon, upx=False,
    )
