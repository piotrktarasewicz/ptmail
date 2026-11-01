from dataclasses import replace

import wx

from ..compose import (
    add_signature,
    attachment_from_file,
    build_message,
    parse_recipients,
    swap_signature,
)
from ..contacts import (
    current_fragment,
    insert_contact,
    matching_contacts,
    suggestion_sentence,
)
from ..formatting import attachment_sentence
from ..i18n import _
from ..speech import speak

CLOSE_DELAY_MS = 600
CLOSE_DELAY_MS_PER_CHAR = 70
SUGGESTION_DELAY_MS = 400


class ComposeDialog(wx.Dialog):
    """Okno pisania. Tab idzie przez Od, Do, DW, Temat, Treść, Załączniki, Wyślij.

    W polach Do i DW NVDA mówi podpowiedź po chwili przerwy w pisaniu: strzałki ją
    zmieniają, Enter wstawia, a Escape ukrywa.
    """

    def __init__(self, parent, accounts, draft, workers, contacts=()):
        super().__init__(
            parent,
            title=_("Nowa wiadomość"),
            size=(700, 600),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.result_text = ""
        self.sent_draft = None
        self._contacts = contacts
        self._suggestions = []
        self._suggestion_index = 0
        self._suggestion_field = None
        self._accounts = accounts
        emails = [account.email for account in accounts]
        sender = emails.index(draft.sender) if draft.sender in emails else 0
        self._base_body = draft.body
        self._signature = accounts[sender].signature
        self._draft = add_signature(
            replace(draft, sender=emails[sender]), self._signature
        )
        draft = self._draft
        self._workers = workers
        self._attachments = list(draft.attachments)
        self._busy = False

        fields = wx.FlexGridSizer(cols=2, vgap=6, hgap=6)
        fields.AddGrowableCol(1)

        def add_field(label, create):
            # NVDA bierze nazwę pola z etykiety stworzonej tuż przed nim.
            fields.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            control = create()
            fields.Add(control, 1, wx.EXPAND)
            return control

        self._sender = add_field(
            _("Od:"),
            lambda: wx.Choice(
                self, choices=[f"{a.name} ({a.email})" for a in accounts]
            ),
        )
        self._sender.SetSelection(sender)
        self._to = add_field(_("Do:"), lambda: wx.TextCtrl(self, value=draft.to))
        self._cc = add_field(_("DW:"), lambda: wx.TextCtrl(self, value=draft.cc))
        self._subject = add_field(
            _("Temat:"), lambda: wx.TextCtrl(self, value=draft.subject)
        )
        body_label = wx.StaticText(self, label=_("Treść:"))
        self._body = wx.TextCtrl(
            self, value=draft.body, style=wx.TE_MULTILINE | wx.TE_RICH2
        )
        self._attachments_label = wx.StaticText(self, label=_("Załączniki:"))
        self._attachment_list = wx.ListBox(self, style=wx.LB_SINGLE)
        self._send_button = wx.Button(self, label=_("Wyślij"))
        self._status = wx.StaticText(self)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(fields, 0, wx.EXPAND | wx.ALL, 8)
        sizer.Add(body_label, 0, wx.LEFT | wx.RIGHT, 8)
        sizer.Add(self._body, 1, wx.EXPAND | wx.ALL, 8)
        sizer.Add(self._attachments_label, 0, wx.LEFT | wx.RIGHT, 8)
        sizer.Add(self._attachment_list, 0, wx.EXPAND | wx.ALL, 8)
        sizer.Add(self._send_button, 0, wx.ALL, 8)
        sizer.Add(self._status, 0, wx.EXPAND | wx.ALL, 8)
        self.SetSizer(sizer)

        self._sender.Bind(wx.EVT_CHOICE, lambda _event: self._on_sender_changed())
        self._send_button.Bind(wx.EVT_BUTTON, lambda _event: self.send())
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        self.Bind(wx.EVT_CLOSE, lambda _event: self.cancel())
        self._suggestion_timer = wx.Timer(self)
        self.Bind(
            wx.EVT_TIMER, lambda _event: self._suggest(), self._suggestion_timer
        )
        for recipients in (self._to, self._cc):
            recipients.Bind(wx.EVT_TEXT, self._on_recipients_typed)
            recipients.Bind(wx.EVT_KILL_FOCUS, self._on_recipients_left)
        self._show_attachments()
        field = self._body if draft.focus_body else self._to
        field.SetFocus()
        field.SetInsertionPoint(0)

    def _on_key(self, event):
        key = event.GetKeyCode()
        # Alt odrzucamy, bo prawy Alt to dla Windows Ctrl+Alt, a Prawy Alt+Shift+A to Ą.
        control = event.ControlDown() and not event.AltDown()
        if self._suggestions and not control and self._on_suggestion_key(key):
            return
        if key == wx.WXK_ESCAPE:
            self.cancel()
        elif control and key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.send()
        elif control and event.ShiftDown() and key == ord("A"):
            self._add_attachments()
        elif key == wx.WXK_DELETE and self._attachment_list.HasFocus():
            self._remove_attachment()
        else:
            event.Skip()

    def _on_suggestion_key(self, key):
        if key == wx.WXK_DOWN:
            self._move_suggestion(1)
        elif key == wx.WXK_UP:
            self._move_suggestion(-1)
        elif key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self._accept_suggestion()
        elif key == wx.WXK_ESCAPE:
            self._hide_suggestions()
            self._say(_("Podpowiedzi ukryte"))
        else:
            return False
        return True

    def _on_recipients_typed(self, event):
        self._hide_suggestions()
        self._suggestion_field = event.GetEventObject()
        self._suggestion_timer.StartOnce(SUGGESTION_DELAY_MS)
        event.Skip()

    def _on_recipients_left(self, event):
        self._hide_suggestions()
        event.Skip()

    def _hide_suggestions(self):
        self._suggestion_timer.Stop()
        self._suggestions = []

    def _suggest(self):
        field = self._suggestion_field
        text = field.GetValue()
        caret = field.GetInsertionPoint()
        start, _end = current_fragment(text, caret)
        self._suggestions = matching_contacts(self._contacts, text[start:caret])
        self._suggestion_index = 0
        if self._suggestions:
            self._say_suggestion()

    def _move_suggestion(self, step):
        count = len(self._suggestions)
        self._suggestion_index = (self._suggestion_index + step) % count
        self._say_suggestion()

    def _say_suggestion(self):
        self._say(
            suggestion_sentence(
                self._suggestions[self._suggestion_index],
                self._suggestion_index,
                len(self._suggestions),
            )
        )

    def _accept_suggestion(self):
        contact = self._suggestions[self._suggestion_index]
        field = self._suggestion_field
        text = field.GetValue()
        start, end = current_fragment(text, field.GetInsertionPoint())
        value, caret = insert_contact(text, start, end, contact)
        # ChangeValue nie wywołuje zdarzenia, więc wstawiony adres nie podpowie się znowu.
        field.ChangeValue(value)
        field.SetInsertionPoint(caret)
        self._hide_suggestions()
        self._say(_("Dodano: {name}").format(name=contact.name or contact.address))

    def EndModal(self, code):
        self._hide_suggestions()
        super().EndModal(code)

    def _sender_account(self):
        return self._accounts[self._sender.GetSelection()]

    def _on_sender_changed(self):
        signature = self._sender_account().signature
        if signature != self._signature:
            self._body.SetValue(
                swap_signature(
                    self._body.GetValue(),
                    self._signature,
                    signature,
                    self._base_body,
                )
            )
            self._signature = signature

    def _current_draft(self):
        return replace(
            self._draft,
            sender=self._sender_account().email,
            to=self._to.GetValue().strip(" ,;"),
            cc=self._cc.GetValue().strip(" ,;"),
            subject=" ".join(self._subject.GetValue().split()),
            body=self._body.GetValue(),
            attachments=tuple(self._attachments),
        )

    def _is_changed(self):
        return self._current_draft() != self._draft

    def _say(self, text):
        self._status.SetLabel(text)
        speak(text)

    def _set_busy(self, busy):
        self._busy = busy
        self._send_button.Enable(not busy)

    def send(self):
        if self._busy:
            return
        draft = self._current_draft()
        to, bad_to = parse_recipients(draft.to)
        cc, bad_cc = parse_recipients(draft.cc)
        if not to and not cc and not bad_to and not bad_cc:
            self._say(_("Wpisz adresata"))
            self._to.SetFocus()
            return
        if bad_to or bad_cc:
            self._say(
                _("Niepoprawny adres: {address}").format(address=(bad_to + bad_cc)[0])
            )
            (self._to if bad_to else self._cc).SetFocus()
            return
        self._set_busy(True)
        self._workers[draft.sender].send(
            to + cc,
            build_message(self._sender_account(), draft),
            lambda success, text: self._on_sent(draft, success, text),
        )

    def cancel(self):
        if self._busy:
            return
        if not self._is_changed():
            self.EndModal(wx.ID_CANCEL)
            return
        with wx.MessageDialog(
            self,
            _("Zapisać wiadomość w roboczych?"),
            _("Nowa wiadomość"),
            wx.YES_NO | wx.CANCEL | wx.CANCEL_DEFAULT,
        ) as dialog:
            dialog.SetYesNoCancelLabels(_("Zapisz"), _("Odrzuć"), _("Wróć"))
            answer = dialog.ShowModal()
        if answer == wx.ID_YES:
            self._set_busy(True)
            draft = self._current_draft()
            self._workers[draft.sender].save_draft(
                build_message(self._sender_account(), draft), self._on_done
            )
        elif answer == wx.ID_NO:
            self.EndModal(wx.ID_CANCEL)

    def _on_sent(self, draft, success, text):
        if success:
            self.sent_draft = draft
        self._on_done(success, text)

    def _on_done(self, success, text):
        self._say(text)
        if success:
            # Zamknięcie zmienia fokus, co ucisza NVDA, więc komunikat musi wybrzmieć.
            delay = max(CLOSE_DELAY_MS, len(text) * CLOSE_DELAY_MS_PER_CHAR)
            wx.CallLater(delay, self._close_after_success, text)
        else:
            self._set_busy(False)

    def _close_after_success(self, text):
        self.result_text = text
        self.EndModal(wx.ID_OK)

    def _add_attachments(self):
        with wx.FileDialog(
            self,
            _("Dołącz pliki"),
            style=wx.FD_OPEN | wx.FD_MULTIPLE | wx.FD_FILE_MUST_EXIST,
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            paths = dialog.GetPaths()
        try:
            self._attachments.extend(attachment_from_file(path) for path in paths)
        except OSError:
            self._say(_("Nie udało się odczytać pliku"))
        self._show_attachments()

    def _remove_attachment(self):
        index = self._attachment_list.GetSelection()
        if index == wx.NOT_FOUND:
            return
        del self._attachments[index]
        self._show_attachments()
        if self._attachments:
            self._attachment_list.SetSelection(min(index, len(self._attachments) - 1))
        else:
            self._body.SetFocus()

    def _show_attachments(self):
        self._attachment_list.Set([attachment_sentence(a) for a in self._attachments])
        shown = bool(self._attachments)
        if shown:
            self._attachment_list.SetSelection(0)
        # Pustej listy nie pokazujemy, żeby Tab na nią nie wchodził.
        self._attachments_label.Show(shown)
        self._attachment_list.Show(shown)
        self.Layout()
