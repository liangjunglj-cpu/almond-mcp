"""Rhino window screenshots for documentation: front + topmost, cursor parked, full-screen grab."""
import ctypes, sys, time
from pathlib import Path
import shot
from PIL import Image

OUT = Path(r"C:\Users\liang\Documents\almond_promo\ui")
OUT.mkdir(exist_ok=True)
user32 = ctypes.windll.user32


def take(name, settle=1.5):
    h = shot.rhino_hwnd()[0][0]
    shot.front(h)
    user32.SetWindowPos(h, -1, 0, 0, 0, 0, 0x0001 | 0x0002)      # HWND_TOPMOST, keep size/pos
    user32.SetCursorPos(1300, 700)                                 # park the cursor over the viewport
    time.sleep(settle)
    path = OUT / f"{name}.png"
    shot.grab(str(path))
    user32.SetWindowPos(h, -2, 0, 0, 0, 0, 0x0001 | 0x0002)      # HWND_NOTOPMOST
    Image.open(path).convert("RGB").resize((1280, 800)).save(OUT / f"{name}_s.jpg", quality=85)
    return path


if __name__ == "__main__":
    print(take(sys.argv[1]))
