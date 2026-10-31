import sqlite3
from datetime import datetime, timezone

import pytest
import wx

from ptmail import cache as cache_module
from ptmail.accounts import Account
from ptmail.cache import MAX_BODY_BYTES, MailCache, open_cache
from ptmail.message_parser import parse_message
from ptmail.models import Folder, Message
from ptmail.sounds import NEW_MAIL
from ptmail.ui import main_frame as mf

EMAIL = "ja@icloud.com"
OTHER = "ja@gmail.com"
RAW = b"From: a@b.pl\r\nSubject: x\r\n\r\ntresc z pamieci"
WHEN = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


def message(uid, seen=False, account=EMAIL, folder="INBOX", date=WHEN):
    return Message(uid, "Jan", f"temat {uid}", date, seen, False, 1, account, folder)


def key(uid, account=EMAIL):
    return (account, "INBOX", uid)


@pytest.fixture
def cache():
    instance = MailCache()
    yield instance
    instance.close()


def test_messages_round_trip_in_order(cache):
    stored = [message(5), message(9, seen=True), message(2, date=None)]
    cache.save_messages(EMAIL, "INBOX", stored)
    assert cache.messages(EMAIL) == {"INBOX": stored}


def test_saving_replaces_list_and_drops_bodies_of_gone_messages(cache):
    cache.save_messages(EMAIL, "INBOX", [message(2), message(1)])
    cache.save_body(key(1), RAW)
    cache.save_body(key(2), RAW)
    cache.save_messages(EMAIL, "INBOX", [message(2)])
    assert [m.uid for m in cache.messages(EMAIL)["INBOX"]] == [2]
    assert cache.body(key(1)) is None
    assert cache.body(key(2)) == RAW


def test_other_folder_and_account_are_untouched(cache):
    cache.save_messages(OTHER, "INBOX", [message(1, account=OTHER)])
    cache.save_body(key(1, OTHER), RAW)
    cache.save_messages(EMAIL, "INBOX", [])
    assert cache.body(key(1, OTHER)) == RAW


def test_folders_keep_order(cache):
    folders = [Folder("INBOX", "Odebrane", "inbox", 3), Folder("A", "A", None, 0)]
    cache.save_folders(EMAIL, folders)
    assert cache.folders(EMAIL) == folders


def test_flags_update(cache):
    cache.save_messages(EMAIL, "INBOX", [message(1)])
    changed = Message(1, "Jan", "x", WHEN, True, True, 1, EMAIL, "INBOX")
    cache.update_flags(changed)
    stored = cache.messages(EMAIL)["INBOX"][0]
    assert stored.seen and stored.flagged


def test_delete_message_removes_body(cache):
    cache.save_messages(EMAIL, "INBOX", [message(1)])
    cache.save_body(key(1), RAW)
    cache.delete_message(key(1))
    assert cache.messages(EMAIL) == {}
    assert cache.body(key(1)) is None


def test_huge_messages_are_not_stored(cache):
    cache.save_body(key(1), b"x" * (MAX_BODY_BYTES + 1))
    assert cache.body(key(1)) is None


def test_keep_accounts_forgets_removed_account(cache):
    cache.save_folders(OTHER, [Folder("INBOX", "Odebrane", "inbox", 0)])
    cache.save_messages(OTHER, "INBOX", [message(1, account=OTHER)])
    cache.save_body(key(1, OTHER), RAW)
    cache.save_messages(EMAIL, "INBOX", [message(1)])
    cache.keep_accounts([EMAIL])
    assert cache.folders(OTHER) == []
    assert cache.messages(OTHER) == {}
    assert cache.body(key(1, OTHER)) is None
    assert cache.messages(EMAIL)


def test_data_survives_reopening(tmp_path):
    path = tmp_path / "cache.db"
    first = MailCache(path)
    first.save_messages(EMAIL, "INBOX", [message(1)])
    first.save_body(key(1), RAW)
    first.close()
    second = MailCache(path)
    assert second.body(key(1)) == RAW
    assert second.messages(EMAIL)["INBOX"][0].date == WHEN
    second.close()


def test_old_schema_is_rebuilt(tmp_path):
    path = tmp_path / "cache.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE messages (stare TEXT)")
    db.commit()
    db.close()
    rebuilt = MailCache(path)
    rebuilt.save_messages(EMAIL, "INBOX", [message(1)])
    assert rebuilt.messages(EMAIL)
    rebuilt.close()


