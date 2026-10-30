"""Zapisywanie i otwieranie załączników. Nazwy plików pochodzą od nadawcy."""

import os
import re
import shutil
import tempfile
from pathlib import Path

from . import APP_NAME

# Tych typów Windows nie otwiera, tylko uruchamia, więc wolno je jedynie zapisać.
BLOCKED_EXTENSIONS = {
    ".bat", ".cmd", ".com", ".cpl", ".exe", ".hta", ".inf", ".jar", ".js", ".jse",
    ".lnk", ".msi", ".msp", ".pif", ".ps1", ".reg", ".scr", ".vbe", ".vbs", ".wsf",
    ".wsh",
}


def downloads_dir():
    folder = Path.home() / "Downloads"
    return folder if folder.is_dir() else Path.home()


def safe_filename(name):
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return cleaned or "zalacznik"


def unique_path(folder, name):
    path = Path(folder) / name
    number = 1
    while path.exists():
        path = Path(folder) / f"{Path(name).stem} ({number}){Path(name).suffix}"
        number += 1
    return path


def can_open(attachment):
    return Path(safe_filename(attachment.filename)).suffix.lower() not in BLOCKED_EXTENSIONS


def save_to_folder(attachments, folder):
    for attachment in attachments:
        path = unique_path(folder, safe_filename(attachment.filename))
        path.write_bytes(attachment.data)


def open_attachment(attachment):
    folder = tempfile.mkdtemp(dir=_temp_root())
    path = Path(folder) / safe_filename(attachment.filename)
    path.write_bytes(attachment.data)
    os.startfile(path)


def clear_temp():
    """Sprząta po poprzednim uruchomieniu, gdy pliki nie są już otwarte."""
    shutil.rmtree(Path(tempfile.gettempdir()) / APP_NAME, ignore_errors=True)


def _temp_root():
    root = Path(tempfile.gettempdir()) / APP_NAME
    root.mkdir(exist_ok=True)
    return root
