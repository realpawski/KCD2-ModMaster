"""SQLite asset index. Archives stay packed – only their listings are stored."""
from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Generator

from kcd2.formats import TYPE_GROUPS

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS archives(
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    group_name TEXT NOT NULL,
    size INTEGER, mtime REAL, entry_count INTEGER, scanned_at REAL
);
CREATE TABLE IF NOT EXISTS assets(
    id INTEGER PRIMARY KEY,
    archive_id INTEGER NOT NULL REFERENCES archives(id) ON DELETE CASCADE,
    vpath TEXT NOT NULL,
    vpath_lower TEXT NOT NULL,
    filename TEXT NOT NULL,
    ext TEXT NOT NULL,
    category TEXT NOT NULL,
    asset_class TEXT NOT NULL,
    size INTEGER, csize INTEGER,
    is_part INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_assets_vpath ON assets(vpath_lower);
CREATE INDEX IF NOT EXISTS ix_assets_ext ON assets(ext);
CREATE INDEX IF NOT EXISTS ix_assets_class ON assets(asset_class);
CREATE INDEX IF NOT EXISTS ix_assets_archive ON assets(archive_id);
-- References parsed from file contents. kind: 'texture' (from .mtl),
-- later: 'material', 'lod', 'dependency'. detail: e.g. MTL Map= slot name.
CREATE TABLE IF NOT EXISTS asset_refs(
    asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    ref TEXT NOT NULL,
    detail TEXT,
    owner TEXT
);
CREATE INDEX IF NOT EXISTS ix_refs_asset ON asset_refs(asset_id);
"""


@dataclass
class AssetRow:
    id: int
    vpath: str
    filename: str
    ext: str
    category: str
    asset_class: str
    size: int
    csize: int
    is_part: bool
    archive_id: int
    archive_name: str
    archive_path: str


_ROW_SQL = (
    "SELECT a.id, a.vpath, a.filename, a.ext, a.category, a.asset_class, a.size, a.csize, a.is_part, "
    "r.id, r.name, r.path FROM assets a JOIN archives r ON r.id = a.archive_id"
)


def _row(t) -> AssetRow:
    return AssetRow(t[0], t[1], t[2], t[3], t[4], t[5], t[6], t[7], bool(t[8]), t[9], t[10], t[11])


class AssetIndex:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        # Ensure schema is initialized once on startup
        with self.connection(read_only=False) as init_conn:
            self._migrate(init_conn)

    def get_connection(self, read_only: bool = False) -> sqlite3.Connection:
        """Creates and returns a new SQLite connection owned by the calling thread."""
        if read_only and self.path.exists():
            uri = f"file:{self.path.resolve().as_posix()}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=30)
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA busy_timeout = 30000")
            return conn
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), timeout=30)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    @contextmanager
    def connection(self, read_only: bool = False) -> Generator[sqlite3.Connection, None, None]:
        """Context manager providing an independent SQLite connection closed upon exit."""
        conn = self.get_connection(read_only=read_only)
        try:
            yield conn
            if not read_only:
                conn.commit()
        finally:
            conn.close()

    def _thread_conn(self, read_only: bool = True) -> sqlite3.Connection:
        """Returns a thread-local connection for the calling thread."""
        conn = getattr(self._local, "conn", None)
        is_ro = getattr(self._local, "is_ro", False)
        if conn is None:
            conn = self.get_connection(read_only=read_only)
            self._local.conn = conn
            self._local.is_ro = read_only
        elif not read_only and is_ro:
            try:
                conn.close()
            except Exception:
                pass
            conn = self.get_connection(read_only=False)
            self._local.conn = conn
            self._local.is_ro = False
        return conn

    @property
    def conn(self) -> sqlite3.Connection:
        """Thread-local connection for the calling thread (RW fallback)."""
        return self._thread_conn(read_only=False)

    def close(self) -> None:
        """Closes the calling thread's connection if active."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            self._local.conn = None

    def _migrate(self, conn: sqlite3.Connection | None = None) -> None:
        c = conn or self._thread_conn(read_only=False)
        cur = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='meta'")
        if cur.fetchone():
            v = self.get_meta("schema_version", conn=c)
            if v is not None and int(v) != SCHEMA_VERSION:
                c.executescript(
                    "DROP TABLE IF EXISTS asset_refs; DROP TABLE IF EXISTS assets; DROP TABLE IF EXISTS archives;"
                )
        c.executescript(SCHEMA)
        self.set_meta("schema_version", str(SCHEMA_VERSION), conn=c)
        # Automatic reclassification migration for Buildings
        migrated_buildings = self.get_meta("buildings_migrated", conn=c)
        if not migrated_buildings:
            c.execute("""
                UPDATE assets SET asset_class = 'Buildings'
                WHERE asset_class = 'Props'
                  AND (
                      vpath_lower LIKE 'objects/manmade/structures/%'
                      OR vpath_lower LIKE 'hlods/structures/%'
                      OR vpath_lower LIKE '%/houses/%'
                      OR vpath_lower LIKE '%/castles/%'
                      OR vpath_lower LIKE '%/fortresses/%'
                      OR vpath_lower LIKE '%/buildings/%'
                  )
            """)
            self.set_meta("buildings_migrated", "1", conn=c)
        c.commit()

    def get_meta(self, key: str, conn: sqlite3.Connection | None = None) -> str | None:
        c = conn or self._thread_conn(read_only=True)
        r = c.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return r[0] if r else None

    def set_meta(self, key: str, value: str, conn: sqlite3.Connection | None = None) -> None:
        c = conn or self._thread_conn(read_only=False)
        c.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)", (key, value))
        if conn is None:
            c.commit()

    def archive_record(self, path: str, conn: sqlite3.Connection | None = None):
        c = conn or self._thread_conn(read_only=True)
        return c.execute(
            "SELECT id, size, mtime FROM archives WHERE path=?", (path,)
        ).fetchone()

    def replace_archive(
        self, path: str, name: str, group: str, size: int, mtime: float, conn: sqlite3.Connection | None = None
    ) -> int:
        c = conn or self._thread_conn(read_only=False)
        c.execute("DELETE FROM archives WHERE path=?", (path,))
        cur = c.execute(
            "INSERT INTO archives(path, name, group_name, size, mtime, entry_count, scanned_at) "
            "VALUES(?,?,?,?,?,0,?)",
            (path, name, group, size, mtime, time.time()),
        )
        if conn is None:
            c.commit()
        return int(cur.lastrowid)

    def remove_archives_not_in(self, paths: set[str], conn: sqlite3.Connection | None = None) -> int:
        c = conn or self._thread_conn(read_only=False)
        rows = c.execute("SELECT id, path FROM archives").fetchall()
        gone = [r[0] for r in rows if r[1] not in paths]
        for aid in gone:
            c.execute("DELETE FROM archives WHERE id=?", (aid,))
        if conn is None:
            c.commit()
        return len(gone)

    def list_archives(self, conn: sqlite3.Connection | None = None) -> list[tuple[int, str, str, int]]:
        c = conn or self._thread_conn(read_only=True)
        return c.execute(
            "SELECT id, name, group_name, entry_count FROM archives ORDER BY group_name, name"
        ).fetchall()

    def stats(self, conn: sqlite3.Connection | None = None) -> dict:
        c = conn or self._thread_conn(read_only=True)
        a = c.execute("SELECT COUNT(*) FROM archives").fetchone()[0]
        n = c.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
        return {"archives": a, "assets": n, "last_scan": self.get_meta("last_scan", conn=c)}

    def search(
        self,
        text: str = "",
        type_group: str | None = None,
        asset_class: str | None = None,
        archive_id: int | None = None,
        include_parts: bool = False,
        limit: int = 5000,
        conn: sqlite3.Connection | None = None,
    ) -> tuple[list[AssetRow], bool]:
        c = conn or self._thread_conn(read_only=True)
        where, args = [], []
        for tok in text.lower().split():
            where.append("a.vpath_lower LIKE ? ESCAPE '\\'")
            esc = tok.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            args.append(f"%{esc}%")
        if type_group and type_group in TYPE_GROUPS:
            exts = TYPE_GROUPS[type_group]
            where.append(f"a.ext IN ({','.join('?' * len(exts))})")
            args += list(exts)
        elif type_group == "Texture parts":
            where.append("a.is_part = 1")
        if asset_class:
            where.append("a.asset_class = ?")
            args.append(asset_class)
        if archive_id is not None:
            where.append("a.archive_id = ?")
            args.append(archive_id)
        if not include_parts and type_group != "Texture parts":
            where.append("a.is_part = 0")
        sql = _ROW_SQL + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY a.vpath_lower LIMIT ?"
        rows = c.execute(sql, args + [limit + 1]).fetchall()
        more = len(rows) > limit
        return [_row(r) for r in rows[:limit]], more

    def get(self, asset_id: int, conn: sqlite3.Connection | None = None) -> AssetRow | None:
        c = conn or self._thread_conn(read_only=True)
        r = c.execute(_ROW_SQL + " WHERE a.id=?", (asset_id,)).fetchone()
        return _row(r) if r else None

    def find_by_vpath(self, vpath: str, conn: sqlite3.Connection | None = None) -> list[AssetRow]:
        c = conn or self._thread_conn(read_only=True)
        rows = c.execute(_ROW_SQL + " WHERE a.vpath_lower=?", (vpath.lower(),)).fetchall()
        return [_row(r) for r in rows]

    def texture_parts(self, dds_vpath: str, conn: sqlite3.Connection | None = None) -> list[AssetRow]:
        """Split mip chunks 'x.dds.1', 'x.dds.a', ... belonging to 'x.dds'."""
        c = conn or self._thread_conn(read_only=True)
        lo = dds_vpath.lower() + "."
        hi = dds_vpath.lower() + "/"  # '/' sorts right after '.'
        rows = c.execute(
            _ROW_SQL + " WHERE a.vpath_lower >= ? AND a.vpath_lower < ? AND a.is_part = 1", (lo, hi)
        ).fetchall()
        return [_row(r) for r in rows]

    def refs(self, asset_id: int, conn: sqlite3.Connection | None = None) -> list[tuple[str, str, str, str]]:
        c = conn or self._thread_conn(read_only=True)
        return c.execute(
            "SELECT kind, ref, detail, owner FROM asset_refs WHERE asset_id=?", (asset_id,)
        ).fetchall()

    def companions(self, row: AssetRow, conn: sqlite3.Connection | None = None) -> list[AssetRow]:
        """Files that belong to `row` by observed KCD2 naming (see research doc)."""
        out: list[AssetRow] = []
        if row.ext == "dds":
            out += self.texture_parts(row.vpath, conn=conn)
        if row.ext in ("cgf", "chr", "skin", "cga"):
            out += self.find_by_vpath(row.vpath + "m", conn=conn)
        return [r for r in out if r.id != row.id]
