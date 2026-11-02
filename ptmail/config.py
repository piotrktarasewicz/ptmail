import json
import os
from dataclasses import asdict
from pathlib import Path

from . import APP_NAME
from .accounts import PROVIDERS, Account


def config_path():
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / APP_NAME / "config.json"


def _read():
    try:
        data = json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(data):
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_accounts():
    """Zwraca zapisane konta. Pierwsze na liście jest domyślne przy nowej wiadomości."""
    entries = _read().get("accounts")
    if not isinstance(entries, list):
        return []
    accounts = []
    for entry in entries:
        try:
            account = Account(**entry)
        except TypeError:
            continue
        if account.provider_key in PROVIDERS:
            accounts.append(account)
    return accounts


def save_accounts(accounts):
    data = _read()
    data["accounts"] = [asdict(account) for account in accounts]
    _write(data)


def _load_flag(name):
    """Przełączniki są domyślnie włączone."""
    return _read().get(name) is not False


def _save_flag(name, enabled):
    data = _read()
    data[name] = enabled
    _write(data)


def load_notifications():
    return _load_flag("notifications")


def save_notifications(enabled):
    _save_flag("notifications", enabled)


def load_hide_on_close():
    return _load_flag("hide_on_close")


def save_hide_on_close(enabled):
    _save_flag("hide_on_close", enabled)
