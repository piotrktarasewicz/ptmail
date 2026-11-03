"""Własny dźwięk nowej wiadomości: plik MP3 lub WAV, a w razie kłopotu wbudowany."""

import pytest
import wx

from ptmail.accounts import Account
from ptmail.config import load_new_mail_sound, save_new_mail_sound
from ptmail.models import Message
from ptmail.sounds import NEW_MAIL, SOUND_WILDCARD
from ptmail.ui import main_frame as mf
from ptmail.ui import sound_dialog as sd

EMAIL = "ja@example.com"
SONG = r"C:\Dzwieki\dzwonek.mp3"


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
    monkeypatch.setattr(mf, "play", played.append)
    monkeypatch.setattr(mf, "speak", lambda text: None)
    window = mf.MainFrame()
    window._accounts = [Account("iCloud", EMAIL, "icloud")]
    window._workers = {EMAIL: FakeWorker()}
    window.played = played
    yield window
    window._workers = {}
    window.Destroy()


def message(uid):
    return Message(uid, "Jan", f"temat {uid}", None, False, False, 0)


def new_mail(window):
    window.on_messages(EMAIL, "INBOX", [message(1)], False)
    window.on_messages(EMAIL, "INBOX", [message(2), message(1)], True, True)


def test_builtin_sound_by_default(frame, monkeypatch):
    files = []
    monkeypatch.setattr(mf, "play_file", files.append)
    new_mail(frame)
    assert frame.played == [NEW_MAIL]
    assert files == []


def test_own_file_replaces_builtin_sound(frame, monkeypatch):
    files = []
    monkeypatch.setattr(mf, "play_file", lambda path: files.append(path) or True)
    frame._new_mail_sound = SONG
    new_mail(frame)
    assert files == [SONG]
    assert frame.played == []


def test_missing_file_falls_back_to_builtin(frame, monkeypatch):
    monkeypatch.setattr(mf, "play_file", lambda path: False)
    frame._new_mail_sound = SONG
    new_mail(frame)
    assert frame.played == [NEW_MAIL]


def test_sound_setting_is_remembered():
    assert load_new_mail_sound() is None
    save_new_mail_sound(SONG)
    assert load_new_mail_sound() == SONG
    save_new_mail_sound(None)
    assert load_new_mail_sound() is None


def test_both_mp3_and_wav_can_be_chosen():
    assert SOUND_WILDCARD == "*.mp3;*.wav"


@pytest.fixture
def dialog(app):
    parent = wx.Frame(None)
    windows = []

    def make(path):
        window = sd.SoundDialog(parent, path)
        windows.append(window)
        return window

    yield make
    for window in windows:
        window.Destroy()
    parent.Destroy()


def test_dialog_shows_builtin_without_file(dialog):
    window = dialog(None)
    assert window._builtin.GetValue()
    assert window._file.GetValue() == "nie wybrano"
    assert window.sound_path is None


def test_dialog_shows_chosen_file_name(dialog):
    window = dialog(SONG)
    assert window._custom.GetValue()
    assert window._file.GetValue() == "dzwonek.mp3"
    assert window.sound_path == SONG


def test_going_back_to_builtin_forgets_file(dialog):
    window = dialog(SONG)
    window._builtin.SetValue(True)
    assert window.sound_path is None


def test_listen_plays_what_is_chosen(dialog, monkeypatch):
    played = []
    monkeypatch.setattr(sd, "play", played.append)
    monkeypatch.setattr(sd, "play_file", lambda path: played.append(path) or True)
    window = dialog(SONG)
    window._listen()
    window._builtin.SetValue(True)
    window._listen()
    assert played == [SONG, NEW_MAIL]


def test_unplayable_file_is_reported(dialog, monkeypatch):
    monkeypatch.setattr(sd, "play_file", lambda path: False)
    window = dialog(SONG)
    window._listen()
    assert window._file.GetValue() == "Nie udało się odtworzyć pliku"


def test_saving_own_sound_without_file_asks_for_it(dialog, monkeypatch):
    window = dialog(None)
    window._custom.SetValue(True)
    asked = []
    monkeypatch.setattr(window, "_choose_file", lambda: asked.append(True))
    window._on_save(None)
    assert asked == [True]
