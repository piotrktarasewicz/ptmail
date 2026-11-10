import json
from datetime import datetime, timezone

import pytest
import wx

from ptmail import config
from ptmail.accounts import Account
from ptmail.compose import Draft
from ptmail.models import Folder, Message, MessageContent
from ptmail.sounds import NEW_MAIL, SYNCED
from ptmail.ui import accounts_dialog as ad
from ptmail.ui.account_dialog import AccountDialog
from ptmail.ui import compose_dialog as cd
from ptmail.ui import main_frame as mf

GMAIL = Account("Prywatny", "ja@gmail.com", "gmail")
WORK = Account("Praca", "praca@gmail.com", "gmail")
ICLOUD = Account("iCloud", "ja@icloud.com", "icloud")
ACCOUNTS = [GMAIL, WORK, ICLOUD]


def at(hour):
    return datetime(2026, 10, 30, hour, 0, tzinfo=timezone.utc)


def message(uid, hour, subject=None):
    return Message(uid, "Jan", subject or f"temat {uid}", at(hour), False, False, 0)


class RecordingClient:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda *args: self.calls.append((name, *args))


class FakeWorker:
    def __init__(self, account):
        self.account = account
        self.client = RecordingClient()
        self.refreshed = []
        self.opened = []
        self.sent = []

    def refresh(self, folder, silent=False):
        self.refreshed.append((folder, silent))

    def open_folder(self, folder):
        self.refreshed.append((folder, "open"))

    def open_message(self, folder, uid):
        self.opened.append((folder, uid))

    def perform(self, run, failure_text):
        run(self.client)

    def send(self, recipients, raw, on_done):
        self.sent.append(raw)

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
    spoken = []
    monkeypatch.setattr(mf, "play", played.append)
    monkeypatch.setattr(mf, "speak", spoken.append)
    window = mf.MainFrame()
    window._accounts = list(ACCOUNTS)
    window._workers = {a.email: FakeWorker(a) for a in ACCOUNTS}
    window.played = played
    window.spoken = spoken
    window.IsActive = lambda: True
    window.Show()
    for account, unread in zip(ACCOUNTS, (1, 2, 3)):
        window.on_folders(
            account.email,
            [
                Folder("INBOX", "Odebrane", "inbox", unread),
                Folder("Trash", "Kosz", "trash", 0),
            ],
        )
    yield window
    window._workers = {}
    window.Destroy()


def load_all(window):
    window.on_messages(GMAIL.email, "INBOX", [message(1, 9), message(2, 8)], False)
    window.on_messages(WORK.email, "INBOX", [message(1, 11)], False)
    window.on_messages(ICLOUD.email, "INBOX", [message(1, 10)], False)


def rows(window):
    box = window._message_list.list
    return [box.GetString(i) for i in range(box.GetCount())]


def key(window, code, ctrl=False, shift=False):
    event = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
    event.SetKeyCode(code)
    event.SetControlDown(ctrl)
    event.SetShiftDown(shift)
    window._on_key(event)


def test_all_mailboxes_merge_accounts_newest_first(frame):
    load_all(frame)
    subjects = [row.split(", ")[3] for row in rows(frame)]
    assert subjects == ["Praca", "iCloud", "Prywatny", "Prywatny"]


def test_same_uid_on_two_accounts_are_separate_messages(frame):
    load_all(frame)
    keys = [m.key for m in frame._visible_messages()]
    assert len(set(keys)) == 4
    assert (WORK.email, "INBOX", 1) in keys and (ICLOUD.email, "INBOX", 1) in keys


def test_mailboxes_are_a_tree_of_accounts_and_folders(frame):
    assert frame._mailbox_view.texts() == [
        (0, "Wszystkie skrzynki, 6 nieprzeczytanych"),
        (0, "Prywatny, 1 nieprzeczytana"),
        (1, "Odebrane, 1 nieprzeczytana"),
        (1, "Kosz"),
        (0, "Praca, 2 nieprzeczytane"),
        (1, "Odebrane, 2 nieprzeczytane"),
        (1, "Kosz"),
        (0, "iCloud, 3 nieprzeczytane"),
        (1, "Odebrane, 3 nieprzeczytane"),
        (1, "Kosz"),
    ]


