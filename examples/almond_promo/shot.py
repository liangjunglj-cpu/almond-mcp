"""Desktop screenshot + Rhino window helpers (physical pixels)."""
import ctypes, sys
from ctypes import wintypes
from PIL import ImageGrab

ctypes.windll.shcore.SetProcessDpiAwareness(2)
user32 = ctypes.windll.user32


def rhino_hwnd():
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _):
        n = user32.GetWindowTextLengthW(h)
        if n and user32.IsWindowVisible(h):
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(h, buf, n + 1)
            if 'Rhinoceros' in buf.value or '.3dm' in buf.value:
                found.append((h, buf.value))
        return True
    user32.EnumWindows(cb, 0)
    return found


def front(h):
    user32.ShowWindow(h, 3)  # maximize
    user32.SetForegroundWindow(h)


def grab(path, box=None, scale=1.0):
    im = ImageGrab.grab(bbox=box, all_screens=False)
    if scale != 1.0:
        im = im.resize((int(im.width * scale), int(im.height * scale)))
    im.save(path)
    return im.size


if __name__ == '__main__':
    wins = rhino_hwnd()
    print(wins)
    if wins and '--front' in sys.argv:
        front(wins[0][0])
    import time; time.sleep(0.6)
    print(grab(sys.argv[1], scale=float(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] != '--front' else 1.0))


def topmost(h, on=True):
    # HWND_TOPMOST=-1, HWND_NOTOPMOST=-2; SWP_NOMOVE|SWP_NOSIZE=3
    user32.SetWindowPos(h, -1 if on else -2, 0, 0, 0, 0, 3)


def rhino_front_top(park=(400, 1300)):
    import time
    h = rhino_hwnd()[0][0]
    front(h); topmost(h, True)
    for p in [(2200, 900), (1000, 800), park]:
        user32.SetCursorPos(*p); time.sleep(0.4)
    return h
