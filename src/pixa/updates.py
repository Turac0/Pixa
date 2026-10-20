"""Checking for and downloading new versions of Pixa (Qt-free).

Releases are published on Pixa's own GitHub repository. Each release is tagged
``v<version>`` and carries the Windows installer plus a ``<installer>.sha256`` file; its
notes are shown to the user.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from pixa import __version__
from pixa.i18n import tr

RELEASES_REPO = "Turac0/Pixa"
LATEST_URL = f"https://api.github.com/repos/{RELEASES_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{RELEASES_REPO}/releases/latest"
TIMEOUT = 15


class UpdateError(Exception):
    """Checking for or downloading an update failed."""


@dataclass
class Release:
    version: str
    notes: str
    page_url: str
    installer_url: str | None = None
    installer_name: str | None = None
    installer_size: int = 0
    checksum_url: str | None = None


def parse_version(text: str) -> tuple[int, ...]:
    """``"v0.10.2"`` -> ``(0, 10, 2)``. Anything after the numbers (``-beta``) is ignored."""
    match = re.match(r"v?(\d+(?:\.\d+)*)", text.strip())
    if not match:
        raise ValueError(f"not a version: {text!r}")
    parts = [int(p) for p in match.group(1).split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()  # 1.0 == 1.0.0
    return tuple(parts)


def is_newer(candidate: str, current: str = __version__) -> bool:
    try:
        return parse_version(candidate) > parse_version(current)
    except ValueError:
        return False


def can_install() -> bool:
    """True when this copy was installed by the Windows installer, which can upgrade it."""
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


def _request(url: str) -> urllib.request.Request:
    return urllib.request.Request(url, headers={
        "User-Agent": f"Pixa/{__version__}",
        "Accept": "application/vnd.github+json",
    })


def release_from_json(data: dict) -> Release:
    tag = data.get("tag_name") or ""
    parse_version(tag)  # raises ValueError for tags that aren't versions
    release = Release(
        version=tag.lstrip("v"),
        notes=data.get("body") or "",
        page_url=data.get("html_url") or RELEASES_PAGE,
    )
    assets = {a.get("name"): a for a in data.get("assets") or []}
    for name, asset in assets.items():
        if name and name.lower().endswith("-setup.exe"):
            release.installer_name = name
            release.installer_url = asset.get("browser_download_url")
            release.installer_size = int(asset.get("size") or 0)
            checksum = assets.get(f"{name}.sha256")
            release.checksum_url = checksum.get("browser_download_url") if checksum else None
            break
    return release


def fetch_latest(url: str = LATEST_URL) -> Release:
    """The newest published release. Raises UpdateError when it can't be fetched."""
    try:
        with urllib.request.urlopen(_request(url), timeout=TIMEOUT) as response:
            data = json.load(response)
        return release_from_json(data)
    except (OSError, ValueError) as exc:
        raise UpdateError(tr("Couldn't check for updates: {error}", error=exc)) from exc


def download_installer(release: Release, progress: Callable[[int, int], bool] | None = None,
                       folder: str | None = None) -> str:
    """Download and verify the release's installer and return its path.

    ``progress(done, total)`` is called while downloading; returning False cancels, which
    raises UpdateError. The file is checked against the release's SHA-256 checksum.
    """
    if not release.installer_url or not release.installer_name:
        raise UpdateError(tr("This release has no Windows installer."))
    if not release.checksum_url:
        raise UpdateError(tr("This release has no checksum to verify the installer with."))
    if not release.installer_url.startswith("https://"):
        raise UpdateError(
            tr("Refusing to download the installer over an insecure connection."))
    folder = folder or os.path.join(tempfile.gettempdir(), "Pixa-update")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, os.path.basename(release.installer_name))
    try:
        with urllib.request.urlopen(_request(release.checksum_url), timeout=TIMEOUT) as r:
            expected = r.read().decode("ascii", "replace").split()[0].lower()
        digest = hashlib.sha256()
        with urllib.request.urlopen(_request(release.installer_url), timeout=TIMEOUT) as r, \
                open(path, "wb") as out:
            total = int(r.headers.get("Content-Length") or release.installer_size or 0)
            done = 0
            while chunk := r.read(256 * 1024):
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress and progress(done, total) is False:
                    raise UpdateError(tr("Download cancelled."))
    except (OSError, IndexError) as exc:
        _remove(path)
        raise UpdateError(tr("Couldn't download the update: {error}", error=exc)) from exc
    except UpdateError:
        _remove(path)
        raise
    if digest.hexdigest() != expected:
        _remove(path)
        raise UpdateError(
            tr("The downloaded installer is damaged (its checksum doesn't match)."))
    return path


def installer_command(path: str) -> list[str]:
    """Run the Inno Setup installer without its wizard; it closes Pixa if it's still open
    and starts the new version when done (``/RELAUNCH=1``, see packaging/pixa.iss)."""
    return [path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS",
            "/RELAUNCH=1"]


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
