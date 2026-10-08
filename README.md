<div align="center">

# KCD2 ModMaster

A desktop workbench for modding **Kingdom Come: Deliverance II**.
Browse the game's files, create and balance items, and install mods without touching a single XML file by hand.

[![Release](https://img.shields.io/github/v/release/realpawski/KCD2-ModMaster?include_prereleases&label=release&color=d6a54e)](https://github.com/realpawski/KCD2-ModMaster/releases)
[![Python](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Qt](https://img.shields.io/badge/UI-PySide6%20%2F%20Qt%206-41CD52?logo=qt&logoColor=white)](https://doc.qt.io/qtforpython-6/)
[![Lua](https://img.shields.io/badge/in--game-Lua%20%2B%20Scaleform-2C2D72?logo=lua&logoColor=white)](#in-game-menu)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0078D6?logo=windows&logoColor=white)](#requirements)
[![Status](https://img.shields.io/badge/status-beta-e88a4c)](#beta-status)
[![License](https://img.shields.io/github/license/realpawski/KCD2-ModMaster?color=6aa7e6)](LICENSE)

</div>

---

## What it does

**Item editor.** Start from any of the game's ~5,600 items, or change an existing one. Every attribute the game accepts for that item type is editable: attack, defense, stab/slash/blunt multipliers, strength and agility requirements, durability, weight, price and more. Values are shown next to the vanilla range and the base item, and each change is validated live against the item schema of your installed game. Items stay editable after they are built.

**Mods.** Group items and assets into mods, then build and install them into the game's `Mods` folder in one step. ModMaster writes the item tables, localization and starting inventory for you, keeps a rollback copy, and only ever replaces folders it created itself.

**Asset browser.** Search all archives of the game, inspect models in a 3D viewport, and view textures, materials and tables. Archives are read in place and never modified.

**Blender bridge.** Open game models in Blender with materials rebuilt and edit them. *Export to KCD2* compiles anything in your scene, from game models to your own FBX or OBJ imports, into a game-ready `.cgf` with material and textures. Add it to a mod and it shows up in the in-game spawn menu or as the model of a new item.

**In-game menu.** An optional companion mod adds a menu to the game for spawning props and items, plus freecam, noclip and god mode for testing your work.

## Requirements

- Windows 10 or 11, 64-bit
- Kingdom Come: Deliverance II (Steam)
- Optional: [Blender](https://www.blender.org/) 4.2 or newer for the Blender bridge
- Optional: KCD2 Blender Toolkit for 3D model previews
- Optional: KCD2 Modding Tools (free on Steam) to compile your own models

## Installation

1. Download `KCD2ModMaster-<version>-Setup.exe` from the [latest release](https://github.com/realpawski/KCD2-ModMaster/releases).
2. Run the installer. No administrator rights are needed.
3. Start ModMaster. It finds the game automatically in most Steam setups; otherwise set the folder in **Settings**.

ModMaster checks GitHub for new versions on start. Updates are verified against the published SHA-256 checksum before the installer runs. To remove ModMaster, use **Windows Settings > Apps**. Your workspace in `Documents\KCD2 ModMaster` is never deleted by the uninstaller.

## Getting started

1. **Index the game files** on the Home page. Repeat this after game updates.
2. **Create a mod** under **Mods > New mod**.
3. **Add an item.** Pick a type, choose a base item from the game, give it a name and adjust its values.
4. **Build & install**, then start the game. New items can be added to Henry's starting inventory in new games, or spawned at any time from the in-game menu.

## In-game menu

Install it from **Settings > In-game menu**. It lives in its own folder under `Mods` and can be removed from the same page.

| Key | Action |
| --- | --- |
| `F5` | Open or close the menu |
| `F4` | Toggle noclip |
| `W` `A` `S` `D` / `Q` `E` | Move in freecam and noclip |
| `Shift` / `Ctrl` | Move faster / slower |

Restart the game after installing or updating the menu.

## Building from source

```bash
git clone https://github.com/realpawski/KCD2-ModMaster.git
cd KCD2-ModMaster
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
python run_modmaster.py
```

Run the tests with `pytest`. To build the installer, install [Inno Setup 6](https://jrsoftware.org/isinfo.php) and run:

```bash
python tools/build_release.py
```

This produces `dist/KCD2ModMaster-<version>-Setup.exe` and the matching `SHA256SUMS.txt` to attach to a GitHub release.

### Project layout

```
src/
  app/            entry point, version, updater
  items/          item schema from the game, editor model, validation, XML generation
  mods/           mod projects
  runtime_tools/  building, packing and installing mods, in-game menu
  archives/       read-only .pak access and the asset index
  preview/        model conversion and 3D preview
  blender/        Blender bridge and add-on
  ui/             PySide6 interface
runtime/          in-game menu (Lua, Scaleform UI)
packaging/        PyInstaller spec, Inno Setup script, icon
tools/            release and menu build scripts
tests/
```

## Beta status

This is the first public beta. The item editor, mod builds and the installer are complete; some in-game features still need wider testing across game versions. Please report problems on the [issue tracker](https://github.com/realpawski/KCD2-ModMaster/issues) and include the log from **Settings > About > Open log folder**.

Back up your saves before testing modified items. Removing a mod that added items to a save can leave missing items behind.

## License

[MIT](LICENSE). The in-game menu embeds glyphs from [Inter](https://rsms.me/inter/) under the SIL Open Font License 1.1, see [third-party notices](THIRD_PARTY_NOTICES.md).

## Disclaimer

KCD2 ModMaster is a fan-made tool and is not affiliated with or endorsed by Warhorse Studios or Deep Silver. It reads the files of your own copy of the game and does not distribute any game data. Kingdom Come: Deliverance is a trademark of its respective owners.

---

<div align="center">

Made by [PAWSKI](https://realpawski.de/releases/)

</div>
