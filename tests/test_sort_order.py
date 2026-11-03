"""Kolejność listy: od najnowszych albo od najstarszych, wybierana w menu Widok."""

import pytest
import wx

from ptmail.accounts import Account
from ptmail.config import load_newest_first
from ptmail.models import Message
from ptmail.sounds import NEW_MAIL, SYNCED
from ptmail.ui import main_frame as mf

EMAIL = "ja@example.com"
SENT = "Sent Messages"


def message(uid):
    return Message(uid, "Jan", f"temat {uid}", None, False, False, 0)


def ref(uid, folder="INBOX"):
    return (EMAIL, folder, uid)


class FakeWorker:
    def __init__(self):
        self.done = []

    def refresh(self, folder, silent=False):
        pass

    def open_folder(self, folder):
        pass

    def perform(self, run, failure):
        self.done.append(failure)

    def stop(self):
        pass


@pytest.fixture(scope="module")
def app():
    application = wx.App()
    yield application
    del application


def make_frame(monkeypatch):
    played = []
    spoken = []
    monkeypatch.setattr(mf, "play", played.append)
    monkeypatch.setattr(mf, "speak", spoken.append)
    window = mf.MainFrame()
    window._accounts = [Account("iCloud", EMAIL, "icloud")]
    window._workers = {EMAIL: FakeWorker()}
    window.IsActive = lambda: True
    window.played = played
    window.spoken = spoken
    window.Show()
    return window


@pytest.fixture
def frame(app, monkeypatch):
    window = make_frame(monkeypatch)
    yield window
    window._workers = {}
    window.Destroy()


@pytest.fixture
def oldest(frame):
    frame._set_newest_first(False)
    frame.spoken.clear()
    return frame


def load(window, *uids, refreshed=True, folder="INBOX"):
    window.on_messages(EMAIL, folder, [message(uid) for uid in uids], refreshed)


def shown_uids(window):
    return [key[2] for key in window._message_list._keys]


def test_newest_first_is_default(frame):
    load(frame, 3, 2, 1)
    assert shown_uids(frame) == [3, 2, 1]
    assert frame._order_items[0].IsChecked()


def test_oldest_first_reverses_list_and_selects_newest(oldest):
    load(oldest, 3, 2, 1)
    assert shown_uids(oldest) == [1, 2, 3]
    assert oldest._message_list.selected_key() == ref(3)


def test_changing_order_keeps_selected_message_and_says_it(frame):
    load(frame, 3, 2, 1)
    frame._message_list.select_key(ref(2))
    frame._set_newest_first(False)
    assert shown_uids(frame) == [1, 2, 3]
    assert frame._message_list.selected_key() == ref(2)
    assert frame.spoken == ["Od najstarszych"]
    assert frame._order_items[1].IsChecked()
    frame._set_newest_first(True)
    assert shown_uids(frame) == [3, 2, 1]
    assert frame.spoken[-1] == "Od najnowszych"


def test_order_is_remembered_after_restart(app, monkeypatch, oldest):
    assert load_newest_first() is False
    other = make_frame(monkeypatch)
    try:
        assert other._newest_first is False
        assert other._order_items[1].IsChecked()
    finally:
        other._workers = {}
        other.Destroy()


def test_new_message_goes_to_bottom_and_takes_selection(oldest):
    load(oldest, 2, 1)
    oldest._message_list.select_key(ref(1))
    load(oldest, 3, 2, 1)
    assert oldest.played == [SYNCED, NEW_MAIL]
    assert shown_uids(oldest) == [1, 2, 3]
    assert oldest._message_list.selected_key() == ref(3)
    assert oldest.spoken == ["nieprzeczytana, Jan, temat 3, iCloud"]


def test_opened_folder_starts_at_newest(oldest):
    load(oldest, 1)
    oldest._folders[EMAIL] = []
    oldest._mailbox_view.set_rows([((EMAIL, SENT), "Wysłane")])
    oldest._mailbox_view.select_key((EMAIL, SENT))
    oldest._open_selected_mailbox()
    load(oldest, 9, 8, 7, refreshed=False, folder=SENT)
    assert shown_uids(oldest) == [7, 8, 9]
    assert oldest._message_list.selected_key() == ref(9, SENT)


def test_all_mailboxes_are_reversed_too(oldest):
    oldest._mailbox_key = mf.ALL_KEY
    load(oldest, 3, 2, 1)
    assert shown_uids(oldest) == [1, 2, 3]


def test_alt_down_opens_next_row_below(oldest, monkeypatch):
    load(oldest, 3, 2, 1)
    opened = []
    monkeypatch.setattr(oldest, "_open_selected_message", lambda: opened.append(1))
    oldest._message_list.select_key(ref(1))
    oldest._open_neighbour(1)
    assert oldest._message_list.selected_key() == ref(2)


def test_deleting_moves_to_next_row_below(oldest):
    load(oldest, 3, 2, 1)
    oldest._message_list.select_key(ref(1))
    oldest._move_to_trash()
    assert shown_uids(oldest) == [2, 3]
    assert oldest._message_list.selected_key() == ref(2)
