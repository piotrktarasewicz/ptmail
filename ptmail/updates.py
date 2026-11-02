"""Aktualizacje z wydań na GitHubie. Program tylko pyta, a instaluje po zgodzie."""

import hashlib
import json
import logging
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import APP_NAME

logger = logging.getLogger(__name__)
API_URL = "https://api.github.com/repos/piotrktarasewicz/ptmail/releases/latest"
DOWNLOAD_PREFIX = "https://github.com/piotrktarasewicz/ptmail/releases/download/"
INSTALLER_RE = re.compile(r"PTMail-Setup-[\d.]+\.exe$")
DIGEST_RE = re.compile(r"sha256:([0-9a-f]{64})$")
VERSION_RE = re.compile(r"v?(\d+(?:\.\d+)*)$")
TIMEOUT_SECONDS = 30
CHUNK_BYTES = 1024 * 1024
HTTP_NOT_FOUND = 404
# /SILENT zostawia okno z paskiem postępu, które NVDA czyta jak każde inne.
INSTALLER_ARGUMENTS = ("/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART")


class UpdateError(Exception):
    pass


class UpdateCancelled(UpdateError):
    pass


@dataclass(frozen=True)
class Release:
    version: str
    url: str
    sha256: str


def is_installed():
    """Program uruchomiony z kodu źródłowego nie ma czego aktualizować."""
    return getattr(sys, "frozen", False)


def parse_version(text):
    """Zwraca wersję jako krotkę liczb albo None, gdy to nie jest numer wersji."""
    match = VERSION_RE.match(text)
    return tuple(int(part) for part in match[1].split(".")) if match else None


def parse_release(data):
    """Wybiera z odpowiedzi GitHuba instalator, ale tylko z tego repozytorium."""
    version = data.get("tag_name", "")
    if parse_version(version) is None:
        return None
    for asset in data.get("assets", []):
        url = asset.get("browser_download_url", "")
        digest = DIGEST_RE.match(asset.get("digest") or "")
        if (
            INSTALLER_RE.match(asset.get("name", ""))
            and url.startswith(DOWNLOAD_PREFIX)
            and digest
        ):
            return Release(version.removeprefix("v"), url, digest[1])
    return None


def _open(url):
    request = urllib.request.Request(url, headers={"User-Agent": APP_NAME})
    return urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS)


def find_update(current):
    """Zwraca nowsze wydanie albo None. Brak jakiegokolwiek wydania to nie błąd."""
    try:
        with _open(API_URL) as response:
            data = json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == HTTP_NOT_FOUND:
            return None
        raise UpdateError(str(error)) from error
    except (OSError, ValueError) as error:
        raise UpdateError(str(error)) from error
    release = parse_release(data)
    if release is None or parse_version(release.version) <= parse_version(current):
        return None
    return release


def download(release, on_progress, cancelled):
    """Pobiera instalator i sprawdza sumę kontrolną. Zwraca ścieżkę pliku.

    on_progress dostaje procent albo None, gdy serwer nie podał rozmiaru.
    cancelled to threading.Event, który przerywa pobieranie.
    """
    folder = Path(tempfile.gettempdir()) / f"{APP_NAME} update"
    shutil.rmtree(folder, ignore_errors=True)
    path = folder / f"PTMail-Setup-{release.version}.exe"
    digest = hashlib.sha256()
    received = 0
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with _open(release.url) as response, open(path, "wb") as file:
            total = int(response.headers.get("Content-Length") or 0)
            while chunk := response.read(CHUNK_BYTES):
                if cancelled.is_set():
                    raise UpdateCancelled()
                digest.update(chunk)
                file.write(chunk)
                received += len(chunk)
                on_progress(min(100, received * 100 // total) if total else None)
    except OSError as error:
        raise UpdateError(str(error)) from error
    except UpdateCancelled:
        path.unlink(missing_ok=True)
        raise
    if digest.hexdigest() != release.sha256:
        path.unlink(missing_ok=True)
        raise UpdateError("Suma kontrolna instalatora się nie zgadza")
    return path


def run_installer(path):
    """Instalator czeka, aż program się zamknie, a potem uruchamia go od nowa."""
    subprocess.Popen([str(path), *INSTALLER_ARGUMENTS])


def in_background(work, on_done):
    """Wywołuje on_done(wynik, False) albo on_done(None, True) po błędzie, w tle."""

    def run():
        try:
            result = work()
        except UpdateCancelled:
            on_done(None, True)
        except UpdateError:
            logger.exception("Aktualizacja nie powiodła się")
            on_done(None, True)
        else:
            on_done(result, False)

    threading.Thread(target=run, daemon=True).start()
