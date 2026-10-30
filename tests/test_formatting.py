from datetime import datetime, timezone

from ptmail.formatting import (
    attachments_text,
    format_date,
    mailbox_sentence,
    message_sentence,
)
from ptmail.models import Message

# Piątek
NOW = datetime(2026, 10, 30, 15, 0, tzinfo=timezone.utc)


def message(**changes):
    values = dict(
        uid=1,
        sender="Jan Kowalski",
        subject="Faktura za październik",
        date=datetime(2026, 10, 30, 13, 20, tzinfo=timezone.utc),
        seen=False,
        flagged=False,
        attachments=2,
    )
    values.update(changes)
    return Message(**values)


def test_sentence_matches_spec_example():
    assert message_sentence(message(), "iCloud", NOW) == (
        "nieprzeczytana, Jan Kowalski, Faktura za październik, "
        "2 załączniki, iCloud, 13:20"
    )


def test_sentence_skips_empty_parts():
    assert (
        message_sentence(message(seen=True, subject="", attachments=0), now=NOW)
        == "Jan Kowalski, 13:20"
    )


def test_flagged_is_read_as_status():
    assert message_sentence(message(seen=True, flagged=True), now=NOW).startswith(
        "oflagowana, Jan Kowalski"
    )


def test_dates():
    def at(day):
        return datetime(2026, 10, day, 8, 5, tzinfo=timezone.utc)

    assert format_date(at(30), NOW) == "08:05"
    assert format_date(at(29), NOW) == "wczoraj"
    assert format_date(at(27), NOW) == "wtorek"
    assert format_date(at(25), NOW) == "25.10.2026"


def test_sunday_after_monday_is_yesterday():
    monday = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)
    sunday = datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc)
    assert format_date(sunday, monday) == "wczoraj"


def test_polish_plurals():
    assert attachments_text(1) == "1 załącznik"
    assert attachments_text(3) == "3 załączniki"
    assert attachments_text(5) == "5 załączników"
    assert attachments_text(12) == "12 załączników"
    assert attachments_text(22) == "22 załączniki"


def test_mailbox_sentence():
    assert (
        mailbox_sentence("Wszystkie skrzynki", 3)
        == "Wszystkie skrzynki, 3 nieprzeczytane"
    )
    assert mailbox_sentence("Kosz", 0) == "Kosz"
