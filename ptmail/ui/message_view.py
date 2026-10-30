import wx

from ..formatting import attachment_sentence, message_document, utf16_ranges
from ..i18n import _
from .rich_links import mark_links


class MessageView(wx.Panel):
    """Wiadomość jako jedno pole tylko do odczytu, a pod nim lista załączników."""

    def __init__(self, parent):
        super().__init__(parent)
        self.content = None
        self._links = []
        heading = wx.StaticText(self, label=_("Wiadomość"))
        # RICH2, bo zwykłe pole Windows ucina długie wiadomości.
        self.text = wx.TextCtrl(
            self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2
        )
        self._attachments_heading = wx.StaticText(self, label=_("Załączniki"))
        self.attachments = wx.ListBox(self, style=wx.LB_SINGLE)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(heading, 0, wx.ALL, 4)
        sizer.Add(self.text, 1, wx.EXPAND | wx.ALL, 4)
        sizer.Add(self._attachments_heading, 0, wx.ALL, 4)
        sizer.Add(self.attachments, 0, wx.EXPAND | wx.ALL, 4)
        self.SetSizer(sizer)

    def show_content(self, content):
        self.content = content
        document = message_document(content)
        self.text.SetValue(document)
        self._links = utf16_ranges(document, content.links)
        mark_links(self.text, self._links)
        self.text.SetInsertionPoint(0)
        self.text.ShowPosition(0)
        self.attachments.Set([attachment_sentence(a) for a in content.attachments])
        has_attachments = bool(content.attachments)
        if has_attachments:
            self.attachments.SetSelection(0)
        # Pustej listy nie pokazujemy, żeby Tab na nią nie wchodził.
        self._attachments_heading.Show(has_attachments)
        self.attachments.Show(has_attachments)
        self.Layout()

    def focus(self):
        self.text.SetFocus()

    def link_at_caret(self):
        caret = self.text.GetInsertionPoint()
        for start, end, link in self._links:
            if start <= caret < end:
                return link
        return None

    def move_to_link(self, step):
        """Przenosi kursor na sąsiedni link i zwraca go, a gdy go nie ma, None."""
        caret = self.text.GetInsertionPoint()
        if step > 0:
            targets = [item for item in self._links if item[0] > caret]
            target = targets[0] if targets else None
        else:
            targets = [item for item in self._links if item[0] < caret]
            target = targets[-1] if targets else None
        if target is None:
            return None
        self.text.SetInsertionPoint(target[0])
        self.text.ShowPosition(target[0])
        return target[2]

    def focus_attachments(self):
        if self.content is not None and self.content.attachments:
            self.attachments.SetFocus()
            return True
        return False

    def attachments_focused(self):
        return self.attachments.HasFocus()

    def selected_attachment(self):
        index = self.attachments.GetSelection()
        if self.content is None or index == wx.NOT_FOUND:
            return None
        return self.content.attachments[index]
