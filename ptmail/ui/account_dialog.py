import threading

import wx

from ..accounts import PROVIDERS, Account
from ..credentials import get_password
from ..i18n import _
from ..imap_client import ImapAuthError, ImapError, check_login


class AccountDialog(wx.Dialog):
    """Dodawanie konta. Dane zatwierdza dopiero udane logowanie na serwerze."""

    def __init__(self, parent, account=None, taken_emails=()):
        super().__init__(parent, title=_("Konto pocztowe"))
        self.account = None
        self.password = None
        self._existing = account
        self._taken_emails = {email.casefold() for email in taken_emails}
        self._provider_keys = list(PROVIDERS)

        fields = wx.FlexGridSizer(cols=2, vgap=6, hgap=6)
        fields.AddGrowableCol(1)

        def add_field(label, create):
            # NVDA bierze nazwę pola z etykiety stworzonej tuż przed nim.
            fields.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            control = create()
            fields.Add(control, 1, wx.EXPAND)
            return control

        self._provider = add_field(
            _("Rodzaj konta:"),
            lambda: wx.Choice(
                self, choices=[PROVIDERS[key].label for key in self._provider_keys]
            ),
        )
        self._provider.SetSelection(0)
        self._name = add_field(_("Nazwa konta:"), lambda: wx.TextCtrl(self))
        self._display_name = add_field(
            _("Imię i nazwisko:"), lambda: wx.TextCtrl(self)
        )
        self._email = add_field(_("Adres e-mail:"), lambda: wx.TextCtrl(self))
        self._password = add_field(
            _("Hasło aplikacji:"), lambda: wx.TextCtrl(self, style=wx.TE_PASSWORD)
        )
        self._signature = add_field(
            _("Podpis:"),
            lambda: wx.TextCtrl(self, size=(-1, 70), style=wx.TE_MULTILINE),
        )
        self._status = add_field(
            _("Stan:"), lambda: wx.TextCtrl(self, style=wx.TE_READONLY)
        )
        if account is not None:
            self._provider.SetSelection(self._provider_keys.index(account.provider_key))
            self._name.SetValue(account.name)
            self._display_name.SetValue(account.display_name)
            self._email.SetValue(account.email)
            self._signature.SetValue(account.signature)

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
        self._provider.Bind(wx.EVT_CHOICE, lambda _event: self._show_password_label())
        self._show_password_label()
        self._provider.SetFocus()

    def _selected_provider(self):
        return PROVIDERS[self._provider_keys[self._provider.GetSelection()]]

    def _show_password_label(self):
        self._password.GetPrevSibling().SetLabel(
            _("Hasło aplikacji:") if self._selected_provider().app_password else _("Hasło:")
        )

    def _on_ok(self, _event):
        provider = self._selected_provider()
        provider_key = provider.key
        email = self._email.GetValue().strip()
        password = self._password.GetValue()
        if provider.app_password:
            # Google pokazuje hasła aplikacji ze spacjami, a serwer chce je bez nich.
            password = password.replace(" ", "")
        if not password and self._existing is not None:
            # Przy zmianie konta puste pole zostawia dotychczasowe hasło.
            password = get_password(self._existing) or ""
        if "@" not in email:
            self._show_error(_("Wpisz adres e-mail"), self._email)
            return
        if email.casefold() in self._taken_emails:
            self._show_error(_("To konto już jest dodane"), self._email)
            return
        if not password:
            self._show_error(
                _("Wpisz hasło aplikacji") if provider.app_password else _("Wpisz hasło"),
                self._password,
            )
            return
        name = self._name.GetValue().strip() or PROVIDERS[provider_key].label
        display_name = " ".join(self._display_name.GetValue().split())
        signature = self._signature.GetValue().strip()
        account = Account(name, email, provider_key, display_name, signature)
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
            error = self._login_error(account.provider)
        except ImapError:
            error = _("Brak połączenia z serwerem")
        wx.CallAfter(self._finish, account, password, error)

    @staticmethod
    def _login_error(provider):
        if not provider.app_password:
            text = _("Serwer odrzucił adres lub hasło")
        else:
            text = _("Serwer odrzucił adres lub hasło aplikacji")
        return f"{text}. {provider.login_hint}" if provider.login_hint else text

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
