import io
import wave

import pytest
import wx

from ptmail.accounts import Account
from ptmail.models import Message
from ptmail.sounds import NEW_MAIL, SYNCED, TONES, build_wav
from ptmail.ui import main_frame as mf


def message(uid):
    return Message(uid, "Jan", f"temat {uid}", None, False, False, 0)


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
    window._account = Account("iCloud", "ja@example.com", "icloud")
    window.IsActive = lambda: True
    window.played = played
    window.spoken = spoken
    window.Show()
    yield window
    window.Destroy()


def load(window, *uids, refreshed=True):
    window.on_messages("INBOX", [message(uid) for uid in uids], refreshed)


def test_first_load_only_confirms(frame):
    load(frame, 2, 1)
    assert frame.played == [SYNCED]
    assert frame.spoken == []
    assert frame._message_list.selected_key() == 2


def test_refresh_without_news_keeps_selection(frame):
    load(frame, 2, 1)
    frame._message_list.select_key(1)
    load(frame, 2, 1)
    assert frame.played == [SYNCED, SYNCED]
    assert frame._message_list.selected_key() == 1


def test_new_message_takes_selection_and_is_read(frame):
    load(frame, 2, 1)
    frame._message_list.select_key(1)
    load(frame, 4, 3, 2, 1)
    assert frame.played == [SYNCED, NEW_MAIL]
    assert frame._message_list.selected_key() == 4
    assert frame.spoken == ["nieprzeczytana, Jan, temat 4, iCloud"]


def test_first_message_in_empty_folder_is_new(frame):
    load(frame)
    load(frame, 1)
    assert frame.played == [SYNCED, NEW_MAIL]


def test_deleted_message_is_not_news(frame):
    load(frame, 3, 2, 1)
    load(frame, 2, 1)
    assert frame.played == [SYNCED, SYNCED]


def test_opening_folder_makes_no_sound(frame):
    load(frame, 1, refreshed=False)
    assert frame.played == []


def test_new_message_in_inactive_window_moves_silently(frame):
    load(frame, 1)
    frame.IsActive = lambda: False
    load(frame, 2, 1)
    assert frame._message_list.selected_key() == 2
    assert frame.spoken == []


def test_reading_and_writing_are_not_interrupted(frame):
    load(frame, 1)
    frame._composing = True
    load(frame, 2, 1)
    assert frame._message_list.selected_key() == 1
    frame._composing = False
    frame._show_view(frame._mailbox_view)
    load(frame, 3, 2, 1)
    assert frame._message_list.selected_key() == 1
    assert frame.played == [SYNCED, NEW_MAIL, NEW_MAIL]
    assert frame.spoken == []


@pytest.mark.parametrize("name", [SYNCED, NEW_MAIL])
def test_sounds_are_valid_wav(name):
    with wave.open(io.BytesIO(build_wav(TONES[name]))) as file:
        assert file.getnchannels() == 1
        seconds = file.getnframes() / file.getframerate()
    assert 0.05 < seconds < 0.3
