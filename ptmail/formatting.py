"""Zdania czytane przez NVDA na listach."""

from datetime import datetime, timedelta
from pathlib import PurePath

from .i18n import _, plural

WEEKDAYS = (
    "poniedziałek",
    "wtorek",
    "środa",
    "czwartek",
    "piątek",
    "sobota",
    "niedziela",
)


def unread_text(count):
    return plural(
        count, "{count} nieprzeczytana", "{count} nieprzeczytane", "{count} nieprzeczytanych"
    )


def attachments_text(count):
    return plural(count, "{count} załącznik", "{count} załączniki", "{count} załączników")


def mailbox_sentence(label, unread, account_name=None):
    parts = (label, unread_text(unread) if unread else "", account_name or "")
    return ", ".join(part for part in parts if part)


def format_date(value, now=None):
    now = now or datetime.now().astimezone()
    value = value.astimezone(now.tzinfo)
    today = now.date()
    day = value.date()
    if day == today:
        return value.strftime("%H:%M")
    if day == today - timedelta(days=1):
        return _("wczoraj")
    if day < today and day.isocalendar()[:2] == today.isocalendar()[:2]:
        return _(WEEKDAYS[day.weekday()])
    return value.strftime("%d.%m.%Y")


def format_size(size):
    if size < 1024:
        return _("{size} B").format(size=size)
    if size < 1024 * 1024:
        return _("{size} KB").format(size=round(size / 1024))
    return _("{size} MB").format(size=f"{size / 1024 / 1024:.1f}".replace(".", ","))


def attachment_sentence(attachment):
    """Nazwa pliku, typ i rozmiar, np. faktura.pdf, PDF, 120 KB."""
    extension = PurePath(attachment.filename).suffix.lstrip(".")
    kind = extension or attachment.content_type.partition("/")[2]
    return ", ".join(
        (attachment.filename, kind.upper(), format_size(len(attachment.data)))
    )


def message_document(content):
    """Tekst pola wiadomości: sama treść i na końcu linia o załącznikach."""
    count = len(content.attachments)
    footer = (
        _("Załączniki: {count}").format(count=count)
        if count
        else _("Brak załączników")
    )
    return "\n\n".join(part for part in (content.body, footer) if part)


def utf16_ranges(text, links):
    """Przelicza pozycje linków na jednostki UTF-16 używane przez pole Windows.

    Emoji to w Pythonie jeden znak, a w polu Windows dwa, więc bez tego
    wszystkie linki za emoji byłyby przesunięte.
    """
    ranges = []
    position = 0
    extra = 0

    def advance(index):
        nonlocal position, extra
        extra += sum(1 for char in text[position:index] if ord(char) > 0xFFFF)
        position = index
        return index + extra

    for link in sorted(links, key=lambda item: item.start):
        ranges.append((advance(link.start), advance(link.end), link))
    return ranges


def message_sentence(message, account_name=None, now=None):
    """Kolejność ze specyfikacji: status, nadawca, temat, załączniki, konto, data."""
    parts = [
        _("nieprzeczytana") if not message.seen else "",
        _("oflagowana") if message.flagged else "",
        message.sender,
        message.subject,
        attachments_text(message.attachments) if message.attachments else "",
        account_name or "",
        format_date(message.date, now) if message.date else "",
    ]
    return ", ".join(part for part in parts if part)
