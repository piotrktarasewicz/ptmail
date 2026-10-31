import threading
from datetime import datetime, timezone

import pytest
import wx

from ptmail.accounts import Account
from ptmail.formatting import found_text
from ptmail.imap_client import ImapClient, ImapError
from ptmail.imap_parser import parse_search_folders
from ptmail.mail_worker import MailWorker
from ptmail.models import Folder, Message, MessageContent
from ptmail.ui import main_frame as mf
from ptmail.ui.search_dialog import SearchDialog

GMAIL = Account("Gmail", "ja@gmail.com", "gmail")
ICLOUD = Account("iCloud", "ja@icloud.com", "icloud")
ALL_MAIL = "[Gmail]/All Mail"


def at(hour):
    return datetime(2026, 10, 30, hour, 0, tzinfo=timezone.utc)


def message(uid, hour, seen=False):
    return Message(uid, "Jan", f"temat {uid}", at(hour), seen, False, 0)


def test_gmail_is_searched_through_all_mail():
    data = [
        b'(\\HasNoChildren) "/" "INBOX"',
        b'(\\HasNoChildren \\All) "/" "[Gmail]/All Mail"',
        b'(\\HasNoChildren) "/" "Rachunki"',
    ]
    assert parse_search_folders(data) == [ALL_MAIL]


def test_icloud_searches_folders_without_trash_and_spam():
    data = [
        b'(\\HasNoChildren) "/" "INBOX"',
        b'(\\HasNoChildren) "/" "Deleted Messages"',
        b'(\\HasNoChildren \\Junk) "/" "Junk"',
        b'(\\HasNoChildren) "/" "Rachunki"',
        b'(\\HasNoChildren) "/" "Archive"',
    ]
    assert parse_search_folders(data) == ["INBOX", "Archive", "Rachunki"]


class FakeImap:
    def __init__(self):
        self.calls = []
        self.literal = None
        self.uids = b"1 2"

    def list(self):
        return "OK", [
            b'(\\HasNoChildren) "/" "INBOX"',
            b'(\\HasNoChildren) "/" "Rachunki"',
        ]

    def select(self, folder, readonly):
        self.calls.append(("select", folder, readonly))
        return "OK", [b"2"]

    def uid(self, *args):
        self.calls.append((*args, self.literal))
        self.literal = None
        if args[0] == "SEARCH":
            return "OK", [self.uids]
        header = b"From: a@b.pl\r\nSubject: x\r\n\r\n"
        return "OK", [
            (b"1 (UID 1 BODY[HEADER.FIELDS (FROM)] {%d}" % len(header), header),
            b")",
        ]


def client_with(imap):
    client = ImapClient(ICLOUD, "x")
    client._imap = imap
    return client


def test_query_goes_as_utf8_literal_in_read_only_folder():
    imap = FakeImap()
    client_with(imap).search("INBOX", "wpłata żółć")
    assert imap.calls[0] == ("select", '"INBOX"', True)
    assert imap.calls[1] == (
        "SEARCH",
        "CHARSET",
        "UTF-8",
        "TEXT",
        "wpłata żółć".encode("utf-8"),
    )


def test_no_results_does_not_fetch():
    imap = FakeImap()
    imap.uids = b""
    assert client_with(imap).search("INBOX", "x") == []
    assert len(imap.calls) == 2


def test_search_everywhere_visits_each_folder():
    imap = FakeImap()
    results = client_with(imap).search_everywhere("x")
    assert [folder for folder, _messages in results] == ["INBOX", "Rachunki"]


def test_search_limit_keeps_newest_uids():
    imap = FakeImap()
    imap.uids = b" ".join(str(uid).encode() for uid in range(1, 151))
    client_with(imap).search("INBOX", "x")
    fetch = next(call for call in imap.calls if call[0] == "FETCH")
    assert fetch[1].startswith("51,") and fetch[1].endswith(",150")


def test_found_text():
    assert found_text(1) == "Znaleziono 1 wiadomość"
    assert found_text(3) == "Znaleziono 3 wiadomości"


class SearchingClient:
    connected = True

    def __init__(self, error=None):
        self.error = error

    def close(self):
        pass

    def search(self, folder, query):
        if self.error:
            raise self.error
        return [message(1, 9)]

    def search_everywhere(self, query):
        return [("INBOX", []), ("A", [message(2, 9)])]


