"""Zasobnik, zamykanie okna i pytanie o aktualizację."""

import pytest
import wx

from ptmail import updates
from ptmail.accounts import Account
from ptmail.config import load_hide_on_close
from ptmail.models import Folder, Message
from ptmail.sounds import SYNCED
from ptmail.ui import main_frame as mf
from ptmail.updates import Release

EMAIL = "ja@example.com"
RELEASE = Release("0.2.0", "url", "abc")


class FakeTray:
    def __init__(self):
        self.unread = []
        self.removed = False

    def show_unread(self, unread):
        self.unread.append(unread)

    def RemoveIcon(self):
        self.removed = True

    def Destroy(self):
        pass


class FakeWorker:
    def refresh(self, folder, silent=False):
        pass

    def stop(self):
        pass


class FakeDialog:
    answer = wx.ID_NO
    shown = []

    def __init__(self, parent, text, *args):
        FakeDialog.shown.append(text)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def SetYesNoLabels(self, yes, no):
        pass

    def ShowModal(self):
        return FakeDialog.answer


@pytest.fixture(scope="module")
def app():
    application = wx.App()
    yield application
    del application


@pytest.fixture
def frame(app, monkeypatch):
    played = []
    spoken = []
    FakeDialog.shown = []
    FakeDialog.answer = wx.ID_NO
    monkeypatch.setattr(mf, "play", played.append)
    monkeypatch.setattr(mf, "speak", spoken.append)
    monkeypatch.setattr(mf.wx, "MessageDialog", FakeDialog)
    window = mf.MainFrame()
    window._accounts = [Account("iCloud", EMAIL, "icloud")]
    window._workers = {EMAIL: FakeWorker()}
    window._tray = FakeTray()
    window.played = played
    window.spoken = spoken
    window.Show()
    yield window
    window._tray = None
    window._workers = {}
    window.Destroy()


class CloseEvent:
    def __init__(self, can_veto):
        self.can_veto = can_veto
        self.vetoed = False
        self.skipped = False

    def CanVeto(self):
        return self.can_veto

    def Veto(self):
        self.vetoed = True

    def Skip(self):
        self.skipped = True


def test_close_hides_to_tray_and_keeps_mail_running(frame):
    event = CloseEvent(True)
    frame._on_close(event)
    assert event.vetoed
    assert not frame.IsShown()
    assert frame._workers
    assert not frame._tray.removed


def test_setting_makes_close_end_the_program(frame, monkeypatch):
    monkeypatch.setattr(frame._cache, "close", lambda: None, raising=False)
    tray = frame._tray
    frame._set_hide_on_close(False)
    event = CloseEvent(True)
    frame._on_close(event)
    assert event.skipped
    assert tray.removed
    assert frame._workers == {}
    assert load_hide_on_close() is False


def test_forced_close_ignores_hiding(frame):
    tray = frame._tray
    event = CloseEvent(False)
    frame._on_close(event)
    assert event.skipped
    assert tray.removed


def test_show_window_brings_back_view_with_focus(frame, monkeypatch):
    frame.Hide()
    focused = []
    monkeypatch.setattr(frame._message_list, "focus", lambda: focused.append(True))
    frame.show_window()
    assert frame.IsShown()
    assert focused == [True]


def test_quit_with_open_dialog_shows_window_instead(frame, monkeypatch):
    closed = []
    monkeypatch.setattr(frame, "IsEnabled", lambda: False)
    monkeypatch.setattr(frame, "Close", lambda force: closed.append(force))
    frame.Hide()
    frame.quit()
    assert closed == []
    assert frame.IsShown()


def test_quit_closes_for_good(frame, monkeypatch):
    closed = []
    monkeypatch.setattr(frame, "Close", lambda force: closed.append(force))
    frame.quit()
    assert closed == [True]


def test_tray_tooltip_follows_unread_count(frame):
    frame._folders[EMAIL] = [Folder("INBOX", "Odebrane", "inbox", 3)]
    frame._show_mailbox_rows()
    assert frame._tray.unread[-1] == 3


