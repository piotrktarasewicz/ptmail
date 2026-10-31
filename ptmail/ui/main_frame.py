import webbrowser
from dataclasses import dataclass, field, replace

import wx

from .. import APP_NAME
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
from ..config import load_accounts, save_accounts
from ..credentials import get_password, set_password
from ..formatting import found_text, mailbox_sentence, message_sentence
from ..i18n import _
from ..idle_watcher import IdleWatcher
from ..mail_worker import INBOX, MailWorker
from ..message_parser import link_host, parse_message
from ..sounds import NEW_MAIL, SYNCED, play
from ..speech import speak
from .account_dialog import AccountDialog
from .accounts_dialog import AccountsDialog
from .compose_dialog import ComposeDialog
from .list_view import ListView
from .message_view import MessageView
from .search_dialog import SearchDialog

ALL_KEY = "all"
SEARCH_KEY = "search"
OPENED_CACHE_SIZE = 30
SEARCH_RESULT_LIMIT = 200
AFTER_FOCUS_SPEECH_DELAY_MS = 300


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
        menu.AppendSeparator()
        close = menu.Append(wx.ID_EXIT, _("&Zakończ"))
        bar = wx.MenuBar()
        bar.Append(menu, _("&Plik"))
        self.SetMenuBar(bar)
        self.Bind(wx.EVT_MENU, lambda _event: self._manage_accounts(), accounts)
        self.Bind(wx.EVT_MENU, lambda _event: self._check_mail(), check)
        self.Bind(wx.EVT_MENU, lambda _event: self._open_search(), search)
        self.Bind(wx.EVT_MENU, lambda _event: self.Close(), close)

    def _start(self):
        clear_temp()
        self._cache = open_cache()
        accounts = load_accounts()
        if accounts:
            self._connect(accounts)
        else:
            self._add_first_account()

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
        self._select_top_message()

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
        rows = self._visible_messages() if visible else []
        at_top = not rows or self._message_list.selected_key() == rows[0].key
        self._messages[key] = messages
        self._cache.save_messages(email, folder, messages)
        self.SetStatusText("")
        if visible:
            self._show_message_rows()
            if self._initial_load and at_top:
                self._select_top_message()
        if refreshed:
            newest = _newest_new_message(previous, messages)
            if newest is not None:
                play(NEW_MAIL)
                self._sync_clean = False
                # Przy starcie o zaznaczeniu decyduje najnowsza ze wszystkich kont.
                if visible and not self._initial_load:
                    self._go_to_new_message(newest)
            if not silent:
                self._finish_sync(email)

    def _select_top_message(self):
        rows = self._visible_messages()
        if rows:
            self._message_list.select_key(rows[0].key)

    def _finish_sync(self, email):
        """Jeden dźwięk za całe pobranie, także gdy kont jest kilka."""
        self._sync_pending.discard(email)
        if self._sync_pending:
            return
        self._initial_load = False
        if self._sync_clean:
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
        if self.IsActive():
            speak(message_sentence(message, self._row_account_name(message)))

    def on_error(self, email, text):
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
            ]
        )

    def _inbox_unread(self, email):
        return sum(f.unread for f in self._folders.get(email, []) if f.name == INBOX)

    def _show_mailbox_rows(self):
        total = sum(self._inbox_unread(a.email) for a in self._accounts)
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
        self._select_top_message()
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
        with ComposeDialog(self, accounts, draft, self._workers) as dialog:
            dialog.ShowModal()
            result = dialog.result_text
        self._composing = False
        if focused is not None:
            focused.SetFocus()
        self.SetStatusText(result)

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
