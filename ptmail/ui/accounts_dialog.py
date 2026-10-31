import wx

from ..config import save_accounts
from ..credentials import delete_password, set_password
from ..i18n import _
from .account_dialog import AccountDialog


class AccountsDialog(wx.Dialog):
    """Lista kont z dodawaniem, zmianą i usuwaniem. Zmiany zapisują się od razu."""

    def __init__(self, parent, accounts):
        super().__init__(parent, title=_("Konta"), size=(460, 320))
        self.accounts = list(accounts)
        self.changed = False

        label = wx.StaticText(self, label=_("Konta:"))
        self._list = wx.ListBox(self, style=wx.LB_SINGLE)
        add = wx.Button(self, label=_("&Dodaj…"))
        self._edit = wx.Button(self, label=_("&Zmień…"))
        self._remove = wx.Button(self, label=_("&Usuń"))
        close = wx.Button(self, wx.ID_CLOSE, _("Zamknij"))
        self.SetEscapeId(wx.ID_CLOSE)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        for button in (add, self._edit, self._remove, close):
            buttons.Add(button, 0, wx.RIGHT, 6)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(label, 0, wx.ALL, 8)
        sizer.Add(self._list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        sizer.Add(buttons, 0, wx.ALL, 8)
        self.SetSizer(sizer)

        add.Bind(wx.EVT_BUTTON, lambda _event: self._add())
        self._edit.Bind(wx.EVT_BUTTON, lambda _event: self._change())
        self._remove.Bind(wx.EVT_BUTTON, lambda _event: self._delete())
        self._show_accounts(0)
        self._list.SetFocus()

    def _show_accounts(self, selection):
        self._list.Set(
            [f"{a.name}, {a.email}, {a.provider.label}" for a in self.accounts]
        )
        has_accounts = bool(self.accounts)
        if has_accounts:
            self._list.SetSelection(min(selection, len(self.accounts) - 1))
        self._edit.Enable(has_accounts)
        self._remove.Enable(has_accounts)

    def _emails(self, excluded=None):
        return [a.email for a in self.accounts if a is not excluded]

    def _save(self, selection):
        save_accounts(self.accounts)
        self.changed = True
        self._show_accounts(selection)

    def _add(self):
        with AccountDialog(self, taken_emails=self._emails()) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            account, password = dialog.account, dialog.password
        set_password(account, password)
        self.accounts.append(account)
        self._save(len(self.accounts) - 1)

    def _change(self):
        index = self._list.GetSelection()
        if index == wx.NOT_FOUND:
            return
        old = self.accounts[index]
        with AccountDialog(self, old, self._emails(old)) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            account, password = dialog.account, dialog.password
        if account.email != old.email:
            delete_password(old)
        set_password(account, password)
        self.accounts[index] = account
        self._save(index)

    def _delete(self):
        index = self._list.GetSelection()
        if index == wx.NOT_FOUND:
            return
        account = self.accounts[index]
        with wx.MessageDialog(
            self,
            _("Usunąć konto {name} z PT Mail? Poczta na serwerze zostanie.").format(
                name=account.name
            ),
            _("Konta"),
            wx.YES_NO | wx.NO_DEFAULT,
        ) as dialog:
            dialog.SetYesNoLabels(_("Usuń"), _("Zostaw"))
            if dialog.ShowModal() != wx.ID_YES:
                return
        delete_password(account)
        del self.accounts[index]
        self._save(index)
