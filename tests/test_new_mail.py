import io
import wave

import pytest
import wx

from ptmail.accounts import Account
from ptmail.config import (
    load_accounts,
    load_notifications,
    save_accounts,
    save_notifications,
)
from ptmail.models import Message
from ptmail.sounds import NEW_MAIL, SYNCED, TONES, build_wav
from ptmail.ui import main_frame as mf

EMAIL = "ja@example.com"
SENT = "Sent Messages"


def message(uid):
    return Message(uid, "Jan", f"temat {uid}", None, False, False, 0)


def ref(uid, folder="INBOX"):
    return (EMAIL, folder, uid)


class FakeWorker:
    def refresh(self, folder, silent=False):
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
    yield window
    window._workers = {}
    window.Destroy()


def load(window, *uids, refreshed=True):
    window.on_messages(EMAIL, "INBOX", [message(uid) for uid in uids], refreshed)


def test_first_load_only_confirms(frame):
    load(frame, 2, 1)
    assert frame.played == [SYNCED]
    assert frame.spoken == []
    assert frame._message_list.selected_key() == ref(2)


def test_refresh_without_news_keeps_selection(frame):
    load(frame, 2, 1)
    frame._message_list.select_key(ref(1))
    load(frame, 2, 1)
    assert frame.played == [SYNCED, SYNCED]
    assert frame._message_list.selected_key() == ref(1)


def test_new_message_takes_selection_and_is_read(frame):
    load(frame, 2, 1)
    frame._message_list.select_key(ref(1))
    load(frame, 4, 3, 2, 1)
    assert frame.played == [SYNCED, NEW_MAIL]
    assert frame._message_list.selected_key() == ref(4)
    # Wiersz czyta sam NVDA, gdy przechodzi na niego zaznaczenie.
    assert frame.spoken == []


def test_first_message_in_empty_folder_is_new(frame):
    load(frame)
    load(frame, 1)
    assert frame.played == [SYNCED, NEW_MAIL]


def test_deleted_message_is_not_news(frame):
    load(frame, 3, 2, 1)
    load(frame, 2, 1)
    assert frame.played == [SYNCED, SYNCED]


def test_automatic_refresh_without_news_is_silent(frame):
    load(frame, 1)
    frame.on_messages(EMAIL, "INBOX", [message(1)], True, True)
    assert frame.played == [SYNCED]


def test_automatic_refresh_announces_new_mail(frame):
    load(frame, 1)
    frame.on_messages(EMAIL, "INBOX", [message(2), message(1)], True, True)
    assert frame.played == [SYNCED, NEW_MAIL]
    assert frame._message_list.selected_key() == ref(2)


def test_new_mail_in_other_folder_only_plays_sound(frame):
    load(frame, 1)
    frame._mailbox_key = (EMAIL, SENT)
    frame.on_messages(EMAIL, SENT, [message(9)], False)
    frame._message_list.select_key(ref(9, SENT))
    frame.on_messages(EMAIL, "INBOX", [message(2), message(1)], True, True)
    assert frame.played == [SYNCED, NEW_MAIL]
    assert frame._message_list.selected_key() == ref(9, SENT)
    assert frame.spoken == []


def test_opening_folder_makes_no_sound(frame):
    load(frame, 1, refreshed=False)
    assert frame.played == []


def test_new_message_in_inactive_window_moves_silently(frame):
    load(frame, 1)
    frame.IsActive = lambda: False
    load(frame, 2, 1)
    assert frame._message_list.selected_key() == ref(2)
    assert frame.spoken == []


def test_reading_and_writing_are_not_interrupted(frame):
    load(frame, 1)
    frame._composing = True
    load(frame, 2, 1)
    assert frame._message_list.selected_key() == ref(1)
    frame._composing = False
    frame._show_view(frame._mailbox_view)
    load(frame, 3, 2, 1)
    assert frame._message_list.selected_key() == ref(1)
    assert frame.played == [SYNCED, NEW_MAIL, NEW_MAIL]
    assert frame.spoken == []


@pytest.fixture
def notified(frame, monkeypatch):
    shown = []
    monkeypatch.setattr(mf, "notify", lambda title, text: shown.append((title, text)))
    monkeypatch.setattr(frame, "_in_background", lambda: True)
    return shown


def test_background_mail_shows_notification_with_sender_and_subject(frame, notified):
    load(frame, 1)
    load(frame, 2, 1)
    assert notified == [("Nowa wiadomość od Jan", "temat 2")]


def test_automatic_refresh_notifies_too(frame, notified):
    load(frame, 1)
    frame.on_messages(EMAIL, "INBOX", [message(2), message(1)], True, True)
    assert len(notified) == 1


def test_several_messages_give_one_notification_about_newest(frame, notified):
    load(frame, 1)
    load(frame, 4, 3, 2, 1)
    assert notified == [("Nowa wiadomość od Jan", "temat 4")]


def test_no_notification_when_program_is_in_front(frame, notified, monkeypatch):
    monkeypatch.setattr(frame, "_in_background", lambda: False)
    load(frame, 1)
    load(frame, 2, 1)
    assert notified == []


def test_no_notification_without_news_or_at_startup(frame, notified):
    frame._initial_load = True
    frame.on_messages(EMAIL, "INBOX", [message(1)], True)
    frame._messages[(EMAIL, "INBOX")] = []
    frame._initial_load = True
    frame.on_messages(EMAIL, "INBOX", [message(2)], True)
    load(frame, 2)
    assert notified == []


def test_turned_off_notifications_stay_off_after_restart(frame, notified):
    frame._set_notifications(False)
    load(frame, 1)
    load(frame, 2, 1)
    assert notified == []
    assert frame.played == [SYNCED, NEW_MAIL]
    assert load_notifications() is False


def test_notification_setting_defaults_to_on_and_keeps_accounts():
    assert load_notifications() is True
    account = Account("iCloud", EMAIL, "icloud")
    save_accounts([account])
    save_notifications(False)
    save_accounts([account])
    assert load_notifications() is False
    assert load_accounts() == [account]


def test_program_with_active_app_is_not_in_background(frame, monkeypatch):
    monkeypatch.setattr(wx.GetApp(), "IsActive", lambda: True, raising=False)
    assert not frame._in_background()
    monkeypatch.setattr(wx.GetApp(), "IsActive", lambda: False, raising=False)
    assert frame._in_background()


@pytest.mark.parametrize("name", [SYNCED, NEW_MAIL])
def test_sounds_are_valid_wav(name):
    with wave.open(io.BytesIO(build_wav(TONES[name]))) as file:
        assert file.getnchannels() == 1
        seconds = file.getnframes() / file.getframerate()
    assert 0.05 < seconds < 0.3
