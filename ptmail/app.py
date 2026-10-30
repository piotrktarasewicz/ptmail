import wx

from . import APP_NAME
from .ui.main_frame import MainFrame


def main():
    app = wx.App()
    app.SetAppName(APP_NAME)
    frame = MainFrame()
    frame.Show()
    app.MainLoop()
