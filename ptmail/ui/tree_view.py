import wx


class TreeView(wx.Panel):
    """Natywne drzewo Windows: strzałka w prawo rozwija gałąź, w lewo ją zwija.

    Węzły mają klucze, dzięki czemu odświeżenie nie przesuwa zaznaczenia, a zmiana
    samych tekstów, np. liczby nieprzeczytanych, nie przebudowuje drzewa.
    """

    def __init__(self, parent, label, on_expanded_change=None):
        super().__init__(parent)
        self._items = {}
        self._shape = None
        self._building = False
        self._on_expanded_change = on_expanded_change
        heading = wx.StaticText(self, label=label)
        self.tree = wx.TreeCtrl(
            self,
            style=wx.TR_HIDE_ROOT
            | wx.TR_HAS_BUTTONS
            | wx.TR_LINES_AT_ROOT
            | wx.TR_SINGLE,
        )
        self._root = self.tree.AddRoot("")
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(heading, 0, wx.ALL, 4)
        sizer.Add(self.tree, 1, wx.EXPAND | wx.ALL, 4)
        self.SetSizer(sizer)
        self.tree.Bind(wx.EVT_TREE_ITEM_EXPANDED, self._on_toggle)
        self.tree.Bind(wx.EVT_TREE_ITEM_COLLAPSED, self._on_toggle)

    def focus(self):
        self.tree.SetFocus()

    def set_nodes(self, nodes, expanded=()):
        """Podmienia węzły (klucz, tekst, dzieci). Gałęzie z expanded są rozwinięte.

        expanded liczy się tylko przy przebudowie; poza nią drzewo pamięta samo.
        """
        shape = _shape(nodes)
        if shape == self._shape:
            for key, text in _texts(nodes):
                item = self._items[key]
                if self.tree.GetItemText(item) != text:
                    self.tree.SetItemText(item, text)
            return
        selected = self.selected_key()
        self._building = True
        try:
            self.tree.DeleteChildren(self._root)
            self._items = {}
            self._add(self._root, nodes)
            for key in expanded:
                if key in self._items and self.tree.ItemHasChildren(self._items[key]):
                    self.tree.Expand(self._items[key])
        finally:
            self._building = False
        self._shape = shape
        self.select_key(selected)

    def _add(self, parent, nodes):
        for key, text, children in nodes:
            item = self.tree.AppendItem(parent, text, data=key)
            self._items[key] = item
            self._add(item, children)

    def selected_key(self):
        item = self.tree.GetSelection()
        return self.tree.GetItemData(item) if item.IsOk() else None

    def select_key(self, key):
        """Zaznacza węzeł, w razie potrzeby rozwijając jego gałąź. Bez klucza pierwszy węzeł."""
        item = self._items.get(key)
        if item is None:
            item, _cookie = self.tree.GetFirstChild(self._root)
        if item.IsOk():
            self.tree.EnsureVisible(item)
            self.tree.SelectItem(item)

    def expanded_keys(self):
        return [
            key
            for key, item in self._items.items()
            if self.tree.ItemHasChildren(item) and self.tree.IsExpanded(item)
        ]

    def texts(self):
        """Pary (poziom, tekst) w kolejności drzewa, rozwinięte czy nie."""
        return list(_walk(self.tree, self._root, 0))

    def _on_toggle(self, event):
        event.Skip()
        if not self._building and self._on_expanded_change is not None:
            self._on_expanded_change(self.expanded_keys())


def _shape(nodes):
    return tuple((key, _shape(children)) for key, _text, children in nodes)


def _texts(nodes):
    for key, text, children in nodes:
        yield key, text
        yield from _texts(children)


def _walk(tree, parent, depth):
    item, cookie = tree.GetFirstChild(parent)
    while item.IsOk():
        yield depth, tree.GetItemText(item)
        yield from _walk(tree, item, depth + 1)
        item, cookie = tree.GetNextChild(parent, cookie)
