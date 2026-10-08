"""Extraction of indexed assets into a workspace folder (worker-thread safe)."""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from archives.pak import PakArchive, PakError, safe_target
from core.tasks import TaskContext, UserFacingError
from database.index import AssetIndex, AssetRow
from utils.helpers import is_within

log = logging.getLogger(__name__)


@dataclass
class ExtractionPlan:
    dest_root: Path
    items: list[AssetRow] = field(default_factory=list)

    def targets(self) -> list[tuple[AssetRow, Path]]:
        return [(r, safe_target(self.dest_root.resolve(), r.vpath)) for r in self.items]

    def conflicts(self) -> list[Path]:
        """Existing files whose size differs (possibly edited by the user)."""
        return [t for r, t in self.targets() if t.exists() and t.stat().st_size != r.size]


def build_plan(index: AssetIndex, rows: list[AssetRow], dest_root: Path, companions: bool,
               protected_dirs: list[Path]) -> ExtractionPlan:
    dest_root = Path(dest_root)
    for p in protected_dirs:
        if p and p.exists() and is_within(dest_root, p):
            raise UserFacingError(
                f"Refusing to extract into the game installation:\n{dest_root}\n\n"
                "Original KCD2 files are read-only. Choose a workspace folder instead."
            )
    seen: dict[str, AssetRow] = {}
    for r in rows:
        group = [r] + (index.companions(r) if companions else [])
        for g in group:
            seen.setdefault(g.vpath.lower(), g)  # same vpath in two paks: first wins
    return ExtractionPlan(dest_root, list(seen.values()))


def run_extraction(ctx: TaskContext, plan: ExtractionPlan) -> list[Path]:
    by_archive: dict[str, list[AssetRow]] = defaultdict(list)
    for r in plan.items:
        by_archive[r.archive_path].append(r)
    done: list[Path] = []
    total = len(plan.items)
    n = 0
    for archive_path, rows in by_archive.items():
        try:
            with PakArchive(archive_path) as pak:
                for r in rows:
                    ctx.progress(n, total, f"Extracting {r.filename}")
                    out = pak.extract(r.vpath, plan.dest_root)
                    done.append(out)
                    n += 1
                    log.info("Extracted %s  ←  %s", r.vpath, Path(archive_path).name)
        except PakError as e:
            raise UserFacingError(str(e)) from e
    ctx.progress(total, total, "Extraction complete")
    return done
