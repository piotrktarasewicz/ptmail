"""Interia: bez MOVE, role folderów z XLIST i zwykłe hasło konta."""

import imaplib

import pytest
import wx

from ptmail.accounts import PROVIDERS, Account
from ptmail.imap_client import ImapClient, ImapError
from ptmail.imap_parser import parse_fetch, parse_folders
from ptmail.ui import account_dialog as ad

INTERIA = Account("Interia", "ja@interia.pl", "interia")
GMAIL = Account("Gmail", "ja@gmail.com", "gmail")
LISTING = [
    b'(\\HasNoChildren \\Inbox) "/" "INBOX"',
    b'(\\HasNoChildren \\Sent) "/" "Wys&AUI-ane"',
    b'(\\HasNoChildren \\Trash) "/" "Kosz"',
    b'(\\HasNoChildren \\Spam) "/" "SPAM"',
    b'(\\HasNoChildren \\Drafts) "/" "Robocze"',
]


class FakeImap:
    def __init__(self, failing=None):
        self.calls = []
        self.failing = failing

    def select(self, folder, readonly):
        self.calls.append(("select", folder, readonly))
        return "OK", [b"1"]

    def uid(self, *args):
        self.calls.append(args)
        if args[0] == self.failing:
            return "NO", [b"nie"]
        return "OK", [None]

    def xatom(self, name, *args):
        self.calls.append((name, *args))
        return "OK", [b"done"]

    def response(self, code):
        return code, LISTING

    def list(self):
        pytest.fail("Interia nie podaje ról przez LIST")

    def status(self, folder, items):
        return "OK", [b'"x" (UNSEEN 0)']


def client_for(account, imap):
    client = ImapClient(account, "x")
    client._imap = imap
    return client


def test_interia_uses_verified_servers():
    provider = PROVIDERS["interia"]
    assert (provider.imap_host, provider.imap_port) == ("poczta.interia.pl", 993)
    assert (provider.smtp_host, provider.smtp_port) == ("poczta.interia.pl", 587)
    assert not provider.saves_sent


def test_imaplib_knows_uid_commands_of_fallback():
    assert {"COPY", "STORE", "EXPUNGE"} <= set(imaplib.Commands)


def test_move_copies_then_removes_only_that_message():
    imap = FakeImap()
    client_for(INTERIA, imap).move_to_folder("INBOX", 5, "Kosz")
    assert imap.calls == [
        ("select", '"INBOX"', False),
        ("COPY", "5", '"Kosz"'),
        ("STORE", "5", "+FLAGS.SILENT", "(\\Deleted)"),
        ("EXPUNGE", "5"),
    ]


def test_failed_copy_leaves_message_alone():
    imap = FakeImap(failing="COPY")
    with pytest.raises(ImapError):
        client_for(INTERIA, imap).move_to_folder("INBOX", 5, "Kosz")
    assert ("STORE", "5", "+FLAGS.SILENT", "(\\Deleted)") not in imap.calls


def test_failed_expunge_still_counts_as_moved():
    imap = FakeImap(failing="EXPUNGE")
    client_for(INTERIA, imap).move_to_folder("INBOX", 5, "Kosz")
    assert ("STORE", "5", "+FLAGS.SILENT", "(\\Deleted)") in imap.calls


def test_message_marked_deleted_is_not_shown():
    header = b"From: Jan <jan@example.com>\r\nSubject: x\r\n\r\n"
    data = [
        (b"1 (UID 5 FLAGS (\\Seen \\Deleted) BODY[HEADER.FIELDS (FROM SUBJECT DATE)] {40}", header),
        b")",
        (b"2 (UID 6 FLAGS (\\Seen) BODY[HEADER.FIELDS (FROM SUBJECT DATE)] {40}", header),
        b")",
    ]
    assert [m.uid for m in parse_fetch(data)] == [6]


def test_other_providers_still_use_move():
    imap = FakeImap()
    client_for(GMAIL, imap).move_to_folder("INBOX", 5, "Kosz")
    assert imap.calls[1:] == [("MOVE", "5", '"Kosz"')]


def test_folder_roles_come_from_xlist():
    roles = {f.role: f.name for f in parse_folders(LISTING)}
    assert roles == {
        "inbox": "INBOX",
        "sent": "Wys&AUI-ane",
        "trash": "Kosz",
        "junk": "SPAM",
        "drafts": "Robocze",
    }


def test_trash_is_found_through_xlist():
    imap = FakeImap()
    client_for(INTERIA, imap).move("INBOX", 5, "trash")
    assert ("XLIST", '"" "*"') in imap.calls
    assert ("COPY", "5", '"Kosz"') in imap.calls


def test_folder_list_uses_xlist():
    folders = client_for(INTERIA, FakeImap()).list_folders()
    assert [f.label for f in folders][:3] == ["Odebrane", "Wysłane", "Robocze"]


@pytest.fixture
def dialog(monkeypatch):
    app = wx.App()
    parent = wx.Frame(None)
    window = ad.AccountDialog(parent)
    window.checked = []
    monkeypatch.setattr(ad.threading, "Thread", FakeThread(window.checked))
    yield window
    window.Destroy()
    parent.Destroy()
    del app


class FakeThread:
    def __init__(self, seen):
        self.seen = seen

    def __call__(self, target, args, daemon):
        self.seen.append(args)
        return self

    def start(self):
        pass


def choose(dialog, key):
    dialog._provider.SetSelection(list(PROVIDERS).index(key))
    dialog._show_password_label()


def test_interia_is_on_provider_list(dialog):
    assert dialog._provider.GetStrings() == ["Gmail", "iCloud", "Interia"]


def test_password_label_follows_provider(dialog):
    label = dialog._password.GetPrevSibling()
    assert label.GetLabel() == "Hasło aplikacji:"
    choose(dialog, "interia")
    assert label.GetLabel() == "Hasło:"
    choose(dialog, "icloud")
    assert label.GetLabel() == "Hasło aplikacji:"


def test_spaces_stay_in_ordinary_password(dialog):
    choose(dialog, "interia")
    dialog._email.SetValue("ja@interia.pl")
    dialog._password.SetValue("moje hasło")
    dialog._on_ok(None)
    account, password = dialog.checked[0]
    assert account.provider_key == "interia"
    assert password == "moje hasło"


def test_spaces_are_removed_from_app_password(dialog):
    dialog._email.SetValue("ja@gmail.com")
    dialog._password.SetValue("abcd efgh")
    dialog._on_ok(None)
    assert dialog.checked[0][1] == "abcdefgh"


def test_missing_password_message_follows_provider(dialog):
    choose(dialog, "interia")
    dialog._email.SetValue("ja@interia.pl")
    dialog._on_ok(None)
    assert dialog._status.GetValue() == "Wpisz hasło"


def test_rejected_login_says_what_to_check():
    interia = ad.AccountDialog._login_error(PROVIDERS["interia"])
    assert interia.startswith("Serwer odrzucił adres lub hasło. ")
    assert "dostęp dla programów pocztowych" in interia
    gmail = ad.AccountDialog._login_error(PROVIDERS["gmail"])
    assert gmail == "Serwer odrzucił adres lub hasło aplikacji"
