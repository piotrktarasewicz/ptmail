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
