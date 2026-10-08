"""Vanilla item catalog and item schema, read from the installed game."""
from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

CATALOG_VERSION = 2
TABLES_PAK = Path("Data") / "Tables.pak"
ENGLISH_PAK = Path("Localization") / "English_xml.pak"
ITEM_XSD = "Libs/Tables/item/item.xsd"
ITEM_TABLE_PREFIX = "Libs/Tables/item/item"
# Rows from these tables exist in the game but are not meant as modding bases.
HIDDEN_SOURCES = ("__autotests", "__test", "__deprecated", "__system")
XS = "{http://www.w3.org/2001/XMLSchema}"
NCNAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-]*$")


@dataclass
class AttrSpec:
    name: str
    xsd: str = ""
    required: bool = False
    numeric: str | None = None
    lo: float | None = None
    hi: float | None = None

    @property
    def is_bool(self) -> bool:
        return self.xsd == "boolean"


@dataclass
class TypeSchema:
    tag: str
    attrs: dict[str, AttrSpec] = field(default_factory=dict)
    count: int = 0

    @property
    def required(self) -> list[str]:
        return [a.name for a in self.attrs.values() if a.required]


@dataclass
class VanillaItem:
    guid: str
    tag: str
    name: str
    display: str
    info: str
    attrs: dict[str, str]
    children: str = ""
    source: str = ""

    @property
    def hidden(self) -> bool:
        return any(s in self.source for s in HIDDEN_SOURCES)

    @property
    def label(self) -> str:
        return self.display or self.name


class GameDataUnavailable(RuntimeError):
    pass


def _parse_xsd(data: bytes) -> dict[str, TypeSchema]:
    root = ET.fromstring(data)
    schemas: dict[str, TypeSchema] = {}
    for element in root.findall(f"{XS}element"):
        tag = element.get("name", "")
        complex_type = element.find(f"{XS}complexType")
        if not tag or tag in ("database", "ItemClasses") or complex_type is None:
            continue
        schema = TypeSchema(tag)
        for attr in complex_type.findall(f"{XS}attribute"):
            name = attr.get("name")
            if not name:
                continue
            xsd_type = attr.get("type", "").replace("xs:", "")
            schema.attrs[name] = AttrSpec(name, xsd_type, attr.get("use") == "required")
        if schema.attrs:
            schemas[tag] = schema
    return schemas


def _load_strings(pak: Path) -> dict[str, str]:
    strings: dict[str, str] = {}
    if not pak.is_file():
        return strings
    with zipfile.ZipFile(pak) as z:
        for name in z.namelist():
            if not name.lower().endswith(".xml"):
                continue
            try:
                root = ET.fromstring(z.read(name))
            except ET.ParseError:
                continue
            for row in root.iter("Row"):
                cells = row.findall("Cell")
                if len(cells) >= 2 and cells[0].text:
                    strings[cells[0].text.strip()] = (cells[-1].text or "").strip()
    return strings


def _numeric_kind(values: list[str]) -> tuple[str | None, float | None, float | None]:
    numbers = []
    is_int = True
    for value in values:
        try:
            number = float(value)
        except ValueError:
            return None, None, None
        numbers.append(number)
        if "." in value or "e" in value.lower():
            is_int = False
    if not numbers:
        return None, None, None
    return ("int" if is_int else "float"), min(numbers), max(numbers)


