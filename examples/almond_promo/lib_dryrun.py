"""Type each query into the Almond panel search and snapshot the result grid (no placement)."""
import time
from PIL import Image
from shot import rhino_front_top, topmost, rhino_hwnd, grab
import ui

SEARCH = (2260, 470)
OUT = r"C:\Users\liang\Documents\almond_promo"
h = rhino_front_top(park=(1200, 1450))
tiles = []
try:
    for q in ["sofa", "throw", "armchair", "lounge chair", "ottoman", "dining chair"]:
        ui.click(*SEARCH, dur=0.3)
        ui.hotkey(ui.VK_CONTROL, ui.VK_A); ui.hotkey(ui.VK_BACK)
        ui.type_text(q, cps=25)
        time.sleep(1.2)
        ui.move_to(1200, 1450, 0.2)
        time.sleep(0.3)
        grab(OUT + r"\desk.png")
        tiles.append(Image.open(OUT + r"\desk.png").crop((2000, 340, 2560, 1600)).resize((280, 630)))
    ui.click(*SEARCH, dur=0.3); ui.hotkey(ui.VK_CONTROL, ui.VK_A); ui.hotkey(ui.VK_BACK)
finally:
    topmost(h, False)
sheet = Image.new('RGB', (280 * len(tiles), 630))
for i, t in enumerate(tiles):
    sheet.paste(t, (280 * i, 0))
sheet.save(OUT + r"\dryrun.png")
