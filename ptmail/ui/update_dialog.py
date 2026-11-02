import wx

from ..i18n import _
from ..speech import speak

SPOKEN_STEP_PERCENT = 25


class UpdateDialog(wx.Dialog):
    """Postęp pobierania aktualizacji. Fokus stoi na Anuluj, a NVDA dostaje pasek i procenty."""

    def __init__(self, parent, on_cancel):
        super().__init__(parent, title=_("Aktualizacja PT Mail"), size=(380, 170))
        self.path = None
        self.failed = False
        self.was_cancelled = False
        self._on_cancel = on_cancel
        self._last_spoken = 0
        self._status = wx.StaticText(self, label=_("Pobieranie aktualizacji"))
        self._gauge = wx.Gauge(self, range=100)
        self._cancel = wx.Button(self, wx.ID_CANCEL, _("Anuluj"))
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self._status, 0, wx.ALL, 8)
        sizer.Add(self._gauge, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        sizer.Add(self._cancel, 0, wx.ALL, 8)
        self.SetSizer(sizer)
        self.Bind(wx.EVT_CLOSE, lambda _event: self.cancel())
        self._cancel.Bind(wx.EVT_BUTTON, lambda _event: self.cancel())
        self._cancel.SetFocus()

    def show_progress(self, percent):
        if percent is None:
            self._gauge.Pulse()
            return
        self._gauge.SetValue(percent)
        self._status.SetLabel(
            _("Pobieranie aktualizacji, {percent} procent").format(percent=percent)
        )
        step = percent - percent % SPOKEN_STEP_PERCENT
        if step > self._last_spoken and not self.was_cancelled:
            self._last_spoken = step
            speak(_("{percent} procent").format(percent=step))

    def cancel(self):
        """Przerywa pobieranie. Okno zamknie finish, gdy wątek w tle już skończy."""
        if not self.was_cancelled:
            self.was_cancelled = True
            self._cancel.Disable()
            self._status.SetLabel(_("Anulowanie"))
            speak(_("Anulowanie"))
            self._on_cancel()

    def finish(self, path, failed):
        self.path = path
        self.failed = failed
        self.EndModal(wx.ID_OK)
