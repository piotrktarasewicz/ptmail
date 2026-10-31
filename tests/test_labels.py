"""Windows łączy etykietę z polem po kolejności okien, a NVDA stąd bierze nazwę pola."""

import ctypes
from ctypes import wintypes

import pytest
import wx

from ptmail.accounts import Account
from ptmail.compose import Draft
from ptmail.ui.account_dialog import AccountDialog
from ptmail.ui.accounts_dialog import AccountsDialog
from ptmail.ui.compose_dialog import ComposeDialog
from ptmail.ui.list_view import ListView
from ptmail.ui.message_view import MessageView

GW_HWNDPREV = 3
FIELD_TYPES = (wx.TextCtrl, wx.Choice, wx.ListBox)
ACCOUNT = Account("iCloud", "ja@example.com", "icloud")

_user32 = ctypes.WinDLL("user32")
_user32.GetWindow.argtypes = (wintypes.HWND, wintypes.UINT)
_user32.GetWindow.restype = wintypes.HWND


@pytest.fixture(scope="module")
def frame():
    app = wx.App()
    window = wx.Frame(None)
    yield window
    window.Destroy()
    del app


def field_labels(parent):
    """Zwraca etykiety pól, sprawdzając, że każda jest tuż przed swoim polem."""
    labels = []
    for child in parent.GetChildren():
        if isinstance(child, FIELD_TYPES):
            previous = child.GetPrevSibling()
            assert isinstance(previous, wx.StaticText), child
            assert _user32.GetWindow(child.GetHandle(), GW_HWNDPREV) == previous.GetHandle()
            labels.append(previous.GetLabel())
    return labels


def test_compose_fields_have_labels(frame):
    dialog = ComposeDialog(frame, [ACCOUNT], Draft(), {})
    assert field_labels(dialog) == ["Od:", "Do:", "DW:", "Temat:", "Treść:", "Załączniki:"]
    dialog.Destroy()


def test_account_fields_have_labels(frame):
    dialog = AccountDialog(frame)
    assert field_labels(dialog) == [
        "Rodzaj konta:",
        "Nazwa konta:",
        "Adres e-mail:",
        "Hasło aplikacji:",
        "Stan:",
    ]
    dialog.Destroy()


def test_accounts_list_has_label(frame):
    dialog = AccountsDialog(frame, [ACCOUNT])
    assert field_labels(dialog) == ["Konta:"]
    dialog.Destroy()


def test_main_views_have_labels(frame):
    assert field_labels(ListView(frame, "Wiadomości")) == ["Wiadomości"]
    assert field_labels(MessageView(frame)) == ["Wiadomość", "Załączniki"]
