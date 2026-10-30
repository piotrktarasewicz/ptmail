from ptmail.imap_client import since_argument
from ptmail.imap_parser import (
    decode_mutf7,
    parse_fetch,
    parse_folders,
    parse_list_item,
    parse_unread,
)
from datetime import date

HEADER = (
    b"From: =?UTF-8?Q?Jan_Kowalski?= <jan@example.com>\r\n"
    b"Subject: =?UTF-8?B?RmFrdHVyYSB6YSBwYcW6ZHppZXJuaWs=?=\r\n"
    b"Date: Fri, 30 Oct 2026 13:20:00 +0100\r\n\r\n"
)


def test_decode_mutf7():
    assert decode_mutf7("[Gmail]/Wa&AXw-ne") == "[Gmail]/Ważne"
    assert decode_mutf7("A&-B") == "A&B"


def test_gmail_folders_skip_duplicates_and_sort():
    folders = parse_folders(
        [
            b'(\\HasChildren \\Noselect) "/" "[Gmail]"',
            b'(\\HasNoChildren) "/" "Rachunki"',
            b'(\\HasNoChildren \\All) "/" "[Gmail]/All Mail"',
            b'(\\HasNoChildren \\Important) "/" "[Gmail]/Wa&AXw-ne"',
            b'(\\HasNoChildren \\Trash) "/" "[Gmail]/Kosz"',
            b'(\\HasNoChildren \\Sent) "/" "[Gmail]/Wys&AUI-ane"',
            b'(\\HasNoChildren) "/" "INBOX"',
        ]
    )
    assert [folder.label for folder in folders] == [
        "Odebrane",
        "Wysłane",
        "Kosz",
        "Rachunki",
    ]
    assert folders[1].name == "[Gmail]/Wys&AUI-ane"


def test_icloud_roles_come_from_names():
    folders = parse_folders(
        [
            b'(\\HasNoChildren) "/" "Deleted Messages"',
            b'(\\HasNoChildren) "/" "Sent Messages"',
            b'(\\HasNoChildren) "/" INBOX',
        ]
    )
    assert [folder.label for folder in folders] == ["Odebrane", "Wysłane", "Kosz"]


def test_list_item_with_literal_name():
    folder = parse_list_item((b'(\\HasNoChildren) "/" {5}', b'a"b c'))
    assert folder.name == 'a"b c'


def test_parse_unread():
    assert parse_unread([b'"INBOX" (UNSEEN 7)']) == 7


def test_parse_fetch():
    data = [
        (
            b'1 (UID 42 FLAGS (\\Flagged) BODYSTRUCTURE (("TEXT" "PLAIN") '
            b'("APPLICATION" "PDF" NIL NIL NIL "BASE64" 10 NIL '
            b'("ATTACHMENT" ("FILENAME" "a.pdf")) NIL) "MIXED") '
            b"BODY[HEADER.FIELDS (FROM SUBJECT DATE)] {%d}" % len(HEADER),
            HEADER,
        ),
        b")",
    ]
    [message] = parse_fetch(data)
    assert message.uid == 42
    assert message.sender == "Jan Kowalski"
    assert message.subject == "Faktura za październik"
    assert not message.seen
    assert message.flagged
    assert message.attachments == 1
    assert message.date is not None


def test_parse_fetch_with_flags_after_literal_and_two_messages():
    header = b"From: anna@example.com\r\n\r\n"
    data = [
        (b"1 (UID 1 BODY[HEADER.FIELDS (FROM)] {%d}" % len(header), header),
        b" FLAGS (\\Seen))",
        (b"2 (UID 2 BODY[HEADER.FIELDS (FROM)] {%d}" % len(header), header),
        b" FLAGS ())",
    ]
    first, second = parse_fetch(data)
    assert first.sender == "anna@example.com"
    assert first.seen
    assert not second.seen
    assert first.date is None


def test_since_argument_is_independent_of_locale():
    assert since_argument(date(2026, 8, 1)) == "01-Aug-2026"
