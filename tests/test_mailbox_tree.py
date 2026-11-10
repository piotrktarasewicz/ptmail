"""Ekran Skrzynki jako drzewo: konta rozwija się i zwija, a stan zostaje zapamiętany."""

import pytest
import wx

from ptmail.accounts import Account
from ptmail.config import load_expanded_accounts, save_expanded_accounts
from ptmail.models import Folder
from ptmail.ui import main_frame as mf

HOME = Account("Prywatny", "ja@gmail.com", "gmail")
WORK = Account("Praca", "ja@icloud.com", "icloud")
FOLDERS = [
    Folder("INBOX", "Odebrane", "inbox", 1),
    Folder("Sent", "Wysłane", "sent"),
]


class FakeWorker:
    def __init__(self):
        self.opened = []

    def refresh(self, folder, silent=False):
        pass

    def open_folder(self, folder):
        self.opened.append(folder)

    def stop(self):
        pass


@pytest.fixture(scope="module")
def app():
    application = wx.App()
    yield application
    del application


def make_frame(monkeypatch):
    monkeypatch.setattr(mf, "play", lambda name: None)
    monkeypatch.setattr(mf, "speak", lambda text: None)
    window = mf.MainFrame()
    window._accounts = [HOME, WORK]
    window._workers = {HOME.email: FakeWorker(), WORK.email: FakeWorker()}
    window.Show()
    for account in (HOME, WORK):
        window.on_folders(account.email, list(FOLDERS))
    return window


@pytest.fixture
def frame(app, monkeypatch):
    window = make_frame(monkeypatch)
    window._show_view(window._mailbox_view)
    yield window
    window._workers = {}
    window.Destroy()


def tree(window):
    return window._mailbox_view


def item(window, key):
    return tree(window)._items[key]


def press(window, code):
    event = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
    event.SetKeyCode(code)
    window._on_key(event)


def test_accounts_start_collapsed(frame):
    assert tree(frame).expanded_keys() == []
    assert not frame._mailbox_view.tree.IsExpanded(item(frame, (HOME.email, None)))


def test_expanding_account_is_remembered_after_restart(frame, monkeypatch):
    frame._mailbox_view.tree.Expand(item(frame, (WORK.email, None)))
    assert load_expanded_accounts() == [WORK.email]
    other = make_frame(monkeypatch)
    try:
        assert tree(other).expanded_keys() == [(WORK.email, None)]
    finally:
        other._workers = {}
        other.Destroy()


def test_collapsing_is_remembered_too(frame):
    frame._mailbox_view.tree.Expand(item(frame, (HOME.email, None)))
    frame._mailbox_view.tree.Collapse(item(frame, (HOME.email, None)))
    assert load_expanded_accounts() == []


def test_account_without_folders_yet_keeps_its_state(frame):
    save_expanded_accounts(["nowe@example.com"])
    frame._mailbox_view.tree.Expand(item(frame, (HOME.email, None)))
    assert load_expanded_accounts() == ["nowe@example.com", HOME.email]


def test_new_unread_count_changes_text_without_rebuilding(frame):
    node = item(frame, (HOME.email, "INBOX"))
    frame._mailbox_view.select_key((HOME.email, "INBOX"))
    frame.on_folders(HOME.email, [Folder("INBOX", "Odebrane", "inbox", 4), FOLDERS[1]])
    assert item(frame, (HOME.email, "INBOX")) == node
    assert frame._mailbox_view.tree.GetItemText(node) == "Odebrane, 4 nieprzeczytane"
    assert tree(frame).selected_key() == (HOME.email, "INBOX")


def test_enter_on_folder_opens_it(frame):
    tree(frame).select_key((WORK.email, "Sent"))
    press(frame, wx.WXK_RETURN)
    assert frame._message_list.IsShown()
    assert frame._mailbox_key == (WORK.email, "Sent")
    assert frame._workers[WORK.email].opened == ["Sent"]


def test_returning_from_folder_shows_it_in_expanded_account(frame):
    tree(frame).select_key((WORK.email, "Sent"))
    press(frame, wx.WXK_RETURN)
    frame._mailbox_view.tree.Collapse(item(frame, (WORK.email, None)))
    press(frame, wx.WXK_ESCAPE)
    assert frame._mailbox_view.IsShown()
    assert tree(frame).selected_key() == (WORK.email, "Sent")
    assert frame._mailbox_view.tree.IsExpanded(item(frame, (WORK.email, None)))


def test_enter_on_account_opens_its_inbox(frame):
    tree(frame).select_key((HOME.email, None))
    press(frame, wx.WXK_RETURN)
    assert frame._mailbox_key == (HOME.email, None)
    assert frame.GetTitle().startswith("Prywatny")
