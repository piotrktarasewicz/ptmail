"""Aktualizacje z wydań na GitHubie. Żaden test nie łączy się z siecią."""

import hashlib
import io
import json
import urllib.error

import pytest

from ptmail import updates
from ptmail.updates import Release, UpdateError

PREFIX = updates.DOWNLOAD_PREFIX
DATA = b"instalator"
SHA = hashlib.sha256(DATA).hexdigest()


def asset(name="PTMail-Setup-0.2.0.exe", url=None, digest=f"sha256:{SHA}"):
    return {
        "name": name,
        "browser_download_url": url or f"{PREFIX}v0.2.0/{name}",
        "digest": digest,
    }


def api_response(*assets, tag="v0.2.0"):
    return {"tag_name": tag, "assets": list(assets)}


class Response(io.BytesIO):
    pass


@pytest.fixture
def fake_url(monkeypatch):
    def install(body):
        def fake_open(url):
            if isinstance(body, Exception):
                raise body
            return Response(body)

        monkeypatch.setattr(updates, "_open", fake_open)

    return install


def test_version_comparison_is_numeric():
    assert updates.parse_version("v0.10.0") > updates.parse_version("0.9.1")
    assert updates.parse_version("1.0") == (1, 0)
    assert updates.parse_version("nightly") is None


def test_release_points_at_installer():
    assert updates.parse_release(api_response(asset("notes.txt"), asset())) == Release(
        "0.2.0", f"{PREFIX}v0.2.0/PTMail-Setup-0.2.0.exe", SHA
    )


@pytest.mark.parametrize(
    "bad",
    [
        asset(url="https://example.com/PTMail-Setup-0.2.0.exe"),
        asset(digest=None),
        asset(digest="md5:abc"),
        asset(name="Inny-0.2.0.exe"),
    ],
)
def test_suspicious_asset_is_ignored(bad):
    assert updates.parse_release(api_response(bad)) is None


def test_tag_without_version_is_ignored():
    assert updates.parse_release(api_response(asset(), tag="wersja")) is None


def test_finds_only_newer_version(fake_url):
    fake_url(json.dumps(api_response(asset())).encode())
    assert updates.find_update("0.1.0").version == "0.2.0"
    assert updates.find_update("0.2.0") is None
    assert updates.find_update("0.3.0") is None


def test_no_release_yet_is_not_a_failure(fake_url):
    fake_url(urllib.error.HTTPError(updates.API_URL, 404, "Not Found", {}, None))
    assert updates.find_update("0.1.0") is None


@pytest.mark.parametrize(
    "body",
    [
        urllib.error.HTTPError(updates.API_URL, 500, "Error", {}, None),
        urllib.error.URLError("brak sieci"),
        b"to nie json",
    ],
)
def test_failures_are_reported(fake_url, body):
    fake_url(body)
    with pytest.raises(UpdateError):
        updates.find_update("0.1.0")


@pytest.fixture
def temp_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(updates.tempfile, "gettempdir", lambda: str(tmp_path))
    return tmp_path


def test_download_saves_verified_installer(fake_url, temp_dir):
    fake_url(DATA)
    path = updates.download(Release("0.2.0", "url", SHA))
    assert path.read_bytes() == DATA
    assert path.name == "PTMail-Setup-0.2.0.exe"


def test_wrong_checksum_removes_file(fake_url, temp_dir):
    fake_url(b"podmieniony plik")
    with pytest.raises(UpdateError):
        updates.download(Release("0.2.0", "url", SHA))
    assert list(temp_dir.rglob("*.exe")) == []


def test_download_failure_is_reported(fake_url, temp_dir):
    fake_url(urllib.error.URLError("brak sieci"))
    with pytest.raises(UpdateError):
        updates.download(Release("0.2.0", "url", SHA))


def test_installer_runs_silently(monkeypatch):
    runs = []
    monkeypatch.setattr(updates.subprocess, "Popen", runs.append)
    updates.run_installer("C:\\t\\s.exe")
    assert runs == [["C:\\t\\s.exe", "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]]


def test_source_run_is_not_an_installation():
    assert not updates.is_installed()