def test_hidden_program_stays_quiet(frame):
    frame.Hide()
    frame._initial_load = True
    frame.on_error(EMAIL, "Brak połączenia z iCloud, spróbuję ponownie")
    assert frame.spoken == []
    assert frame.GetStatusBar().GetStatusText() != ""
    frame._sync_clean = True
    frame._finish_sync(EMAIL)
    assert SYNCED not in frame.played


def test_hidden_program_counts_as_background(frame):
    frame.Hide()
    assert frame._in_background()


def test_new_mail_while_hidden_selects_it_silently(frame):
    message = Message(1, "Jan", "temat", None, False, False, 0)
    frame.on_messages(EMAIL, "INBOX", [message], True)
    frame.Hide()
    newer = Message(2, "Jan", "nowy", None, False, False, 0)
    frame.on_messages(EMAIL, "INBOX", [newer, message], True, True)
    assert frame._message_list.selected_key() == (EMAIL, "INBOX", 2)
    assert frame.spoken == []


def checked(frame, release, failed=False, asked=False):
    frame._on_update_checked(release, failed, asked)


def test_found_update_asks_once(frame):
    checked(frame, RELEASE)
    assert FakeDialog.shown == [
        "Jest nowa wersja PT Mail: 0.2.0. Zainstalować ją teraz?"
    ]
    frame._offer_update()
    assert len(FakeDialog.shown) == 1


def test_asking_from_menu_asks_again_after_declining(frame):
    checked(frame, RELEASE)
    checked(frame, RELEASE, asked=True)
    assert len(FakeDialog.shown) == 2


def test_hidden_program_waits_with_question_until_shown(frame):
    frame.Hide()
    checked(frame, RELEASE)
    assert FakeDialog.shown == []
    frame.show_window()
    assert len(FakeDialog.shown) == 1


def test_open_dialog_postpones_question(frame, monkeypatch):
    monkeypatch.setattr(frame, "IsEnabled", lambda: False)
    checked(frame, RELEASE)
    assert FakeDialog.shown == []


def test_automatic_check_is_silent_without_news(frame):
    checked(frame, None)
    checked(frame, None, failed=True)
    assert frame.spoken == []


def test_menu_check_reports_result(frame):
    checked(frame, None, asked=True)
    assert frame.spoken == ["Masz najnowszą wersję, 0.1.0"]
    checked(frame, None, failed=True, asked=True)
    assert frame.spoken[-1] == "Nie udało się sprawdzić aktualizacji"


def test_source_run_explains_missing_updates(frame):
    frame._check_for_update(asked=True)
    assert frame.spoken == ["Aktualizacje działają tylko w zainstalowanej wersji"]


def test_source_run_checks_nothing_automatically(frame, monkeypatch):
    monkeypatch.setattr(updates, "in_background", pytest.fail)
    frame._check_for_update()
    assert frame.spoken == []


def test_accepting_downloads_installer(frame, monkeypatch):
    work = []
    monkeypatch.setattr(frame, "_run_update_step", lambda run, done: work.append(done))
    FakeDialog.answer = wx.ID_YES
    checked(frame, RELEASE)
    assert frame.spoken == ["Pobieranie aktualizacji"]
    assert work == [frame._on_update_downloaded]


def test_failed_download_is_spoken_and_nothing_runs(frame, monkeypatch):
    monkeypatch.setattr(updates, "run_installer", pytest.fail)
    frame._on_update_downloaded(None, True)
    assert frame.spoken == ["Nie udało się pobrać aktualizacji"]


def test_installing_waits_for_open_dialog(frame, monkeypatch):
    later = []
    monkeypatch.setattr(mf.wx, "CallLater", lambda delay, *args: later.append(delay))
    monkeypatch.setattr(frame, "IsEnabled", lambda: False)
    frame._install_update("s.exe")
    assert later == [mf.UPDATE_RETRY_MS]
    assert frame.spoken == []


def test_installer_starts_before_program_closes(frame, monkeypatch):
    order = []
    monkeypatch.setattr(updates, "run_installer", lambda path: order.append(path))
    monkeypatch.setattr(frame, "quit", lambda: order.append("koniec"))
    frame._close_for_installer("s.exe")
    assert order == ["s.exe", "koniec"]
