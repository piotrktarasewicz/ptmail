from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Folder:
    name: str  # nazwa na serwerze, w zmodyfikowanym UTF-7
    label: str
    role: str | None = None
    unread: int = 0


@dataclass(frozen=True)
class Message:
    uid: int
    sender: str
    subject: str
    date: datetime | None
    seen: bool
    flagged: bool
    attachments: int


@dataclass(frozen=True)
class Attachment:
    filename: str
    content_type: str
    data: bytes


@dataclass(frozen=True)
class Link:
    start: int  # pozycje w treści, w znakach Pythona
    end: int
    url: str
    text: str


@dataclass(frozen=True)
class MessageContent:
    sender: str
    recipients: str
    subject: str
    date: datetime | None
    body: str
    attachments: tuple[Attachment, ...]
    links: tuple[Link, ...] = ()
    # Pary (nazwa, adres) i identyfikatory potrzebne przy odpowiadaniu.
    from_addresses: tuple[tuple[str, str], ...] = ()
    reply_to_addresses: tuple[tuple[str, str], ...] = ()
    to_addresses: tuple[tuple[str, str], ...] = ()
    cc_addresses: tuple[tuple[str, str], ...] = ()
    message_id: str = ""
    references: str = ""
