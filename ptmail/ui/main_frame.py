import threading
import webbrowser
from dataclasses import dataclass, field, replace

import wx

from .. import APP_NAME, __version__, updates
from ..attachments import (
    can_open,
    clear_temp,
    downloads_dir,
    open_attachment,
    safe_filename,
    save_to_folder,
)
from ..cache import MailCache, open_cache
from ..compose import Draft, forward_draft, reply_draft
from ..config import (
    load_accounts,
    load_hide_on_close,
    load_new_mail_sound,
    load_newest_first,
    load_notifications,
    save_accounts,
    save_hide_on_close,
    save_new_mail_sound,
    save_newest_first,
    save_notifications,
    save_pending_update,
    take_pending_update,
)
from ..contacts import merge_contacts, parse_contacts
from ..credentials import get_password, set_password
from ..formatting import found_text, mailbox_sentence, message_sentence
from ..i18n import _
from ..idle_watcher import IdleWatcher
from ..mail_worker import INBOX, MailWorker
from ..message_parser import link_host, parse_message
from ..notifications import notify
from ..sounds import ATTENTION, FAILURE, NEW_MAIL, SYNCED, beep, play, play_file
from ..speech import speak
from .account_dialog import AccountDialog
from .accounts_dialog import AccountsDialog
from .compose_dialog import ComposeDialog
from .list_view import ListView
from .message_view import MessageView
from .move_dialog import MoveDialog
from .search_dialog import SearchDialog
from .sound_dialog import SoundDialog
from .tray import TrayIcon
from .update_dialog import UpdateDialog

ALL_KEY = "all"
SEARCH_KEY = "search"
OPENED_CACHE_SIZE = 30
SEARCH_RESULT_LIMIT = 200
AFTER_FOCUS_SPEECH_DELAY_MS = 300
STARTUP_SPEECH_DELAY_MS = 2000
UPDATE_CHECK_DELAY_MS = 5000
UPDATE_CHECK_INTERVAL_MS = 24 * 60 * 60 * 1000
UPDATE_RETRY_MS = 5000
UPDATE_CLOSE_DELAY_MS = 3000


@dataclass
class PendingSearch:
    search_id: int
    waiting: set
    messages: list = field(default_factory=list)
    failed: list = field(default_factory=list)


def _newest_new_message(previous, messages):
    """Zwraca najnowszą wiadomość spoza poprzedniej listy. Lista jest od najnowszej."""
    if previous is None:
        return None
    highest = max((message.uid for message in previous), default=0)
    return next((m for m in messages if m.uid > highest), None)


def _newest_first(message):
    return (message.date.timestamp() if message.date else 0, message.uid)