def run_search(client, folder):
    results = []
    done = threading.Event()

    class Listener:
        def on_search_done(self, search_id, found):
            results.append((search_id, found))
            done.set()

    worker = MailWorker(
        ICLOUD, "x", Listener(), lambda _w, handler, *args: handler(*args)
    )
    worker._client = client
    worker.start()
    worker.search(7, "x", folder)
    assert done.wait(2)
    worker.stop()
    worker.join(2)
    return results


def test_worker_searches_one_folder():
    assert run_search(SearchingClient(), "INBOX") == [
        (7, [("INBOX", [message(1, 9)])])
    ]


def test_worker_searches_whole_account():
    assert run_search(SearchingClient(), None)[0][1][1][0] == "A"


def test_worker_reports_failure():
    assert run_search(SearchingClient(ImapError("x")), "INBOX") == [(7, None)]


class RecordingClient:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda *args: self.calls.append((name, *args))


class FakeWorker:
    def __init__(self):
        self.client = RecordingClient()
        self.searches = []
        self.opened = []

    def search(self, search_id, query, folder=None):
        self.searches.append((search_id, query, folder))

    def open_message(self, folder, uid):
        self.opened.append((folder, uid))

    def open_folder(self, folder):
        pass

    def refresh(self, folder, silent=False):
        pass

    def perform(self, run, failure_text):
        run(self.client)

    def stop(self):
        pass


@pytest.fixture(scope="module")
def app():
    application = wx.App()
    yield application
    del application


@pytest.fixture
def frame(app, monkeypatch):
    spoken = []
    monkeypatch.setattr(mf, "speak", spoken.append)
    monkeypatch.setattr(mf, "play", lambda name: None)
    monkeypatch.setattr(
        mf.wx, "CallLater", lambda ms, run, *args: run(*args)
    )
    window = mf.MainFrame()
    window._accounts = [GMAIL, ICLOUD]
    window._workers = {GMAIL.email: FakeWorker(), ICLOUD.email: FakeWorker()}
    window.spoken = spoken
    window.Show()
    window.on_folders(GMAIL.email, [Folder("INBOX", "Odebrane", "inbox", 1)])
    window.on_folders(ICLOUD.email, [Folder("INBOX", "Odebrane", "inbox", 1)])
    window.on_messages(GMAIL.email, "INBOX", [message(1, 9)], False)
    window.on_messages(ICLOUD.email, "INBOX", [message(1, 8), message(2, 7)], False)
    yield window
    window._workers = {}
    window.Destroy()


def key(window, code, ctrl=False):
    event = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
    event.SetKeyCode(code)
    event.SetControlDown(ctrl)
    window._on_key(event)


def search(frame, everywhere=False):
    frame._start_search("faktura", everywhere)
    return frame._last_search_id


def finish(frame, search_id):
    frame.on_search_done(
        GMAIL.email, search_id, [(ALL_MAIL, [message(5, 10)])]
    )
    frame.on_search_done(
        ICLOUD.email, search_id, [("INBOX", [message(1, 8)]), ("A", [message(3, 11)])]
    )


def test_current_all_mailboxes_searches_inbox_of_each_account(frame):
    search(frame)
    assert frame._workers[GMAIL.email].searches == [(1, "faktura", "INBOX")]
    assert frame._workers[ICLOUD.email].searches == [(1, "faktura", "INBOX")]
    assert frame.spoken == ["Wyszukiwanie"]


def test_current_folder_searches_only_that_account(frame):
    frame._mailbox_key = (ICLOUD.email, "Rachunki")
    search(frame)
    assert frame._workers[ICLOUD.email].searches == [(1, "faktura", "Rachunki")]
    assert frame._workers[GMAIL.email].searches == []


def test_everywhere_searches_whole_accounts(frame):
    frame._mailbox_key = (ICLOUD.email, "Rachunki")
    search(frame, everywhere=True)
    assert frame._workers[GMAIL.email].searches == [(1, "faktura", None)]
    assert frame._workers[ICLOUD.email].searches == [(1, "faktura", None)]


def test_results_wait_for_all_accounts_and_are_merged(frame):
    search_id = search(frame)
    frame.on_search_done(GMAIL.email, search_id, [(ALL_MAIL, [message(5, 10)])])
    assert frame._mailbox_key == mf.ALL_KEY
    frame.on_search_done(ICLOUD.email, search_id, [("A", [message(3, 11)])])
    assert frame._mailbox_key == mf.SEARCH_KEY
    assert frame._message_list.selected_key() == (ICLOUD.email, "A", 3)
    box = frame._message_list.list
    assert box.GetCount() == 2
    assert frame.GetTitle().startswith("Wyniki wyszukiwania")
    assert frame.spoken[-1].startswith("Znaleziono 2 wiadomości. nieprzeczytana, Jan, temat 3, iCloud")


