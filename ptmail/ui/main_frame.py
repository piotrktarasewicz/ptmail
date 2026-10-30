import wx

from .. import APP_NAME
from ..config import load_account, save_account
from ..credentials import get_password, set_password
from ..formatting import mailbox_sentence, message_sentence
from ..i18n import _
from ..mail_worker import INBOX, MailWorker
from .account_dialog import AccountDialog
from .list_view import ListView

ALL_KEY = "all"
ACCOUNT_KEY = "account"


class MainFrame(wx.Frame):
    """Okno główne. Zawsze widać w nim tylko jeden widok: listę albo Skrzynki."""

    def __init__(self):
        super().__init__(None, title=APP_NAME, size=(800, 600))
        self._account = None
        self._worker = None
        self._folders = []
        self._messages = {}
        self._mailbox_key = ALL_KEY

        self._build_menu()
        self.CreateStatusBar()
        panel = wx.Panel(self)
        self._message_view = ListView(panel, _("Wiadomości"))
        self._mailbox_view = ListView(panel, _("Skrzynki"))
        self._mailbox_view.Hide()
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self._message_view, 1, wx.EXPAND)
        sizer.Add(self._mailbox_view, 1, wx.EXPAND)
        panel.SetSizer(sizer)
        self._panel = panel

        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self._update_title()
        self._show_mailboxes_rows()
        self._message_view.list.SetFocus()
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
        self._show_mailboxes_rows()
        self._worker = MailWorker(account, password, self, self._dispatch)
        self._worker.start()
        self._check_mail()

    def _check_mail(self):
        if self._worker is not None:
            self._worker.refresh(self._current_folder())

    def _current_folder(self):
        if self._mailbox_key in (ALL_KEY, ACCOUNT_KEY):
            return INBOX
        return self._mailbox_key

    # Wyniki z wątku w tle

    def _dispatch(self, worker, handler, *args):
        wx.CallAfter(self._deliver, worker, handler, args)

    def _deliver(self, worker, handler, args):
        if worker is self._worker:
            handler(*args)

    def on_folders(self, folders):
        self._folders = folders
        self.SetStatusText("")
        self._show_mailboxes_rows()

    def on_messages(self, folder, messages):
        self._messages[folder] = messages
        self.SetStatusText("")
        if folder == self._current_folder():
            self._show_message_rows()

    def on_error(self, text):
        self.SetStatusText(text)

    # Widoki

    def _show_message_rows(self):
        account_name = self._account.name if self._mailbox_key == ALL_KEY else None
        messages = self._messages.get(self._current_folder(), [])
        self._message_view.set_rows(
            [(m.uid, message_sentence(m, account_name)) for m in messages]
        )

    def _show_mailboxes_rows(self):
        inbox_unread = sum(f.unread for f in self._folders if f.name == INBOX)
        rows = [(ALL_KEY, mailbox_sentence(_("Wszystkie skrzynki"), inbox_unread))]
        if self._account is not None:
            rows.append(
                (ACCOUNT_KEY, mailbox_sentence(self._account.name, inbox_unread))
            )
        rows += [(f.name, mailbox_sentence(f.label, f.unread)) for f in self._folders]
        self._mailbox_view.set_rows(rows)
        self._mailbox_view.select_key(self._mailbox_key)

    def _update_title(self):
        label = self._mailbox_label()
        self.SetTitle(f"{label} - {APP_NAME}")

    def _mailbox_label(self):
        if self._mailbox_key == ACCOUNT_KEY and self._account is not None:
            return self._account.name
        for folder in self._folders:
            if folder.name == self._mailbox_key:
                return folder.label
        return _("Wszystkie skrzynki")

    def _show_view(self, shown, hidden):
        hidden.Hide()
        shown.Show()
        self._panel.Layout()
        shown.list.SetFocus()

    def _go_to_mailboxes(self):
        self._mailbox_view.select_key(self._mailbox_key)
        self._show_view(self._mailbox_view, self._message_view)

    def _open_selected_mailbox(self):
        key = self._mailbox_view.selected_key()
        if key is None:
            return
        if key != self._mailbox_key:
            self._mailbox_key = key
            self._message_view.set_rows([])
            self._show_message_rows()
            self._update_title()
            if self._worker is not None:
                self._worker.open_folder(self._current_folder())
        self._show_view(self._message_view, self._mailbox_view)

    # Zdarzenia

    def _on_key(self, event):
        key = event.GetKeyCode()
        if key == wx.WXK_ESCAPE and self._message_view.IsShown():
            self._go_to_mailboxes()
        elif key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) and self._mailbox_view.IsShown():
            self._open_selected_mailbox()
        else:
            event.Skip()

    def _on_close(self, event):
        self._stop_worker()
        event.Skip()

    def _stop_worker(self):
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.stop()
