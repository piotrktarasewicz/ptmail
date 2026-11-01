"""Podpowiadanie adresów z wysłanej poczty."""

import pytest
import wx

from ptmail import mail_worker
from ptmail.accounts import Account
from ptmail.cache import MailCache
from ptmail.compose import Draft, parse_recipients
from ptmail.contacts import (
    contacts_from_headers,
    current_fragment,
    insert_contact,
    matching_contacts,
    merge_contacts,
    parse_contacts,
    suggestion_sentence,
)
from ptmail.imap_client import ImapClient, ImapConnectionError
from ptmail.imap_parser import parse_header_blocks
from ptmail.models import Contact
from ptmail.ui import compose_dialog as cd
from ptmail.ui import main_frame as mf

GMAIL = Account("Gmail", "Ja@gmail.com", "gmail")
ANNA = Contact("Anna Kowalska", "anna@example.com", 5)
ANDRZEJ = Contact("Andrzej Nowak", "andrzej@example.com", 2)
BOK = Contact("", "bok@sklep.pl", 1)
CONTACTS = [ANNA, ANDRZEJ, BOK]


def test_headers_are_counted_with_most_used_first():
    blocks = [
        b"To: bok@sklep.pl\r\n\r\n",
        b"To: =?utf-8?b?QW5uYSBLb3dhbHNrYQ==?= <Anna@Example.com>,\r\n"
        b" bok@sklep.pl\r\nCc: Jan <jan@example.com>\r\n\r\n",
        b"To: bok@sklep.pl, undisclosed-recipients:;\r\n\r\n",
    ]
    assert contacts_from_headers(blocks) == [
        Contact("", "bok@sklep.pl", 3),
        Contact("Anna Kowalska", "anna@example.com"),
        Contact("Jan", "jan@example.com"),
    ]


def test_newest_name_wins_and_empty_name_does_not_erase_it():
    contacts = [
        Contact("Stara", "a@b.pl"),
        Contact("Nowa", "a@b.pl"),
        Contact("", "a@b.pl"),
    ]
    assert merge_contacts(contacts) == [Contact("Nowa", "a@b.pl", 3)]


def test_name_that_would_break_the_field_is_dropped():
    assert parse_contacts('"a@b.pl" <a@b.pl>') == [Contact("", "a@b.pl")]
    assert contacts_from_headers([b'To: "Kowalski; Anna" <a@b.pl>\r\n\r\n']) == [
        Contact("", "a@b.pl")
    ]


def test_matching_by_address_and_every_word_of_name():
    assert matching_contacts(CONTACTS, "an") == [ANNA, ANDRZEJ]
    assert matching_contacts(CONTACTS, "KOW") == [ANNA]
    assert matching_contacts(CONTACTS, "anna kow") == [ANNA]
    assert matching_contacts(CONTACTS, "bok@s") == [BOK]
    assert matching_contacts(CONTACTS, "example") == []


def test_single_letter_suggests_nothing():
    assert matching_contacts(CONTACTS, "a") == []
    assert matching_contacts(CONTACTS, " ") == []


def test_fragment_is_the_address_under_the_caret():
    assert current_fragment("an", 2) == (0, 2)
    assert current_fragment("a@b.pl, an", 10) == (8, 10)
    assert current_fragment("a@b.pl; an", 10) == (8, 10)
    assert current_fragment("an, a@b.pl", 2) == (0, 2)


def test_insert_replaces_only_the_fragment():
    assert insert_contact("an", 0, 2, ANNA) == (
        "Anna Kowalska <anna@example.com>, ",
        34,
    )
    text, caret = insert_contact("x@y.pl, bo", 8, 10, BOK)
    assert text == "x@y.pl, bok@sklep.pl, "
    assert caret == len(text)
    text, caret = insert_contact("an, x@y.pl", 0, 2, BOK)
    assert text == "bok@sklep.pl, x@y.pl"
    assert caret == 14


def test_sentence_gives_position_only_among_several():
    assert suggestion_sentence(BOK, 0, 1) == "bok@sklep.pl"
    assert suggestion_sentence(ANNA, 1, 3) == "Anna Kowalska, anna@example.com, 2 z 3"


def test_comma_in_name_stays_inside_one_address():
    contact = Contact("Kowalska, Anna", "anna@example.com")
    text, _caret = insert_contact("an", 0, 2, contact)
    valid, invalid = parse_recipients(text.strip(" ,;"))
    assert valid == ["anna@example.com"]
    assert invalid == []