def test_account_row_opens_its_inbox_without_account_in_rows(frame):
    load_all(frame)
    frame._show_view(frame._mailbox_view)
    frame._mailbox_view.select_key((WORK.email, None))
    key(frame, wx.WXK_RETURN)
    assert len(rows(frame)) == 1
    assert "Praca" not in rows(frame)[0]
    assert frame._workers[WORK.email].refreshed == [("INBOX", "open")]
    assert frame.GetTitle().startswith("Praca")


def test_f5_on_all_mailboxes_checks_every_account_and_sounds_once(frame):
    load_all(frame)
    frame._check_mail()
    assert all(w.refreshed == [("INBOX", False)] for w in frame._workers.values())
    for account in ACCOUNTS[:2]:
        frame.on_messages(account.email, "INBOX", [], True)
    assert frame.played == []
    frame.on_messages(ICLOUD.email, "INBOX", [], True)
    assert frame.played == [SYNCED]


def test_f5_in_folder_checks_only_that_account(frame):
    load_all(frame)
    frame._mailbox_key = (WORK.email, "Trash")
    frame._check_mail()
    assert frame._workers[WORK.email].refreshed == [("Trash", False)]
    assert frame._workers[GMAIL.email].refreshed == []


def test_error_on_one_account_blocks_confirmation_sound(frame):
    load_all(frame)
    frame._check_mail()
    frame.on_error(WORK.email, "Brak połączenia z Praca, spróbuję ponownie")
    frame.on_messages(GMAIL.email, "INBOX", [], True)
    frame.on_messages(ICLOUD.email, "INBOX", [], True)
    assert frame.played == []
    assert frame.spoken == ["Brak połączenia z Praca, spróbuję ponownie"]


def test_error_at_startup_is_spoken_after_window_is_read(frame, monkeypatch):
    delayed = []
    monkeypatch.setattr(
        mf.wx, "CallLater", lambda ms, run, *args: delayed.append((ms, run, args))
    )
    frame._initial_load = True
    frame._check_mail()
    frame.on_error(WORK.email, "Brak połączenia z Praca, spróbuję ponownie")
    assert frame.spoken == []
    assert delayed == [
        (2000, mf.speak, ("Brak połączenia z Praca, spróbuję ponownie",))
    ]
    assert frame.GetStatusBar().GetStatusText().startswith("Brak połączenia")


def test_new_mail_on_any_account_selects_it_in_all_mailboxes(frame):
    load_all(frame)
    newest = message(2, 12, "nowy")
    frame.on_messages(ICLOUD.email, "INBOX", [newest, message(1, 10)], True, True)
    assert frame.played == [NEW_MAIL]
    assert frame._message_list.selected_key() == (ICLOUD.email, "INBOX", 2)
    assert frame.spoken[0].startswith("nieprzeczytana, Jan, nowy, iCloud, ")


def test_startup_stays_on_newest_as_accounts_arrive(frame):
    frame._initial_load = True
    frame.on_messages(GMAIL.email, "INBOX", [message(1, 9)], False)
    frame.on_messages(WORK.email, "INBOX", [message(1, 11)], False)
    assert frame._message_list.selected_key() == (WORK.email, "INBOX", 1)


def test_startup_does_not_move_user_who_already_moved(frame):
    frame._initial_load = True
    frame.on_messages(GMAIL.email, "INBOX", [message(1, 9), message(2, 8)], False)
    frame._message_list.select_key((GMAIL.email, "INBOX", 2))
    frame.on_messages(WORK.email, "INBOX", [message(1, 11)], False)
    assert frame._message_list.selected_key() == (GMAIL.email, "INBOX", 2)


def test_delete_goes_to_message_account_and_next_row_from_another(frame):
    load_all(frame)
    frame._message_list.select_key((WORK.email, "INBOX", 1))
    key(frame, wx.WXK_DELETE)
    assert frame._workers[WORK.email].client.calls == [("move", "INBOX", 1, "trash")]
    assert frame._workers[ICLOUD.email].client.calls == []
    assert frame._message_list.selected_key() == (ICLOUD.email, "INBOX", 1)
    assert frame._mailbox_view.texts()[0][1].startswith("Wszystkie skrzynki, 5")


