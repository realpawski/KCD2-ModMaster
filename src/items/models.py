"""Game item definitions owned by a ModMaster mod project."""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

ITEM_METADATA_FILENAME = ".modmaster_item.json"
ITEM_FORMAT_VERSION = 2

MODE_NEW = "new"
MODE_OVERRIDE = "override"

# Flat fields written by format version 1, mapped to their XML attribute.
_LEGACY_ATTRS = (
    ("item_class", "Class", "int"), ("sub_class", "SubClass", "int"),
    ("model_path", "Model", "str"), ("clothing", "Clothing", "str"),
    ("icon_id", "IconId", "str"), ("ui_sound", "UiSound", "str"),
    ("attack", "Attack", "int"), ("attack_mod_slash", "AttackModSlash", "num"),
    ("attack_mod_stab", "AttackModStab", "num"), ("attack_mod_smash", "AttackModSmash", "num"),
    ("defense", "Defense", "int"), ("str_req", "StrReq", "int"), ("agi_req", "AgiReq", "int"),
    ("weight", "Weight", "num"), ("price", "Price", "int"), ("max_status", "MaxStatus", "int"),
    ("max_quality", "MaxQuality", "int"), ("is_breakable", "IsBreakable", "bool"),
    ("broken_item_class_id", "BrokenItemClassId", "str"), ("visibility", "Visibility", "num"),
    ("visibility_coef", "VisibilityCoef", "num"), ("conspicuousness", "Conspicuousness", "num"),
    ("charisma", "Charisma", "int"), ("fade_coef", "FadeCoef", "num"),
    ("social_class_id", "SocialClassId", "int"), ("wealth_level", "WealthLevel", "int"),
)


def format_number(value: float, kind: str | None = None) -> str:
    if kind == "int" or (kind is None and float(value).is_integer()):
        return str(int(round(value)))
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text or "0"


def slug(text: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_]+", "_", text.strip()).strip("_").lower()
    if not s or not s[0].isalpha():
        s = f"item_{s}" if s else "item"
    return s[:48]


def new_guid() -> str:
    return str(uuid.uuid4()).lower()


@dataclass
class GameItemDefinition:
    item_id: str
    guid: str
    name: str
    display_name: str = ""
    description: str = ""
    item_type: str = "MeleeWeapon"
    attributes: dict[str, str] = field(default_factory=dict)
    children: str = ""
    mode: str = MODE_NEW
    base_guid: str = ""
    base_name: str = ""
    ui_name: str = ""
    ui_info: str = ""
    write_text: bool = True
    workspace_asset_id: str = ""
    add_to_player_inventory: bool = False
    icon_image: str = ""  # mod-relative PNG that becomes the inventory icon
    format_version: int = ITEM_FORMAT_VERSION
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self):
        try:
            self.guid = str(uuid.UUID(str(self.guid))).lower()
        except (ValueError, AttributeError, TypeError):
            self.guid = new_guid()
        if self.mode != MODE_OVERRIDE:
            if not self.ui_name:
                self.ui_name = f"ui_nm_{self.item_id}"
            if not self.ui_info:
                self.ui_info = f"ui_in_{self.item_id}"

    @property
    def model_path(self) -> str:
        return self.attributes.get("Model", "")

    @property
    def uses_custom_model(self) -> bool:
        return bool(self.workspace_asset_id)

    def xml_attributes(self) -> dict[str, str]:
        attrs = {k: v for k, v in self.attributes.items() if v != ""}
        attrs["Id"] = self.guid
        attrs["Name"] = self.name
        if self.ui_name:
            attrs["UIName"] = self.ui_name
        if self.ui_info:
            attrs["UIInfo"] = self.ui_info
        return attrs

    def get_number(self, attr: str, default: float = 0.0) -> float:
        try:
            return float(self.attributes.get(attr, default))
        except (TypeError, ValueError):
            return default

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GameItemDefinition:
        if "attributes" not in data:
            data = _migrate_v1(data)
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})

    @classmethod
    def load_from_file(cls, path: Path) -> GameItemDefinition | None:
        if not path.is_file():
            return None
        try:
            return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception as exc:
            log.warning("Could not read item definition %s: %s", path, exc)
            return None

    def save_to_file(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.updated_at = time.time()
        self.format_version = ITEM_FORMAT_VERSION
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load_for_asset(cls, asset_dir: Path) -> GameItemDefinition | None:
        for candidate in (asset_dir / "metadata" / ITEM_METADATA_FILENAME,
                          asset_dir / ITEM_METADATA_FILENAME):
            if candidate.is_file():
                return cls.load_from_file(candidate)
        return None

    def save_for_asset(self, asset_dir: Path) -> Path:
        target = asset_dir / "metadata" / ITEM_METADATA_FILENAME
        self.save_to_file(target)
        return target


def _migrate_v1(data: dict[str, Any]) -> dict[str, Any]:
    attrs: dict[str, str] = {}
    for key, attr, kind in _LEGACY_ATTRS:
        if key not in data or data[key] in (None, ""):
            continue
        value = data[key]
        if kind == "bool":
            attrs[attr] = "true" if value else "false"
        elif kind == "int":
            attrs[attr] = str(int(round(float(value))))
        elif kind == "num":
            attrs[attr] = format_number(float(value))
        else:
            attrs[attr] = str(value)
    migrated = {k: v for k, v in data.items() if k not in {a[0] for a in _LEGACY_ATTRS}}
    migrated["attributes"] = attrs
    migrated["mode"] = MODE_NEW
    migrated["base_name"] = data.get("template_id", "")
    migrated["format_version"] = ITEM_FORMAT_VERSION
    return migrated


def new_item_from_base(base, item_id: str, display_name: str, description: str = "",
                       mode: str = MODE_NEW) -> GameItemDefinition:
    """Clone every attribute of a vanilla row, as Warhorse recommends for new items."""
    attrs = dict(base.attrs)
    for key in ("Id", "Name", "UIName", "UIInfo"):
        attrs.pop(key, None)
    if mode == MODE_OVERRIDE:
        return GameItemDefinition(
            item_id=item_id, guid=base.guid, name=base.name,
            display_name=display_name or base.display, description=description or base.info,
            item_type=base.tag, attributes=attrs, children=base.children, mode=MODE_OVERRIDE,
            base_guid=base.guid, base_name=base.name,
            ui_name=base.attrs.get("UIName", ""), ui_info=base.attrs.get("UIInfo", ""),
            write_text=False,
        )
    if attrs.get("IsQuestItem") == "true":
        attrs["IsQuestItem"] = "false"
    return GameItemDefinition(
        item_id=item_id, guid=new_guid(), name=item_id,
        display_name=display_name, description=description or base.info,
        item_type=base.tag, attributes=attrs, children=base.children, mode=MODE_NEW,
        base_guid=base.guid, base_name=base.name,
    )
