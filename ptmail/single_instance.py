"""Jedna kopia programu. Skrót kliknięty, gdy program już działa, tylko pokazuje okno."""

import ctypes
import threading
from ctypes import wintypes

# Tej samej nazwy pilnuje instalator, żeby nie podmieniać plików działającego programu.
MUTEX_NAME = "PTMailRunning"
SHOW_EVENT_NAME = "PTMailShowWindow"
ERROR_ALREADY_EXISTS = 183
EVENT_MODIFY_STATE = 0x0002
INFINITE = 0xFFFFFFFF
ASFW_ANY = wintypes.DWORD(-1)

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CreateEventW.argtypes = (
    wintypes.LPVOID,
    wintypes.BOOL,
    wintypes.BOOL,
    wintypes.LPCWSTR,
)
_kernel32.CreateEventW.restype = wintypes.HANDLE
_kernel32.OpenEventW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
_kernel32.OpenEventW.restype = wintypes.HANDLE
_kernel32.SetEvent.argtypes = (wintypes.HANDLE,)
_kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
_kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
_kernel32.WaitForSingleObject.restype = wintypes.DWORD

_mutex = None


def claim():
    """Zwraca True, gdy to pierwsza kopia. System zwalnia blokadę przy jej końcu."""
    global _mutex
    _mutex = _kernel32.CreateMutexW(None, False, MUTEX_NAME)
    return ctypes.get_last_error() != ERROR_ALREADY_EXISTS


def show_running():
    """Prosi działającą kopię o pokazanie okna i pozwala jej wyjść na wierzch."""
    ctypes.windll.user32.AllowSetForegroundWindow(ASFW_ANY)
    event = _kernel32.OpenEventW(EVENT_MODIFY_STATE, False, SHOW_EVENT_NAME)
    if event:
        _kernel32.SetEvent(event)
        _kernel32.CloseHandle(event)


def listen(on_show):
    """Wywołuje on_show w osobnym wątku przy każdej prośbie z innej kopii."""
    event = _kernel32.CreateEventW(None, False, False, SHOW_EVENT_NAME)

    def wait():
        while True:
            _kernel32.WaitForSingleObject(event, INFINITE)
            on_show()

    threading.Thread(target=wait, daemon=True).start()