def test_nothing_found_stays_in_place(frame):
    frame._message_list.select_key((ICLOUD.email, "INBOX", 2))
    search_id = search(frame)
    frame.on_search_done(GMAIL.email, search_id, [])
    frame.on_search_done(ICLOUD.email, search_id, [("INBOX", [])])
    assert frame.spoken[-1] == "Nic nie znaleziono"
    assert frame._mailbox_key == mf.ALL_KEY
    assert frame._message_list.selected_key() == (ICLOUD.email, "INBOX", 2)


def test_failed_account_is_named(frame):
    search_id = search(frame)
    frame.on_search_done(GMAIL.email, search_id, None)
    frame.on_search_done(ICLOUD.email, search_id, [("INBOX", [message(1, 8)])])
    assert frame.spoken[-1].startswith(
        "Nie przeszukano: Gmail. Znaleziono 1 wiadomość."
    )


def test_escape_returns_to_list_and_same_message(frame):
    selected = (ICLOUD.email, "INBOX", 2)
    frame._message_list.select_key(selected)
    finish(frame, search(frame))
    key(frame, wx.WXK_ESCAPE)
    assert frame._mailbox_key == mf.ALL_KEY
    assert frame._message_list.IsShown()
    assert frame._message_list.selected_key() == selected
    assert frame._search_results == []
    assert frame.GetTitle().startswith("Wszystkie skrzynki")


def test_escape_returns_to_mailboxes_when_started_there(frame):
    frame._show_view(frame._mailbox_view)
    finish(frame, search(frame))
    assert frame._message_list.IsShown()
    key(frame, wx.WXK_ESCAPE)
    assert frame._mailbox_view.IsShown()


def test_second_search_keeps_original_return_point(frame):
    selected = (ICLOUD.email, "INBOX", 2)
    frame._message_list.select_key(selected)
    finish(frame, search(frame))
    finish(frame, search(frame))
    key(frame, wx.WXK_ESCAPE)
    assert frame._message_list.selected_key() == selected
    assert frame._mailbox_key == mf.ALL_KEY


def test_stale_results_are_ignored(frame):
    first = search(frame)
    search(frame)
    frame.on_search_done(GMAIL.email, first, [("INBOX", [message(9, 9)])])
    assert frame._pending_search.messages == []


@pytest.mark.parametrize("move", ["mailboxes", "message", "compose"])
def test_moving_away_cancels_search(frame, monkeypatch, move):
    search_id = search(frame)
    if move == "mailboxes":
        key(frame, wx.WXK_ESCAPE)
    elif move == "message":
        frame._show_message(MessageContent("a", "b", "c", None, "d", ()))
    else:
        monkeypatch.setattr(mf.ComposeDialog, "ShowModal", lambda self: wx.ID_CANCEL)
        frame._new_message()
    finish(frame, search_id)
    assert frame._mailbox_key == mf.ALL_KEY


def test_result_opens_on_account_it_came_from(frame):
    finish(frame, search(frame))
    key(frame, wx.WXK_RETURN)
    assert frame._workers[ICLOUD.email].opened == [("A", 3)]


def test_actions_work_on_results_and_inbox_copy(frame):
    frame.on_messages(ICLOUD.email, "INBOX", [message(1, 8)], False)
    search_id = search(frame)
    frame.on_search_done(GMAIL.email, search_id, [])
    frame.on_search_done(
        ICLOUD.email, search_id, [("INBOX", [message(1, 8)]), ("A", [message(3, 7)])]
    )
    key(frame, wx.WXK_DELETE)
    worker = frame._workers[ICLOUD.email]
    assert worker.client.calls == [("move", "INBOX", 1, "trash")]
    assert [m.uid for m in frame._search_results] == [3]
    assert frame._messages[(ICLOUD.email, "INBOX")] == []
    assert frame._message_list.selected_key() == (ICLOUD.email, "A", 3)


