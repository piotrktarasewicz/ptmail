from pathlib import Path

import wx
import wx.adv

from .. import APP_NAME
from ..formatting import mailbox_sentence
from ..i18n import _

ICON_PATH = Path(__file__).parent.parent / "assets" / "ptmail.ico"


class TrayIcon(wx.adv.TaskBarIcon):
    """Ikona obok zegara. Enter lub kliknięcie otwiera okno, klawisz menu pokazuje resztę."""

    def __init__(self, on_open, on_check, on_quit):
        super().__init__()
        self._on_open = on_open
        self._on_check = on_check
        self._on_quit = on_quit
        self._icon = wx.Icon(str(ICON_PATH), wx.BITMAP_TYPE_ICO)
        self.show_unread(0)
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_UP, lambda _event: on_open())

    def show_unread(self, unread):
        self.SetIcon(self._icon, mailbox_sentence(APP_NAME, unread))

    def CreatePopupMenu(self):
        menu = wx.Menu()
        items = (
            (_("&Otwórz PT Mail"), self._on_open),
            (_("&Sprawdź pocztę teraz"), self._on_check),
            (_("&Zakończ"), self._on_quit),
        )
        for label, handler in items:
            entry = menu.Append(wx.ID_ANY, label)
            self.Bind(wx.EVT_MENU, lambda _event, run=handler: run(), entry)
        return menu