class SentImap:
    def __init__(self, uids=b"1 2 3"):
        self.uids = uids
        self.commands = []

    def list(self):
        return "OK", [b'(\\HasNoChildren \\Sent) "/" "[Gmail]/Wys&AUI-ane"']

    def select(self, mailbox, readonly):
        self.commands.append(("select", mailbox, readonly))
        return "OK", [b"3"]

    def uid(self, command, *args):
        self.commands.append((command, *args))
        if command == "SEARCH":
            return "OK", [self.uids]
        return "OK", [
            (b"1 (BODY[HEADER.FIELDS (TO CC)] {20}", b"To: a@b.pl\r\n\r\n"),
            b")",
        ]


def client_with(imap):
    client = ImapClient(GMAIL, "x")
    client._imap = imap
    return client


def test_only_recipient_headers_are_read_without_touching_flags():
    imap = SentImap()
    assert client_with(imap).fetch_sent_contacts() == [Contact("", "a@b.pl")]
    assert imap.commands == [
        ("select", '"[Gmail]/Wys&AUI-ane"', True),
        ("SEARCH", "ALL"),
        ("FETCH", "1,2,3", "(BODY.PEEK[HEADER.FIELDS (TO CC)])"),
    ]


def test_empty_sent_folder_gives_no_contacts():
    assert client_with(SentImap(b"")).fetch_sent_contacts() == []


def test_header_blocks_skip_other_items():
    data = [(b"1 (BODY[HEADER.FIELDS (TO CC)] {3}", b"abc"), b")", (b"x", b"y"), None]
    assert parse_header_blocks(data) == [b"abc"]


class Listener:
    def __init__(self):
        self.contacts = []

    def on_contacts(self, contacts):
        self.contacts.append(contacts)


class FailingClient:
    connected = True

    def __init__(self):
        self.closed = False

    def fetch_sent_contacts(self):
        raise ImapConnectionError("brak")

    def connect(self):
        raise ImapConnectionError("brak")

    def close(self):
        self.closed = True


def make_worker(listener):
    return mail_worker.MailWorker(
        GMAIL, "x", listener, lambda _worker, handler, *args: handler(*args)
    )


def test_worker_passes_contacts_to_listener():
    listener = Listener()
    worker = make_worker(listener)
    worker._client = client_with(SentImap())
    worker._collect_contacts()
    assert listener.contacts == [[Contact("", "a@b.pl")]]


def test_failed_collection_is_silent():
    listener = Listener()
    worker = make_worker(listener)
    worker._client = FailingClient()
    worker._collect_contacts()
    assert listener.contacts == []
    assert worker._client.closed


def test_cache_replaces_account_contacts_and_keeps_others():
    cache = MailCache()
    cache.save_contacts("a", [ANNA])
    cache.save_contacts("b", [BOK])
    cache.save_contacts("a", [ANDRZEJ])
    assert sorted(c.address for c in cache.contacts()) == [
        "andrzej@example.com",
        "bok@sklep.pl",
    ]


def test_cache_adds_sent_recipients():
    cache = MailCache()
    cache.save_contacts("a", [ANNA])
    cache.add_contacts("a", [Contact("", ANNA.address), Contact("Jan", "jan@b.pl")])
    stored = {c.address: c for c in cache.contacts()}
    assert stored[ANNA.address] == Contact("Anna Kowalska", ANNA.address, 6)
    assert stored["jan@b.pl"] == Contact("Jan", "jan@b.pl", 1)


def test_cache_forgets_contacts_of_removed_account():
    cache = MailCache()
    cache.save_contacts("a", [ANNA])
    cache.keep_accounts(["b"])
    assert cache.contacts() == []


class FakeWorker:
    def __init__(self):
        self.sent = []
        self.account = GMAIL

    def send(self, recipients, raw, on_done):
        self.sent.append((recipients, raw))
        self.on_done = on_done

    def save_draft(self, raw, on_done):
        self.on_done = on_done

    def stop(self):
        pass


@pytest.fixture(scope="module")
def app():
    application = wx.App()
    yield application
    del application


@pytest.fixture
def spoken(monkeypatch):
    said = []
    monkeypatch.setattr(cd, "speak", said.append)
    return said


@pytest.fixture
def dialog(app, spoken):
    parent = wx.Frame(None)
    window = cd.ComposeDialog(
        parent, [GMAIL], Draft(), {GMAIL.email: FakeWorker()}, CONTACTS
    )
    yield window
    window.Destroy()
    parent.Destroy()


def type_text(dialog, text, field=None):
    field = field or dialog._to
    field.SetValue(text)
    field.SetInsertionPointEnd()
    dialog._suggestion_timer.Stop()
    dialog._suggest()


