import imaplib
import re
import ssl
import time
from dataclasses import replace
from datetime import date, timedelta

from .imap_parser import parse_body, parse_fetch, parse_folders, parse_unread

TIMEOUT_SECONDS = 30
IDLE_TAG = b"PTIDLE"
IDLE_ACK_SECONDS = 30
IDLE_POLL_SECONDS = 5
EXISTS_RE = re.compile(rb"\* \d+ EXISTS\b")
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

    def append(self, role, flags, raw):
        """Dopisuje wiadomość do folderu o danej roli, np. Wysłane lub Robocze."""
        folders = parse_folders(self._call(self._imap.list))
        folder = next((f for f in folders if f.role == role), None)
        if folder is None:
            raise ImapError(f"Brak folderu {role}")
        self._call(self._imap.append, quote(folder.name), flags, None, raw)

    def select_for_idle(self, folder):
        self._call(self._imap.select, quote(folder), True)

    def wait_for_new_mail(self, seconds, stopped):
        """Czeka w trybie IDLE. Zwraca True, gdy serwer zgłosił nową wiadomość.

        imaplib w Pythonie 3.13 nie zna IDLE, a czytanie przez jego plik psuje się
        po pierwszym przekroczeniu czasu, więc czytamy wprost z gniazda.
        """
        lines = _SocketLines(self._imap.sock)
        has_mail = False
        try:
            self._imap.send(IDLE_TAG + b" IDLE\r\n")
            has_mail = self._await_idle_start(lines)
            if not has_mail:
                has_mail = self._await_exists(lines, seconds, stopped)
            self._imap.send(b"DONE\r\n")
            return self._await_idle_end(lines) or has_mail
        except (OSError, EOFError) as error:
            raise ImapConnectionError(str(error)) from error
        finally:
            lines.restore_timeout()

    def _await_idle_start(self, lines):
        has_mail = False
        while True:
            line = lines.read(IDLE_ACK_SECONDS)
            if line is None:
                raise ImapConnectionError("Brak odpowiedzi na IDLE")
            if line.startswith(b"+"):
                return has_mail
            if line.startswith(IDLE_TAG):
                raise ImapError(line.decode("ascii", "replace"))
            has_mail = has_mail or _is_new_mail(line)

    def _await_exists(self, lines, seconds, stopped):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and not stopped():
            line = lines.read(IDLE_POLL_SECONDS)
            if line is None:
                continue
            if line.startswith(b"* BYE"):
                raise ImapConnectionError("Serwer zakończył połączenie")
            if _is_new_mail(line):
                return True
        return False

    def _await_idle_end(self, lines):
        has_mail = False
        while True:
            line = lines.read(IDLE_ACK_SECONDS)
            if line is None:
                raise ImapConnectionError("Brak odpowiedzi na DONE")
            if line.startswith(IDLE_TAG):
                return has_mail
            has_mail = has_mail or _is_new_mail(line)

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


class _SocketLines:
    """Czyta wiersze wprost z gniazda z limitem czasu na każdy odczyt."""

    def __init__(self, sock):
        self._sock = sock
        self._buffer = b""

    def read(self, timeout):
        """Zwraca wiersz albo None, gdy w tym czasie nic nie przyszło."""
        self._sock.settimeout(timeout)
        while b"\r\n" not in self._buffer:
            try:
                chunk = self._sock.recv(4096)
            except TimeoutError:
                return None
            if not chunk:
                raise EOFError("Serwer zamknął połączenie")
            self._buffer += chunk
        line, _crlf, self._buffer = self._buffer.partition(b"\r\n")
        return line

    def restore_timeout(self):
        self._sock.settimeout(TIMEOUT_SECONDS)


def _is_new_mail(line):
    return EXISTS_RE.match(line) is not None


def _sort_key(message):
    return (message.date.timestamp() if message.date else 0, message.uid)


def check_login(account, password):
    """Sprawdza dane logowania i od razu się rozłącza."""
    client = ImapClient(account, password)
    client.connect()
    client.close()
