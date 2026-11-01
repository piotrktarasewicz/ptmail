"""Pamięć podręczna SQLite. Używa jej tylko wątek interfejsu.

To wyłącznie przyspieszenie: każdy błąd bazy oznacza po prostu brak danych,
a źródłem prawdy zostaje serwer.
"""

import functools
import logging
import sqlite3
from datetime import datetime

from .config import config_path
from .models import Contact, Folder, Message

logger = logging.getLogger(__name__)
SCHEMA_VERSION = 1
MAX_BODY_BYTES = 10 * 1024 * 1024
TABLES = ("folders", "messages", "bodies", "contacts")
SCHEMA = """
CREATE TABLE IF NOT EXISTS folders (
    account TEXT, name TEXT, label TEXT, role TEXT, unread INTEGER, position INTEGER,
    PRIMARY KEY (account, name)
);
CREATE TABLE IF NOT EXISTS messages (
    account TEXT, folder TEXT, uid INTEGER, sender TEXT, subject TEXT, date TEXT,
    seen INTEGER, flagged INTEGER, attachments INTEGER, position INTEGER,
    PRIMARY KEY (account, folder, uid)
);
CREATE TABLE IF NOT EXISTS bodies (
    account TEXT, folder TEXT, uid INTEGER, raw BLOB,
    PRIMARY KEY (account, folder, uid)
);
CREATE TABLE IF NOT EXISTS contacts (
    account TEXT, address TEXT, name TEXT, uses INTEGER,
    PRIMARY KEY (account, address)
);
"""


def _quiet(default=None):
    def decorate(method):
        @functools.wraps(method)
        def wrapper(*args):
            try:
                return method(*args)
            except sqlite3.Error:
                logger.exception("Błąd bazy w %s", method.__name__)
                return default

        return wrapper

    return decorate


class MailCache:
    def __init__(self, path=":memory:"):
        self._db = sqlite3.connect(path, timeout=1)
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        if version != SCHEMA_VERSION:
            with self._db:
                for table in TABLES:
                    self._db.execute(f"DROP TABLE IF EXISTS {table}")
                self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self._db.executescript(SCHEMA)

    def close(self):
        self._db.close()

    @_quiet(())
    def folders(self, account):
        rows = self._db.execute(
            "SELECT name, label, role, unread FROM folders"
            " WHERE account = ? ORDER BY position",
            (account,),
        )
        return [Folder(*row) for row in rows]

    @_quiet()
    def save_folders(self, account, folders):
        with self._db:
            self._db.execute("DELETE FROM folders WHERE account = ?", (account,))
            self._db.executemany(
                "INSERT INTO folders VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (account, f.name, f.label, f.role, f.unread, position)
                    for position, f in enumerate(folders)
                ],
            )

    @_quiet({})
    def messages(self, account):
        """Zwraca słownik {folder: wiadomości od najnowszej} dla konta."""
        rows = self._db.execute(
            "SELECT folder, uid, sender, subject, date, seen, flagged, attachments"
            " FROM messages WHERE account = ? ORDER BY folder, position",
            (account,),
        )
        result = {}
        for folder, uid, sender, subject, date, seen, flagged, attachments in rows:
            result.setdefault(folder, []).append(
                Message(
                    uid,
                    sender,
                    subject,
                    datetime.fromisoformat(date) if date else None,
                    bool(seen),
                    bool(flagged),
                    attachments,
                    account,
                    folder,
                )
            )
        return result

    @_quiet()
    def save_messages(self, account, folder, messages):
        """Zastępuje listę folderu. Treści spoza niej, np. starsze niż 90 dni, znikają."""
        where = "account = ? AND folder = ?"
        with self._db:
            self._db.execute(f"DELETE FROM messages WHERE {where}", (account, folder))
            self._db.executemany(
                "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        account,
                        folder,
                        m.uid,
                        m.sender,
                        m.subject,
                        m.date.isoformat() if m.date else None,
                        m.seen,
                        m.flagged,
                        m.attachments,
                        position,
                    )
                    for position, m in enumerate(messages)
                ],
            )
            self._db.execute(
                f"DELETE FROM bodies WHERE {where} AND uid NOT IN"
                f" (SELECT uid FROM messages WHERE {where})",
                (account, folder, account, folder),
            )

    @_quiet()
    def update_flags(self, message):
        with self._db:
            self._db.execute(
                "UPDATE messages SET seen = ?, flagged = ?"
                " WHERE account = ? AND folder = ? AND uid = ?",
                (message.seen, message.flagged, *message.key),
            )

    @_quiet()
    def delete_message(self, key):
        with self._db:
            for table in ("messages", "bodies"):
                self._db.execute(
                    f"DELETE FROM {table} WHERE account = ? AND folder = ? AND uid = ?",
                    key,
                )

    @_quiet()
    def body(self, key):
        row = self._db.execute(
            "SELECT raw FROM bodies WHERE account = ? AND folder = ? AND uid = ?", key
        ).fetchone()
        return row[0] if row else None

    @_quiet()
    def save_body(self, key, raw):
        if len(raw) > MAX_BODY_BYTES:
            return
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO bodies VALUES (?, ?, ?, ?)", (*key, raw)
            )

    @_quiet(())
    def contacts(self):
        """Zwraca adresatów ze wszystkich kont. Ten sam adres może się powtórzyć."""
        rows = self._db.execute("SELECT name, address, uses FROM contacts")
        return [Contact(*row) for row in rows]

    @_quiet()
    def save_contacts(self, account, contacts):
        with self._db:
            self._db.execute("DELETE FROM contacts WHERE account = ?", (account,))
            self._db.executemany(
                "INSERT INTO contacts VALUES (?, ?, ?, ?)",
                [(account, c.address, c.name, c.uses) for c in contacts],
            )

    @_quiet()
    def add_contacts(self, account, contacts):
        """Dopisuje adresatów właśnie wysłanej wiadomości."""
        with self._db:
            self._db.executemany(
                "INSERT INTO contacts VALUES (?, ?, ?, ?)"
                " ON CONFLICT (account, address) DO UPDATE SET"
                " uses = uses + excluded.uses,"
                " name = CASE WHEN excluded.name = '' THEN name ELSE excluded.name END",
                [(account, c.address, c.name, c.uses) for c in contacts],
            )

    @_quiet()
    def keep_accounts(self, emails):
        """Usuwa dane kont, których już nie ma na liście."""
        with self._db:
            for table in TABLES:
                stored = self._db.execute(f"SELECT DISTINCT account FROM {table}")
                for (account,) in stored.fetchall():
                    if account not in emails:
                        self._db.execute(
                            f"DELETE FROM {table} WHERE account = ?", (account,)
                        )


def open_cache():
    """Otwiera bazę w folderze programu. Uszkodzoną tworzy od nowa, bo to tylko kopia."""
    path = config_path().parent / "cache.db"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            return MailCache(path)
        except sqlite3.OperationalError:
            # Np. baza zajęta przez drugie okno programu: nie jest uszkodzona.
            raise
        except sqlite3.DatabaseError:
            logger.warning("Baza jest uszkodzona i powstanie od nowa")
            path.unlink(missing_ok=True)
            return MailCache(path)
    except (OSError, sqlite3.Error):
        logger.exception("Nie udało się otworzyć bazy, działa pamięć tymczasowa")
        return MailCache()
