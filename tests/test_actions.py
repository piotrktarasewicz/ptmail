import imaplib

import pytest
import wx

from ptmail.accounts import Account
from ptmail.imap_client import ImapClient, ImapError
from ptmail.models import Folder, Message, MessageContent
from ptmail.ui import main_frame as mf

ICLOUD = Account("iCloud", "ja@icloud.com", "icloud")
GMAIL = Account("Gmail", "ja@gmail.com", "gmail")
EMAIL = ICLOUD.email
FOLDERS = [
    Folder("INBOX", "Odebrane", "inbox", 2),
    Folder("Deleted Messages", "Kosz", "trash", 0),
    Folder("Archive", "Archiwum", "archive", 0),
]


def message(uid, seen=False, flagged=False):
    return Message(uid, "Jan", f"temat {uid}", None, seen, flagged, 0)


def content():
    return MessageContent("Jan", "ja", "temat", None, "tresc", ())


def ref(uid, folder="INBOX"):
    return (EMAIL, folder, uid)


class RecordingClient:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda *args: self.calls.append((name, *args))


class FakeWorker:
    def __init__(self):
        self.client = RecordingClient()
        self.refreshed = []
        self.failures = []

    def perform(self, run, failure_text):
        run(self.client)
        self.failures.append(failure_text)

    def refresh(self, folder, silent=False):
        self.refreshed.append((folder, silent))

    def open_message(self, folder, uid):
        pass

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
    delayed = []
    monkeypatch.setattr(mf.wx, "CallLater", lambda ms, run, *args: delayed.append(args))
    window = mf.MainFrame()
    window._accounts = [ICLOUD]
    window.worker = FakeWorker()
    window._workers = {EMAIL: window.worker}
    window.spoken = spoken
    window.delayed = delayed
    window.Show()
    window.on_folders(EMAIL, list(FOLDERS))
    window.on_messages(
        EMAIL, "INBOX", [message(3), message(2, seen=True), message(1)], False
    )
    window._message_list.select_key(ref(3))
    yield window
    window._workers = {}
    window.Destroy()


def key(window, code, ctrl=False, shift=False, alt=False):
    event = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
    event.SetKeyCode(code)
    event.SetControlDown(ctrl)
    event.SetShiftDown(shift)
    event.SetAltDown(alt)
    window._on_key(event)


def uids(window):
    return [m.uid for m in window._messages[(EMAIL, "INBOX")]]


def inbox_unread(window):
    return next(f.unread for f in window._folders[EMAIL] if f.name == "INBOX")


def use_gmail(frame, folder="INBOX"):
    frame._accounts = [GMAIL]
    frame._workers = {GMAIL.email: frame.worker}
    frame._folders = {GMAIL.email: list(FOLDERS)}
    frame._messages = {}
    frame._mailbox_key = (GMAIL.email, folder)
    frame.on_messages(GMAIL.email, folder, [message(3)], False)
    frame._message_list.select_key((GMAIL.email, folder, 3))


def test_delete_moves_to_next_message_and_reads_it(frame):
    key(frame, wx.WXK_DELETE)
    assert uids(frame) == [2, 1]
    assert frame.worker.client.calls == [("move", "INBOX", 3, "trash")]
    assert frame._message_list.selected_key() == ref(2)
    assert frame.spoken == ["Jan, temat 2, iCloud"]
    assert frame.GetStatusBar().GetStatusText() == "Przeniesiono do kosza"
    assert inbox_unread(frame) == 1


def test_delete_of_read_message_keeps_unread_count(frame):
    frame._message_list.select_key(ref(2))
    key(frame, wx.WXK_DELETE)
    assert inbox_unread(frame) == 2


def test_delete_last_message_goes_to_previous(frame):
    frame._message_list.select_key(ref(1))
    key(frame, wx.WXK_DELETE)
    assert frame._message_list.selected_key() == ref(2)


def test_delete_only_message_leaves_empty_list(frame):
    frame.on_messages(EMAIL, "INBOX", [message(5)], False)
    frame._message_list.select_key(ref(5))
    key(frame, wx.WXK_DELETE)
    assert frame._message_list.list.GetCount() == 0
    assert frame.spoken == ["Przeniesiono do kosza"]


