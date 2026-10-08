"""Read-only access to KCD2 .pak archives (plain ZIP files, never opened for writing)."""
from __future__ import annotations

import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterator


class PakError(Exception):
    pass


@dataclass(frozen=True)
class PakEntry:
    vpath: str
    size: int
    csize: int
    compress_type: int


class PakArchive:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._zf: zipfile.ZipFile | None = None

    def __enter__(self) -> "PakArchive":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def open(self) -> None:
        if self._zf is not None:
            return
        if not self.path.exists():
            raise PakError(f"Archive not found:\n{self.path}")
        try:
            self._zf = zipfile.ZipFile(self.path, mode="r")
        except zipfile.BadZipFile as e:
            raise PakError(f"{self.path.name} is not a readable PAK/ZIP archive ({e}).") from e
        except OSError as e:
            raise PakError(f"Could not open {self.path}:\n{e}") from e

    def close(self) -> None:
        if self._zf is not None:
            self._zf.close()
            self._zf = None

    @property
    def zf(self) -> zipfile.ZipFile:
        if self._zf is None:
            self.open()
        assert self._zf is not None
        return self._zf

    def entries(self) -> Iterator[PakEntry]:
        for zi in self.zf.infolist():
            if zi.is_dir():
                continue
            yield PakEntry(zi.filename, zi.file_size, zi.compress_size, zi.compress_type)

    def read(self, vpath: str, max_size: int | None = None) -> bytes:
        try:
            zi = self.zf.getinfo(vpath)
        except KeyError as e:
            raise PakError(f"'{vpath}' is not inside {self.path.name}.") from e
        if max_size is not None and zi.file_size > max_size:
            raise PakError(f"'{vpath}' is too large to read into memory ({zi.file_size} bytes).")
        return self.zf.read(zi)

    def extract(self, vpath: str, dest_root: str | Path) -> Path:
        """Extract one entry to dest_root/<virtual path>. Returns output path."""
        dest_root = Path(dest_root).resolve()
        target = safe_target(dest_root, vpath)
        try:
            zi = self.zf.getinfo(vpath)
        except KeyError as e:
            raise PakError(f"'{vpath}' is not inside {self.path.name}.") from e
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".mmpart")
        try:
            with self.zf.open(zi, "r") as src, open(tmp, "wb") as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
            tmp.replace(target)
        except (OSError, zipfile.BadZipFile) as e:
            tmp.unlink(missing_ok=True)
            raise PakError(f"Failed to extract '{vpath}' from {self.path.name}:\n{e}") from e
        return target


def safe_target(dest_root: Path, vpath: str) -> Path:
    """Map a virtual path into dest_root, refusing path traversal."""
    parts = [p for p in PurePosixPath(vpath.replace("\\", "/")).parts if p not in ("", ".", "/")]
    if not parts or any(p == ".." or ":" in p for p in parts):
        raise PakError(f"Refusing unsafe archive path: {vpath!r}")
    target = dest_root.joinpath(*parts).resolve()
    try:
        target.relative_to(dest_root)
    except ValueError as e:
        raise PakError(f"Refusing unsafe archive path: {vpath!r}") from e
    return target
