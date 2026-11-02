import logging
import sys

import wx

from . import APP_NAME, single_instance
from .config import config_path
from .notifications import register_app
from .ui.main_frame import MainFrame

HIDDEN_ARGUMENT = "--hidden"  # start z Windows: program od razu chowa się do zasobnika


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
    hidden = HIDDEN_ARGUMENT in sys.argv
    if not single_instance.claim():
        if not hidden:
            single_instance.show_running()
        return
    register_app()
    app = wx.App()
    app.SetAppName(APP_NAME)
    frame = MainFrame()
    # Bez tego zamknięcie Windows zablokowałoby chowanie okna do zasobnika.
    app.Bind(wx.EVT_QUERY_END_SESSION, lambda _event: frame.quit())
    single_instance.listen(lambda: wx.CallAfter(frame.show_window))
    if not hidden:
        frame.Show()
    app.MainLoop()
