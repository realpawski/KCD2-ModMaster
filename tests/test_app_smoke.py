"""Every module imports and the main window builds with a fresh configuration."""
import importlib
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
SKIP = ("blender.addon",)


def _modules():
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).with_suffix("")
        name = ".".join(rel.parts)
        if name.endswith("__init__"):
            name = name[: -len(".__init__")]
        if name and not name.startswith(SKIP):
            yield name


@pytest.mark.parametrize("name", list(_modules()))
def test_module_imports(name):
    importlib.import_module(name)


def test_main_window_builds_and_navigates(tmp_path, qapp):
    from core.config import Settings
    from ui.main_window import MainWindow

    game = tmp_path / "game"
    game.mkdir()
    settings = Settings(workspace_dir=str(tmp_path / "ws"), game_dir=str(game), window_geometry="00")
    settings._path = tmp_path / "config.json"
    window = MainWindow(settings)
    for key in ("home", "browser", "weapons", "mods", "my_assets", "settings", "build"):
        window._on_navigate(key, {})
    for key in ("game", "index", "ingame", "blender", "updates", "about"):
        window.settings_page.show_section(key)
    window.close()
    window.deleteLater()
    qapp.processEvents()
