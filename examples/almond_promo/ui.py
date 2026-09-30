"""Human-paced mouse/keyboard input via SendInput (physical pixel coordinates)."""
import ctypes, math, random, time
from ctypes import wintypes

ctypes.windll.shcore.SetProcessDpiAwareness(2)
user32 = ctypes.windll.user32
SW, SH = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)

ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG), ('mouseData', wintypes.DWORD),
                ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD), ('dwExtraInfo', ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [('wVk', wintypes.WORD), ('wScan', wintypes.WORD), ('dwFlags', wintypes.DWORD),
                ('time', wintypes.DWORD), ('dwExtraInfo', ULONG_PTR)]


class _U(ctypes.Union):
    _fields_ = [('mi', MOUSEINPUT), ('ki', KEYBDINPUT), ('pad', ctypes.c_byte * 32)]


class INPUT(ctypes.Structure):
    _fields_ = [('type', wintypes.DWORD), ('u', _U)]


def _send(*inputs):
    arr = (INPUT * len(inputs))(*inputs)
    user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def _mouse(flags, x=0, y=0, data=0):
    i = INPUT(type=0)
    i.u.mi = MOUSEINPUT(x, y, data, flags, 0, 0)
    return i


def pos():
    p = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def move_to(x, y, dur=0.6, fps=120):
    x0, y0 = pos()
    n = max(2, int(dur * fps))
    # slight arc for a human-looking path
    mx, my = (x0 + x) / 2 + (y - y0) * 0.08, (y0 + y) / 2 - (x - x0) * 0.08
    for k in range(1, n + 1):
        t = k / n
        e = t * t * (3 - 2 * t)
        px = (1 - e) ** 2 * x0 + 2 * (1 - e) * e * mx + e * e * x
        py = (1 - e) ** 2 * y0 + 2 * (1 - e) * e * my + e * e * y
        user32.SetCursorPos(int(round(px)), int(round(py)))
        time.sleep(1 / fps)


def click(x=None, y=None, dur=0.6, hold=0.08):
    if x is not None:
        move_to(x, y, dur)
    time.sleep(0.08)
    _send(_mouse(0x0002))  # left down
    time.sleep(hold)
    _send(_mouse(0x0004))  # left up


def key(vk, up=False):
    i = INPUT(type=1)
    i.u.ki = KEYBDINPUT(vk, 0, 2 if up else 0, 0, 0)
    return i


def hotkey(*vks):
    _send(*[key(v) for v in vks])
    time.sleep(0.03)
    _send(*[key(v, True) for v in reversed(vks)])


def type_text(s, cps=11):
    for ch in s:
        d = INPUT(type=1); d.u.ki = KEYBDINPUT(0, ord(ch), 0x0004, 0, 0)
        u = INPUT(type=1); u.u.ki = KEYBDINPUT(0, ord(ch), 0x0004 | 0x0002, 0, 0)
        _send(d, u)
        time.sleep(1 / cps * random.uniform(0.7, 1.3))


VK_CONTROL, VK_A, VK_BACK, VK_ESC, VK_RETURN = 0x11, 0x41, 0x08, 0x1B, 0x0D
