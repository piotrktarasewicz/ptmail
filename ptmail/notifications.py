"""Powiadomienia systemowe Windows, które NVDA czyta sam, nawet nad innym programem."""

import ctypes
import logging
import winreg

import wx.adv

from . import APP_NAME

logger = logging.getLogger(__name__)
APP_ID = "PTMail"
APP_ID_KEY = rf"Software\Classes\AppUserModelId\{APP_ID}"

_shown = None


def register_app():
    """Przedstawia program Windows, bo inaczej powiadomienia idą od Pythona.

    Trzeba to zrobić przed utworzeniem pierwszego okna. Wpis jest tylko w gałęzi
    użytkownika, a jego brak najwyżej przywraca nazwę Python.
    """
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, APP_ID_KEY) as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except OSError:
        logger.exception("Nie udało się przedstawić programu Windows")


def notify(title, text):
    # Obiekt musi przeżyć wywołanie, bo jego usunięcie zamyka powiadomienie.
    global _shown
    _shown = wx.adv.NotificationMessage(title, text)
    _shown.Show()


def dismiss():
    """Zamyka ostatnie powiadomienie. Jego ukryte okno trzymałoby program przy życiu."""
    global _shown
    if _shown is not None:
        _shown.Close()
        _shown = None
