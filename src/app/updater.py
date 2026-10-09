"""Checks GitHub releases for a newer build and downloads its installer."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.version import APP_NAME, REPOSITORY, VERSION
from core.tasks import UserFacingError

API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases"
INSTALLER_PATTERN = re.compile(r"Setup.*\.exe$", re.IGNORECASE)
CHECKSUM_NAME = "SHA256SUMS.txt"
_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.\-]+))?$")


class UpdateError(UserFacingError):
    pass


@dataclass
class Release:
    version: str
    title: str
    notes: str
    page_url: str
    installer_name: str
    installer_url: str
    installer_size: int
    checksum_url: str
    prerelease: bool


def parse_version(text: str) -> tuple:
    match = _VERSION.match(text.strip())
    if not match:
        raise ValueError(f"Not a version: {text!r}")
    major, minor, patch, pre = match.groups()
    # A release without a pre-release tag ranks above any pre-release of the same number.
    pre_key = (1,) if not pre else (0,) + tuple(
        (0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre.split("."))
    return int(major), int(minor), int(patch), pre_key


def is_newer(candidate: str, current: str = VERSION) -> bool:
    try:
        return parse_version(candidate) > parse_version(current)
    except ValueError:
        return False


def _get(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(url, headers={
        "User-Agent": f"{APP_NAME}/{VERSION}",
        "Accept": "application/vnd.github+json",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except OSError as exc:
        raise UpdateError(f"Could not reach GitHub: {exc}") from exc


def _release_from(data: dict) -> Release | None:
    tag = str(data.get("tag_name", ""))
    installer = next((a for a in data.get("assets", []) if INSTALLER_PATTERN.search(a.get("name", ""))), None)
    if not installer:
        return None
    checksum = next((a for a in data.get("assets", []) if a.get("name") == CHECKSUM_NAME), None)
    return Release(
        version=tag.lstrip("v"),
        title=data.get("name") or tag,
        notes=data.get("body") or "",
        page_url=data.get("html_url", ""),
        installer_name=installer["name"],
        installer_url=installer["browser_download_url"],
        installer_size=int(installer.get("size", 0)),
        checksum_url=checksum["browser_download_url"] if checksum else "",
        prerelease=bool(data.get("prerelease")),
    )


def latest_release(include_prerelease: bool = True, timeout: float = 8.0) -> Release | None:
    try:
        releases = json.loads(_get(f"{API_URL}?per_page=10", timeout))
    except ValueError as exc:
        raise UpdateError("GitHub returned an unexpected response.") from exc
    best = None
    for data in releases:
        if data.get("draft") or (data.get("prerelease") and not include_prerelease):
            continue
        release = _release_from(data)
        if release is None:
            continue
        try:
            if best is None or parse_version(release.version) > parse_version(best.version):
                best = release
        except ValueError:
            continue
    return best


def check_for_update(include_prerelease: bool = True) -> Release | None:
    release = latest_release(include_prerelease)
    if release and is_newer(release.version):
        return release
    return None


def _expected_hash(release: Release) -> str | None:
    if not release.checksum_url:
        return None
    text = _get(release.checksum_url, 15).decode("utf-8", "replace")
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == release.installer_name:
            return parts[0].lower()
    return None


def download_installer(release: Release, progress: Callable[[int, int], None] | None = None,
                       cancelled: Callable[[], bool] | None = None) -> Path:
    expected = _expected_hash(release)
    target = Path(tempfile.gettempdir()) / release.installer_name
    digest = hashlib.sha256()
    received = 0
    request = urllib.request.Request(release.installer_url, headers={"User-Agent": f"{APP_NAME}/{VERSION}"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response, open(target, "wb") as out:
            total = int(response.headers.get("Content-Length") or release.installer_size or 0)
            while True:
                if cancelled and cancelled():
                    raise UpdateError("Download cancelled.")
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                received += len(chunk)
                if progress:
                    progress(received, total)
    except OSError as exc:
        target.unlink(missing_ok=True)
        raise UpdateError(f"Download failed: {exc}") from exc
    if release.installer_size and received != release.installer_size:
        target.unlink(missing_ok=True)
        raise UpdateError("The download is incomplete. Please try again.")
    if expected and digest.hexdigest() != expected:
        target.unlink(missing_ok=True)
        raise UpdateError("The downloaded installer failed its checksum test and was deleted.")
    return target


def launch_installer(path: Path) -> None:
    """Start the installer detached; it replaces the program files in place and starts the app again."""
    flags = 0x00000008 | 0x00000200 if os.name == "nt" else 0
    subprocess.Popen([str(path), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/CLOSEAPPLICATIONS"],
                     close_fds=True, creationflags=flags)