def test_flag_on_result_outside_cached_folders(frame):
    finish(frame, search(frame))
    frame._message_list.select_key((GMAIL.email, ALL_MAIL, 5))
    event = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
    event.SetKeyCode(ord("U"))
    event.SetControlDown(True)
    frame._on_key(event)
    assert frame._search_results[1].seen or frame._search_results[0].seen
    assert frame._workers[GMAIL.email].client.calls == [
        ("set_flag", ALL_MAIL, 5, "\\Seen", True)
    ]


def test_new_mail_during_search_view_does_not_disturb_results(frame):
    finish(frame, search(frame))
    selected = frame._message_list.selected_key()
    frame.on_messages(GMAIL.email, "INBOX", [message(9, 12), message(1, 9)], True, True)
    assert frame._message_list.selected_key() == selected
    assert frame._mailbox_key == mf.SEARCH_KEY


def in_open_dialog(frame, steps):
    """Wykonuje kroki w prawdziwym oknie modalnym i zawsze je zamyka."""
    failures = []

    def run():
        dialog = frame._search_dialog
        try:
            steps(dialog)
        except Exception as error:
            failures.append(error)
        if frame._found_search is None and dialog.IsModal():
            dialog.EndModal(wx.ID_CANCEL)

    wx.CallAfter(run)
    frame._open_search()
    if failures:
        raise failures[0]


def test_dialog_stays_open_until_results_then_shows_them(frame):
    def steps(dialog):
        dialog._query.SetValue(" faktura ")
        dialog._scope.SetSelection(1)
        dialog.start()
        assert dialog.IsModal()
        assert not dialog._search.IsEnabled()
        assert dialog._status.GetLabel() == "Wyszukiwanie"
        assert frame.spoken == ["Wyszukiwanie"]
        finish(frame, frame._last_search_id)
        assert frame._found_search is not None

    in_open_dialog(frame, steps)
    assert frame._workers[GMAIL.email].searches == [(1, "faktura", None)]
    assert frame._last_query == "faktura"
    assert frame._last_everywhere
    assert frame._mailbox_key == mf.SEARCH_KEY
    assert frame._message_list.selected_key() == (ICLOUD.email, "A", 3)
    assert frame.spoken[-1].startswith("Znaleziono 3 wiadomości. ")


def test_dialog_stays_open_when_nothing_found(frame):
    def steps(dialog):
        dialog._query.SetValue("xyz")
        dialog.start()
        frame.on_search_done(GMAIL.email, frame._last_search_id, [])
        frame.on_search_done(ICLOUD.email, frame._last_search_id, [])
        assert dialog.IsModal()
        assert dialog._search.IsEnabled()
        assert dialog._status.GetLabel() == "Nic nie znaleziono"
        assert frame.spoken[-1] == "Nic nie znaleziono"
        dialog.start()
        assert len(frame._workers[GMAIL.email].searches) == 2

    in_open_dialog(frame, steps)
    assert frame._mailbox_key == mf.ALL_KEY


def test_escape_during_search_cancels_it(frame):
    captured = []

    def steps(dialog):
        dialog._query.SetValue("xyz")
        dialog.start()
        captured.append(frame._last_search_id)
        dialog.EndModal(wx.ID_CANCEL)

    in_open_dialog(frame, steps)
    assert frame._pending_search is None
    finish(frame, captured[0])
    assert frame._mailbox_key == mf.ALL_KEY


def test_empty_query_does_not_search(frame):
    def steps(dialog):
        dialog.start()
        assert dialog._status.GetLabel() == "Wpisz szukany tekst"
        assert dialog._search.IsEnabled()

    in_open_dialog(frame, steps)
    assert frame._workers[GMAIL.email].searches == []


def test_new_mail_while_searching_keeps_list_selection(frame):
    selected = (ICLOUD.email, "INBOX", 2)
    frame._message_list.select_key(selected)

    def steps(dialog):
        dialog._query.SetValue("xyz")
        dialog.start()
        frame.on_messages(
            GMAIL.email, "INBOX", [message(9, 12), message(1, 9)], True, True
        )

    in_open_dialog(frame, steps)
    assert frame._message_list.selected_key() == selected


def test_search_dialog_fields_have_labels(frame):
    dialog = SearchDialog(frame, "abc", True, lambda query, everywhere: None)
    assert dialog.query == "abc"
    assert dialog.everywhere
    labels = [c.GetPrevSibling().GetLabel() for c in (dialog._query, dialog._scope)]
    assert labels == ["Szukaj:", "Gdzie:"]
    dialog.Destroy()