class MainFrame(wx.Frame):
    """Okno główne. Zawsze widać w nim tylko jeden widok naraz.

    Skrzynka to ALL_KEY, SEARCH_KEY albo para (adres konta, folder); folder None
    oznacza Odebrane wybrane z wiersza konta.
    """

    def __init__(self):
        super().__init__(None, title=APP_NAME, size=(800, 600))
        self._accounts = []
        self._cache = MailCache()
        self._workers = {}
        self._watchers = {}
        self._folders = {}
        self._messages = {}
        self._opened = {}
        self._removed = set()
        self._pending_open = None
        self._mailbox_key = ALL_KEY
        self._composing = False
        self._sync_pending = set()
        self._sync_clean = True
        self._initial_load = False
        self._search_results = []
        self._pending_search = None
        self._search_dialog = None
        self._found_search = None
        self._last_search_id = 0
        self._before_search = None
        self._last_query = ""
        self._last_everywhere = False
        self._notifications = load_notifications()
        self._hide_on_close = load_hide_on_close()
        self._newest_first = load_newest_first()
        self._new_mail_sound = load_new_mail_sound()
        self._tray = None
        self._update = None
        self._declined_update = None
        self._update_timer = wx.Timer(self)

        self._build_menu()
        self.CreateStatusBar()
        panel = wx.Panel(self)
        self._message_list = ListView(panel, _("Wiadomości"))
        self._mailbox_view = ListView(panel, _("Skrzynki"))
        self._message_view = MessageView(panel)
        self._views = (self._message_list, self._mailbox_view, self._message_view)
        sizer = wx.BoxSizer(wx.VERTICAL)
        for view in self._views:
            sizer.Add(view, 1, wx.EXPAND)
        panel.SetSizer(sizer)
        self._panel = panel

        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.Bind(
            wx.EVT_TIMER, lambda _event: self._check_for_update(), self._update_timer
        )
        self._message_list.list.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
        self._update_title()
        self._show_mailbox_rows()
        self._show_view(self._message_list)
        wx.CallAfter(self._start)

    def _build_menu(self):
        menu = wx.Menu()
        accounts = menu.Append(wx.ID_ANY, _("&Konta…"))
        check = menu.Append(wx.ID_ANY, _("&Sprawdź pocztę teraz\tF5"))
        search = menu.Append(wx.ID_ANY, _("S&zukaj…\tCtrl+F"))
        notifications = menu.AppendCheckItem(
            wx.ID_ANY, _("P&owiadomienia systemowe")
        )
        notifications.Check(self._notifications)
        hide_on_close = menu.AppendCheckItem(
            wx.ID_ANY, _("Alt+F4 &chowa do zasobnika")
        )
        hide_on_close.Check(self._hide_on_close)
        sound = menu.Append(wx.ID_ANY, _("&Dźwięk nowej wiadomości…"))
        update = menu.Append(wx.ID_ANY, _("Sprawdź &aktualizacje…"))
        menu.AppendSeparator()
        close = menu.Append(wx.ID_EXIT, _("&Zakończ\tCtrl+Q"))
        view = wx.Menu()
        newest = view.AppendRadioItem(wx.ID_ANY, _("Od &najnowszych"))
        oldest = view.AppendRadioItem(wx.ID_ANY, _("Od n&ajstarszych"))
        (newest if self._newest_first else oldest).Check()
        view.AppendSeparator()
        reverse = view.Append(wx.ID_ANY, _("&Odwróć kolejność\tCtrl+Shift+O"))
        self._order_items = (newest, oldest)
        bar = wx.MenuBar()
        bar.Append(menu, _("&Plik"))
        bar.Append(view, _("&Widok"))
        self.SetMenuBar(bar)
        self.Bind(wx.EVT_MENU, lambda _event: self._set_newest_first(True), newest)
        self.Bind(wx.EVT_MENU, lambda _event: self._set_newest_first(False), oldest)
        self.Bind(
            wx.EVT_MENU,
            lambda _event: self._set_newest_first(not self._newest_first),
            reverse,
        )
        self.Bind(wx.EVT_MENU, lambda _event: self._manage_accounts(), accounts)
        self.Bind(wx.EVT_MENU, lambda _event: self._check_mail(), check)
        self.Bind(wx.EVT_MENU, lambda _event: self._open_search(), search)
        self.Bind(
            wx.EVT_MENU,
            lambda event: self._set_notifications(event.IsChecked()),
            notifications,
        )
        self.Bind(
            wx.EVT_MENU,
            lambda event: self._set_hide_on_close(event.IsChecked()),
            hide_on_close,
        )
        self.Bind(wx.EVT_MENU, lambda _event: self._choose_sound(), sound)
        self.Bind(
            wx.EVT_MENU, lambda _event: self._check_for_update(asked=True), update
        )
        self.Bind(wx.EVT_MENU, lambda _event: self.quit(), close)

    def _set_notifications(self, enabled):
        self._notifications = enabled
        save_notifications(enabled)

    def _set_hide_on_close(self, enabled):
        self._hide_on_close = enabled
        save_hide_on_close(enabled)

    def _choose_sound(self):
        with SoundDialog(self, self._new_mail_sound) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            path = dialog.sound_path
        self._new_mail_sound = path
        save_new_mail_sound(path)
        self._say_after_focus(_("Zapisano"))

    def _play_new_mail(self):
        # Gdy własnego pliku już nie ma, nowa poczta i tak nie przyjdzie po cichu.
        if self._new_mail_sound is None or not play_file(self._new_mail_sound):
            play(NEW_MAIL)

    def _set_newest_first(self, enabled):
        """Zmienia kolejność wszystkich list, a zaznaczenie zostaje na tej samej wiadomości."""
        self._newest_first = enabled
        save_newest_first(enabled)
        self._order_items[0 if enabled else 1].Check()
        self._show_message_rows()
        self._say(_("Od najnowszych") if enabled else _("Od najstarszych"))

    def _start(self):
        clear_temp()
        self._cache = open_cache()
        self._tray = TrayIcon(self.show_window, self._check_mail, self.quit)
        accounts = load_accounts()
        if accounts:
            self._connect(accounts)
        else:
            self.show_window()
            self._add_first_account()
        self._report_finished_update()
        wx.CallLater(UPDATE_CHECK_DELAY_MS, self._check_for_update)
        self._update_timer.Start(UPDATE_CHECK_INTERVAL_MS)

    def show_window(self):
        """Przywraca okno z zasobnika lub z paska zadań, z fokusem na bieżącym widoku."""
        self.Iconize(False)
        self.Show()
        self.Raise()
        if self.IsEnabled():
            next(view for view in self._views if view.IsShown()).focus()
        self._offer_update()

    def quit(self):
        """Kończy program. Otwarte okno, np. pisania, nie może zniknąć bez pytania."""
        if self.IsEnabled():
            self.Close(force=True)
        else:
            self.show_window()

    # Aktualizacje

    def _check_for_update(self, asked=False):
        if not updates.is_installed():
            if asked:
                self._say(_("Aktualizacje działają tylko w zainstalowanej wersji"))
            return
        if asked:
            self._say(_("Sprawdzanie aktualizacji"))
        self._run_update_step(
            lambda: updates.find_update(__version__),
            lambda release, failed: self._on_update_checked(release, failed, asked),
        )

    def _run_update_step(self, work, on_done):
        updates.in_background(
            work, lambda result, failed: wx.CallAfter(on_done, result, failed)
        )

    def _report_finished_update(self):
        """Po instalacji program startuje od nowa i dopiero wtedy zna jej wynik."""
        version = take_pending_update()
        if version is None:
            return
        if version == __version__:
            beep(ATTENTION)
            text = _("Zaktualizowano do wersji {version}").format(version=version)
        else:
            beep(FAILURE)
            text = _("Nie udało się zainstalować aktualizacji")
        self.SetStatusText(text)
        wx.CallLater(STARTUP_SPEECH_DELAY_MS, speak, text)

    def _on_update_checked(self, release, failed, asked):
        if failed:
            if asked:
                beep(FAILURE)
                self._say(_("Nie udało się sprawdzić aktualizacji"))
        elif release is None:
            if asked:
                self._say(
                    _("Masz najnowszą wersję, {version}").format(version=__version__)
                )
        else:
            self._update = release
            self._offer_update(asked)

    def _offer_update(self, asked=False):
        """Pyta tylko wtedy, gdy okno jest widoczne i nic innego się w nim nie dzieje."""
        release = self._update
        if release is None or not self.IsShown() or not self.IsEnabled():
            return
        if release.version == self._declined_update and not asked:
            return
        question = _("Jest nowa wersja PT Mail: {version}. Zainstalować ją teraz?").format(
            version=release.version
        )
        beep(ATTENTION)
        if self._in_background():
            notify(APP_NAME, question)
        with wx.MessageDialog(
            self,
            question,
            APP_NAME,
            wx.YES_NO | wx.YES_DEFAULT | wx.ICON_QUESTION,
        ) as dialog:
            dialog.SetYesNoLabels(_("Zainstaluj"), _("Później"))
            answer = dialog.ShowModal()
        if answer == wx.ID_YES:
            self._download_update(release)
        else:
            self._declined_update = release.version

    def _download_update(self, release):
        cancelled = threading.Event()
        with UpdateDialog(self, cancelled.set) as dialog:
            report = lambda percent: wx.CallAfter(dialog.show_progress, percent)
            self._run_update_step(
                lambda: updates.download(release, report, cancelled), dialog.finish
            )
            dialog.ShowModal()
            path = dialog.path
            failed = dialog.failed
            was_cancelled = dialog.was_cancelled
        if was_cancelled:
            self._declined_update = release.version
            self._say_after_focus(_("Anulowano aktualizację"))
        elif failed:
            beep(FAILURE)
            self._say_after_focus(_("Nie udało się pobrać aktualizacji"))
        else:
            self._install_update(release.version, path)

    def _say_after_focus(self, text):
        self.SetStatusText(text)
        wx.CallLater(AFTER_FOCUS_SPEECH_DELAY_MS, speak, text)

    def _install_update(self, version, path):
        # Zakończenie programu zamknęłoby otwarte okno pisania, więc czekamy na jego koniec.
        if not self.IsEnabled():
            wx.CallLater(UPDATE_RETRY_MS, self._install_update, version, path)
            return
        self._say_after_focus(_("Instalowanie, program uruchomi się ponownie"))
        wx.CallLater(UPDATE_CLOSE_DELAY_MS, self._close_for_installer, version, path)

    def _close_for_installer(self, version, path):
        if not self.IsEnabled():
            self._install_update(version, path)
            return
        save_pending_update(version)
        try:
            updates.run_installer(path)
        except OSError:
            take_pending_update()
            beep(FAILURE)
            self._say(_("Nie udało się uruchomić instalatora"))
            return
        self.quit()

    def _add_first_account(self):
        with AccountDialog(self) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                save_accounts([dialog.account])
                set_password(dialog.account, dialog.password)
                self._connect([dialog.account])

    def _manage_accounts(self):
        with AccountsDialog(self, self._accounts) as dialog:
            dialog.ShowModal()
            changed = dialog.changed
            accounts = dialog.accounts
        if changed:
            self._connect(accounts)

    def _connect(self, accounts):
        self._stop_sessions()
        self._accounts = accounts
        self._folders = {}
        self._messages = {}
        self._opened = {}
        self._removed = set()
        self._pending_open = None
        self._pending_search = None
        self._search_results = []
        if self._mailbox_key == SEARCH_KEY:
            self._mailbox_key = self._before_search[0]
            self._show_view(self._message_list)
        if self._mailbox_key != ALL_KEY and not any(
            account.email == self._mailbox_key[0] for account in accounts
        ):
            self._mailbox_key = ALL_KEY
        self._update_title()
        self._load_from_cache()
        for account in accounts:
            self._start_session(account)
        self._initial_load = True
        self._check_mail()
        for worker in self._workers.values():
            worker.collect_contacts()

    def _load_from_cache(self):
        """Pokazuje od razu to, co program już ma. Nowości dojdą w tle."""
        emails = [account.email for account in self._accounts]
        self._cache.keep_accounts(emails)
        for email in emails:
            folders = self._cache.folders(email)
            if folders:
                self._folders[email] = list(folders)
            for folder, messages in self._cache.messages(email).items():
                self._messages[(email, folder)] = messages
        self._show_mailbox_rows()
        self._show_message_rows()
        self._select_newest_message()

    def _start_session(self, account):
        password = get_password(account)
        if not password:
            self._say(_("Brak hasła do konta {name}").format(name=account.name))
            return
        worker = MailWorker(account, password, self, self._dispatch)
        worker.start()
        watcher = IdleWatcher(account, password, worker.refresh_inbox_silently)
        watcher.start()
        self._workers[account.email] = worker
        self._watchers[account.email] = watcher

    def _check_mail(self):
        target = self._target()
        emails = [target[0]] if target else list(self._workers)
        emails = [email for email in emails if email in self._workers]
        self._sync_pending = set(emails)
        self._sync_clean = True
        for email in emails:
            self._workers[email].refresh(self._folder_for(email))

    def _target(self):
        """Zwraca (adres, folder) wybranej skrzynki albo None dla Wszystkich skrzynek."""
        if self._mailbox_key in (ALL_KEY, SEARCH_KEY):
            return None
        email, folder = self._mailbox_key
        return email, folder or INBOX

    def _folder_for(self, email):
        target = self._target()
        return target[1] if target and target[0] == email else INBOX

    def _is_visible(self, email, folder):
        if self._mailbox_key == SEARCH_KEY:
            return False
        target = self._target()
        return folder == INBOX if target is None else target == (email, folder)

    def _visible_messages(self):
        """Wiadomości bieżącej skrzynki w kolejności wybranej w menu Widok."""
        messages = self._visible_newest_first()
        return messages if self._newest_first else messages[::-1]

    def _visible_newest_first(self):
        if self._mailbox_key == SEARCH_KEY:
            return self._search_results
        target = self._target()
        if target is not None:
            return self._messages.get(target, [])
        merged = [
            message
            for account in self._accounts
            for message in self._messages.get((account.email, INBOX), [])
        ]
        return sorted(merged, key=_newest_first, reverse=True)

    def _newest_visible_key(self):
        messages = self._visible_newest_first()
        return messages[0].key if messages else None

    def _account_for(self, email):
        return next(a for a in self._accounts if a.email == email)

    def _sender_accounts(self):
        return [a for a in self._accounts if a.email in self._workers]

    def _say(self, text):
        self.SetStatusText(text)
        speak(text)

    # Wyniki z wątków w tle

    def _dispatch(self, worker, handler, *args):
        wx.CallAfter(self._deliver, worker, handler, args)

    def _deliver(self, worker, handler, args):
        email = worker.account.email
        if self._workers.get(email) is worker:
            handler(email, *args)

    def on_folders(self, email, folders):
        self._folders[email] = folders
        self._cache.save_folders(email, folders)
        self.SetStatusText("")
        self._show_mailbox_rows()

    def on_contacts(self, email, contacts):
        self._cache.save_contacts(email, contacts)

    def on_action_failed(self, email, text):
        self._say(text)
        self._removed.clear()
        worker = self._workers.get(email)
        if worker is not None:
            worker.refresh(self._folder_for(email), silent=True)

    def on_messages(self, email, folder, messages, refreshed, silent=False):
        key = (email, folder)
        previous = self._messages.get(key)
        tagged = (replace(m, account=email, folder=folder) for m in messages)
        # Pobranie mogło wyruszyć, zanim serwer dostał polecenie usunięcia.
        messages = [m for m in tagged if m.key not in self._removed]
        visible = self._is_visible(email, folder)
        newest_key = self._newest_visible_key() if visible else None
        at_newest = (
            newest_key is None or self._message_list.selected_key() == newest_key
        )
        self._messages[key] = messages
        self._cache.save_messages(email, folder, messages)
        self.SetStatusText("")
        if visible:
            self._show_message_rows()
            if self._initial_load and at_newest:
                self._select_newest_message()
        if refreshed:
            newest = _newest_new_message(previous, messages)
            if newest is not None:
                self._play_new_mail()
                self._sync_clean = False
                # Przy starcie o zaznaczeniu decyduje najnowsza ze wszystkich kont.
                if visible and not self._initial_load:
                    self._go_to_new_message(newest)
                self._notify_new_message(newest)
            if not silent:
                self._finish_sync(email)

    def _notify_new_message(self, message):
        if self._notifications and not self._initial_load and self._in_background():
            notify(
                _("Nowa wiadomość od {sender}").format(sender=message.sender),
                message.subject,
            )

    def _in_background(self):
        # Pytamy aplikację, bo przy otwartym oknie pisania nieaktywna jest tylko ramka.
        return not self.IsShown() or not wx.GetApp().IsActive()

    def _select_newest_message(self):
        """Najnowsza wiadomość jest na górze albo na dole listy, zależnie od kolejności."""
        newest_key = self._newest_visible_key()
        if newest_key is not None:
            self._message_list.select_key(newest_key)

    def _finish_sync(self, email):
        """Jeden dźwięk za całe pobranie, także gdy kont jest kilka."""
        self._sync_pending.discard(email)
        if self._sync_pending:
            return
        self._initial_load = False
        if self._sync_clean and self.IsShown():
            play(SYNCED)

    def _go_to_new_message(self, message):
        # Nie przerywamy czytania wiadomości, pisania ani szukania.
        if (
            not self._message_list.IsShown()
            or self._composing
            or self._search_dialog is not None
        ):
            return
        self._message_list.select_key(message.key)
        if self.IsActive() and self.IsShown():
            speak(message_sentence(message, self._row_account_name(message)))

    def on_error(self, email, text):
        if not self.IsShown():
            # Schowany program nie mówi, np. gdy przy starcie Windows nie ma jeszcze sieci.
            self.SetStatusText(text)
        elif self._initial_load:
            # NVDA ucisza mowę, gdy czyta dopiero co otwarte okno.
            self.SetStatusText(text)
            wx.CallLater(STARTUP_SPEECH_DELAY_MS, speak, text)
        else:
            self._say(text)
        self._sync_clean = False
        self._finish_sync(email)

    def on_message_opened(self, email, folder, uid, content, raw):
        key = (email, folder, uid)
        self._remember_content(key, content)
        self._cache.save_body(key, raw)
        self._mark_seen(key)
        pending = self._pending_open
        if pending is not None and pending[0] == key:
            self._pending_open = None
            pending[1](content)

    def _remember_content(self, key, content):
        self._opened[key] = content
        if len(self._opened) > OPENED_CACHE_SIZE:
            del self._opened[next(iter(self._opened))]

    def on_open_failed(self, email, folder, uid):
        pending = self._pending_open
        if pending is not None and pending[0] == (email, folder, uid):
            self._pending_open = None
            self._say(_("Nie udało się otworzyć wiadomości"))

    def on_outgoing_done(self, _email, on_done, success, text):
        on_done(success, text)

    def on_search_done(self, email, search_id, results):
        search = self._pending_search
        if search is None or search.search_id != search_id:
            return
        search.waiting.discard(email)
        if results is None:
            search.failed.append(self._account_for(email).name)
        else:
            for folder, messages in results:
                search.messages += [
                    replace(m, account=email, folder=folder) for m in messages
                ]
        if not search.waiting:
            self._pending_search = None
            self._finish_search(search)

    # Widoki

    def _row_account_name(self, message):
        if self._mailbox_key not in (ALL_KEY, SEARCH_KEY):
            return None
        return self._account_for(message.account).name

    def _show_message_rows(self):
        self._message_list.set_rows(
            [
                (m.key, message_sentence(m, self._row_account_name(m)))
                for m in self._visible_messages()
            ],
            # Nowo otwarta lista zaczyna od najnowszej wiadomości.
            fallback=self._newest_visible_key(),
        )

    def _inbox_unread(self, email):
        return sum(f.unread for f in self._folders.get(email, []) if f.name == INBOX)

    def _show_mailbox_rows(self):
        total = sum(self._inbox_unread(a.email) for a in self._accounts)
        if self._tray is not None:
            self._tray.show_unread(total)
        rows = [(ALL_KEY, mailbox_sentence(_("Wszystkie skrzynki"), total))]
        for account in self._accounts:
            email = account.email
            rows.append(
                ((email, None), mailbox_sentence(account.name, self._inbox_unread(email)))
            )
            rows += [
                ((email, f.name), mailbox_sentence(f.label, f.unread, account.name))
                for f in self._folders.get(email, [])
            ]
        self._mailbox_view.set_rows(rows)

    def _message_lists(self, key):
        """Listy z tą wiadomością: jej folder i wyniki wyszukiwania."""
        email, folder, _uid = key
        lists = [self._messages.get((email, folder), []), self._search_results]
        return [items for items in lists if any(m.key == key for m in items)]

    def _store_message(self, message):
        for items in self._message_lists(message.key):
            items[[m.key for m in items].index(message.key)] = message
        self._cache.update_flags(message)

    def _mark_seen(self, key):
        lists = self._message_lists(key)
        if not lists:
            return
        message = next(m for m in lists[0] if m.key == key)
        if not message.seen:
            self._store_message(replace(message, seen=True))
            self._change_unread(message.account, message.folder, -1)
            self._show_message_rows()

    def _change_unread(self, email, folder, change):
        self._folders[email] = [
            replace(f, unread=max(0, f.unread + change)) if f.name == folder else f
            for f in self._folders.get(email, [])
        ]
        self._cache.save_folders(email, self._folders[email])
        self._show_mailbox_rows()

    def _update_title(self):
        self.SetTitle(f"{self._mailbox_label()} - {APP_NAME}")

    def _mailbox_label(self):
        if self._mailbox_key == ALL_KEY:
            return _("Wszystkie skrzynki")
        if self._mailbox_key == SEARCH_KEY:
            return _("Wyniki wyszukiwania")
        email, folder = self._mailbox_key
        name = self._account_for(email).name
        if folder is None:
            return name
        for candidate in self._folders.get(email, []):
            if candidate.name == folder:
                return f"{candidate.label}, {name}"
        return name

    def _show_view(self, shown):
        for view in self._views:
            view.Show(view is shown)
        self._panel.Layout()
        shown.focus()

    def _go_to_mailboxes(self):
        self._pending_open = None
        self._pending_search = None
        self._mailbox_view.select_key(self._mailbox_key)
        self._show_view(self._mailbox_view)

    def _open_selected_mailbox(self):
        key = self._mailbox_view.selected_key()
        if key is None:
            return
        self._pending_search = None
        if key != self._mailbox_key:
            self._mailbox_key = key
            self._message_list.set_rows([])
            self._show_message_rows()
            self._update_title()
            target = self._target()
            if target is not None and target[0] in self._workers:
                self._workers[target[0]].open_folder(target[1])
        self._show_view(self._message_list)

    def _open_selected_message(self):
        self._with_selected_content(self._show_message)

    def _with_selected_content(self, action):
        """Wywołuje action z treścią zaznaczonej wiadomości, w razie potrzeby po pobraniu."""
        message = self._selected_message()
        if message is None or message.account not in self._workers:
            return
        content = self._known_content(message)
        if content is not None:
            self._pending_open = None
            self._mark_read_on_server(message)
            action(content)
        else:
            self._pending_open = (message.key, action)
            self._workers[message.account].open_message(message.folder, message.uid)

    def _known_content(self, message):
        content = self._opened.get(message.key)
        if content is None:
            raw = self._cache.body(message.key)
            if raw is not None:
                content = parse_message(raw)
                self._remember_content(message.key, content)
        return content

    def _mark_read_on_server(self, message):
        """Otwarcie z pamięci nie dotyka serwera, więc stan trzeba przekazać osobno."""
        if message.seen:
            return
        self._mark_seen(message.key)
        self._workers[message.account].perform(
            lambda client: client.set_flag(message.folder, message.uid, "\\Seen", True),
            _("Nie udało się zmienić stanu wiadomości"),
        )

    def _show_message(self, content):
        self._pending_search = None
        self._message_view.show_content(content)
        self._show_view(self._message_view)

    def _open_neighbour(self, step):
        """Alt+strzałka: sąsiednia wiadomość, a NVDA czyta jej wiersz z listy."""
        messages = self._visible_messages()
        keys = [message.key for message in messages]
        current = self._message_list.selected_key()
        index = keys.index(current) + step if current in keys else -1
        if not 0 <= index < len(messages):
            self._say(_("Nie ma kolejnej wiadomości"))
            return
        self._message_list.select_key(keys[index])
        speak(message_sentence(messages[index], self._row_account_name(messages[index])))
        self._open_selected_message()

    def _back_to_list(self):
        self._pending_open = None
        self._show_view(self._message_list)

    # Wyszukiwanie

    def _open_search(self):
        if not self._workers:
            self._say(_("Najpierw dodaj konto"))
            return
        with SearchDialog(
            self, self._last_query, self._last_everywhere, self._start_search
        ) as dialog:
            self._search_dialog = dialog
            dialog.ShowModal()
            self._search_dialog = None
        # Zamknięcie okna Escape'em przerywa szukanie.
        self._pending_search = None
        if self._found_search is not None:
            found, parts = self._found_search
            self._found_search = None
            self._show_search_results(found, parts)

    def _start_search(self, query, everywhere):
        self._last_query = query
        self._last_everywhere = everywhere
        target = self._target()
        if self._mailbox_key == SEARCH_KEY:
            target = self._before_target()
        emails = [target[0]] if target and not everywhere else list(self._workers)
        self._last_search_id += 1
        self._pending_search = PendingSearch(self._last_search_id, set(emails))
        self._say(_("Wyszukiwanie"))
        for email in emails:
            if everywhere:
                folder = None
            else:
                folder = target[1] if target else INBOX
            self._workers[email].search(self._last_search_id, query, folder)

    def _before_target(self):
        key = self._before_search[0]
        return None if key == ALL_KEY else (key[0], key[1] or INBOX)

    def _finish_search(self, search):
        found = sorted(search.messages, key=_newest_first, reverse=True)
        found = found[:SEARCH_RESULT_LIMIT]
        parts = []
        if search.failed:
            names = ", ".join(search.failed)
            parts.append(_("Nie przeszukano: {names}").format(names=names))
        dialog = self._search_dialog
        if not found:
            parts.append(_("Nic nie znaleziono"))
            text = ". ".join(parts)
            if dialog is not None:
                dialog.show_message(text)
            self._say(text)
        elif dialog is not None:
            self._found_search = (found, parts)
            dialog.EndModal(wx.ID_OK)
        else:
            self._show_search_results(found, parts)

    def _show_search_results(self, found, parts):
        if self._mailbox_key != SEARCH_KEY:
            view = self._mailbox_view if self._mailbox_view.IsShown() else None
            selected = self._message_list.selected_key()
            self._before_search = (self._mailbox_key, selected, view)
        self._mailbox_key = SEARCH_KEY
        self._search_results = found
        self._update_title()
        self._show_message_rows()
        self._select_newest_message()
        self._show_view(self._message_list)
        parts.append(found_text(len(found)))
        parts.append(message_sentence(found[0], self._row_account_name(found[0])))
        self.SetStatusText(parts[-2])
        wx.CallLater(AFTER_FOCUS_SPEECH_DELAY_MS, speak, ". ".join(parts))

    def _leave_search(self):
        """Escape wraca tam, skąd weszło się do wyszukiwania."""
        mailbox, selected, view = self._before_search
        self._mailbox_key = mailbox
        self._search_results = []
        self._update_title()
        self._show_message_rows()
        self._message_list.select_key(selected)
        self._show_view(view or self._message_list)

    # Czynności na wiadomościach

    def _selected_message(self):
        key = self._message_list.selected_key()
        return next((m for m in self._visible_messages() if m.key == key), None)

    def _selected_with_worker(self):
        message = self._selected_message()
        if message is None or message.account not in self._workers:
            return None
        return message

    def _role_of(self, message):
        folders = self._folders.get(message.account, [])
        return next((f.role for f in folders if f.name == message.folder), None)

    def _move_to_trash(self):
        message = self._selected_with_worker()
        if message is None:
            return
        if self._role_of(message) == "trash":
            self._say(_("Wiadomość jest już w koszu"))
            return
        self._remove_message(
            message,
            lambda client: client.move(message.folder, message.uid, "trash"),
            _("Przeniesiono do kosza"),
            _("Nie udało się przenieść do kosza"),
            announce=False,
        )

    def _archive(self):
        message = self._selected_with_worker()
        if message is None:
            return
        if self._account_for(message.account).provider.archive_by_label:
            if message.folder != INBOX:
                self._say(_("Archiwizować można tylko z Odebranych"))
                return
            run = lambda client: client.remove_inbox_label(message.uid)
        elif self._role_of(message) == "archive":
            self._say(_("Wiadomość jest już w archiwum"))
            return
        else:
            run = lambda client: client.move(message.folder, message.uid, "archive")
        self._remove_message(
            message, run, _("Zarchiwizowano"), _("Nie udało się zarchiwizować")
        )

    def _choose_folder(self):
        message = self._selected_with_worker()
        if message is None:
            return
        folders = [
            f for f in self._folders.get(message.account, [])
            if f.name != message.folder
        ]
        if not folders:
            self._say(_("Nie ma innego folderu"))
            return
        with MoveDialog(self, folders) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            target = dialog.folder
        self._remove_message(
            message,
            lambda client: client.move_to_folder(
                message.folder, message.uid, target.name
            ),
            _("Przeniesiono do: {folder}").format(folder=target.label),
            _("Nie udało się przenieść wiadomości"),
        )
        if not message.seen:
            self._change_unread(message.account, target.name, 1)

    def _remove_message(self, message, run, status, failure, announce=True):
        """Usuwa wiadomość z listy od razu, a serwer dostaje polecenie w tle.

        Bez announce NVDA czyta tylko następną wiadomość, co nie męczy przy
        kasowaniu serii. Status padnie, gdy nie ma już czego czytać.
        """
        visible = self._visible_messages()
        index = visible.index(message)
        following = None
        if index + 1 < len(visible):
            following = visible[index + 1]
        elif index > 0:
            following = visible[index - 1]
        reading = self._message_view.IsShown()
        for items in self._message_lists(message.key):
            items[:] = [m for m in items if m.key != message.key]
        self._removed.add(message.key)
        self._opened.pop(message.key, None)
        self._cache.delete_message(message.key)
        if not message.seen:
            self._change_unread(message.account, message.folder, -1)
        self._show_message_rows()
        if following is not None:
            self._message_list.select_key(following.key)
        self._workers[message.account].perform(run, failure)
        if reading:
            # Powrót na listę czyta następną wiadomość, a komunikat przychodzi po nim.
            self._pending_open = None
            self._show_view(self._message_list)
            self.SetStatusText(status)
            if announce or following is None:
                wx.CallLater(AFTER_FOCUS_SPEECH_DELAY_MS, speak, status)
            return
        self.SetStatusText(status)
        if following is None:
            speak(status)
            return
        sentence = message_sentence(following, self._row_account_name(following))
        speak(f"{status}. {sentence}" if announce else sentence)

    def _toggle_read(self):
        message = self._selected_with_worker()
        if message is None:
            return
        seen = not message.seen
        self._store_message(replace(message, seen=seen))
        self._show_message_rows()
        self._change_unread(message.account, message.folder, -1 if seen else 1)
        self._workers[message.account].perform(
            lambda client: client.set_flag(message.folder, message.uid, "\\Seen", seen),
            _("Nie udało się zmienić stanu wiadomości"),
        )
        self._say(
            _("Oznaczono jako przeczytaną")
            if seen
            else _("Oznaczono jako nieprzeczytaną")
        )

    def _toggle_flag(self):
        message = self._selected_with_worker()
        if message is None:
            return
        flagged = not message.flagged
        self._store_message(replace(message, flagged=flagged))
        self._show_message_rows()
        self._workers[message.account].perform(
            lambda client: client.set_flag(
                message.folder, message.uid, "\\Flagged", flagged
            ),
            _("Nie udało się zmienić flagi"),
        )
        self._say(_("Oflagowano") if flagged else _("Zdjęto flagę"))

    def _build_context_menu(self):
        message = self._selected_message()
        items = (
            (_("&Otwórz\tEnter"), self._open_selected_message),
            (_("O&dpowiedz\tCtrl+R"), lambda: self._reply(False)),
            (_("Odpowiedz &wszystkim\tCtrl+Shift+R"), lambda: self._reply(True)),
            (_("&Przekaż dalej\tCtrl+L"), self._forward),
            None,
            (_("Przenieś do &kosza\tDelete"), self._move_to_trash),
            (_("&Archiwizuj\tCtrl+Shift+A"), self._archive),
            (_("Prz&enieś do folderu…\tCtrl+M"), self._choose_folder),
            (
                _("Oznacz jako &nieprzeczytaną\tCtrl+U")
                if message.seen
                else _("Oznacz jako p&rzeczytaną\tCtrl+U"),
                self._toggle_read,
            ),
            (
                _("&Zdejmij flagę\tCtrl+Shift+F")
                if message.flagged
                else _("O&flaguj\tCtrl+Shift+F"),
                self._toggle_flag,
            ),
            None,
            (_("&Nowa wiadomość\tCtrl+N"), self._new_message),
            (_("S&zukaj\tCtrl+F"), self._open_search),
            (_("&Sprawdź pocztę teraz\tF5"), self._check_mail),
        )
        menu = wx.Menu()
        for item in items:
            if item is None:
                menu.AppendSeparator()
                continue
            label, handler = item
            entry = menu.Append(wx.ID_ANY, label)
            menu.Bind(wx.EVT_MENU, lambda _event, run=handler: run(), entry)
        return menu

    def _on_context_menu(self, _event):
        if self._selected_message() is None:
            return
        menu = self._build_context_menu()
        self._message_list.list.PopupMenu(menu)
        menu.Destroy()

    # Pisanie

    def _compose(self, draft):
        accounts = self._sender_accounts()
        if not accounts:
            self._say(_("Najpierw dodaj konto"))
            return
        focused = wx.Window.FindFocus()
        self._composing = True
        self._pending_search = None
        with ComposeDialog(
            self, accounts, draft, self._workers, self._contacts()
        ) as dialog:
            dialog.ShowModal()
            result = dialog.result_text
            sent = dialog.sent_draft
        self._composing = False
        if sent is not None:
            self._cache.add_contacts(
                sent.sender, parse_contacts(sent.to) + parse_contacts(sent.cc)
            )
        if focused is not None:
            focused.SetFocus()
        self.SetStatusText(result)

    def _contacts(self):
        """Adresaci ze wszystkich kont, bez adresów samych kont."""
        own = {account.email.lower() for account in self._accounts}
        return [
            contact
            for contact in merge_contacts(self._cache.contacts())
            if contact.address not in own
        ]

    def _new_message(self):
        self._compose(Draft())

    def _compose_from_selected(self, build):
        """Odpowiedź i przekazanie idą z konta, na które przyszła wiadomość."""
        message = self._selected_with_worker()
        if message is None:
            return
        action = lambda content: self._compose(build(content, message.account))
        if self._message_view.IsShown():
            action(self._message_view.content)
        else:
            self._with_selected_content(action)

    def _reply(self, reply_all):
        self._compose_from_selected(
            lambda content, email: reply_draft(content, email, reply_all)
        )

    def _forward(self):
        self._compose_from_selected(forward_draft)

    # Linki

    def _move_to_link(self, step):
        link = self._message_view.move_to_link(step)
        if link is not None:
            speak(link.text)
        elif step > 0:
            self._say(_("Nie ma kolejnego linku"))
        else:
            self._say(_("Nie ma poprzedniego linku"))

    def _open_link(self):
        link = self._message_view.link_at_caret()
        if link is None:
            return False
        if not webbrowser.open(link.url):
            self._say(_("Nie udało się otworzyć linku"))
        return True

    def _read_link_address(self):
        """Mówi domenę, bo to ona pokazuje, dokąd link naprawdę prowadzi."""
        link = self._message_view.link_at_caret()
        if link is None:
            self._say(_("Kursor nie jest na linku"))
            return
        self.SetStatusText(link.url)
        speak(link_host(link.url) or link.url)

    # Załączniki

    def _open_attachment(self):
        attachment = self._message_view.selected_attachment()
        if attachment is None:
            return
        if not can_open(attachment):
            self._say(_("Tego typu pliku nie można otworzyć, można go zapisać"))
            return
        try:
            open_attachment(attachment)
        except OSError:
            self._say(_("Nie udało się otworzyć załącznika"))

    def _save_attachment(self):
        attachment = self._message_view.selected_attachment()
        if attachment is None:
            return
        with wx.FileDialog(
            self,
            _("Zapisz załącznik"),
            defaultDir=str(downloads_dir()),
            defaultFile=safe_filename(attachment.filename),
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            path = dialog.GetPath()
        try:
            with open(path, "wb") as file:
                file.write(attachment.data)
        except OSError:
            self._say(_("Nie udało się zapisać załącznika"))
        else:
            self._say(_("Zapisano"))

    def _save_all_attachments(self):
        content = self._message_view.content
        if content is None or not content.attachments:
            return
        with wx.DirDialog(
            self, _("Zapisz załączniki w folderze"), str(downloads_dir())
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            folder = dialog.GetPath()
        try:
            save_to_folder(content.attachments, folder)
        except OSError:
            self._say(_("Nie udało się zapisać załączników"))
        else:
            self._say(_("Zapisano"))

    # Zdarzenia

    def _on_key(self, event):
        if self._on_compose_key(event) or self._on_action_key(event):
            return
        if self._message_view.IsShown():
            handled = self._on_message_key(event)
        else:
            handled = self._on_list_key(event)
        if not handled:
            event.Skip()

    def _on_compose_key(self, event):
        if not event.ControlDown() or event.AltDown():
            return False
        key = event.GetKeyCode()
        shift = event.ShiftDown()
        if key == ord("N") and not shift:
            self._new_message()
        elif key == ord("F") and not shift and not self._message_view.IsShown():
            self._open_search()
        elif self._mailbox_view.IsShown():
            return False
        elif key == ord("R"):
            self._reply(reply_all=shift)
        elif key == ord("L") and not shift:
            self._forward()
        else:
            return False
        return True

    def _on_action_key(self, event):
        if self._mailbox_view.IsShown():
            return False
        key = event.GetKeyCode()
        control = event.ControlDown() and not event.AltDown()
        shift = event.ShiftDown()
        if key in (wx.WXK_DELETE, wx.WXK_NUMPAD_DELETE) and not (
            event.ControlDown() or event.AltDown() or shift
        ):
            self._move_to_trash()
        elif control and shift and key == ord("A"):
            self._archive()
        elif control and not shift and key == ord("M"):
            self._choose_folder()
        elif control and shift and key == ord("F"):
            self._toggle_flag()
        elif control and not shift and key == ord("U"):
            self._toggle_read()
        else:
            return False
        return True

    def _on_list_key(self, event):
        key = event.GetKeyCode()
        if key == wx.WXK_ESCAPE and self._message_list.IsShown():
            if self._mailbox_key == SEARCH_KEY:
                self._leave_search()
            else:
                self._go_to_mailboxes()
        elif key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            if self._mailbox_view.IsShown():
                self._open_selected_mailbox()
            else:
                self._open_selected_message()
        else:
            return False
        return True

    def _on_message_key(self, event):
        key = event.GetKeyCode()
        in_attachments = self._message_view.attachments_focused()
        if key == wx.WXK_ESCAPE:
            self._back_to_list()
        elif event.AltDown() and key == ord("Z"):
            self._message_view.focus_attachments()
        elif event.AltDown() and key == wx.WXK_DOWN:
            self._open_neighbour(1)
        elif event.AltDown() and key == wx.WXK_UP:
            self._open_neighbour(-1)
        elif event.AltDown() and key == ord("L"):
            self._move_to_link(-1 if event.ShiftDown() else 1)
        elif event.AltDown() and key == ord("A"):
            self._read_link_address()
        elif in_attachments and key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self._open_attachment()
        elif key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            return self._open_link()
        elif in_attachments and event.ControlDown() and key == ord("S"):
            if event.ShiftDown():
                self._save_all_attachments()
            else:
                self._save_attachment()
        else:
            return False
        return True

    def _on_close(self, event):
        if event.CanVeto() and self._hide_on_close and self._tray is not None:
            event.Veto()
            self.Hide()
            return
        self._update_timer.Stop()
        if self._tray is not None:
            self._tray.RemoveIcon()
            self._tray.Destroy()
            self._tray = None
        self._stop_sessions()
        self._cache.close()
        event.Skip()

    def _stop_sessions(self):
        for worker in self._workers.values():
            worker.stop()
        for watcher in self._watchers.values():
            watcher.stop()
        self._workers = {}
        self._watchers = {}
