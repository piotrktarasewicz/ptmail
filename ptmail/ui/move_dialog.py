import wx

from ..i18n import _


class MoveDialog(wx.Dialog):
    """Wybór folderu docelowego. Enter przenosi, Escape anuluje."""

    def __init__(self, parent, folders):
        super().__init__(parent, title=_("Przenieś do folderu"), size=(380, 340))
        self._folders = folders
        label = wx.StaticText(self, label=_("Folder:"))
        self._list = wx.ListBox(
            self, choices=[f.label for f in folders], style=wx.LB_SINGLE
        )
        self._list.SetSelection(0)
        move = wx.Button(self, wx.ID_OK, _("Przenieś"))
        move.SetDefault()
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        buttons.Add(move, 0, wx.RIGHT, 6)
        buttons.Add(wx.Button(self, wx.ID_CANCEL, _("Anuluj")))
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(label, 0, wx.ALL, 8)
        sizer.Add(self._list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        sizer.Add(buttons, 0, wx.ALL, 8)
        self.SetSizer(sizer)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        self._list.SetFocus()

    def _on_key(self, event):
        if event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.EndModal(wx.ID_OK)
        else:
            event.Skip()

    @property
    def folder(self):
        return self._folders[self._list.GetSelection()]
