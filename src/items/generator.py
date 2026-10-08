"""Writes item patch tables, localization and inventory presets for a mod."""
from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Sequence

from items.models import GameItemDefinition

PLAYER_INVENTORY_PRESET = "inventory_player_henry"
_ZIP_DATE = (2025, 1, 1, 0, 0, 0)


def _database(schema: str) -> ET.Element:
    return ET.Element("database", {
        "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "name": "barbora",
        "xsi:noNamespaceSchemaLocation": schema,
    })


def _serialize(root: ET.Element) -> str:
    ET.indent(root, space="\t")
    body = ET.tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="us-ascii"?>\n' + body + "\n"


def item_table_path(mod_id: str) -> str:
    return f"Libs/Tables/item/item__{mod_id}.xml"


def inventory_preset_path(mod_id: str) -> str:
    return f"Libs/Tables/item/InventoryPreset__{mod_id}.xml"


def localization_filename(mod_id: str) -> str:
    # KM-A-91: mod text files must be named *_<modid>.xml; "text__<modid>" also loads pre-1.3.
    return f"text__{mod_id}.xml"


def generate_item_xml(items: Sequence[GameItemDefinition], mod_id: str) -> str:
    root = _database("item.xsd")
    classes = ET.SubElement(root, "ItemClasses", {"version": "8"})
    for item in items:
        row = ET.SubElement(classes, item.item_type, item.xml_attributes())
        if item.children:
            for child in ET.fromstring(f"<r>{item.children}</r>"):
                row.append(child)
    return _serialize(root)


def generate_inventory_preset_xml(items: Sequence[GameItemDefinition]) -> str | None:
    granted = [i for i in items if i.add_to_player_inventory]
    if not granted:
        return None
    root = _database("InventoryPreset.xsd")
    presets = ET.SubElement(root, "InventoryPresets", {"version": "2"})
    henry = ET.SubElement(presets, "InventoryPreset", {"Name": PLAYER_INVENTORY_PRESET})
    for item in granted:
        ET.SubElement(henry, "PresetItem", {"Name": item.name, "Amount": "1"})
    return _serialize(root)


def localized_items(items: Sequence[GameItemDefinition]) -> list[GameItemDefinition]:
    return [i for i in items if i.write_text and i.ui_name]


def generate_localization_xml(items: Sequence[GameItemDefinition]) -> str:
    root = ET.Element("Table")
    for item in localized_items(items):
        for key, text in ((item.ui_name, item.display_name), (item.ui_info, item.description)):
            if not key:
                continue
            row = ET.SubElement(root, "Row")
            for value in (key, text, text):
                ET.SubElement(row, "Cell").text = value
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode") + "\n"


def build_localization_pak(items: Sequence[GameItemDefinition], output_pak_path: Path,
                           mod_id: str) -> bool:
    if not localized_items(items):
        return False
    output_pak_path.parent.mkdir(parents=True, exist_ok=True)
    data = generate_localization_xml(items).encode("utf-8")
    with zipfile.ZipFile(output_pak_path, "w", compression=zipfile.ZIP_STORED) as z:
        z.writestr(zipfile.ZipInfo(localization_filename(mod_id), _ZIP_DATE), data)
    return True


def generate_weapon_mtl(material_name: str, diffuse_map: str = "") -> str:
    diffuse = diffuse_map or f"./{material_name}_diff.tif"
    return f"""<?xml version="1.0" encoding="us-ascii"?>
<Material MtlFlags="524544" vertModifType="0">
  <SubMaterials>
    <Material CloakAmount="0" CustomSortPriority="1" Diffuse="1,1,1" GenMask="20000000000000" LayerAct="1" MatTemplate="" MtlFlags="524416" Name="proxy" Opacity="1" Shader="NoDraw" Shininess="10" Specular="0,0,0" StringGenMask="%SUBSURFACE_SCATTERING" SurfaceType="mat_metal" vertModifType="0">
      <Textures />
      <PublicParams EmittanceMapGamma="1" RockDarkeningSoftEdge="0" RockDarkeningStrength="0" RockDarkeningThreshold="0" SSSIndex="0" />
    </Material>
    <Material CloakAmount="0" Diffuse="1,1,1" GenMask="34000810002000" LayerAct="1" MatTemplate="" MtlFlags="524416" Name="{material_name}" Opacity="1" Shader="Illum" Shininess="128" Specular="0.5,0.5,0.5" StringGenMask="%DETAIL_MAPPING%NORMAL_MAP%SPECULAR_MAP%WEAPON" SurfaceType="" vertModifType="0">
      <Textures>
        <Texture File="{diffuse}" Map="Diffuse" />
      </Textures>
      <PublicParams EmittanceMapGamma="1" RockDarkeningSoftEdge="0" RockDarkeningStrength="0" RockDarkeningThreshold="0" SSSIndex="0" />
    </Material>
  </SubMaterials>
  <PublicParams EmittanceMapGamma="1" RockDarkeningSoftEdge="0" RockDarkeningStrength="0" RockDarkeningThreshold="0" SSSIndex="0" />
</Material>
"""
