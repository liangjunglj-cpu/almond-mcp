"""Rhino window screenshots for documentation.

Captures ONLY the Rhino main window (PrintWindow renders that window itself), so no other
application can end up in a screenshot even when Rhino is covered, minimised to another virtual
desktop, or behind another window. The image is placed on a screen-sized canvas at the window's
position so crops written in screen coordinates keep working.
"""
import ctypes, sys, time
from ctypes import wintypes
from pathlib import Path
import shot
from PIL import Image

OUT = Path(r"C:\Users\liang\Documents\almond_promo\ui")
OUT.mkdir(exist_ok=True)
user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
PW_RENDERFULLCONTENT = 2


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


def window_image(h) -> tuple[Image.Image, tuple]:
    r = wintypes.RECT()
    user32.GetWindowRect(h, ctypes.byref(r))
    w, ht = r.right - r.left, r.bottom - r.top
    hdc = user32.GetWindowDC(h)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, ht)
    gdi32.SelectObject(mdc, bmp)
    try:
        if not user32.PrintWindow(h, mdc, PW_RENDERFULLCONTENT):
            raise RuntimeError("PrintWindow failed")
        bih = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -ht, 1, 32, 0, 0, 0, 0, 0, 0)
        buf = ctypes.create_string_buffer(w * ht * 4)
        gdi32.GetDIBits(mdc, bmp, 0, ht, buf, ctypes.byref(bih), 0)
        img = Image.frombuffer("RGBA", (w, ht), buf, "raw", "BGRA", 0, 1).convert("RGB")
    finally:
        gdi32.DeleteObject(bmp); gdi32.DeleteDC(mdc); user32.ReleaseDC(h, hdc)
    return img, (r.left, r.top, r.right, r.bottom)


def take(name, settle=1.5):
    h = shot.rhino_hwnd()[0][0]
    shot.front(h)
    user32.SetCursorPos(1300, 700)                                 # park the cursor over the viewport
    time.sleep(settle)
    img, (left, top, _, _) = window_image(h)
    canvas = Image.new("RGB", (user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)), (0, 0, 0))
    canvas.paste(img, (left, top))
    path = OUT / f"{name}.png"
    canvas.save(path)
    canvas.resize((1280, 800)).save(OUT / f"{name}_s.jpg", quality=85)
    return path


if __name__ == "__main__":
    print(take(sys.argv[1]))
