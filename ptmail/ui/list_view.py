import wx

# Po tylu milisekundach od wejścia na listę albo od zmiany wierszy przez program dostaje
# fokus zaznaczony wiersz. Gdy Windows zgłasza kilka zmian naraz (fokus listy, nowy wiersz,
# zaznaczenie), NVDA czyta wiersz dwa albo trzy razy, zależnie od wyścigu.
ROW_FOCUS_DELAY_MS = 100


class ListView(wx.Panel):
    """Lista Windows taka jak w Eksploratorze, w której każdy wiersz to jedno zdanie dla NVDA.

    Zwykłej listy (ListBox) NVDA czyta zaznaczony wiersz dwa razy, gdy wchodzi się na nią
    z innego miejsca, a tę raz i dodaje pozycję, np. „1 z 3”. Wiersze mają klucze,
    dzięki czemu odświeżenie nie przesuwa zaznaczenia.
    """

    def __init__(self, parent, label):
        super().__init__(parent)
        self._keys = []
        self._texts = []
        self._row_focus_pending = False
        heading = wx.StaticText(self, label=label)
        self.list = wx.ListCtrl(
            self, style=wx.LC_REPORT | wx.LC_NO_HEADER | wx.LC_SINGLE_SEL
        )
        self.list.InsertColumn(0, label)
        self.list.Bind(wx.EVT_SIZE, self._on_size)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(heading, 0, wx.ALL, 4)
        sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 4)
        self.SetSizer(sizer)

    def _on_size(self, event):
        # Jedna kolumna na całą szerokość, żeby długie wiersze nie były ucięte na ekranie.
        event.Skip()
        self.list.SetColumnWidth(0, max(self.list.GetClientSize().width, 100))

    def focus(self):
        """Przenosi fokus na listę tak, żeby NVDA przeczytał zaznaczony wiersz jeden raz."""
        if self._has_focus() or self.list.GetFocusedItem() == -1:
            self.list.SetFocus()
            return
        self._postpone_row_focus()
        self.list.SetFocus()

    def _has_focus(self):
        return wx.Window.FindFocus() is self.list

    def _postpone_row_focus(self):
        """Zdejmuje fokus z wiersza; wróci na zaznaczony wiersz po ROW_FOCUS_DELAY_MS."""
        self.hold_row_focus(ROW_FOCUS_DELAY_MS)

    def hold_row_focus(self, delay_ms):
        """Zdejmuje fokus z wiersza na delay_ms. Zmiany w tym czasie tylko zaznaczają wiersz."""
        index = self.list.GetFocusedItem()
        if index != -1:
            self.list.SetItemState(index, 0, wx.LIST_STATE_FOCUSED)
        if not self._row_focus_pending:
            self._row_focus_pending = True
            wx.CallLater(delay_ms, self._focus_selected_row)

    def _focus_selected_row(self):
        if not self:
            return
        self._row_focus_pending = False
        index = self.list.GetFirstSelected()
        if index != -1 and self.list.GetFocusedItem() == -1:
            self.list.Focus(index)

    def texts(self):
        return list(self._texts)

    def set_rows(self, rows, fallback=None):
        """Podmienia wiersze (klucz, tekst), zostawiając zaznaczenie na tym samym kluczu.

        Zmienia tylko wiersze, które naprawdę się zmieniły. Ponowne ustawienie całej
        listy albo zaznaczenia sprawia, że NVDA czyta zaznaczony wiersz jeszcze raz.
        Gdy zaznaczonego klucza już nie ma, zaznacza fallback, a bez niego pierwszy wiersz.
        """
        keys = [key for key, _text in rows]
        texts = [text for _key, text in rows]
        selected = self.selected_key()
        start, old_end, new_end = _changed_range(self._keys, keys)
        if self._has_focus() and (old_end > start or new_end > start):
            # Nowe albo usunięte wiersze na liście z fokusem: NVDA ma przeczytać wynik raz.
            self._postpone_row_focus()
        # Windows sam trzyma zaznaczenie na tym samym wierszu, gdy inne znikają lub dochodzą.
        for _index in range(start, old_end):
            self.list.DeleteItem(start)
        for index in range(start, new_end):
            self.list.InsertItem(index, texts[index])
        old_texts = dict(zip(self._keys, self._texts))
        for index, (key, text) in enumerate(zip(keys, texts)):
            if not start <= index < new_end and old_texts[key] != text:
                self.list.SetItemText(index, text)
        self._keys = keys
        self._texts = texts
        if self.selected_key() != selected or self.list.GetFirstSelected() == -1:
            self.select_key(selected if selected in keys else fallback)

    def selected_key(self):
        index = self.list.GetFirstSelected()
        return self._keys[index] if index != -1 else None

    def select_key(self, key):
        """Zaznacza wiersz z kluczem, a bez niego pierwszy. Zaznaczony zostaje w spokoju."""
        if not self._keys:
            return
        index = self._keys.index(key) if key in self._keys else 0
        if self.list.GetFirstSelected() != index:
            self.list.Select(index)
        if self._row_focus_pending:
            # Fokus dojdzie za chwilę na zaznaczony wiersz, razem z resztą zmian.
            return
        if self.list.GetFocusedItem() != index:
            # NVDA czyta wiersz z fokusem, a strzałki ruszają się od niego.
            self.list.Focus(index)


def _changed_range(old, new):
    """Zwraca (początek, koniec w starych, koniec w nowych) części, która się różni."""
    start = 0
    while start < len(old) and start < len(new) and old[start] == new[start]:
        start += 1
    old_end, new_end = len(old), len(new)
    while old_end > start and new_end > start and old[old_end - 1] == new[new_end - 1]:
        old_end -= 1
        new_end -= 1
    return start, old_end, new_end
