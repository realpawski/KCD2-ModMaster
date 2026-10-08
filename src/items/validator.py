"""Checks item definitions against the game's own item schema before building."""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from items.fields import field_info
from items.gamedata import NCNAME, ItemCatalog
from items.models import MODE_OVERRIDE, GameItemDefinition

ERROR = "error"
WARNING = "warning"
MOD_ID = re.compile(r"^[a-z][a-z_]{0,63}$")


@dataclass
class ItemValidationError:
    check_name: str
    message: str
    severity: str = ERROR
    attribute: str = ""

    def __str__(self) -> str:
        return f"[{self.check_name}] {self.message}"


def errors_only(issues: Sequence[ItemValidationError]) -> list[ItemValidationError]:
    return [i for i in issues if i.severity == ERROR]


def _custom_model_found(item: GameItemDefinition, asset_dir: Path | None) -> bool:
    if not asset_dir or not item.model_path:
        return False
    name = Path(item.model_path).name
    for candidate in (asset_dir / "source" / name, asset_dir / name, asset_dir / "export" / name):
        if candidate.is_file() and candidate.read_bytes()[:4] == b"CrCh":
            return True
    return False


def validate_game_item(item: GameItemDefinition, catalog: ItemCatalog | None,
                       mod_id: str = "", asset_dir: Path | None = None) -> list[ItemValidationError]:
    issues: list[ItemValidationError] = []

    def err(check, msg, attr=""):
        issues.append(ItemValidationError(check, msg, ERROR, attr))

    def warn(check, msg, attr=""):
        issues.append(ItemValidationError(check, msg, WARNING, attr))

    if mod_id and not MOD_ID.fullmatch(mod_id):
        err("Mod ID", f"'{mod_id}' is not a valid KCD2 mod ID (lowercase letters and underscores).")

    try:
        canonical = str(uuid.UUID(item.guid)).lower() == item.guid
    except (ValueError, AttributeError, TypeError):
        canonical = False
    if not canonical:
        err("GUID", f"'{item.guid}' is not a canonical lowercase GUID.")

    if not NCNAME.fullmatch(item.name or ""):
        err("Name", f"Internal name '{item.name}' may only contain letters, digits, '_', '-' and '.'.")

    if item.mode != MODE_OVERRIDE and not item.display_name.strip():
        err("Display name", "New items need a display name, otherwise the inventory shows a raw key.")

    if catalog is None:
        err("Game data", "Game data is not available. Set the KCD2 install folder in Settings.")
        return issues

    schema = catalog.schema(item.item_type)
    if schema is None:
        err("Item type", f"'{item.item_type}' is not an item type of this game version.")
        return issues

    base = catalog.item(item.guid)
    if item.mode == MODE_OVERRIDE:
        if base is None:
            err("Override", "The item to override no longer exists in the game data.")
        elif base.tag != item.item_type:
            err("Override", f"The original item is a {base.tag}, not a {item.item_type}.")
    else:
        if base is not None:
            err("GUID", f"GUID is already used by the vanilla item '{base.label}'.")
        clash = catalog.by_name(item.name)
        if clash is not None:
            err("Name", f"Internal name '{item.name}' is already used by '{clash.label}'.")

    attrs = item.xml_attributes()
    for name in attrs:
        if name not in schema.attrs:
            err("Schema", f"'{name}' is not a valid attribute for {item.item_type}. "
                          "The game would refuse to load the item table.", name)
    for name in schema.required:
        if not str(attrs.get(name, "")).strip():
            err("Schema", f"Required attribute '{name}' is missing.", name)

    for name, value in attrs.items():
        spec = schema.attrs.get(name)
        if spec is None or name in ("Id", "Name"):
            continue
        label = field_info(name).label
        if spec.is_bool:
            if value not in ("true", "false"):
                err("Value", f"{label} must be true or false.", name)
            continue
        if spec.numeric:
            try:
                number = float(value)
            except ValueError:
                err("Value", f"{label} must be a number, got '{value}'.", name)
                continue
            if spec.numeric == "int" and not number.is_integer():
                err("Value", f"{label} must be a whole number.", name)
            if spec.hi is not None and number > spec.hi:
                warn("Balance", f"{label} {value} is above the highest vanilla value ({spec.hi:g}).", name)
            if spec.lo is not None and number < spec.lo:
                warn("Balance", f"{label} {value} is below the lowest vanilla value ({spec.lo:g}).", name)
            continue
        if spec.xsd == "NCName" and value and not NCNAME.fullmatch(value):
            err("Value", f"{label} contains characters the game does not accept: '{value}'.", name)

    if item.uses_custom_model:
        if not item.model_path.lower().endswith(".cgf"):
            err("Model", "A custom model must be a compiled .cgf file.", "Model")
        elif asset_dir is not None and not _custom_model_found(item, asset_dir):
            err("Model", f"Compiled model {Path(item.model_path).name} was not found in the workspace asset.",
                "Model")
    elif item.model_path and base is None and item.base_guid:
        original = catalog.item(item.base_guid)
        if original and original.attrs.get("Model") != item.model_path:
            warn("Model", "Model differs from the base item. Make sure the path exists in the game.", "Model")

    return issues


def validate_mod_items(items: Sequence[GameItemDefinition]) -> list[ItemValidationError]:
    issues: list[ItemValidationError] = []
    seen_guid: dict[str, str] = {}
    seen_name: dict[str, str] = {}
    for item in items:
        label = item.display_name or item.name
        if item.guid in seen_guid:
            issues.append(ItemValidationError("Duplicate", f"'{label}' and '{seen_guid[item.guid]}' share a GUID."))
        if item.name.lower() in seen_name:
            issues.append(ItemValidationError("Duplicate", f"'{label}' and '{seen_name[item.name.lower()]}' share an internal name."))
        seen_guid[item.guid] = label
        seen_name[item.name.lower()] = label
    return issues
