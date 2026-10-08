"""Unit and integration tests for KCD2 ModMaster backend components."""
import tempfile
import zipfile
from pathlib import Path

import pytest

from archives.pak import PakArchive, safe_target
from assets.extract import build_plan, run_extraction
from core.config import Settings
from core.tasks import TaskContext, TaskSignals
from database.index import AssetIndex, AssetRow
from database.scanner import scan
from kcd2.formats import asset_class, pretty_path, split_ext


def test_split_ext():
    ext, is_part = split_ext("Objects/weapons/sword.cgf")
    assert ext == "cgf"
    assert not is_part

    ext, is_part = split_ext("Textures/metal_ddna.dds.1")
    assert ext == "dds-part"
    assert is_part

    ext, is_part = split_ext("Textures/metal_ddna.dds.1a")
    assert ext == "dds-part"
    assert is_part


def test_pretty_path():
    assert pretty_path("Objects/manmade/weapons/swords/longsword.cgf") == "Manmade / Weapons / Swords / longsword.cgf"


def test_asset_class():
    assert asset_class("objects/manmade/weapons/swords/sword.cgf") == "Weapons"
    assert asset_class("objects/characters/humans/cloth/armor_plate.cgf") == "Armor"
    assert asset_class("objects/characters/humans/male/head.skin") == "Characters"
    assert asset_class("objects/manmade/structures/living/houses/cv_house_1s_2r_a_001.cgf") == "Buildings"
    assert asset_class("objects/manmade/structures/defensive/castles/tower.cgf") == "Buildings"
    assert asset_class("objects/manmade/common_furniture/chair.cgf") == "Props"


def test_pak_archive_and_safe_target(tmp_path: Path):
    pak_file = tmp_path / "Test.pak"
    with zipfile.ZipFile(pak_file, "w") as z:
        z.writestr("Objects/weapons/test_sword.cgf", b"CrChF_test_bytes")
        z.writestr("Objects/weapons/test_sword.cgfm", b"mesh_data_test")

    with PakArchive(pak_file) as pak:
        entries = list(pak.entries())
        assert len(entries) == 2
        content = pak.read("Objects/weapons/test_sword.cgf")
        assert content == b"CrChF_test_bytes"

        dest_dir = tmp_path / "extracted"
        extracted_file = pak.extract("Objects/weapons/test_sword.cgf", dest_dir)
        assert extracted_file.exists()
        assert extracted_file.read_bytes() == b"CrChF_test_bytes"
        assert extracted_file == dest_dir / "Objects" / "weapons" / "test_sword.cgf"


def test_asset_index_and_search(tmp_path: Path):
    db_file = tmp_path / "index.sqlite"
    idx = AssetIndex(db_file)

    aid = idx.replace_archive("C:/fake/Objects.pak", "Objects.pak", "Data", 1000, 123456.0)
    idx.conn.execute(
        "INSERT INTO assets(archive_id, vpath, vpath_lower, filename, ext, category, asset_class, size, csize, is_part) "
        "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (aid, "Objects/manmade/weapons/longsword_x.cgf", "objects/manmade/weapons/longsword_x.cgf",
         "longsword_x.cgf", "cgf", "CGF", "Weapons", 500, 200, 0)
    )
    idx.conn.commit()

    rows, more = idx.search("longsword")
    assert len(rows) == 1
    assert rows[0].filename == "longsword_x.cgf"
    assert rows[0].archive_name == "Objects.pak"
    assert rows[0].asset_class == "Weapons"

    rows, _ = idx.search("", asset_class="Weapons")
    assert len(rows) == 1
    rows, _ = idx.search("", asset_class="Armor")
    assert len(rows) == 0

    idx.close()
