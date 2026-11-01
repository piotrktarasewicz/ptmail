"""Parsowanie odpowiedzi IMAP. Bez sieci, żeby dało się to testować."""

import base64
import email
import re
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime

from .i18n import _
from .models import Folder, Message

LIST_RE = re.compile(
    rb'^\((?P<flags>[^)]*)\)\s+(?:"(?:[^"\\]|\\.)*"|NIL)\s+(?P<name>.+)$'
)
UID_RE = re.compile(rb"\bUID (\d+)")
FLAGS_RE = re.compile(rb"\bFLAGS \(([^)]*)\)")
ATTACHMENT_RE = re.compile(rb'"attachment"', re.IGNORECASE)
HEADER_MARKER = b"BODY[HEADER"

# Etykiety zamiast serwerowych nazw. Kolejność słownika to kolejność na liście.
ROLE_LABELS = {
    "inbox": "Odebrane",
    "sent": "Wysłane",
    "drafts": "Robocze",
    "trash": "Kosz",
    "junk": "Spam",
    "archive": "Archiwum",
}
ROLE_FLAGS = {
    b"\\sent": "sent",
    b"\\drafts": "drafts",
    b"\\trash": "trash",
    b"\\junk": "junk",
    b"\\archive": "archive",
}
# iCloud nie zawsze zgłasza role flagami, więc rozpoznajemy je też po nazwie.
ROLE_NAMES = {
    "inbox": "inbox",
    "sent messages": "sent",
    "drafts": "drafts",
    "deleted messages": "trash",
    "junk": "junk",
    "archive": "archive",
}
# \All i \Important to gmailowe Wszystkie wiadomości i Ważne, które dublują skrzynkę.
SKIPPED_FLAGS = {b"\\noselect", b"\\nonexistent", b"\\all", b"\\important"}
SKIPPED_SEARCH_ROLES = {"trash", "junk"}
GMAIL_PREFIX = "[Gmail]/"


def decode_mutf7(value):
    """Dekoduje zmodyfikowany UTF-7 z nazw folderów, np. Wa&AXw-ne na Ważne."""

    def replace(match):
        encoded = match.group(1)
        if not encoded:
            return "&"
        data = encoded.replace(",", "/")
        data += "=" * (-len(data) % 4)
        return base64.b64decode(data).decode("utf-16-be")

    return re.sub(r"&([A-Za-z0-9+,]*)-", replace, value)


def parse_list_item(item):
    """Zamienia wiersz odpowiedzi LIST na Folder albo None, gdy folder pomijamy."""
    fields = _list_fields(item)
    if fields is None:
        return None
    flags, name = fields
    if flags & SKIPPED_FLAGS:
        return None
    role = _folder_role(name, flags)
    return Folder(name, _folder_label(name, role), role)


def _list_fields(item):
    if isinstance(item, tuple):
        line = item[0].rsplit(b"{", 1)[0] + _quoted(item[1])
    else:
        line = item
    match = LIST_RE.match(line)
    if match is None:
        return None
    flags = {flag.lower() for flag in match["flags"].split()}
    return flags, _unquote(match["name"]).decode("ascii", "replace")


def parse_folders(data):
    folders = [parse_list_item(item) for item in data if item]
    return sort_folders([folder for folder in folders if folder is not None])


def parse_search_folders(data):
    """Zwraca foldery do przeszukania całego konta.

    Gmail ma folder z całą pocztą, także zarchiwizowaną. Na liście folderów go
    pomijamy, ale do wyszukiwania jest najlepszy i wystarczy sam jeden.
    """
    for item in data:
        fields = _list_fields(item) if item else None
        if fields is not None and b"\\all" in fields[0]:
            return [fields[1]]
    return [
        folder.name
        for folder in parse_folders(data)
        if folder.role not in SKIPPED_SEARCH_ROLES
    ]


def sort_folders(folders):
    order = {role: index for index, role in enumerate(ROLE_LABELS)}
    return sorted(
        folders,
        key=lambda f: (order.get(f.role, len(order)), f.label.casefold()),
    )


def parse_unread(data):
    match = re.search(rb"UNSEEN (\d+)", _flatten(data))
    return int(match.group(1)) if match else 0


def parse_fetch(data):
    """Rozkłada odpowiedź FETCH. Każda wiadomość kończy się zwykłym wierszem bytes."""
    messages = []
    meta = b""
    header = None
    for item in data:
        if isinstance(item, tuple):
            meta += item[0]
            if HEADER_MARKER in item[0]:
                header = item[1]
        elif item:
            meta += item
            message = _parse_message(meta, header)
            if message is not None:
                messages.append(message)
            meta = b""
            header = None
    return messages


def parse_header_blocks(data):
    """Wyciąga same nagłówki z odpowiedzi FETCH, gdy reszta nie jest potrzebna."""
    return [
        item[1]
        for item in data
        if isinstance(item, tuple) and HEADER_MARKER in item[0]
    ]


def parse_body(data):
    """Wyciąga surową wiadomość z odpowiedzi na FETCH BODY[]."""
    for item in data:
        if isinstance(item, tuple) and b"BODY[" in item[0]:
            return item[1]
    return None


def _parse_message(meta, header):
    uid = UID_RE.search(meta)
    if uid is None or header is None:
        return None
    flags = FLAGS_RE.search(meta)
    flags = flags.group(1).lower().split() if flags else []
    parsed = email.message_from_bytes(header)
    return Message(
        uid=int(uid.group(1)),
        sender=_sender(parsed.get("From", "")),
        subject=decode_header_text(parsed.get("Subject", "")),
        date=parse_date(parsed.get("Date")),
        seen=b"\\seen" in flags,
        flagged=b"\\flagged" in flags,
        attachments=len(ATTACHMENT_RE.findall(meta)),
    )


def _sender(value):
    name, address = parseaddr(decode_header_text(value))
    return name or address


def decode_header_text(value):
    try:
        text = str(make_header(decode_header(str(value))))
    except (LookupError, UnicodeDecodeError, ValueError):
        text = str(value)
    return " ".join(text.split())


def parse_date(value):
    if not value:
        return None
    try:
        return parsedate_to_datetime(str(value)).astimezone()
    except (TypeError, ValueError, OverflowError):
        return None


def _folder_role(name, flags):
    for flag, role in ROLE_FLAGS.items():
        if flag in flags:
            return role
    return ROLE_NAMES.get(name.casefold())


def _folder_label(name, role):
    if role is not None:
        return _(ROLE_LABELS[role])
    return decode_mutf7(name).removeprefix(GMAIL_PREFIX)


def _flatten(data):
    parts = []
    for item in data:
        if isinstance(item, tuple):
            parts.extend(item)
        elif item:
            parts.append(item)
    return b" ".join(parts)


def _quoted(value):
    return b'"' + value.replace(b"\\", b"\\\\").replace(b'"', b'\\"') + b'"'


def _unquote(value):
    value = value.strip()
    if value.startswith(b'"') and value.endswith(b'"'):
        return re.sub(rb"\\(.)", rb"\1", value[1:-1])
    return value
