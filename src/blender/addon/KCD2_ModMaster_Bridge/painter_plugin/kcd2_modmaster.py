"""KCD2 ModMaster for Substance 3D Painter: exports textures where ModMaster's Blender add-on picks them up.

Installed by the Blender add-on's Open in Substance Painter button. Enable it once under Python > kcd2_modmaster.
"""
from pathlib import Path

import substance_painter.export
import substance_painter.project
import substance_painter.textureset
import substance_painter.ui

try:
    from PySide6 import QtGui, QtWidgets
except ImportError:  # Painter versions before 10
    from PySide2 import QtGui, QtWidgets

_elements = []


def _rgb(name):
    return [{"destChannel": c, "srcChannel": c, "srcMapType": "documentMap", "srcMapName": name} for c in "RGB"]


def _gray(name, map_type="documentMap"):
    return [{"destChannel": "L", "srcChannel": "L", "srcMapType": map_type, "srcMapName": name}]


PRESET = {
    "name": "KCD2 ModMaster",
    "maps": [
        {"fileName": "$textureSet_BaseColor", "channels": _rgb("baseColor")},
        {"fileName": "$textureSet_Normal",
         "channels": [{"destChannel": c, "srcChannel": c, "srcMapType": "virtualMap", "srcMapName": "Normal_DirectX"}
                      for c in "RGB"]},
        {"fileName": "$textureSet_Roughness", "channels": _gray("roughness")},
        {"fileName": "$textureSet_Metallic", "channels": _gray("metallic")},
    ],
}


def export_folder():
    """The textures folder next to the mesh ModMaster sent over."""
    mesh = substance_painter.project.last_imported_mesh_path()
    return Path(mesh).parent / "textures" if mesh else None


def export_for_modmaster():
    parent = substance_painter.ui.get_main_window()
    if not substance_painter.project.is_open():
        QtWidgets.QMessageBox.warning(parent, "KCD2 ModMaster", "Open a project first.")
        return
    folder = export_folder()
    if folder is None:
        QtWidgets.QMessageBox.warning(parent, "KCD2 ModMaster",
                                      "This project was not started from ModMaster's Blender add-on.")
        return
    folder.mkdir(parents=True, exist_ok=True)
    config = {
        "exportShaderParams": False,
        "exportPath": str(folder),
        "defaultExportPreset": PRESET["name"],
        "exportPresets": [PRESET],
        "exportList": [{"rootPath": ts.name()} for ts in substance_painter.textureset.all_texture_sets()],
        "exportParameters": [{"parameters": {"fileFormat": "png", "bitDepth": "8", "dithering": True,
                                             "paddingAlgorithm": "infinite"}}],
    }
    result = substance_painter.export.export_project_textures(config)
    files = [f for maps in (result.textures or {}).values() for f in maps]
    if result.status != substance_painter.export.ExportStatus.Success:
        QtWidgets.QMessageBox.warning(parent, "KCD2 ModMaster", f"Export failed: {result.message}")
        return
    QtWidgets.QMessageBox.information(
        parent, "KCD2 ModMaster",
        f"{len(files)} textures exported to\n{folder}\n\nIn Blender, click IMPORT SUBSTANCE TEXTURES, "
        "then EXPORT TO KCD2.")


def start_plugin():
    action = QtGui.QAction("Export for KCD2 ModMaster") if hasattr(QtGui, "QAction") else \
        QtWidgets.QAction("Export for KCD2 ModMaster")
    action.triggered.connect(export_for_modmaster)
    substance_painter.ui.add_action(substance_painter.ui.ApplicationMenu.File, action)
    _elements.append(action)


def close_plugin():
    for element in _elements:
        substance_painter.ui.delete_ui_element(element)
    _elements.clear()


if __name__ == "__main__":
    start_plugin()
