from pathlib import Path

import wx

from ..i18n import _
from ..sounds import NEW_MAIL, SOUND_WILDCARD, play, play_file


class SoundDialog(wx.Dialog):
    """Wybór dźwięku nowej wiadomości: wbudowany albo własny plik MP3 lub WAV."""

    def __init__(self, parent, path):
        super().__init__(parent, title=_("Dźwięk nowej wiadomości"))
        self._path = path
        self._builtin = wx.RadioButton(self, label=_("&Wbudowany"), style=wx.RB_GROUP)
        self._custom = wx.RadioButton(self, label=_("Wł&asny plik"))
        (self._custom if path else self._builtin).SetValue(True)
        # NVDA bierze nazwę pola z etykiety stworzonej tuż przed nim.
        file_label = wx.StaticText(self, label=_("Plik:"))
        self._file = wx.TextCtrl(self, style=wx.TE_READONLY)
        self._show_file()
        choose = wx.Button(self, label=_("Wybierz &plik…"))
        listen = wx.Button(self, label=_("&Odtwórz"))
        save = wx.Button(self, wx.ID_OK, _("Zapisz"))
        save.SetDefault()

        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(file_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        row.Add(self._file, 1)
        actions = wx.BoxSizer(wx.HORIZONTAL)
        actions.Add(choose, 0, wx.RIGHT, 6)
        actions.Add(listen)
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        buttons.Add(save, 0, wx.RIGHT, 6)
        buttons.Add(wx.Button(self, wx.ID_CANCEL, _("Anuluj")))
        sizer = wx.BoxSizer(wx.VERTICAL)
        for item in (self._builtin, self._custom, row, actions, buttons):
            sizer.Add(item, 0, wx.EXPAND | wx.ALL, 8)
        self.SetSizerAndFit(sizer)
        self.SetMinSize((420, -1))
        self.Fit()

        choose.Bind(wx.EVT_BUTTON, lambda _event: self._choose_file())
        listen.Bind(wx.EVT_BUTTON, lambda _event: self._listen())
        save.Bind(wx.EVT_BUTTON, self._on_save)
        (self._custom if path else self._builtin).SetFocus()

    @property
    def sound_path(self):
        """Wybrany plik albo None, gdy zostaje dźwięk wbudowany."""
        return self._path if self._custom.GetValue() else None

    def _show_file(self):
        self._file.SetValue(Path(self._path).name if self._path else _("nie wybrano"))

    def _choose_file(self):
        with wx.FileDialog(
            self,
            _("Wybierz dźwięk"),
            defaultDir=str(Path(self._path).parent) if self._path else "",
            wildcard=_("Dźwięki (MP3, WAV)") + f"|{SOUND_WILDCARD}",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            path = dialog.GetPath()
        self._path = path
        self._custom.SetValue(True)
        self._show_file()
        self._custom.SetFocus()
        self._listen()

    def _listen(self):
        if self.sound_path is None:
            play(NEW_MAIL)
        elif not play_file(self.sound_path):
            self._file.SetValue(_("Nie udało się odtworzyć pliku"))
            self._file.SetFocus()

    def _on_save(self, _event):
        if self._custom.GetValue() and not self._path:
            # Bez pliku nie ma czego zapisać, więc od razu otwieramy wybór.
            self._choose_file()
            return
        self.EndModal(wx.ID_OK)