def test_archive_follows_rules_of_message_account(frame):
    load_all(frame)
    frame._message_list.select_key((ICLOUD.email, "INBOX", 1))
    key(frame, ord("A"), ctrl=True, shift=True)
    assert frame._workers[ICLOUD.email].client.calls == [
        ("move", "INBOX", 1, "archive")
    ]
    frame._message_list.select_key((GMAIL.email, "INBOX", 1))
    key(frame, ord("A"), ctrl=True, shift=True)
    assert frame._workers[GMAIL.email].client.calls == [("remove_inbox_label", 1)]


def test_failed_action_refreshes_only_that_account(frame):
    load_all(frame)
    frame.on_action_failed(WORK.email, "Nie udało się")
    assert frame._workers[WORK.email].refreshed == [("INBOX", True)]
    assert frame._workers[GMAIL.email].refreshed == []


def test_reply_uses_account_the_message_came_to(frame, monkeypatch):
    load_all(frame)
    drafts = []
    monkeypatch.setattr(frame, "_compose", drafts.append)
    selected = (ICLOUD.email, "INBOX", 1)
    frame._message_list.select_key(selected)
    frame._opened[selected] = MessageContent(
        "Jan", "ja", "Temat", None, "tresc", (), from_addresses=(("", "jan@a.pl"),)
    )
    key(frame, ord("R"), ctrl=True)
    key(frame, ord("L"), ctrl=True)
    assert [draft.sender for draft in drafts] == [ICLOUD.email, ICLOUD.email]


def test_opening_uses_worker_of_message_account(frame):
    load_all(frame)
    frame._message_list.select_key((WORK.email, "INBOX", 1))
    key(frame, wx.WXK_RETURN)
    assert frame._workers[WORK.email].opened == [("INBOX", 1)]
    assert frame._workers[GMAIL.email].opened == []


def test_stale_worker_results_are_ignored(frame):
    old = FakeWorker(GMAIL)
    frame._deliver(old, frame.on_error, ("x",))
    assert frame.spoken == []


def test_compose_lists_accounts_and_selects_sender(frame):
    workers = frame._workers
    dialog = cd.ComposeDialog(frame, ACCOUNTS, Draft(sender=ICLOUD.email), workers)
    assert dialog._sender.GetCount() == 3
    assert dialog._sender.GetStringSelection() == f"iCloud ({ICLOUD.email})"
    assert not dialog._is_changed()
    dialog._sender.SetSelection(0)
    assert dialog._is_changed()
    dialog._to.SetValue("a@b.pl")
    dialog._busy = False
    dialog.send()
    assert len(workers[GMAIL.email].sent) == 1
    assert b"From: ja@gmail.com" in workers[GMAIL.email].sent[0]
    assert workers[ICLOUD.email].sent == []
    dialog.Destroy()


def test_new_message_defaults_to_first_account(frame):
    dialog = cd.ComposeDialog(frame, ACCOUNTS, Draft(), frame._workers)
    assert dialog._sender.GetSelection() == 0
    assert not dialog._is_changed()
    dialog.Destroy()


