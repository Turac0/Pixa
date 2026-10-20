import hashlib
import io
import json

import pytest

from pixa import updates

INSTALLER = b"MZ fake installer " * 1000
NAME = "Pixa-windows-x86_64-9.0.0-setup.exe"


def release_json(tag="v9.0.0", checksum=True):
    assets = [
        {"name": NAME, "size": len(INSTALLER),
         "browser_download_url": f"https://example.com/{NAME}"},
        {"name": "Pixa-macos-arm64-9.0.0.dmg",
         "browser_download_url": "https://example.com/Pixa.dmg"},
    ]
    if checksum:
        assets.append({"name": f"{NAME}.sha256",
                       "browser_download_url": f"https://example.com/{NAME}.sha256"})
    return {"tag_name": tag, "body": "### New\n\n- Things", "assets": assets,
            "html_url": "https://github.com/Turac0/Pixa/releases/tag/" + tag}


class FakeResponse(io.BytesIO):
    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}


@pytest.fixture
def served(monkeypatch):
    """Serve fake URLs instead of going to the network."""
    files = {}

    def urlopen(request, timeout=None):
        url = request.full_url
        if url not in files:
            raise OSError(f"404 {url}")
        return FakeResponse(files[url])

    monkeypatch.setattr(updates.urllib.request, "urlopen", urlopen)
    return files


def test_versions():
    assert updates.parse_version("v0.10.2") == (0, 10, 2)
    assert updates.parse_version("1.0") == updates.parse_version("1.0.0")
    assert updates.is_newer("0.10.0", "0.9.9")
    assert updates.is_newer("v1.0.1", "1.0")
    assert not updates.is_newer("0.5.1", "0.5.1")
    assert not updates.is_newer("0.5.0", "0.5.1")
    assert not updates.is_newer("nightly", "0.5.1")


def test_release_picks_windows_installer_and_checksum():
    release = updates.release_from_json(release_json())
    assert release.version == "9.0.0"
    assert release.installer_name == NAME
    assert release.installer_size == len(INSTALLER)
    assert release.checksum_url.endswith(".sha256")
    assert "Things" in release.notes


def test_fetch_latest(served):
    served[updates.LATEST_URL] = json.dumps(release_json()).encode()
    assert updates.fetch_latest().version == "9.0.0"


def test_fetch_latest_reports_failures(served):
    with pytest.raises(updates.UpdateError):
        updates.fetch_latest()  # nothing served
    served[updates.LATEST_URL] = b"<html>not json"
    with pytest.raises(updates.UpdateError):
        updates.fetch_latest()


def _serve_release(served, digest=None):
    release = updates.release_from_json(release_json())
    served[release.installer_url] = INSTALLER
    digest = digest or hashlib.sha256(INSTALLER).hexdigest()
    served[release.checksum_url] = f"{digest}  {NAME}\n".encode()
    return release


def test_download_verifies_checksum(served, tmp_path):
    release = _serve_release(served)
    seen = []
    path = updates.download_installer(
        release, lambda done, total: seen.append((done, total)), str(tmp_path))
    assert open(path, "rb").read() == INSTALLER
    assert seen[-1] == (len(INSTALLER), len(INSTALLER))


def test_damaged_download_is_rejected(served, tmp_path):
    release = _serve_release(served, digest="0" * 64)
    with pytest.raises(updates.UpdateError, match="damaged"):
        updates.download_installer(release, folder=str(tmp_path))
    assert not list(tmp_path.iterdir())


def test_download_can_be_cancelled(served, tmp_path):
    release = _serve_release(served)
    with pytest.raises(updates.UpdateError, match="cancelled"):
        updates.download_installer(release, lambda done, total: False, str(tmp_path))
    assert not list(tmp_path.iterdir())


def test_release_without_checksum_is_not_installed(tmp_path):
    release = updates.release_from_json(release_json(checksum=False))
    with pytest.raises(updates.UpdateError, match="checksum"):
        updates.download_installer(release, folder=str(tmp_path))
