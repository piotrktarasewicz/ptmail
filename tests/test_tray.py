"""Zasobnik, zamykanie okna i pytanie o aktualizację."""

import pytest
import wx

from ptmail import config, updates
from ptmail.accounts import Account
from ptmail.config import load_hide_on_close
from ptmail.models import Folder, Message
from ptmail.sounds import SYNCED
from ptmail.ui import main_frame as mf
from ptmail.ui import update_dialog as update_dialog_module
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
    assert frame.spoken == [f"Masz najnowszą wersję, {mf.__version__}"]
    checked(frame, None, failed=True, asked=True)
    assert frame.spoken[-1] == "Nie udało się sprawdzić aktualizacji"


def test_source_run_explains_missing_updates(frame):
    frame._check_for_update(asked=True)
    assert frame.spoken == ["Aktualizacje działają tylko w zainstalowanej wersji"]


def test_source_run_checks_nothing_automatically(frame, monkeypatch):
    monkeypatch.setattr(updates, "in_background", pytest.fail)
    frame._check_for_update()
    assert frame.spoken == []


class FakeUpdateDialog:
    """Kończy się od razu podanym wynikiem, bez prawdziwego okna."""

    path = None
    failed = False
    was_cancelled = False
    made = []

    def __init__(self, parent, on_cancel):
        self.on_cancel = on_cancel
        FakeUpdateDialog.made.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def ShowModal(self):
        return wx.ID_OK

    def finish(self, path, failed):
        pass


@pytest.fixture
def update_dialog(frame, monkeypatch):
    FakeUpdateDialog.made = []
    monkeypatch.setattr(FakeUpdateDialog, "path", None)
    monkeypatch.setattr(FakeUpdateDialog, "failed", False)
    monkeypatch.setattr(FakeUpdateDialog, "was_cancelled", False)
    monkeypatch.setattr(mf, "UpdateDialog", FakeUpdateDialog)
    monkeypatch.setattr(frame, "_run_update_step", lambda work, done: None)
    monkeypatch.setattr(frame, "_say_after_focus", frame.spoken.append)
    return FakeUpdateDialog


@pytest.fixture
def beeps(monkeypatch):
    heard = []
    monkeypatch.setattr(mf, "beep", heard.append)
    return heard


def test_question_plays_system_sound(frame, beeps):
    checked(frame, RELEASE)
    assert beeps == [mf.ATTENTION]


def test_question_in_background_also_notifies(frame, monkeypatch):
    shown = []
    monkeypatch.setattr(mf, "notify", lambda title, text: shown.append(text))
    monkeypatch.setattr(frame, "_in_background", lambda: True)
    checked(frame, RELEASE)
    assert shown == ["Jest nowa wersja PT Mail: 0.2.0. Zainstalować ją teraz?"]


def test_accepting_opens_progress_window(frame, update_dialog, monkeypatch):
    installs = []
    monkeypatch.setattr(frame, "_install_update", lambda *args: installs.append(args))
    monkeypatch.setattr(update_dialog, "path", "s.exe")
    FakeDialog.answer = wx.ID_YES
    checked(frame, RELEASE)
    assert len(update_dialog.made) == 1
    assert installs == [("0.2.0", "s.exe")]


def test_failed_download_sounds_and_speaks(frame, update_dialog, beeps, monkeypatch):
    monkeypatch.setattr(updates, "run_installer", pytest.fail)
    monkeypatch.setattr(update_dialog, "failed", True)
    frame._download_update(RELEASE)
    assert beeps == [mf.FAILURE]
    assert frame.spoken == ["Nie udało się pobrać aktualizacji"]


def test_cancelling_is_not_an_error_and_is_not_asked_again(
    frame, update_dialog, beeps, monkeypatch
):
    monkeypatch.setattr(update_dialog, "failed", True)
    monkeypatch.setattr(update_dialog, "was_cancelled", True)
    frame._update = RELEASE
    frame._download_update(RELEASE)
    assert beeps == []
    assert frame.spoken == ["Anulowano aktualizację"]
    frame._offer_update()
    assert FakeDialog.shown == []


def test_cancel_at_last_moment_does_not_install(frame, update_dialog, monkeypatch):
    monkeypatch.setattr(frame, "_install_update", pytest.fail)
    monkeypatch.setattr(update_dialog, "path", "s.exe")
    monkeypatch.setattr(update_dialog, "was_cancelled", True)
    frame._download_update(RELEASE)
    assert frame.spoken == ["Anulowano aktualizację"]


