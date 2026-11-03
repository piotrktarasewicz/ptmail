"""Testy nigdy nie dotykają prawdziwych kont, haseł, bazy ani serwerów."""

import imaplib

import pytest

from ptmail import credentials
from ptmail.ui import main_frame, sound_dialog
from ptmail.ui.main_frame import MainFrame


def _no_real_server(*args, **kwargs):
    raise AssertionError("Test próbował połączyć się z prawdziwym serwerem")


@pytest.fixture(autouse=True)
def isolated_from_real_data(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    # Start jest odłożony przez wx.CallAfter, więc odpaliłaby go każda pętla okna.
    monkeypatch.setattr(MainFrame, "_start", lambda self: None)
    monkeypatch.setattr(main_frame, "notify", lambda title, text: None)
    monkeypatch.setattr(main_frame, "beep", lambda kind: None)
    monkeypatch.setattr(main_frame, "play_file", lambda path: True)
    monkeypatch.setattr(sound_dialog, "play", lambda name: None)
    monkeypatch.setattr(sound_dialog, "play_file", lambda path: True)
    monkeypatch.setattr(imaplib, "IMAP4_SSL", _no_real_server)
    monkeypatch.setattr(credentials.keyring, "get_password", lambda *args: None)
    monkeypatch.setattr(credentials.keyring, "set_password", _no_real_server)
    monkeypatch.setattr(credentials.keyring, "delete_password", _no_real_server)
