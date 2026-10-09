from pathlib import Path

from app import updater
from blender.bridge_manager import BlenderBridgeManager
from core.config import Settings


def test_refresh_replaces_only_installed_addon_copies(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    blender = tmp_path / "Blender Foundation" / "Blender"
    installed = blender / "5.2" / "scripts" / "addons" / "KCD2_ModMaster_Bridge"
    installed.mkdir(parents=True)
    (installed / "stale.py").write_text("old", encoding="utf-8")
    (blender / "4.2").mkdir(parents=True)
    manager = BlenderBridgeManager(Settings(_path=tmp_path / "config.json"))

    refreshed = manager.refresh_installed_addons()

    assert refreshed == [str(installed)]
    assert not (installed / "stale.py").exists()
    assert (installed / "__init__.py").is_file()
    assert not (blender / "4.2" / "scripts").exists()


def test_installer_runs_in_place_and_relaunches(monkeypatch):
    calls = []
    monkeypatch.setattr(updater.subprocess, "Popen", lambda args, **kw: calls.append(args))
    updater.launch_installer(Path("Setup.exe"))
    assert "/VERYSILENT" in calls[0] and "/RESTARTAPPLICATIONS" not in calls[0]
    script = (Path(__file__).resolve().parents[1] / "packaging" / "installer.iss").read_text(encoding="utf-8")
    assert "Check: WizardSilent" in script