def test_config_round_trip_and_bad_entries(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert config.load_accounts() == []
    config.save_accounts(ACCOUNTS)
    assert config.load_accounts() == ACCOUNTS
    path = config.config_path()
    data = json.loads(path.read_text(encoding="utf-8"))
    data["accounts"].append({"name": "x"})
    data["accounts"].append({"name": "x", "email": "e", "provider_key": "nieznany"})
    path.write_text(json.dumps(data), encoding="utf-8")
    assert config.load_accounts() == ACCOUNTS


def test_accounts_saved_before_display_name_still_load(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    path = config.config_path()
    path.parent.mkdir()
    old = {"name": "iCloud", "email": ICLOUD.email, "provider_key": "icloud"}
    path.write_text(json.dumps({"accounts": [old]}), encoding="utf-8")
    assert config.load_accounts() == [ICLOUD]
    named = Account("iCloud", ICLOUD.email, "icloud", "Jan Kowalski")
    config.save_accounts([named])
    assert config.load_accounts() == [named]


def test_account_dialog_shows_and_keeps_display_name(app):
    parent = wx.Frame(None)
    named = Account("iCloud", ICLOUD.email, "icloud", "Jan Kowalski")
    dialog = AccountDialog(parent, named)
    assert dialog._display_name.GetValue() == "Jan Kowalski"
    dialog.Destroy()
    parent.Destroy()


def test_compose_sends_name_of_selected_account(frame):
    named = Account("iCloud", ICLOUD.email, "icloud", "Jan Kowalski")
    workers = {GMAIL.email: FakeWorker(GMAIL), ICLOUD.email: FakeWorker(named)}
    dialog = cd.ComposeDialog(frame, [GMAIL, named], Draft(sender=ICLOUD.email), workers)
    dialog._to.SetValue("a@b.pl")
    dialog.send()
    assert b"From: Jan Kowalski <ja@icloud.com>" in workers[ICLOUD.email].sent[0]
    dialog.Destroy()


def test_compose_shows_signature_without_counting_as_change(frame):
    signed = Account("iCloud", ICLOUD.email, "icloud", "", "Jan\nFirma")
    dialog = cd.ComposeDialog(frame, [signed], Draft(), frame._workers)
    assert dialog._body.GetValue() == "\n\n-- \nJan\nFirma"
    assert not dialog._is_changed()
    dialog.Destroy()


def test_changing_sender_changes_signature(frame):
    first = Account("A", GMAIL.email, "gmail", "", "Prywatny")
    second = Account("B", ICLOUD.email, "icloud", "", "Służbowy")
    dialog = cd.ComposeDialog(
        frame, [first, second], Draft(body="\n\nW dniu x:\n> y"), frame._workers
    )
    dialog._body.SetValue("Treść" + dialog._body.GetValue())
    dialog._sender.SetSelection(1)
    dialog._on_sender_changed()
    assert dialog._body.GetValue() == "Treść\n\n-- \nSłużbowy\n\nW dniu x:\n> y"
    dialog.Destroy()


def test_account_dialog_keeps_multiline_signature(app):
    parent = wx.Frame(None)
    signed = Account("iCloud", ICLOUD.email, "icloud", "", "Jan\nFirma")
    dialog = AccountDialog(parent, signed)
    assert dialog._signature.GetValue() == "Jan\nFirma"
    dialog.Destroy()
    parent.Destroy()


def test_signature_survives_config(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    signed = Account("iCloud", ICLOUD.email, "icloud", "Jan", "Jan\nFirma")
    config.save_accounts([signed])
    assert config.load_accounts() == [signed]


def test_passwords_never_reach_config(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    config.save_accounts(ACCOUNTS)
    assert "password" not in config.config_path().read_text(encoding="utf-8")


def test_accounts_dialog_removes_account_and_password(app, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    removed = []
    monkeypatch.setattr(ad, "delete_password", removed.append)

    class Yes:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def SetYesNoLabels(self, *args):
            pass

        def ShowModal(self):
            return wx.ID_YES

    monkeypatch.setattr(ad.wx, "MessageDialog", Yes)
    parent = wx.Frame(None)
    dialog = ad.AccountsDialog(parent, ACCOUNTS)
    dialog._list.SetSelection(1)
    dialog._delete()
    assert dialog.accounts == [GMAIL, ICLOUD]
    assert dialog.changed
    assert removed == [WORK]
    assert config.load_accounts() == [GMAIL, ICLOUD]
    assert dialog._list.GetSelection() == 1
    dialog.Destroy()
    parent.Destroy()


def test_removing_active_account_returns_to_all_mailboxes(frame, monkeypatch):
    monkeypatch.setattr(mf, "get_password", lambda account: None)
    frame._mailbox_key = (WORK.email, "Trash")
    frame._connect([GMAIL])
    assert frame._mailbox_key == mf.ALL_KEY
    assert frame.spoken == ["Brak hasła do konta Prywatny"]
