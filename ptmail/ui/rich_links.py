"""Oznacza zakresy pola RichEdit jako linki, co wxPython nie ma w swoim API."""

import ctypes
from ctypes import wintypes

EM_SETSEL = 0x00B1
EM_SETCHARFORMAT = 0x0444
SCF_SELECTION = 0x0001
CFM_LINK = 0x00000020
CFE_LINK = 0x00000020

_user32 = ctypes.WinDLL("user32")
_user32.SendMessageW.argtypes = (
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)
_user32.SendMessageW.restype = wintypes.LPARAM


class CHARFORMAT2W(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwMask", wintypes.DWORD),
        ("dwEffects", wintypes.DWORD),
        ("yHeight", wintypes.LONG),
        ("yOffset", wintypes.LONG),
        ("crTextColor", wintypes.DWORD),
        ("bCharSet", wintypes.BYTE),
        ("bPitchAndFamily", wintypes.BYTE),
        ("szFaceName", wintypes.WCHAR * 32),
        ("wWeight", wintypes.WORD),
        ("sSpacing", wintypes.SHORT),
        ("crBackColor", wintypes.DWORD),
        ("lcid", wintypes.DWORD),
        ("dwReserved", wintypes.DWORD),
        ("sStyle", wintypes.SHORT),
        ("wKerning", wintypes.WORD),
        ("bUnderlineType", wintypes.BYTE),
        ("bAnimation", wintypes.BYTE),
        ("bRevAuthor", wintypes.BYTE),
        ("bUnderlineColor", wintypes.BYTE),
    ]


def mark_links(text_ctrl, ranges):
    hwnd = text_ctrl.GetHandle()
    style = CHARFORMAT2W()
    style.cbSize = ctypes.sizeof(CHARFORMAT2W)
    style.dwMask = CFM_LINK
    style.dwEffects = CFE_LINK
    for start, end, _link in ranges:
        _user32.SendMessageW(hwnd, EM_SETSEL, start, end)
        _user32.SendMessageW(
            hwnd, EM_SETCHARFORMAT, SCF_SELECTION, ctypes.addressof(style)
        )
    _user32.SendMessageW(hwnd, EM_SETSEL, 0, 0)
