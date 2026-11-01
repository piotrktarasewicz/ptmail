import logging

import wx

from . import APP_NAME
from .config import config_path
from .notifications import register_app
from .ui.main_frame import MainFrame


def _start_logging():
    """Dziennik techniczny dla usterek, które program celowo przemilcza."""
    path = config_path().parent / "ptmail.log"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            filename=path,
            encoding="utf-8",
            level=logging.WARNING,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
    except OSError:
        pass


def main():
    _start_logging()
    register_app()
    app = wx.App()
    app.SetAppName(APP_NAME)
    frame = MainFrame()
    frame.Show()
    app.MainLoop()
