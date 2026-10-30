import imaplib
import ssl
from dataclasses import replace
from datetime import date, timedelta

from .imap_parser import parse_body, parse_fetch, parse_folders, parse_unread

TIMEOUT_SECONDS = 30
CACHE_DAYS = 90
MESSAGE_LIMIT = 200
FETCH_ITEMS = "(UID FLAGS BODYSTRUCTURE BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])"
# Skróty miesięcy z RFC 3501, bo strftime zależy od ustawień regionalnych.
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


class ImapError(Exception):
    pass


class ImapAuthError(ImapError):
    pass


class ImapConnectionError(ImapError):
    pass


def quote(name):
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def since_argument(day):
    return f"{day.day:02d}-{MONTHS[day.month - 1]}-{day.year}"


class ImapClient:
    def __init__(self, account, password):
        self._account = account
        self._password = password
        self._imap = None

    @property
    def connected(self):
        return self._imap is not None

    def connect(self):
        provider = self._account.provider
        try:
            self._imap = imaplib.IMAP4_SSL(
                provider.imap_host,
                provider.imap_port,
                ssl_context=ssl.create_default_context(),
                timeout=TIMEOUT_SECONDS,
            )
        except (OSError, imaplib.IMAP4.error) as error:
            raise ImapConnectionError(str(error)) from error
        try:
            self._imap.login(self._account.email, self._password)
        except (imaplib.IMAP4.abort, OSError) as error:
            self.close()
            raise ImapConnectionError(str(error)) from error
        except (imaplib.IMAP4.error, UnicodeEncodeError) as error:
            self.close()
            raise ImapAuthError(str(error)) from error

    def close(self):
        imap, self._imap = self._imap, None
        if imap is None:
            return
        try:
            imap.logout()
        except (OSError, imaplib.IMAP4.error):
            pass

    def list_folders(self):
        data = self._call(self._imap.list)
        return [
            replace(folder, unread=self._unread(folder.name))
            for folder in parse_folders(data)
        ]

    def fetch_recent(self, folder):
        """Nagłówki najnowszych wiadomości z folderu, od najnowszej."""
        self._call(self._imap.select, quote(folder), True)
        since = since_argument(date.today() - timedelta(days=CACHE_DAYS))
        data = self._call(self._imap.uid, "SEARCH", "SINCE", since)
        uids = data[0].split()[-MESSAGE_LIMIT:] if data and data[0] else []
        if not uids:
            return []
        data = self._call(
            self._imap.uid, "FETCH", b",".join(uids).decode("ascii"), FETCH_ITEMS
        )
        return sorted(parse_fetch(data), key=_sort_key, reverse=True)

    def fetch_message(self, folder, uid):
        """Pobiera całą wiadomość i oznacza ją jako przeczytaną."""
        self._call(self._imap.select, quote(folder), False)
        data = self._call(self._imap.uid, "FETCH", str(uid), "(BODY.PEEK[])")
        raw = parse_body(data)
        if raw is None:
            raise ImapError(f"Brak wiadomości {uid}")
        self._call(self._imap.uid, "STORE", str(uid), "+FLAGS.SILENT", "(\\Seen)")
        return raw

    def _unread(self, folder):
        return parse_unread(self._call(self._imap.status, quote(folder), "(UNSEEN)"))

    def _call(self, command, *args):
        try:
            status, data = command(*args)
        except (imaplib.IMAP4.abort, OSError) as error:
            raise ImapConnectionError(str(error)) from error
        except imaplib.IMAP4.error as error:
            raise ImapError(str(error)) from error
        if status != "OK":
            raise ImapError(str(data))
        return data


def _sort_key(message):
    return (message.date.timestamp() if message.date else 0, message.uid)


def check_login(account, password):
    """Sprawdza dane logowania i od razu się rozłącza."""
    client = ImapClient(account, password)
    client.connect()
    client.close()