def test_corrupted_file_is_replaced(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    folder = tmp_path / "PT Mail"
    folder.mkdir()
    (folder / "cache.db").write_bytes(b"to nie jest baza" * 100)
    cache = open_cache()
    cache.save_messages(EMAIL, "INBOX", [message(1)])
    assert cache.messages(EMAIL)
    cache.close()


def test_locked_database_is_not_deleted(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    first = open_cache()
    first.save_messages(EMAIL, "INBOX", [message(1)])
    first.close()
    path = tmp_path / "PT Mail" / "cache.db"

    def locked(database=":memory:"):
        if database == ":memory:":
            return MailCache()
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(cache_module, "MailCache", locked)
    second = open_cache()
    second.close()
    reopened = MailCache(path)
    assert reopened.messages(EMAIL)
    reopened.close()


def test_unusable_path_falls_back_to_memory(tmp_path, monkeypatch):
    blocked = tmp_path / "plik"
    blocked.write_text("x")
    monkeypatch.setattr(cache_module, "config_path", lambda: blocked / "config.json")
    cache = open_cache()
    cache.save_messages(EMAIL, "INBOX", [message(1)])
    assert cache.messages(EMAIL)
    cache.close()


def test_database_errors_do_not_reach_the_program(cache):
    cache.close()
    assert cache.messages(EMAIL) == {}
    assert cache.folders(EMAIL) == ()
    assert cache.body(key(1)) is None
    cache.save_messages(EMAIL, "INBOX", [message(1)])


class RecordingClient:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda *args: self.calls.append((name, *args))


class FakeWorker:
    def __init__(self):
        self.client = RecordingClient()
        self.opened = []

    def refresh(self, folder, silent=False):
        pass

    def open_message(self, folder, uid):
        self.opened.append((folder, uid))

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
    played = []
    monkeypatch.setattr(mf, "play", played.append)
    monkeypatch.setattr(mf, "speak", lambda text: None)
    monkeypatch.setattr(mf, "get_password", lambda account: None)
    window = mf.MainFrame()
    window.played = played
    window.Show()
    yield window
    window._workers = {}
    window.Destroy()


ACCOUNT = Account("iCloud", EMAIL, "icloud")


def start(frame):
    frame._connect([ACCOUNT])
    frame.worker = FakeWorker()
    frame._workers = {EMAIL: frame.worker}


def press_enter(frame):
    event = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
    event.SetKeyCode(wx.WXK_RETURN)
    frame._on_key(event)


def test_list_and_mailboxes_appear_from_cache_before_server(frame):
    frame._cache.save_folders(EMAIL, [Folder("INBOX", "Odebrane", "inbox", 1)])
    frame._cache.save_messages(EMAIL, "INBOX", [message(2), message(1, seen=True)])
    start(frame)
    box = frame._message_list.list
    assert box.GetCount() == 2
    assert frame._message_list.selected_key() == key(2)
    assert frame._mailbox_view.list.GetString(0) == (
        "Wszystkie skrzynki, 1 nieprzeczytana"
    )


def test_mail_that_came_while_closed_is_new(frame):
    frame._cache.save_messages(EMAIL, "INBOX", [message(1)])
    start(frame)
    frame.on_messages(EMAIL, "INBOX", [message(2), message(1)], True)
    assert frame.played == [NEW_MAIL]
    assert frame._message_list.selected_key() == key(2)


def test_server_list_is_saved(frame):
    start(frame)
    frame.on_messages(EMAIL, "INBOX", [message(1)], True)
    assert [m.uid for m in frame._cache.messages(EMAIL)["INBOX"]] == [1]


def test_opened_message_comes_from_cache_without_server(frame):
    frame._cache.save_messages(EMAIL, "INBOX", [message(1, seen=True)])
    frame._cache.save_body(key(1), RAW)
    start(frame)
    press_enter(frame)
    assert frame.worker.opened == []
    assert frame._message_view.IsShown()
    assert frame._message_view.text.GetValue().startswith("tresc z pamieci")
    assert frame.worker.client.calls == []


def test_unread_message_from_cache_is_marked_on_server(frame):
    frame._cache.save_messages(EMAIL, "INBOX", [message(1)])
    frame._cache.save_body(key(1), RAW)
    start(frame)
    press_enter(frame)
    assert frame.worker.client.calls == [("set_flag", "INBOX", 1, "\\Seen", True)]
    assert frame._cache.messages(EMAIL)["INBOX"][0].seen


def test_fetched_message_is_stored(frame):
    frame._cache.save_messages(EMAIL, "INBOX", [message(1)])
    start(frame)
    press_enter(frame)
    assert frame.worker.opened == [("INBOX", 1)]
    frame.on_message_opened(EMAIL, "INBOX", 1, parse_message(RAW), RAW)
    assert frame._cache.body(key(1)) == RAW


def test_opened_body_survives_refresh_and_restart(frame, tmp_path):
    path = tmp_path / "cache.db"
    frame._cache = MailCache(path)
    frame._cache.save_messages(EMAIL, "INBOX", [message(1)])
    start(frame)
    press_enter(frame)
    frame.on_message_opened(EMAIL, "INBOX", 1, parse_message(RAW), RAW)
    frame.on_messages(EMAIL, "INBOX", [message(1, seen=True)], True)
    frame._cache.close()
    frame._cache = MailCache(path)
    assert frame._cache.body(key(1)) == RAW
    frame._cache.keep_accounts([EMAIL])
    assert frame._cache.body(key(1)) == RAW
    frame._cache.close()
    frame._cache = MailCache()


def test_database_errors_are_logged(cache, caplog):
    cache.close()
    cache.save_body(key(1), RAW)
    assert "save_body" in caplog.text


def test_removed_message_leaves_cache(frame):
    frame._cache.save_folders(EMAIL, [Folder("INBOX", "Odebrane", "inbox", 1)])
    frame._cache.save_messages(EMAIL, "INBOX", [message(2), message(1)])
    frame._cache.save_body(key(2), RAW)
    start(frame)
    event = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
    event.SetKeyCode(wx.WXK_DELETE)
    frame._on_key(event)
    assert [m.uid for m in frame._cache.messages(EMAIL)["INBOX"]] == [1]
    assert frame._cache.body(key(2)) is None
    assert frame._cache.folders(EMAIL)[0].unread == 0
