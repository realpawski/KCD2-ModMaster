"""Owned-only transactional mod deployment with one workspace rollback snapshot."""
from __future__ import annotations

import json
import hashlib
import logging
import shutil
import struct
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from app.paths import resource_dir
from runtime_tools import REGISTRY_VERSION, RUNTIME_ID, RUNTIME_VERSION, game_catalog
from runtime_tools.packaging import hashes, mod_id, pack_data, read_spawn_descriptors, registry_lua, write_manifest

MARKER = ".modmaster-install.json"
OWNER = "KCD2 ModMaster"
log = logging.getLogger(__name__)


@dataclass
class InstallStatus:
    state: str
    version: str = ""
    details: str = ""
    registry: str = "Not synced"


class RuntimeManager:
    def __init__(self, game_dir: Path, workspace: Path, source_root: Path | None = None):
        self.game = Path(game_dir)
        self.workspace = Path(workspace)
        self.source = source_root or resource_dir("runtime/kcd2/modmaster_dev")
        self.mods = self.game / "Mods"
        self.state_root = self.workspace / "runtime"

    def _audit(self, event: str, **details) -> None:
        path = self.workspace / "logs/runtime_install.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"event": event, **details}, ensure_ascii=False) + "\n")
        log.info("Runtime %s: %s", event, details)

    @staticmethod
    def _contained(path: Path, parent: Path) -> None:
        if path.is_symlink() or path.is_junction() or not path.resolve().is_relative_to(parent.resolve()) or path.resolve() == parent.resolve():
            raise ValueError(f"Unsafe generated directory: {path}")

    def _target(self, identifier: str) -> Path:
        mod_id(identifier)
        if not (self.game / "Data").is_dir() or not (self.game / "Bin").is_dir():
            raise ValueError("Configure a KCD2 installation containing Data and Bin")
        if self.mods.is_symlink() or self.mods.is_junction():
            raise ValueError("Refusing a linked Mods directory")
        target = self.mods / identifier
        if target.is_symlink() or target.is_junction():
            raise ValueError("Refusing a linked installed mod")
        for p in target.rglob("*") if target.exists() else []:
            if p.is_symlink() or p.is_junction():
                raise ValueError(f"Refusing a linked installed file: {p}")
        if target.resolve().parent != self.mods.resolve():
            raise ValueError("Mod target escaped Mods")
        return target

    def _owned(self, target: Path, identifier: str, repair=False) -> dict:
        try:
            data = json.loads((target / MARKER).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"Refusing to overwrite/uninstall an unowned mod: {target}") from exc
        if data.get("owner") != OWNER or data.get("modid") != identifier or not isinstance(data.get("hashes"), dict):
            raise ValueError("Invalid ModMaster ownership marker")
        actual = hashes(target)
        if set(actual) - set(data["hashes"]):
            raise ValueError("Installed mod has additional files; move them out before replacing it")
        if not repair and actual != data["hashes"]:
            raise ValueError("Installed files changed: use explicit Repair or preserve your edits first")
        return data

    def _write_marker(self, built: Path, identifier: str, version: str) -> None:
        data = {"owner": OWNER, "modid": identifier, "version": version,
                "runtime_version": RUNTIME_VERSION, "registry_version": REGISTRY_VERSION,
                "hashes": hashes(built)}
        (built / MARKER).write_text(json.dumps(data, indent=2), encoding="utf-8")

    def status(self) -> InstallStatus:
        try:
            target = self._target(RUNTIME_ID)
            if not target.exists():
                return InstallStatus("Not installed")
            marker = self._owned(target, RUNTIME_ID)
            registry = json.loads((target / "modmaster_registry.json").read_text(encoding="utf-8"))
            bundled = self.source_digest()
            state = "Installed" if marker["version"] == RUNTIME_VERSION else "Update available"
            if marker.get("source_digest") != bundled:
                state = "Update available"
            count = sum(len(m["assets"]) for m in registry["mods"])
            return InstallStatus(state, marker["version"], "", f"{count:,} spawnable entries")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return InstallStatus("Repair required", details=str(exc))

    def source_digest(self) -> dict:
        return hashes(self.source)

    def _backup(self, target: Path, identifier: str) -> None:
        # Replaces one known snapshot, never creates an unbounded version history.
        backup = self.state_root / "rollback" / identifier
        backup.parent.mkdir(parents=True, exist_ok=True)
        self._contained(backup, self.workspace)
        if backup.exists():
            if backup.is_symlink() or backup.is_junction():
                raise ValueError("Linked rollback folder")
            shutil.rmtree(backup)
        shutil.copytree(target, backup)

    def install_built(self, built: Path, identifier: str, *, repair=False) -> Path:
        target = self._target(identifier)
        # A built folder must itself have a valid manifest and owned receipt.
        self._owned(built, identifier)
        from xml.etree import ElementTree as ET
        if ET.parse(built / "mod.manifest").findtext("info/modid") != identifier:
            raise ValueError("Built manifest does not match requested mod")
        self.mods.mkdir(exist_ok=True)
        if target.exists():
            self._owned(target, identifier, repair=repair)
            self._backup(target, identifier)
        incoming = self.mods / (".modmaster-stage-" + uuid.uuid4().hex)
        previous = self.mods / (".modmaster-swap-" + uuid.uuid4().hex)
        try:
            shutil.copytree(built, incoming)
            self._owned(incoming, identifier)
            if target.exists():
                target.rename(previous)
            try:
                incoming.rename(target)
            except BaseException:
                if previous.exists():
                    previous.rename(target)
                raise
            if previous.exists():
                self._contained(previous, self.mods)
                shutil.rmtree(previous)
        finally:
            if incoming.exists():
                self._contained(incoming, self.mods)
                shutil.rmtree(incoming)
        self._enable_in_existing_order(identifier)
        self._audit("installed", modid=identifier, path=str(target), restart_required=True)
        return target

    def uninstall_mod(self, identifier: str) -> bool:
        """Removes an installed mod built by ModMaster; any other mod folder is refused."""
        if identifier == RUNTIME_ID:
            raise ValueError("The in-game menu is removed under Settings > In-game menu.")
        target = self._target(identifier)
        if not target.exists():
            return False
        self._owned(target, identifier, repair=True)
        self._backup(target, identifier)
        shutil.rmtree(target)
        self._audit("mod_uninstalled", modid=identifier)
        return True

    def uninstall(self) -> None:
        target = self._target(RUNTIME_ID)
        self._owned(target, RUNTIME_ID)
        self._backup(target, RUNTIME_ID)
        shutil.rmtree(target)
        self._audit("uninstalled", modid=RUNTIME_ID)

    def _enable_in_existing_order(self, identifier):
        order = self.mods / "mod_order.txt"
        if not order.exists():
            return  # Automatic alphabetical loading remains intact.
        if order.is_symlink():
            raise ValueError("Linked mod_order.txt; enable the mod manually")
        text = order.read_text(encoding="utf-8-sig")
        if identifier in [line.strip() for line in text.splitlines()]:
            return
        # Keep one original copy; append only our exact ID, preserving unrelated lines.
        saved = self.state_root / "mod_order.previous.txt"
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_bytes(order.read_bytes())
        newline = "\r\n" if "\r\n" in text else "\n"
        updated = text + (newline if text and not text.endswith("\n") else "") + identifier + newline
        temporary = self.mods / ".modmaster-order.tmp"
        if temporary.exists():
            raise ValueError("Existing order staging file; refusing to overwrite")
        temporary.write_text(updated, encoding="utf-8", newline="")
        temporary.replace(order)
        self._audit("load_order_appended", modid=identifier)

    def rollback(self, identifier=RUNTIME_ID) -> Path:
        mod_id(identifier)
        snapshot = self.state_root / "rollback" / identifier
        if not snapshot.is_dir():
            raise ValueError("No rollback snapshot")
        # install_built replaces the snapshot, so use a stable temporary copy first.
        self.state_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.state_root) as tmp:
            stable = Path(tmp) / identifier
            shutil.copytree(snapshot, stable)
            return self.install_built(stable, identifier)

    def load_installed_registry(self) -> dict:
        registry = {"format_version": REGISTRY_VERSION, "runtime_version": RUNTIME_VERSION, "mods": []}
        try:
            catalog = game_catalog.load(self.game, self.state_root / "game_catalog.json")
            registry["mods"].append({"id": "base_game", "name": "Installed KCD2", "version": "local",
                                     "assets": catalog["assets"]})
        except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
            log.warning("Game catalog unavailable: %s", exc)
        if not self.mods.exists():
            return registry
        for target in sorted(self.mods.iterdir()):
            if not target.is_dir() or target.name == RUNTIME_ID or target.name.startswith("."):
                continue
            try:
                self._target(target.name)
                self._owned(target, target.name)
                entry = json.loads((target / "modmaster_assets.json").read_text(encoding="utf-8"))
                registry["mods"].append(entry)
            except (OSError, ValueError, KeyError):
                continue  # Unrelated mods are never imported into the owned registry.
        return registry

    def _character_tables(self, looks: list[dict]) -> dict[str, bytes]:
        """Full character tables with every creature look from installed mods, or nothing without looks."""
        from creatures.generator import CLOTHING_TABLE, COMPONENT_TABLE, merge_looks

        if not looks:
            return {}
        with zipfile.ZipFile(self.game / "Data" / "Tables.pak") as z:
            clothing = z.read(CLOTHING_TABLE).decode("utf-8-sig")
            component = z.read(COMPONENT_TABLE).decode("utf-8-sig")
        clothing, component = merge_looks(clothing, component, looks)
        self._audit("creature_looks_merged", looks=[l.get("name") for l in looks])
        return {CLOTHING_TABLE: clothing.encode("utf-8"), COMPONENT_TABLE: component.encode("utf-8")}

    def build_companion(self, registry: dict) -> Path:
        if not (self.source / "Data/Scripts/Mods/kcd_modmaster_dev.lua").is_file():
            raise ValueError("Bundled runtime source is missing")
        ui_source = self.source / "ui/ModMasterMenu.as"
        if ui_source.exists():
            try:
                built_ui = json.loads((self.source / "ui/build.json").read_text(encoding="utf-8"))
                swf = self.source / "Data/Libs/UI/ModMasterMenu.swf"
                if (built_ui["source_sha256"] != hashlib.sha256(ui_source.read_bytes()).hexdigest()
                        or built_ui["swf_sha256"] != hashlib.sha256(swf.read_bytes()).hexdigest()):
                    raise ValueError("Native UI source/artifact changed; run tools/build_runtime_ui.py first")
            except (OSError, KeyError, TypeError) as exc:
                raise ValueError("Native UI build missing; run tools/build_runtime_ui.py first") from exc
        self.state_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.state_root) as tmp:
            built = Path(tmp) / RUNTIME_ID
            built.mkdir()
            project = SimpleNamespace(id=RUNTIME_ID, name="KCD2 ModMaster In-Game Menu", author="PAWSKI",
                                      version=RUNTIME_VERSION, description="Spawn menu, freecam, noclip and god mode for KCD2 ModMaster.")
            write_manifest(built / "mod.manifest", project)
            looks = [look for mod in registry["mods"] for look in mod.pop("looks", None) or []]
            extra = {"Scripts/ModMaster/registry.lua": registry_lua(registry)}
            extra.update(self._character_tables(looks))
            pack_data(self.source / "Data", built / "Data/modmaster_dev.pak", extra)
            (built / "modmaster_registry.json").write_text(json.dumps(registry, indent=2), encoding="utf-8")
            self._write_marker(built, RUNTIME_ID, RUNTIME_VERSION)
            marker = json.loads((built / MARKER).read_text())
            marker["source_digest"] = self.source_digest()
            (built / MARKER).write_text(json.dumps(marker, indent=2), encoding="utf-8")
            destination = self.state_root / "build" / RUNTIME_ID
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                self._contained(destination, self.state_root)
                shutil.rmtree(destination)
            shutil.copytree(built, destination)
        self._audit("companion_built", registry_mods=len(registry["mods"]))
        return destination

    def sync(self, *, repair=False) -> Path:
        registry = self.load_installed_registry()
        return self.install_built(self.build_companion(registry), RUNTIME_ID, repair=repair)

    def _drop_generated_descriptors(self, root: Path) -> None:
        path = root / "runtime_assets.json"
        if not path.is_file():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            return
        kept = [a for a in data.get("assets", [])
                if not (a.get("spawn_type") == "inventory_item" and a.get("source") == "compiled_custom")]
        if len(kept) != len(data.get("assets", [])):
            data["assets"] = kept
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _stage_game_items(self, project) -> tuple[list, dict[str, bytes]]:
        from items.gamedata import GameDataUnavailable, ItemCatalog
        from items.generator import (generate_inventory_preset_xml, generate_item_xml,
                                     generate_weapon_mtl, inventory_preset_path, item_table_path)
        from items.store import ModItemStore
        from items.validator import errors_only, validate_game_item, validate_mod_items

        root = Path(project.project_dir)
        stored = ModItemStore(project, self.workspace).list()
        self._drop_generated_descriptors(root)
        stale_table = root / "game" / item_table_path(project.id)
        if stale_table.is_file():
            stale_table.unlink()
        if not stored:
            return [], {}

        try:
            catalog = ItemCatalog.load(self.game, self.workspace / "cache")
        except GameDataUnavailable as exc:
            raise ValueError(f"Item data cannot be validated: {exc}") from exc

        issues = validate_mod_items([s.item for s in stored])
        for s in stored:
            issues += validate_game_item(s.item, catalog, project.id, s.asset_dir)
        blocking = errors_only(issues)
        if blocking:
            details = "\n".join(f"  - {e}" for e in blocking)
            raise ValueError(f"Item validation failed:\n{details}")

        game_objects = root / "game" / "Objects"
        for s in stored:
            item, asset_dir = s.item, s.asset_dir
            if not item.uses_custom_model or not item.model_path or asset_dir is None:
                continue
            if (asset_dir / "compiled" / "Objects" / item.model_path).is_file():
                continue
            target_cgf = game_objects / item.model_path
            target_cgf.parent.mkdir(parents=True, exist_ok=True)
            if not target_cgf.is_file():
                for cand in (asset_dir / "source" / target_cgf.name, asset_dir / target_cgf.name,
                             asset_dir / "export" / target_cgf.name):
                    if cand.is_file():
                        shutil.copy2(cand, target_cgf)
                        break
            target_mtl = target_cgf.with_suffix(".mtl")
            if not target_mtl.is_file():
                for cand in (asset_dir / "source" / target_mtl.name, asset_dir / target_mtl.name):
                    if cand.is_file():
                        shutil.copy2(cand, target_mtl)
                        break
                else:
                    if item.item_type in ("MeleeWeapon", "MissileWeapon"):
                        target_mtl.write_text(generate_weapon_mtl(target_cgf.stem), encoding="us-ascii")
            textures = asset_dir / "textures"
            if textures.is_dir():
                for tex in textures.glob("*.dds"):
                    if not (target_cgf.parent / tex.name).exists():
                        shutil.copy2(tex, target_cgf.parent / tex.name)

        items = [s.item for s in stored]
        extra = {item_table_path(project.id): generate_item_xml(items, project.id).encode("ascii")}
        extra.update(self._item_attachments(stored, catalog))
        from items.icons import icon_dds, icon_game_path
        for item in items:
            icon = root / item.icon_image if item.icon_image else None
            if icon is not None and icon.is_file() and item.attributes.get("IconId"):
                extra[icon_game_path(item.attributes["IconId"])] = icon_dds(icon)
        preset = generate_inventory_preset_xml(items)
        if preset:
            extra[inventory_preset_path(project.id)] = preset.encode("ascii")
        return items, extra

    def _item_attachments(self, stored, catalog) -> dict[str, bytes]:
        """Compiled item models with the grip, scabbard, pickup and physics points of their base item."""
        from compiler.attachments import apply_points, graft_attachments
        from runtime_tools.animations import _game_files, _read

        result: dict[str, bytes] = {}
        files = None
        for s in stored:
            item, asset_dir = s.item, s.asset_dir
            if not item.uses_custom_model or asset_dir is None or not item.model_path:
                continue
            compiled = asset_dir / "compiled" / "Objects" / item.model_path
            base = catalog.item(item.base_guid) if item.base_guid else None
            base_model = base.attrs.get("Model", "") if base else ""
            if not compiled.is_file():
                continue
            data, added = compiled.read_bytes(), []
            if base_model.lower().endswith(".cgf"):
                files = files if files is not None else _game_files(self.game)
                source = _read(files, "Objects/" + base_model)
                try:
                    data, added = graft_attachments(data, source) if source else (data, [])
                except (ValueError, struct.error) as exc:
                    log.warning("Attachment points of %s not copied: %s", base_model, exc)
            # Points placed in Blender win over the base weapon's, so a custom grip can be fine-tuned.
            placed = asset_dir / "metadata" / "attachments.json"
            moved: list[str] = []
            if placed.is_file():
                try:
                    data, moved = apply_points(data, json.loads(placed.read_text(encoding="utf-8")))
                except (ValueError, struct.error, KeyError, TypeError) as exc:
                    log.warning("Weapon points of %s not applied: %s", item.item_id, exc)
            if added or moved:
                result["Objects/" + item.model_path] = data
                self._audit("item_attachments", item=item.item_id, base=base_model, nodes=added, placed=moved)
        return result

    def _stage_compiled_assets(self, project, items, creatures=()) -> tuple[list[dict], dict[str, bytes]]:
        from compiler import cdf_skeleton, compiled_files, compiled_models
        from workspace.asset_model import list_workspace_assets

        known = {a.asset_id: a for a in list_workspace_assets(self.workspace)}
        used_by_items = {i.workspace_asset_id for i in items if i.workspace_asset_id}
        used_by_items |= {c.workspace_asset_id for c in creatures if c.workspace_asset_id}
        entries, extra = [], {}
        for asset_id in list(dict.fromkeys(list(project.assets) + sorted(used_by_items))):
            asset = known.get(asset_id)
            asset_dir = Path(asset.workspace_dir) if asset else self.workspace / "Assets" / asset_id
            models = compiled_models(asset_dir)
            if not models:
                if asset_id in used_by_items:
                    continue
                name = asset.name if asset else asset_id
                raise ValueError(f"{name} has no compiled model yet. In Blender, use Export to KCD2 (.cgf), "
                                 "or remove the asset from this mod.")
            for path, file in compiled_files(asset_dir).items():
                data = file.read_bytes()
                extra[path] = self._fix_cdf(data) if path.lower().endswith(".cdf") else data
            if asset_id not in project.assets:
                continue
            for model in models:
                stem = Path(model).stem
                suffix = Path(model).suffix.lower().lstrip(".")
                entry = {"id": asset_id if len(models) == 1 else f"{asset_id}_{stem}_{suffix}",
                         "name": asset.name if asset else asset_id, "category": "props",
                         "spawn_type": "static_prop", "spawn_id": f"{project.id}:{asset_id}",
                         "model_path": model, "status": "packaged_unverified",
                         "lods": [], "physics": False, "source": "compiled_custom"}
                if model.lower().endswith(".cdf"):
                    entry["animation"] = self._idle_animation(self._skeleton(cdf_skeleton(asset_dir / "compiled" / model)))
                entries.append(entry)
        return entries, extra

    def _skeleton(self, model: str) -> str:
        from runtime_tools.animations import resolve_skeleton
        if not model or model.lower().endswith(".chr"):
            return model
        if not hasattr(self, "_skeletons"):
            self._skeletons = {}
        if model not in self._skeletons:
            try:
                self._skeletons[model] = resolve_skeleton(self.game, model)
            except OSError as exc:
                log.warning("Skeleton for %s unavailable: %s", model, exc)
                self._skeletons[model] = ""
        return self._skeletons[model]

    def _fix_cdf(self, data: bytes) -> bytes:
        """A character definition must name a .chr skeleton; older exports wrote the .skin there."""
        from xml.etree import ElementTree as ET
        try:
            root = ET.fromstring(data)
        except ET.ParseError:
            return data
        model = root.find("Model")
        current = model.get("File", "") if model is not None else ""
        skeleton = self._skeleton(current)
        if not skeleton or skeleton == current:
            return data
        model.set("File", skeleton)
        return ET.tostring(root, encoding="utf-8")

    def _idle_animation(self, skeleton: str) -> str:
        from runtime_tools.animations import animation_names, default_animation
        if not skeleton:
            return ""
        try:
            return default_animation(animation_names(self.game, skeleton))
        except (OSError, ValueError) as exc:
            log.warning("Animations of %s unavailable: %s", skeleton, exc)
            return ""

    def creature_bodies(self) -> dict:
        from creatures.gamedata import load_bodies
        return {b.entity_class: b for b in load_bodies(self.game, self.workspace / "cache" / "creature_bodies.json")}

    def model_skeletons(self) -> dict[str, str]:
        """Compiled .cdf game path -> skeleton, for every workspace asset."""
        from compiler import cdf_skeleton, compiled_models

        result = {}
        assets = self.workspace / "Assets"
        for asset_dir in sorted(assets.iterdir()) if assets.is_dir() else []:
            for model in compiled_models(asset_dir, kinds=(".cdf",)):
                result[model] = self._skeleton(cdf_skeleton(asset_dir / "compiled" / model))
        return result

    def _stage_creatures(self, project) -> tuple[list, list[dict], dict[str, bytes]]:
        from creatures import generator
        from creatures.store import CreatureStore

        creatures = CreatureStore(project).list()
        if not creatures:
            return [], [], {}
        bodies = self.creature_bodies()
        issues = generator.validate(creatures, bodies, self.model_skeletons())
        errors = [f"  - {name}: {message}" for severity, name, message in issues if severity == generator.ERROR]
        if errors:
            raise ValueError("Creature check failed:\n" + "\n".join(errors))
        extra = {generator.soul_table_path(project.id):
                 generator.generate_soul_xml(project.id, creatures, bodies).encode("ascii")}
        looks: list[dict] = []
        for c in creatures:
            body = bodies[c.base_class]
            if not generator.custom_look(c, body):
                continue
            skin, material, files = self._creature_skin(c.model_path)
            folder = f"modmaster/{generator.clothing_name(project.id, c)}/"
            # Bodies are looked up under Objects/Characters/, so the skin is packed there as well.
            for name, data in files.items():
                extra[f"Objects/Characters/{folder}{name}"] = data
            looks.append(generator.look_rows(project.id, c, body, folder, skin, material))
        self._looks = looks
        entries = [generator.registry_entry(project.id, c, bodies[c.base_class], self._gaits(bodies[c.base_class].skeleton))
                   for c in creatures]
        return creatures, entries, extra

    def _gaits(self, skeleton: str) -> dict[str, str]:
        from runtime_tools.animations import animation_names, gaits
        if not skeleton:
            return {}
        try:
            return gaits(animation_names(self.game, skeleton))
        except (OSError, ValueError) as exc:
            log.warning("Animations of %s unavailable: %s", skeleton, exc)
            return {}

    def _creature_skin(self, model_path: str) -> tuple[str, str, dict[str, bytes]]:
        """The skin and material a compiled .cdf binds, as (skin name, material name, files)."""
        from compiler import compiled_files
        from xml.etree import ElementTree as ET

        assets = self.workspace / "Assets"
        for asset_dir in sorted(assets.iterdir()) if assets.is_dir() else []:
            files = compiled_files(asset_dir)
            if model_path not in files:
                continue
            root = ET.parse(files[model_path]).getroot()
            skin = next((a for a in root.iter("Attachment") if a.get("Type", "").upper() == "CA_SKIN"), None)
            if skin is None or skin.get("Binding") not in files:
                raise ValueError(f"{model_path} names no exported skin; export it again as Rigged.")
            result = {Path(skin.get("Binding")).name: files[skin.get("Binding")].read_bytes()}
            material = skin.get("Material", "")
            if material in files:
                result[Path(material).name] = files[material].read_bytes()
            return Path(skin.get("Binding")).name, Path(material).name, result
        raise ValueError(f"{model_path} is not exported. Export the asset as Rigged from Blender.")

    @staticmethod
    def _item_registry_entry(item) -> dict:
        from items.fields import RUNTIME_CATEGORY
        # Prefixed so an item never collides with the prop entry of the asset that gives it its model.
        return {"id": "item:" + item.item_id, "name": item.display_name or item.name,
                "category": RUNTIME_CATEGORY.get(item.item_type, "items"),
                "spawn_type": "inventory_item", "item_guid": item.guid,
                "status": "packaged_unverified", "source": "compiled_custom"}

    def build_project(self, project) -> Path:
        mod_id(project.id)
        items, extra = self._stage_game_items(project)
        self._looks = []
        creatures, creature_entries, creature_files = self._stage_creatures(project)
        props, compiled = self._stage_compiled_assets(project, items, creatures)
        extra = {**compiled, **extra, **creature_files}
        assets = (read_spawn_descriptors(project) + props + [self._item_registry_entry(i) for i in items]
                  + creature_entries)
        entry = {"id": project.id, "name": project.name, "version": project.version, "assets": assets}
        if self._looks:
            entry["looks"] = self._looks
        root = Path(project.project_dir)
        if root.is_symlink() or root.is_junction():
            raise ValueError("Linked project directory")
        build_parent = root / "build"
        build_parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=build_parent) as tmp:
            built = Path(tmp) / project.id
            built.mkdir()
            pack_data(root / "game", built / f"Data/{project.id}.pak", extra)
            if items:
                from items.generator import build_localization_pak
                build_localization_pak(items, built / "Localization" / "English_xml.pak", project.id)
            self._version_for_content(project, built, entry)
            entry["version"] = project.version
            write_manifest(built / "mod.manifest", project)
            (built / "modmaster_assets.json").write_text(json.dumps(entry, indent=2), encoding="utf-8")
            self._write_marker(built, project.id, project.version)
            destination = build_parent / project.id
            if destination.exists():
                self._contained(destination, root)
                shutil.rmtree(destination)
            shutil.copytree(built, destination)
        self._audit("project_built", modid=project.id, assets=len(assets), items=len(items))
        return destination

    @staticmethod
    def _version_for_content(project, built: Path, entry: dict) -> None:
        """Raises the patch version when the mod's content differs from its last build."""
        from mods.project import next_patch_version

        digest = hashlib.sha256()
        for pak in sorted(built.rglob("*.pak")):
            digest.update(pak.relative_to(built).as_posix().encode())
            digest.update(pak.read_bytes())
        digest.update(json.dumps({k: v for k, v in entry.items() if k != "version"}, sort_keys=True).encode())
        content = digest.hexdigest()
        previous = getattr(project, "build_digest", "")
        if content == previous:
            return
        if previous and hasattr(project, "save"):
            project.version = next_patch_version(project.version)
        project.build_digest = content
        if hasattr(project, "save"):
            project.save()

    def build_install(self, project) -> Path:
        built = self.build_project(project)
        target = self.install_built(built, project.id)
        try:
            self.sync()
        except Exception as exc:
            self._audit("registry_sync_failed", modid=project.id, error=str(exc))
            raise RuntimeError(f"Mod installed, but registry sync failed: {exc}") from exc
        return target
