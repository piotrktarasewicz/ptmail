"""Zdania czytane przez NVDA na listach."""

from datetime import datetime, timedelta

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


def mailbox_sentence(label, unread):
    return f"{label}, {unread_text(unread)}" if unread else label


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