def test_failed_menu_check_plays_error_sound(frame, beeps):
    checked(frame, None, failed=True, asked=True)
    assert beeps == [mf.FAILURE]


def test_automatic_check_failure_is_silent(frame, beeps):
    checked(frame, None, failed=True)
    assert beeps == []


def test_installing_waits_for_open_dialog(frame, monkeypatch):
    later = []
    monkeypatch.setattr(mf.wx, "CallLater", lambda delay, *args: later.append(delay))
    monkeypatch.setattr(frame, "IsEnabled", lambda: False)
    frame._install_update("0.2.0", "s.exe")
    assert later == [mf.UPDATE_RETRY_MS]
    assert frame.spoken == []


def test_installer_starts_before_program_closes(frame, monkeypatch):
    order = []
    monkeypatch.setattr(updates, "run_installer", lambda path: order.append(path))
    monkeypatch.setattr(frame, "quit", lambda: order.append("koniec"))
    frame._close_for_installer("0.2.0", "s.exe")
    assert order == ["s.exe", "koniec"]
    assert config.take_pending_update() == "0.2.0"


def test_installer_that_cannot_start_keeps_program_running(frame, beeps, monkeypatch):
    def refuse(path):
        raise OSError("brak pliku")

    monkeypatch.setattr(updates, "run_installer", refuse)
    monkeypatch.setattr(frame, "quit", pytest.fail)
    frame._close_for_installer("0.2.0", "s.exe")
    assert beeps == [mf.FAILURE]
    assert frame.spoken == ["Nie udało się uruchomić instalatora"]
    assert config.take_pending_update() is None


@pytest.fixture
def startup_speech(monkeypatch):
    said = []
    monkeypatch.setattr(
        mf.wx,
        "CallLater",
        lambda delay, function, *args: said.append((delay, *args)),
    )
    return said


def test_restart_reports_successful_update(frame, beeps, startup_speech):
    config.save_pending_update(mf.__version__)
    frame._report_finished_update()
    assert beeps == [mf.ATTENTION]
    text = f"Zaktualizowano do wersji {mf.__version__}"
    assert startup_speech == [(mf.STARTUP_SPEECH_DELAY_MS, text)]
    assert config.take_pending_update() is None


def test_restart_with_old_version_reports_failure(frame, beeps, startup_speech):
    config.save_pending_update("99.0")
    frame._report_finished_update()
    assert beeps == [mf.FAILURE]
    assert startup_speech == [
        (mf.STARTUP_SPEECH_DELAY_MS, "Nie udało się zainstalować aktualizacji")
    ]


def test_ordinary_start_reports_nothing(frame, beeps, startup_speech):
    frame._report_finished_update()
    assert beeps == []
    assert startup_speech == []


@pytest.fixture
def progress(app, monkeypatch):
    spoken = []
    monkeypatch.setattr(update_dialog_module, "speak", spoken.append)
    parent = wx.Frame(None)
    cancelled = []
    dialog = update_dialog_module.UpdateDialog(parent, lambda: cancelled.append(True))
    dialog.spoken = spoken
    dialog.cancel_calls = cancelled
    yield dialog
    dialog.Destroy()
    parent.Destroy()


def test_progress_speaks_only_every_quarter(progress):
    for percent in (5, 24, 25, 30, 49, 74, 100):
        progress.show_progress(percent)
    assert progress.spoken == ["25 procent", "50 procent", "100 procent"]


def test_progress_sets_gauge_and_tolerates_unknown_size(progress):
    progress.show_progress(40)
    assert progress._gauge.GetValue() == 40
    progress.show_progress(None)
    assert progress.spoken == ["25 procent"]


def test_window_closes_with_result_of_download(progress):
    wx.CallAfter(progress.show_progress, 50)
    wx.CallAfter(progress.finish, "s.exe", False)
    assert progress.ShowModal() == wx.ID_OK
    assert progress.path == "s.exe"
    assert not progress.failed
    assert progress.spoken == ["50 procent"]


def test_progress_bar_has_label_for_nvda(progress):
    assert progress._gauge.GetPrevSibling() is progress._status


def test_cancel_stops_once_and_waits_for_download(progress):
    progress.cancel()
    progress.cancel()
    assert progress.cancel_calls == [True]
    assert progress.spoken == ["Anulowanie"]
    assert not progress._cancel.IsEnabled()