def test_delete_from_message_view_returns_to_next_on_list(frame):
    frame._opened[(EMAIL, "INBOX", 3)] = content()
    frame._show_message(content())
    key(frame, wx.WXK_DELETE)
    assert frame._message_list.IsShown()
    assert frame._message_list.selected_key() == ref(2)
    assert (EMAIL, "INBOX", 3) not in frame._opened
    assert frame.delayed == []


def test_delete_from_message_view_speaks_when_list_is_empty(frame):
    frame.on_messages(EMAIL, "INBOX", [message(5)], False)
    frame._message_list.select_key(ref(5))
    frame._show_message(content())
    key(frame, wx.WXK_DELETE)
    assert frame.delayed == [("Przeniesiono do kosza",)]


def test_delete_in_trash_does_nothing(frame):
    frame._mailbox_key = (EMAIL, "Deleted Messages")
    frame.on_messages(EMAIL, "Deleted Messages", [message(7)], False)
    frame._message_list.select_key(ref(7, "Deleted Messages"))
    key(frame, wx.WXK_DELETE)
    assert frame.worker.client.calls == []
    assert frame.spoken == ["Wiadomość jest już w koszu"]
    assert len(frame._messages[(EMAIL, "Deleted Messages")]) == 1


def test_removed_message_does_not_come_back_with_older_fetch(frame):
    key(frame, wx.WXK_DELETE)
    frame.on_messages(EMAIL, "INBOX", [message(3), message(2, seen=True), message(1)], False)
    assert uids(frame) == [2, 1]


def test_failure_says_so_and_restores_from_server(frame):
    key(frame, wx.WXK_DELETE)
    frame.on_action_failed(EMAIL, "Nie udało się przenieść do kosza")
    assert frame.spoken[-1] == "Nie udało się przenieść do kosza"
    assert frame.worker.refreshed == [("INBOX", True)]
    frame.on_messages(EMAIL, "INBOX", [message(3), message(2, seen=True), message(1)], True, True)
    assert uids(frame) == [3, 2, 1]


def test_archive_on_icloud_moves_to_archive(frame):
    key(frame, ord("A"), ctrl=True, shift=True)
    assert frame.worker.client.calls == [("move", "INBOX", 3, "archive")]
    assert frame.spoken[0].startswith("Zarchiwizowano. ")


def test_archive_on_gmail_removes_inbox_label(frame):
    use_gmail(frame)
    key(frame, ord("A"), ctrl=True, shift=True)
    assert frame.worker.client.calls == [("remove_inbox_label", 3)]


def test_archive_on_gmail_only_from_inbox(frame):
    use_gmail(frame, "Rachunki")
    key(frame, ord("A"), ctrl=True, shift=True)
    assert frame.worker.client.calls == []
    assert frame.spoken == ["Archiwizować można tylko z Odebranych"]


def test_right_alt_does_not_trigger_actions(frame):
    key(frame, ord("A"), ctrl=True, shift=True, alt=True)
    key(frame, ord("U"), ctrl=True, alt=True)
    assert frame.worker.client.calls == []


def test_toggle_read_keeps_selection_and_updates_row(frame):
    key(frame, ord("U"), ctrl=True)
    assert frame.worker.client.calls == [("set_flag", "INBOX", 3, "\\Seen", True)]
    assert frame._message_list.selected_key() == ref(3)
    assert frame._message_list.list.GetString(0) == "Jan, temat 3, iCloud"
    assert inbox_unread(frame) == 1
    assert frame.spoken == ["Oznaczono jako przeczytaną"]
    key(frame, ord("U"), ctrl=True)
    assert frame._message_list.list.GetString(0).startswith("nieprzeczytana")
    assert inbox_unread(frame) == 2
    assert frame._message_list.selected_key() == ref(3)


def test_mark_unread_forgets_opened_copy(frame):
    frame._message_list.select_key(ref(2))
    frame._opened[(EMAIL, "INBOX", 2)] = content()
    key(frame, ord("U"), ctrl=True)
    assert (EMAIL, "INBOX", 2) not in frame._opened


