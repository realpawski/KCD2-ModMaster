# PyInstaller spec, run through tools/build_release.py.
from pathlib import Path

ROOT = Path(SPECPATH).parent
SRC = ROOT / "src"

datas = [
    (str(ROOT / "runtime/kcd2/modmaster_dev/Data"), "runtime/kcd2/modmaster_dev/Data"),
    (str(ROOT / "runtime/kcd2/modmaster_dev/ui"), "runtime/kcd2/modmaster_dev/ui"),
    (str(ROOT / "runtime/kcd2/modmaster_dev/version.json"), "runtime/kcd2/modmaster_dev"),
    (str(SRC / "blender/addon"), "blender/addon"),
    (str(SRC / "ui/assets"), "ui/assets"),
]

a = Analysis(
    [str(SRC / "app/main.py")],
    pathex=[str(SRC)],
    datas=datas,
    hiddenimports=["OpenGL.platform.win32", "OpenGL.arrays.numpymodule", "OpenGL.arrays.ctypesarrays"],
    excludes=["tkinter", "pytest", "fontTools", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
              "PySide6.QtQuick", "PySide6.QtQml", "PySide6.Qt3DCore", "PySide6.QtMultimedia",
              "PySide6.QtPdf", "PySide6.QtCharts", "PySide6.QtDataVisualization"],
    noarchive=False,
)

# English-only UI without Quick/QML/PDF: drop what Qt plugins pull in anyway.
DROP = ("translations", "qt6quick", "qt6qml", "qt6pdf", "qpdf", "qt6virtualkeyboard")
a.binaries = [b for b in a.binaries if not any(d in b[0].lower().replace("\\", "/") for d in DROP)]
a.datas = [d for d in a.datas if not any(x in d[0].lower().replace("\\", "/") for x in DROP)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="KCD2ModMaster",
    icon=str(ROOT / "packaging/modmaster.ico"),
    version=str(ROOT / "build/version_info.txt"),
    console=False,
    upx=False,
)

coll = COLLECT(exe, a.binaries, a.datas, name="KCD2ModMaster", upx=False)
