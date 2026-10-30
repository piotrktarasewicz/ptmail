import json
import os
from dataclasses import asdict
from pathlib import Path

from . import APP_NAME
from .accounts import PROVIDERS, Account


def config_path():
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / APP_NAME / "config.json"


def load_account():
    """Zwraca zapisane konto albo None. Etap 1 zaczyna od jednego konta."""
    try:
        data = json.loads(config_path().read_text(encoding="utf-8"))
        account = Account(**data["accounts"][0])
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return None
    return account if account.provider_key in PROVIDERS else None


def save_account(account):
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"accounts": [asdict(account)]}
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
