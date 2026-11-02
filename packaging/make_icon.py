"""Rysuje ikonę programu: białą kopertę na niebieskim tle. Uruchamiane raz, ręcznie."""

import io
import struct
from pathlib import Path

import wx

SIZES = (16, 32, 48, 256)
TARGET = Path(__file__).parent.parent / "ptmail" / "assets" / "ptmail.ico"


def draw(size):
    bitmap = wx.Bitmap(size, size, 32)
    dc = wx.MemoryDC(bitmap)
    gc = wx.GraphicsContext.Create(dc)
    gc.SetBrush(wx.Brush(wx.Colour(24, 90, 170)))
    gc.SetPen(wx.TRANSPARENT_PEN)
    gc.DrawRoundedRectangle(0, 0, size, size, size * 0.18)
    margin = size * 0.14
    width = size - 2 * margin
    height = width * 0.68
    top = (size - height) / 2
    gc.SetBrush(wx.WHITE_BRUSH)
    gc.DrawRectangle(margin, top, width, height)
    gc.SetPen(wx.Pen(wx.Colour(24, 90, 170), max(1, round(size * 0.06))))
    flap = gc.CreatePath()
    flap.MoveToPoint(margin, top)
    flap.AddLineToPoint(size / 2, top + height * 0.58)
    flap.AddLineToPoint(size - margin, top)
    gc.StrokePath(flap)
    del gc
    dc.SelectObject(wx.NullBitmap)
    return bitmap


def png_bytes(bitmap):
    stream = io.BytesIO()
    bitmap.ConvertToImage().SaveFile(stream, wx.BITMAP_TYPE_PNG)
    return stream.getvalue()


def write_icon(images):
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries = b""
    for size, data in images:
        side = 0 if size == 256 else size
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    TARGET.parent.mkdir(exist_ok=True)
    TARGET.write_bytes(header + entries + b"".join(data for _size, data in images))


if __name__ == "__main__":
    app = wx.App(False)
    write_icon([(size, png_bytes(draw(size))) for size in SIZES])
