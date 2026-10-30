import webbrowser
from dataclasses import replace

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
from ..compose import Draft, forward_draft, reply_draft
from ..config import load_account, save_account
from ..credentials import get_password, set_password
from ..formatting import mailbox_sentence, message_sentence
from ..i18n import _
from ..idle_watcher import IdleWatcher
from ..mail_worker import INBOX, MailWorker
from ..message_parser import link_host
from ..sounds import NEW_MAIL, SYNCED, play
from ..speech import speak
from .account_dialog import AccountDialog
from .compose_dialog import ComposeDialog
from .list_view import ListView
from .message_view import MessageView

ALL_KEY = "all"
ACCOUNT_KEY = "account"
OPENED_CACHE_SIZE = 30


def _newest_new_message(previous, messages):
    """Zwraca najnowszą wiadomość spoza poprzedniej listy. Lista jest od najnowszej."""
    if previous is None:
        return None
    highest = max((message.uid for message in previous), default=0)
    return next((m for m in messages if m.uid > highest), None)


class MainFrame(wx.Frame):
    """Okno główne. Zawsze widać w nim tylko jeden widok naraz."""

    def __init__(self):
        super().__init__(None, title=APP_NAME, size=(800, 600))
        self._account = None
        self._worker = None
        self._watcher = None
        self._folders = []
        self._messages = {}
        self._opened = {}
        self._pending_open = None
        self._mailbox_key = ALL_KEY
        self._composing = False

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
        self._update_title()
        self._show_mailbox_rows()
        self._show_view(self._message_list)
        wx.CallAfter(self._start)

    def _build_menu(self):
        menu = wx.Menu()
        account = menu.Append(wx.ID_ANY, _("&Konto…"))
        check = menu.Append(wx.ID_ANY, _("&Sprawdź pocztę teraz\tF5"))
        menu.AppendSeparator()
        close = menu.Append(wx.ID_EXIT, _("&Zakończ"))
        bar = wx.MenuBar()
        bar.Append(menu, _("&Plik"))
        self.SetMenuBar(bar)
        self.Bind(wx.EVT_MENU, lambda _event: self._edit_account(), account)
        self.Bind(wx.EVT_MENU, lambda _event: self._check_mail(), check)
        self.Bind(wx.EVT_MENU, lambda _event: self.Close(), close)

    def _start(self):
        clear_temp()
        account = load_account()
        password = get_password(account) if account else None
        if account and password:
            self._connect(account, password)
        else:
            self._edit_account()

    def _edit_account(self):
        with AccountDialog(self, self._account) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                save_account(dialog.account)
                set_password(dialog.account, dialog.password)
                self._connect(dialog.account, dialog.password)

    def _connect(self, account, password):
        self._stop_worker()
        self._account = account
        self._folders = []
        self._messages = {}
        self._opened = {}
        self._pending_open = None
        self._show_mailbox_rows()
        self._worker = MailWorker(account, password, self, self._dispatch)
        self._worker.start()
        self._watcher = IdleWatcher(
            account, password, self._worker.refresh_inbox_silently
        )
        self._watcher.start()
        self._check_mail()

    def _check_mail(self):
        if self._worker is not None:
            self._worker.refresh(self._current_folder())

    def _current_folder(self):
        if self._mailbox_key in (ALL_KEY, ACCOUNT_KEY):
            return INBOX
        return self._mailbox_key

    def _say(self, text):
        self.SetStatusText(text)
        speak(text)

    # Wyniki z wątku w tle

    def _dispatch(self, worker, handler, *args):
        wx.CallAfter(self._deliver, worker, handler, args)

    def _deliver(self, worker, handler, args):
        if worker is self._worker:
            handler(*args)

    def on_folders(self, folders):
        self._folders = folders
        self.SetStatusText("")
        self._show_mailbox_rows()

    def on_messages(self, folder, messages, refreshed, silent=False):
        previous = self._messages.get(folder)
        self._messages[folder] = messages
        self.SetStatusText("")
        current = folder == self._current_folder()
        if current:
            self._show_message_rows()
        if refreshed:
            newest = _newest_new_message(previous, messages)
            if newest is not None:
                play(NEW_MAIL)
                if current:
                    self._go_to_new_message(newest)
            elif not silent:
                play(SYNCED)

    def _go_to_new_message(self, message):
        # Nie przerywamy czytania wiadomości ani pisania.
        if not self._message_list.IsShown() or self._composing:
            return
        self._message_list.select_key(message.uid)
        if self.IsActive():
            speak(message_sentence(message, self._row_account_name()))

    def on_error(self, text):
        self._say(text)

    def on_message_opened(self, folder, uid, content):
        self._opened[(folder, uid)] = content
        if len(self._opened) > OPENED_CACHE_SIZE:
            del self._opened[next(iter(self._opened))]
        self._mark_seen(folder, uid)
        pending = self._pending_open
        if pending is not None and pending[:2] == (folder, uid):
            self._pending_open = None
            pending[2](content)

    def on_open_failed(self, folder, uid):
        pending = self._pending_open
        if pending is not None and pending[:2] == (folder, uid):
            self._pending_open = None
            self._say(_("Nie udało się otworzyć wiadomości"))

    def on_outgoing_done(self, on_done, success, text):
        on_done(success, text)

    # Widoki

    def _row_account_name(self):
        return self._account.name if self._mailbox_key == ALL_KEY else None

    def _show_message_rows(self):
        account_name = self._row_account_name()
        messages = self._messages.get(self._current_folder(), [])
        self._message_list.set_rows(
            [(m.uid, message_sentence(m, account_name)) for m in messages]
        )

    def _show_mailbox_rows(self):
        inbox_unread = sum(f.unread for f in self._folders if f.name == INBOX)
        rows = [(ALL_KEY, mailbox_sentence(_("Wszystkie skrzynki"), inbox_unread))]
        if self._account is not None:
            rows.append(
                (ACCOUNT_KEY, mailbox_sentence(self._account.name, inbox_unread))
            )
        rows += [(f.name, mailbox_sentence(f.label, f.unread)) for f in self._folders]
        self._mailbox_view.set_rows(rows)

    def _mark_seen(self, folder, uid):
        messages = self._messages.get(folder, [])
        for index, message in enumerate(messages):
            if message.uid == uid and not message.seen:
                messages[index] = replace(message, seen=True)
                self._folders = [
                    replace(f, unread=max(0, f.unread - 1)) if f.name == folder else f
                    for f in self._folders
                ]
                self._show_mailbox_rows()
                if folder == self._current_folder():
                    self._show_message_rows()
                return

    def _update_title(self):
        self.SetTitle(f"{self._mailbox_label()} - {APP_NAME}")

    def _mailbox_label(self):
        if self._mailbox_key == ACCOUNT_KEY and self._account is not None:
            return self._account.name
        for folder in self._folders:
            if folder.name == self._mailbox_key:
                return folder.label
        return _("Wszystkie skrzynki")

    def _show_view(self, shown):
        for view in self._views:
            view.Show(view is shown)
        self._panel.Layout()
        shown.focus()

    def _go_to_mailboxes(self):
        self._pending_open = None
        self._mailbox_view.select_key(self._mailbox_key)
        self._show_view(self._mailbox_view)

    def _open_selected_mailbox(self):
        key = self._mailbox_view.selected_key()
        if key is None:
            return
        if key != self._mailbox_key:
            self._mailbox_key = key
            self._message_list.set_rows([])
            self._show_message_rows()
            self._update_title()
            if self._worker is not None:
                self._worker.open_folder(self._current_folder())
        self._show_view(self._message_list)

    def _open_selected_message(self):
        self._with_selected_content(self._show_message)

    def _with_selected_content(self, action):
        """Wywołuje action z treścią zaznaczonej wiadomości, w razie potrzeby po pobraniu."""
        uid = self._message_list.selected_key()
        if uid is None or self._worker is None:
            return
        folder = self._current_folder()
        content = self._opened.get((folder, uid))
        if content is not None:
            self._pending_open = None
            action(content)
        else:
            self._pending_open = (folder, uid, action)
            self._worker.open_message(folder, uid)

    def _show_message(self, content):
        self._message_view.show_content(content)
        self._show_view(self._message_view)

    def _open_neighbour(self, step):
        """Alt+strzałka: sąsiednia wiadomość, a NVDA czyta jej wiersz z listy."""
        messages = self._messages.get(self._current_folder(), [])
        uids = [message.uid for message in messages]
        current = self._message_list.selected_key()
        index = uids.index(current) + step if current in uids else -1
        if not 0 <= index < len(messages):
            self._say(_("Nie ma kolejnej wiadomości"))
            return
        self._message_list.select_key(uids[index])
        speak(message_sentence(messages[index]))
        self._open_selected_message()

    def _back_to_list(self):
        self._pending_open = None
        self._show_view(self._message_list)

    # Pisanie

    def _compose(self, draft):
        if self._worker is None:
            self._say(_("Najpierw dodaj konto"))
            return
        focused = wx.Window.FindFocus()
        self._composing = True
        with ComposeDialog(self, self._account, draft, self._worker) as dialog:
            dialog.ShowModal()
            result = dialog.result_text
        self._composing = False
        if focused is not None:
            focused.SetFocus()
        self.SetStatusText(result)

    def _compose_from_selected(self, build):
        action = lambda content: self._compose(build(content))
        if self._message_view.IsShown():
            action(self._message_view.content)
        else:
            self._with_selected_content(action)

    def _reply(self, reply_all):
        self._compose_from_selected(
            lambda content: reply_draft(content, self._account.email, reply_all)
        )

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
        if self._on_compose_key(event):
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
            self._compose(Draft())
        elif self._mailbox_view.IsShown():
            return False
        elif key == ord("R"):
            self._reply(reply_all=shift)
        elif key == ord("L") and not shift:
            self._compose_from_selected(forward_draft)
        else:
            return False
        return True

    def _on_list_key(self, event):
        key = event.GetKeyCode()
        if key == wx.WXK_ESCAPE and self._message_list.IsShown():
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
        self._stop_worker()
        event.Skip()

    def _stop_worker(self):
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.stop()
        watcher, self._watcher = self._watcher, None
        if watcher is not None:
            watcher.stop()