def press(dialog, key, control=False):
    event = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
    event.SetKeyCode(key)
    event.SetControlDown(control)
    dialog._on_key(event)


def test_typing_speaks_first_suggestion_with_position(dialog, spoken):
    type_text(dialog, "an")
    assert spoken == ["Anna Kowalska, anna@example.com, 1 z 2"]


def test_typing_only_arms_the_timer(dialog, spoken):
    dialog._to.SetValue("an")
    assert dialog._suggestion_timer.IsRunning()
    assert spoken == []
    dialog._hide_suggestions()


def test_arrows_move_between_suggestions_and_wrap(dialog, spoken):
    type_text(dialog, "an")
    press(dialog, wx.WXK_DOWN)
    assert spoken[-1] == "Andrzej Nowak, andrzej@example.com, 2 z 2"
    press(dialog, wx.WXK_DOWN)
    assert spoken[-1] == "Anna Kowalska, anna@example.com, 1 z 2"
    press(dialog, wx.WXK_UP)
    assert spoken[-1] == "Andrzej Nowak, andrzej@example.com, 2 z 2"


def test_enter_inserts_address_and_stays_in_field(dialog, spoken):
    type_text(dialog, "x@y.pl, an")
    press(dialog, wx.WXK_DOWN)
    press(dialog, wx.WXK_RETURN)
    assert dialog._to.GetValue() == "x@y.pl, Andrzej Nowak <andrzej@example.com>, "
    assert dialog._to.GetInsertionPoint() == len(dialog._to.GetValue())
    assert spoken[-1] == "Dodano: Andrzej Nowak"
    assert dialog._suggestions == []
    assert not dialog._suggestion_timer.IsRunning()


def test_suggestions_work_in_cc(dialog):
    type_text(dialog, "bo", dialog._cc)
    press(dialog, wx.WXK_RETURN)
    assert dialog._cc.GetValue() == "bok@sklep.pl, "
    assert dialog._to.GetValue() == ""


def test_escape_hides_suggestions_and_keeps_window(dialog, spoken, monkeypatch):
    cancelled = []
    monkeypatch.setattr(dialog, "cancel", lambda: cancelled.append(True))
    type_text(dialog, "an")
    press(dialog, wx.WXK_ESCAPE)
    assert spoken[-1] == "Podpowiedzi ukryte"
    assert cancelled == []
    press(dialog, wx.WXK_ESCAPE)
    assert cancelled == [True]


def test_ctrl_enter_sends_despite_suggestions(dialog):
    type_text(dialog, "bok@sklep.pl")
    press(dialog, wx.WXK_RETURN, control=True)
    assert len(dialog._workers[GMAIL.email].sent) == 1


def test_no_match_says_nothing(dialog, spoken):
    type_text(dialog, "zzz")
    assert spoken == []
    assert dialog._suggestions == []


def test_comma_left_after_insert_does_not_break_sending(dialog):
    type_text(dialog, "bo")
    press(dialog, wx.WXK_RETURN)
    type_text(dialog, dialog._to.GetValue() + "an")
    press(dialog, wx.WXK_RETURN)
    dialog.send()
    recipients, raw = dialog._workers[GMAIL.email].sent[0]
    assert recipients == ["bok@sklep.pl", "anna@example.com"]
    assert b"To: bok@sklep.pl, Anna Kowalska <anna@example.com>\r\n" in raw


def test_sent_draft_is_set_only_after_success(dialog, monkeypatch):
    monkeypatch.setattr(cd.wx, "CallLater", lambda *args: None)
    dialog._to.SetValue("a@b.pl")
    dialog.send()
    worker = dialog._workers[GMAIL.email]
    worker.on_done(False, "Nie udało się")
    assert dialog.sent_draft is None
    dialog.send()
    worker.on_done(True, "Wysłano")
    assert dialog.sent_draft.to == "a@b.pl"


def test_frame_offers_merged_contacts_without_own_addresses(app, monkeypatch):
    monkeypatch.setattr(mf, "get_password", lambda account: None)
    frame = mf.MainFrame()
    frame._accounts = [GMAIL]
    frame._cache.save_contacts("x", [ANNA, Contact("", "ja@gmail.com", 9)])
    frame._cache.save_contacts("y", [Contact("", ANNA.address, 1)])
    assert frame._contacts() == [Contact("Anna Kowalska", ANNA.address, 6)]
    frame._workers = {}
    frame.Destroy()


def test_frame_stores_contacts_from_worker(app, monkeypatch):
    frame = mf.MainFrame()
    frame.on_contacts("x", [ANNA])
    assert frame._cache.contacts() == [ANNA]
    frame.Destroy()
