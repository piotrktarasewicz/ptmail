import threading

import wx

from ..accounts import PROVIDERS, Account
from ..i18n import _
from ..imap_client import ImapAuthError, ImapError, check_login


class AccountDialog(wx.Dialog):
    """Dodawanie konta. Dane zatwierdza dopiero udane logowanie na serwerze."""

    def __init__(self, parent, account=None):
        super().__init__(parent, title=_("Konto pocztowe"))
        self.account = None
        self.password = None
        self._provider_keys = list(PROVIDERS)

        self._provider = wx.Choice(
            self, choices=[PROVIDERS[key].label for key in self._provider_keys]
        )
        self._provider.SetSelection(0)
        self._name = wx.TextCtrl(self)
        self._email = wx.TextCtrl(self)
        self._password = wx.TextCtrl(self, style=wx.TE_PASSWORD)
        self._status = wx.TextCtrl(self, style=wx.TE_READONLY)
        if account is not None:
            self._provider.SetSelection(self._provider_keys.index(account.provider_key))
            self._name.SetValue(account.name)
            self._email.SetValue(account.email)

        fields = wx.FlexGridSizer(cols=2, vgap=6, hgap=6)
        fields.AddGrowableCol(1)
        for label, control in (
            (_("Rodzaj konta:"), self._provider),
            (_("Nazwa konta:"), self._name),
            (_("Adres e-mail:"), self._email),
            (_("Hasło aplikacji:"), self._password),
            (_("Stan:"), self._status),
        ):
            fields.Add(
                wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL
            )
            fields.Add(control, 1, wx.EXPAND)

        self._ok = wx.Button(self, wx.ID_OK, _("Zapisz"))
        self._ok.SetDefault()
        buttons = wx.StdDialogButtonSizer()
        buttons.AddButton(self._ok)
        buttons.AddButton(wx.Button(self, wx.ID_CANCEL, _("Anuluj")))
        buttons.Realize()

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(fields, 1, wx.EXPAND | wx.ALL, 10)
        sizer.Add(buttons, 0, wx.EXPAND | wx.ALL, 10)
        self.SetSizerAndFit(sizer)
        self.SetMinSize((420, -1))
        self.Fit()
        self._ok.Bind(wx.EVT_BUTTON, self._on_ok)
        self._provider.SetFocus()

    def _on_ok(self, _event):
        provider_key = self._provider_keys[self._provider.GetSelection()]
        email = self._email.GetValue().strip()
        # Google pokazuje hasła aplikacji ze spacjami, a serwer chce je bez nich.
        password = self._password.GetValue().replace(" ", "")
        if "@" not in email:
            self._show_error(_("Wpisz adres e-mail"), self._email)
            return
        if not password:
            self._show_error(_("Wpisz hasło aplikacji"), self._password)
            return
        name = self._name.GetValue().strip() or PROVIDERS[provider_key].label
        account = Account(name, email, provider_key)
        self._ok.Disable()
        self._status.SetValue(_("Sprawdzam połączenie"))
        threading.Thread(
            target=self._check, args=(account, password), daemon=True
        ).start()

    def _check(self, account, password):
        try:
            check_login(account, password)
            error = None
        except ImapAuthError:
            error = _("Serwer odrzucił adres lub hasło aplikacji")
        except ImapError:
            error = _("Brak połączenia z serwerem")
        wx.CallAfter(self._finish, account, password, error)

    def _finish(self, account, password, error):
        if not self or not self.IsModal():
            return
        self._ok.Enable()
        if error is not None:
            self._show_error(error, self._status)
            return
        self.account = account
        self.password = password
        self.EndModal(wx.ID_OK)

    def _show_error(self, text, control):
        # Fokus na polu sprawia, że NVDA odczytuje komunikat bez dodatkowego okna.
        self._status.SetValue(text)
        control.SetFocus()
