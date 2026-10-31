import wx


class ListView(wx.Panel):
    """Natywna lista, w której każdy wiersz to jedno zdanie dla NVDA.

    Wiersze mają klucze, dzięki czemu odświeżenie nie przesuwa zaznaczenia.
    """

    def __init__(self, parent, label):
        super().__init__(parent)
        self._keys = []
        self._texts = []
        heading = wx.StaticText(self, label=label)
        self.list = wx.ListBox(self, style=wx.LB_SINGLE)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(heading, 0, wx.ALL, 4)
        sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 4)
        self.SetSizer(sizer)

    def focus(self):
        self.list.SetFocus()

    def set_rows(self, rows):
        """Podmienia wiersze (klucz, tekst), zostawiając zaznaczenie na tym samym kluczu."""
        keys = [key for key, _text in rows]
        texts = [text for _key, text in rows]
        if keys == self._keys:
            # Zmieniamy tylko inne wiersze, żeby NVDA nie gubił pozycji na liście.
            for index, (old, new) in enumerate(zip(self._texts, texts)):
                if old != new:
                    self.list.SetString(index, new)
            self._texts = texts
            return
        selected = self.selected_key()
        self._keys = keys
        self._texts = texts
        self.list.Set(texts)
        if keys:
            self.select_key(selected)

    def selected_key(self):
        index = self.list.GetSelection()
        return self._keys[index] if index != wx.NOT_FOUND else None

    def select_key(self, key):
        index = self._keys.index(key) if key in self._keys else 0
        if self._keys:
            self.list.SetSelection(index)