def test_toggle_flag(frame):
    frame._message_list.select_key(ref(2))
    key(frame, ord("F"), ctrl=True, shift=True)
    assert frame.worker.client.calls == [("set_flag", "INBOX", 2, "\\Flagged", True)]
    assert frame._message_list.list.GetString(1).startswith("oflagowana, Jan")
    assert frame._message_list.selected_key() == ref(2)
    key(frame, ord("F"), ctrl=True, shift=True)
    assert frame.spoken == ["Oflagowano", "Zdjęto flagę"]


def test_actions_work_in_message_view(frame):
    frame._show_message(content())
    key(frame, ord("F"), ctrl=True, shift=True)
    key(frame, ord("U"), ctrl=True)
    assert frame._message_view.IsShown()
    assert len(frame.worker.client.calls) == 2


def test_actions_do_nothing_on_mailboxes(frame):
    frame._show_view(frame._mailbox_view)
    key(frame, wx.WXK_DELETE)
    assert frame.worker.client.calls == []


def labels(menu):
    return [item.GetItemLabelText() for item in menu.GetMenuItems()]


def test_context_menu_names_current_state_and_shortcuts(frame):
    menu = frame._build_context_menu()
    texts = [item.GetItemLabel().replace("&", "") for item in menu.GetMenuItems()]
    assert "Oznacz jako przeczytaną\tCtrl+U" in texts
    assert "Oflaguj\tCtrl+Shift+F" in texts
    assert "Przenieś do kosza\tDelete" in texts
    menu.Destroy()
    frame._message_list.select_key(ref(2))
    menu = frame._build_context_menu()
    assert "Oznacz jako nieprzeczytaną" in labels(menu)
    menu.Destroy()


def test_context_menu_item_runs_action(frame):
    menu = frame._build_context_menu()
    item = next(i for i in menu.GetMenuItems() if "kosza" in i.GetItemLabelText())
    event = wx.CommandEvent(wx.wxEVT_MENU, item.GetId())
    menu.ProcessEvent(event)
    menu.Destroy()
    assert frame.worker.client.calls == [("move", "INBOX", 3, "trash")]


class FakeImap:
    def __init__(self):
        self.calls = []

    def list(self):
        return "OK", [
            b'(\\HasNoChildren \\Trash) "/" "[Gmail]/Kosz"',
            b'(\\HasNoChildren) "/" "INBOX"',
        ]

    def select(self, folder, readonly):
        self.calls.append(("select", folder, readonly))
        return "OK", [b"1"]

    def uid(self, *args):
        self.calls.append(args)
        return "OK", [None]


def client_with(imap):
    client = ImapClient(GMAIL, "x")
    client._imap = imap
    return client


def test_imaplib_knows_uid_move():
    assert "MOVE" in imaplib.Commands


def test_move_uses_writable_selection():
    imap = FakeImap()
    client_with(imap).move("INBOX", 5, "trash")
    assert imap.calls == [
        ("select", '"INBOX"', False),
        ("MOVE", "5", '"[Gmail]/Kosz"'),
    ]


def test_move_without_target_folder_fails_before_touching_mail():
    imap = FakeImap()
    with pytest.raises(ImapError):
        client_with(imap).move("INBOX", 5, "archive")
    assert imap.calls == []


def test_role_folders_are_remembered():
    imap = FakeImap()
    imap.list = lambda: pytest.fail("LIST bez potrzeby") or ("OK", [])
    client = client_with(imap)
    client._role_folders = {"trash": "[Gmail]/Kosz"}
    client.move("INBOX", 5, "trash")


def test_flags_and_gmail_label():
    imap = FakeImap()
    client = client_with(imap)
    client.set_flag("INBOX", 5, "\\Seen", False)
    client.set_flag("INBOX", 5, "\\Flagged", True)
    client.remove_inbox_label(5)
    assert [call for call in imap.calls if call[0] == "STORE"] == [
        ("STORE", "5", "-FLAGS.SILENT", "(\\Seen)"),
        ("STORE", "5", "+FLAGS.SILENT", "(\\Flagged)"),
        ("STORE", "5", "-X-GM-LABELS", "(\\Inbox)"),
    ]
