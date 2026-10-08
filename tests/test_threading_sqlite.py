"""Regression tests for thread-safe SQLite architecture and preview supersession."""
import concurrent.futures
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from core.config import Settings
from database.index import AssetIndex, AssetRow
from preview.lods import find_lod_family


def _setup_test_db(db_path: Path) -> AssetIndex:
    """Creates a sample asset index database on the current thread."""
    idx = AssetIndex(db_path)
    with idx.connection(read_only=False) as conn:
        aid1 = idx.replace_archive("C:/Games/Data/Objects-part0.pak", "Objects-part0.pak", "Data", 100000, time.time(), conn=conn)
        aid2 = idx.replace_archive("C:/Games/Data/Objects-part1.pak", "Objects-part1.pak", "Data", 100000, time.time(), conn=conn)
        conn.executemany(
            """INSERT INTO assets(archive_id, vpath, vpath_lower, filename, ext, category, asset_class, size, csize, is_part)
               VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (aid1, "Objects/weapons/arrows/arrow.cgf", "objects/weapons/arrows/arrow.cgf", "arrow.cgf", "cgf", "Geometry", "Weapons", 5000, 2500, 0),
                (aid2, "Objects/weapons/arrows/arrow.cgfm", "objects/weapons/arrows/arrow.cgfm", "arrow.cgfm", "cgfm", "Geometry", "Weapons", 15000, 7500, 0),
                (aid1, "Objects/weapons/arrows/arrow_lod1.cgf", "objects/weapons/arrows/arrow_lod1.cgf", "arrow_lod1.cgf", "cgf", "Geometry", "Weapons", 2000, 1000, 0),
                (aid2, "Objects/weapons/arrows/arrow_lod1.cgfm", "objects/weapons/arrows/arrow_lod1.cgfm", "arrow_lod1.cgfm", "cgfm", "Geometry", "Weapons", 6000, 3000, 0),
                (aid1, "Objects/weapons/sword.cgf", "objects/weapons/sword.cgf", "sword.cgf", "cgf", "Geometry", "Weapons", 10000, 5000, 0),
                (aid2, "Objects/weapons/sword.cgfm", "objects/weapons/sword.cgfm", "sword.cgfm", "cgfm", "Geometry", "Weapons", 30000, 15000, 0),
                (aid1, "Objects/weapons/textures/sword.dds", "objects/weapons/textures/sword.dds", "sword.dds", "dds", "Textures", "Weapons", 200000, 100000, 0),
                (aid1, "Objects/weapons/textures/sword.dds.1", "objects/weapons/textures/sword.dds.1", "sword.dds.1", "dds", "Textures", "Weapons", 400000, 200000, 1),
            ],
        )
        conn.execute("INSERT INTO asset_refs(asset_id, kind, ref, detail, owner) VALUES(1, 'texture', 'sword_diff.dds', 'diffuse', 'mat1')")
    return idx


def test_worker_thread_companions_query(tmp_path: Path):
    """Test 1-6: Query assets, resolve companions, resolve refs from background worker without ProgrammingError."""
    db_file = tmp_path / "index.sqlite"
    main_idx = _setup_test_db(db_file)

    main_rows, _ = main_idx.search("arrow.cgf")
    assert len(main_rows) >= 1
    target = main_rows[0]

    worker_results = {}
    worker_error = []

    def worker_job():
        try:
            with main_idx.connection(read_only=True) as conn:
                found = main_idx.find_by_vpath(target.vpath, conn=conn)
                assert len(found) == 1

                comps = main_idx.companions(target, conn=conn)
                assert len(comps) == 1
                assert comps[0].filename == "arrow.cgfm"

                refs = main_idx.refs(target.id, conn=conn)
                assert len(refs) == 1

                family = find_lod_family(main_idx, target, conn=conn)
                assert len(family.lods) >= 2

            comps_implicit = main_idx.companions(target)
            assert len(comps_implicit) == 1

            worker_results["success"] = True
        except Exception as e:
            worker_error.append(e)

    thread = threading.Thread(target=worker_job)
    thread.start()
    thread.join()

    assert not worker_error, f"Worker thread encountered SQLite error: {worker_error[0]}"
    assert worker_results.get("success") is True


def test_concurrent_database_queries(tmp_path: Path):
    """Test 7 & 8: Run concurrent worker queries and verify no SQLite connections are shared across threads."""
    db_file = tmp_path / "index.sqlite"
    idx = _setup_test_db(db_file)

    thread_conns: dict[int, int] = {}
    lock = threading.Lock()

    def query_task(i: int):
        tid = threading.get_ident()
        with idx.connection(read_only=True) as conn:
            with lock:
                thread_conns[tid] = id(conn)

            stats = idx.stats(conn=conn)
            assert stats["assets"] > 0
            rows, _ = idx.search("arrow", conn=conn)
            assert len(rows) > 0
            if rows:
                comps = idx.companions(rows[0], conn=conn)
                assert len(comps) >= 1
        return True

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(query_task, i) for i in range(16)]
        for f in concurrent.futures.as_completed(futures):
            assert f.result() is True

    assert len(thread_conns) > 1, "Expected multiple threads to execute concurrently"


def test_read_only_connection_blocks_writes(tmp_path: Path):
    """Verify that read-only worker connections enforce read-only access."""
    db_file = tmp_path / "index.sqlite"
    idx = _setup_test_db(db_file)

    with idx.connection(read_only=True) as ro_conn:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            ro_conn.execute("INSERT INTO meta(key, value) VALUES('hack', 'fail')")


def test_rapid_preview_supersession():
    """Verify that when Asset A and Asset B are requested rapidly, only Asset B's preview takes effect."""
    from PySide6.QtWidgets import QApplication
    from core.tasks import Task, TaskManager
    from ui.context import AppContext

    app = QApplication.instance() or QApplication([])

    settings = Settings.load()
    ctx = AppContext(settings)

    displayed_results = []
    current_token = 0

    def simulate_selection(asset_name: str, delay: float):
        nonlocal current_token
        current_token += 1
        token = current_token

        def task_fn(task_ctx):
            time.sleep(delay)
            if task_ctx.cancelled or token != current_token:
                return None
            return f"Model for {asset_name}"

        task = Task(f"Preview {asset_name}", task_fn)

        def on_done(result):
            if token != current_token or result is None:
                return  # Superseded!
            displayed_results.append(result)

        task.signals.finished.connect(on_done)
        ctx.tasks.start(task)
        return task

    task_a = simulate_selection("Asset_A", 0.15)
    task_b = simulate_selection("Asset_B", 0.05)

    t0 = time.time()
    while len(displayed_results) == 0 and time.time() - t0 < 3.0:
        app.processEvents()
        time.sleep(0.01)

    time.sleep(0.2)
    app.processEvents()

    assert displayed_results == ["Model for Asset_B"]