class ItemCatalog:
    def __init__(self, schemas: dict[str, TypeSchema], items: list[VanillaItem]):
        self.schemas = schemas
        self.items = items
        self._by_guid = {i.guid: i for i in items}
        self._by_name = {i.name.lower(): i for i in items}

    @classmethod
    def build(cls, game_dir: Path) -> ItemCatalog:
        tables = Path(game_dir) / TABLES_PAK
        if not tables.is_file():
            raise GameDataUnavailable(f"Tables.pak not found in {game_dir}")
        strings = _load_strings(Path(game_dir) / ENGLISH_PAK)
        items: list[VanillaItem] = []
        with zipfile.ZipFile(tables) as z:
            names = z.namelist()
            if ITEM_XSD not in names:
                raise GameDataUnavailable("item.xsd is missing from Tables.pak")
            schemas = _parse_xsd(z.read(ITEM_XSD))
            for name in sorted(names):
                if not (name.startswith(ITEM_TABLE_PREFIX) and name.endswith(".xml")):
                    continue
                stem = Path(name).stem
                if not (stem == "item" or stem.startswith("item__")):
                    continue
                try:
                    root = ET.fromstring(z.read(name))
                except ET.ParseError:
                    log.warning("Skipping unreadable item table %s", name)
                    continue
                classes = root.find("ItemClasses")
                if classes is None:
                    continue
                for row in classes:
                    guid = row.get("Id", "").lower()
                    if not guid:
                        continue
                    children = "".join(
                        ET.tostring(child, encoding="unicode").strip() for child in row
                    )
                    items.append(VanillaItem(
                        guid=guid,
                        tag=row.tag,
                        name=row.get("Name", ""),
                        display=strings.get(row.get("UIName", ""), ""),
                        info=strings.get(row.get("UIInfo", ""), ""),
                        attrs=dict(row.attrib),
                        children=children,
                        source=stem,
                    ))
        values: dict[tuple[str, str], list[str]] = {}
        for item in items:
            schemas.setdefault(item.tag, TypeSchema(item.tag)).count += 1
            for key, value in item.attrs.items():
                values.setdefault((item.tag, key), []).append(value)
        for (tag, key), vals in values.items():
            spec = schemas[tag].attrs.setdefault(key, AttrSpec(key))
            if spec.is_bool:
                continue
            spec.numeric, spec.lo, spec.hi = _numeric_kind(vals)
        return cls(schemas, items)

    @classmethod
    def load(cls, game_dir: Path, cache_dir: Path) -> ItemCatalog:
        game_dir = Path(game_dir)
        stamp = []
        for rel in (TABLES_PAK, ENGLISH_PAK):
            p = game_dir / rel
            if p.is_file():
                st = p.stat()
                stamp.append([str(rel), st.st_size, int(st.st_mtime)])
        cache_file = Path(cache_dir) / "item_catalog.json"
        if cache_file.is_file():
            try:
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                if data.get("version") == CATALOG_VERSION and data.get("stamp") == stamp:
                    return cls._from_json(data)
            except (ValueError, KeyError, TypeError):
                log.info("Item catalog cache is stale, rebuilding")
        catalog = cls.build(game_dir)
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(catalog._to_json(stamp)), encoding="utf-8")
        except OSError as exc:
            log.warning("Could not write item catalog cache: %s", exc)
        return catalog

    def _to_json(self, stamp) -> dict:
        return {
            "version": CATALOG_VERSION,
            "stamp": stamp,
            "schemas": {
                tag: {"count": s.count, "attrs": [asdict(a) for a in s.attrs.values()]}
                for tag, s in self.schemas.items()
            },
            "items": [asdict(i) for i in self.items],
        }

    @classmethod
    def _from_json(cls, data: dict) -> ItemCatalog:
        schemas = {}
        for tag, raw in data["schemas"].items():
            schema = TypeSchema(tag, count=raw.get("count", 0))
            for a in raw["attrs"]:
                schema.attrs[a["name"]] = AttrSpec(**a)
            schemas[tag] = schema
        items = [VanillaItem(**i) for i in data["items"]]
        return cls(schemas, items)

    def schema(self, tag: str) -> TypeSchema | None:
        return self.schemas.get(tag)

    def item(self, guid: str) -> VanillaItem | None:
        return self._by_guid.get(str(guid).lower())

    def by_name(self, name: str) -> VanillaItem | None:
        return self._by_name.get(str(name).lower())

    def has_guid(self, guid: str) -> bool:
        return str(guid).lower() in self._by_guid

    def has_name(self, name: str) -> bool:
        return str(name).lower() in self._by_name

    def types(self) -> list[str]:
        return sorted(t for t, s in self.schemas.items() if s.count)

    def search(self, query: str = "", tag: str | None = None, limit: int = 500,
               include_hidden: bool = False) -> list[VanillaItem]:
        terms = [t for t in query.lower().split() if t]
        result = []
        for item in self.items:
            if tag and item.tag != tag:
                continue
            if not include_hidden and (item.hidden or not item.display):
                continue
            haystack = f"{item.display} {item.name}".lower()
            if all(t in haystack for t in terms):
                result.append(item)
        result.sort(key=lambda i: (i.label.lower(), i.name.lower()))
        return result[:limit]
