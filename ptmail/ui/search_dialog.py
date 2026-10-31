import wx

from ..i18n import _


class SearchDialog(wx.Dialog):
    """Okno wyszukiwania. Zostaje otwarte do końca szukania, a Escape je przerywa."""

    def __init__(self, parent, query, everywhere, on_search):
        super().__init__(parent, title=_("Szukaj"))
        self._on_search = on_search
        fields = wx.FlexGridSizer(cols=2, vgap=6, hgap=6)
        fields.AddGrowableCol(1)

        def add_field(label, create):
            # NVDA bierze nazwę pola z etykiety stworzonej tuż przed nim.
            fields.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            control = create()
            fields.Add(control, 1, wx.EXPAND)
            return control

        self._query = add_field(_("Szukaj:"), lambda: wx.TextCtrl(self, value=query))
        self._scope = add_field(
            _("Gdzie:"),
            lambda: wx.Choice(
                self,
                choices=[_("W bieżącej skrzynce"), _("We wszystkich skrzynkach")],
            ),
        )
        self._scope.SetSelection(1 if everywhere else 0)
        self._search = wx.Button(self, label=_("Szukaj"))
        self._search.SetDefault()
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        buttons.Add(self._search, 0, wx.RIGHT, 6)
        buttons.Add(wx.Button(self, wx.ID_CANCEL, _("Anuluj")))
        self._status = wx.StaticText(self)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(fields, 0, wx.EXPAND | wx.ALL, 10)
        sizer.Add(buttons, 0, wx.ALL, 10)
        sizer.Add(self._status, 0, wx.EXPAND | wx.ALL, 10)
        self.SetSizerAndFit(sizer)
        self.SetMinSize((420, -1))
        self.Fit()
        self._search.Bind(wx.EVT_BUTTON, lambda _event: self.start())
        self._query.SetFocus()
        self._query.SelectAll()

    @property
    def query(self):
        return self._query.GetValue().strip()

    @property
    def everywhere(self):
        return self._scope.GetSelection() == 1

    def start(self):
        if not self.query:
            self._status.SetLabel(_("Wpisz szukany tekst"))
            return
        self._status.SetLabel(_("Wyszukiwanie"))
        # Wyłączony przycisk gubi fokus, więc zawsze zostaje on w polu tekstowym.
        self._query.SetFocus()
        self._search.Disable()
        self._on_search(self.query, self.everywhere)

    def show_message(self, text):
        """Szukanie skończyło się bez wyników: można od razu poprawić zapytanie."""
        self._search.Enable()
        self._status.SetLabel(text)
        self._query.SetFocus()
        self._query.SelectAll()
