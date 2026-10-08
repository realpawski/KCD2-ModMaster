"""Material parser and inspector module."""
from materials.mtl_parser import (
    MTLDefinition,
    SubMaterialInfo,
    parse_mtl_xml,
    resolve_and_stage_textures,
)

__all__ = [
    "MTLDefinition",
    "SubMaterialInfo",
    "parse_mtl_xml",
    "resolve_and_stage_textures",
]
