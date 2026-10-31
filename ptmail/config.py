import json
import os
from dataclasses import asdict
from pathlib import Path

from . import APP_NAME
from .accounts import PROVIDERS, Account


def config_path():
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / APP_NAME / "config.json"


def load_accounts():
    """Zwraca zapisane konta. Pierwsze na liście jest domyślne przy nowej wiadomości."""
    try:
        data = json.loads(config_path().read_text(encoding="utf-8"))
        entries = data["accounts"]
    except (OSError, ValueError, KeyError, TypeError):
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
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"accounts": [asdict(account) for account in accounts]}
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
