"""Compose documentation images (docs/images/native-solver) and a walkthrough video from the
stills captured by native_doc_capture.py.

    uv run python examples/almond_promo/native_doc_compose.py [--video]
"""
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SRC = Path(r"C:\Users\liang\Documents\almond_promo\native_doc")
REPO = Path(__file__).resolve().parents[2]
IMG = REPO / "docs" / "images" / "native-solver"
VID = Path(r"C:\Users\liang\Documents\almond_promo\native_solver_walkthrough.mp4")
FONTS = Path(r"C:\Windows\Fonts")
INK, WHITE, GREY, RED, GREEN, CYAN = (14, 14, 16), (240, 240, 236), (150, 150, 158), (233, 68, 43), (40, 220, 90), (0, 229, 255)
LOG = {r["name"]: r for r in json.loads((SRC / "log.json").read_text())}


def font(name, size):
    return ImageFont.truetype(str(FONTS / {"bold": "arialbd.ttf", "ocr": "OCRAEXT.TTF", "mono": "consola.ttf"}[name]), size)


def still(name, size=None):
    im = Image.open(SRC / (name if "." in name else name + ".jpg")).convert("RGB")
    return im.resize(size, Image.LANCZOS) if size else im


def label(d, xy, head, sub, accent):
    x, y = xy
    d.rectangle((x, y, x + 6, y + 58), fill=accent)
    d.text((x + 18, y - 2), head, font=font("bold", 30), fill=WHITE)
    d.text((x + 20, y + 36), sub.replace("·", "/"), font=font("ocr", 17), fill=accent)   # OCR-A has no middle dot


def grid(names, heads, cols, cell=(960, 540), pad=24, top=70, title=None):
    rows = (len(names) + cols - 1) // cols
    W, H = cols * cell[0] + (cols + 1) * pad, rows * (cell[1] + 92) + top + pad
    im = Image.new("RGB", (W, H), INK)
    d = ImageDraw.Draw(im)
    if title:
        d.text((pad, 20), title, font=font("ocr", 22), fill=GREY)
    for i, (n, (head, sub, acc)) in enumerate(zip(names, heads)):
        x, y = pad + (i % cols) * (cell[0] + pad), top + (i // cols) * (cell[1] + 92)
        label(d, (x, y), head, sub, acc)
        im.paste(still(n, cell), (x, y + 76))
    return im


def save(im, name, width=1600):
    IMG.mkdir(parents=True, exist_ok=True)
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    im.save(IMG / name, quality=86, optimize=True, progressive=True)
    print("wrote", IMG / name, (IMG / name).stat().st_size // 1024, "KB")


def fmt(n):
    r = LOG.get(n) or {}
    return f'{r.get("max_mm", 0):.1f} mm  ·  u {r.get("util", 0):.2f}  ·  {str(r.get("status", "")).upper()}'


def images():
    save(still("rhino_ui.png"), "rhino-native-no-karamba.jpg")
    save(grid(["karamba_114", "native_114"],
              [("KARAMBA3D 3.1", "183.0 mm  ·  u 3.59  ·  FAIL  ·  1.2 s", GREY),
               ("ALMOND NATIVE FEA", fmt("native_114") + "  ·  13 ms solve", RED)], 2,
              title="SAME FRAME, SAME LOADS  //  CHS 114.3x4, 150 kN + SELF WEIGHT, PINNED"), "native-vs-karamba.jpg")
    sizes = ["CHS 114.3x4", "CHS 139.7x5", "CHS 168.3x6.3", "CHS 193.7x8"]
    save(grid([f"iter_{i}" for i in range(4)],
              [(s, fmt(f"iter_{i}"), GREEN if LOG[f"iter_{i}"]["status"] == "pass" else RED) for i, s in enumerate(sizes)], 2,
              title="SIZING LOOP  //  visualize_structure(load_kn=150, span_m=6.2, beam_diameter_mm=...)"), "iteration.jpg")
    save(grid(["section_fail", "section_pass"],
              [("SECTION A-A  ·  CHS 114.3x4", fmt("section_fail"), RED),
               ("SECTION A-A  ·  CHS 193.7x8", fmt("section_pass"), GREEN)], 2,
              title="display_guids: one frame line drawn, all 20 members solved"), "section.jpg")


# ------------------------------------------------------------------ walkthrough video (1920x1080, 30 fps)
W, H, FPS = 1920, 1080, 30


def card(lines, kicker="ALMOND  //  NATIVE STRUCTURAL ENGINE", accent=RED):
    im = Image.new("RGB", (W, H), INK)
    d = ImageDraw.Draw(im)
    d.text((120, 120), kicker, font=font("ocr", 26), fill=accent)
    d.rectangle((120, 168, 700, 172), fill=accent)
    y = 230
    for text, kind in lines:
        f = {"h": font("bold", 84), "m": font("bold", 44), "t": font("mono", 32), "o": font("ocr", 26)}[kind]
        d.text((120, y), text, font=f, fill=WHITE if kind != "o" else GREY)
        y += {"h": 110, "m": 70, "t": 50, "o": 46}[kind]
    return im


def captioned(name, head, sub, accent, step=None):
    im = still(name, (W, H)).copy()
    d = ImageDraw.Draw(im, "RGBA")
    d.rectangle((60, H - 210, 1180, H - 60), fill=(*INK, 225))
    d.rectangle((60, H - 210, 68, H - 60), fill=accent)
    if step:
        d.text((92, H - 196), step, font=font("ocr", 20), fill=accent)
    d.text((92, H - 166), head, font=font("bold", 40), fill=WHITE)
    d.text((94, H - 112), sub, font=font("mono", 26), fill=WHITE)
    return im


def ui_frame():
    """The whole Rhino window, letterboxed (16:10 screen in a 16:9 frame), with the proof line called out."""
    shot = Image.open(SRC / "rhino_ui.png").convert("RGB")
    h = H - 150
    shot = shot.resize((round(shot.width * h / shot.height), h), Image.LANCZOS)
    im = Image.new("RGB", (W, H), INK)
    x0 = (W - shot.width) // 2
    im.paste(shot, (x0, 0))
    d = ImageDraw.Draw(im)
    sx = shot.width / 2560
    d.rectangle((x0 + 8 * sx, 64 * sx, x0 + 640 * sx, 96 * sx), outline=RED, width=3)   # command-line proof line
    d.text((x0, H - 120), "RHINO 8  //  KARAMBA ASSEMBLIES LOADED: 0", font=font("ocr", 30), fill=RED)
    d.text((x0, H - 76), "The frame is solved in the MCP server and drawn by the bridge's overlay.", font=font("mono", 28), fill=WHITE)
    return im


def pipeline():
    im = card([("How it works", "h")])
    d = ImageDraw.Draw(im)
    boxes = [("1  RHINO", "lines + support points", "structure_model", "~160 ms"),
             ("2  MCP SERVER", "numpy frame solver", "frame_solver.py", "~13 ms"),
             ("3  RHINO", "live overlay", "structure_draw", "~200 ms")]
    for i, (a, b, c, t) in enumerate(boxes):
        x = 120 + i * 580
        d.rectangle((x, 420, x + 500, 700), outline=WHITE, width=3)
        d.text((x + 30, 450), a, font=font("ocr", 26), fill=RED)
        d.text((x + 30, 500), b, font=font("bold", 40), fill=WHITE)
        d.text((x + 30, 590), c, font=font("mono", 30), fill=CYAN)
        d.text((x + 30, 640), t, font=font("ocr", 24), fill=GREY)
        if i < 2:
            d.polygon([(x + 515, 545), (x + 560, 560), (x + 515, 575)], fill=RED)
    d.text((120, 780), "No Karamba install, licence or 20-member trial cap. Karamba stays optional for shells.",
           font=font("mono", 32), fill=WHITE)
    return im


def bench():
    rows = [("Closed-form cases (6)", "exact to ~1e-16"), ("Karamba cross-check, 9 runs", "deflection within 1.3 %"),
            ("", "max utilization within 2.4 %"), ("Live Rhino, mezzanine CHS 114.3x4", "182.31 vs 182.53 mm"),
            ("Live Rhino, mezzanine CHS 193.7x8", "20.70 vs 20.85 mm"), ("Test suite", "162 passed")]
    im = card([("Benchmarked", "h")], accent=GREEN)
    d = ImageDraw.Draw(im)
    for i, (a, b) in enumerate(rows):
        d.text((120, 400 + i * 70), a, font=font("ocr", 28), fill=GREY)
        d.text((900, 396 + i * 70), b, font=font("bold", 38), fill=WHITE)
    d.text((120, 880), "Linear-elastic first-order 3D frames  ·  EN 1993-1-1 member checks  ·  preliminary design check",
           font=font("mono", 28), fill=GREY)
    return im


def video():
    seq = []                                  # (image, seconds)
    seq.append((card([("Structural checks", "h"), ("without Karamba", "h"), ("", "t"),
                      ("validate_structure + visualize_structure", "t"), ("now run on Almond's own 3D frame solver", "t")]), 4.0))
    seq.append((pipeline(), 5.0))
    seq.append((ui_frame(), 4.0))
    seq.append((captioned("ramp_000", "Self weight only", fmt("ramp_000"), GREEN, "LIVE  //  LOAD RAMP"), 1.4))
    for q in (25, 50, 75, 100, 125):
        seq.append((captioned(f"ramp_{q:03d}", f"Load {q} kN", fmt(f"ramp_{q:03d}"), RED, "LIVE  //  LOAD RAMP"), 0.8))
    seq.append((captioned("ramp_150", "Service load 150 kN", fmt("ramp_150"), RED, "LIVE  //  LOAD RAMP"), 2.2))
    for i, s in enumerate(["CHS 114.3x4", "CHS 139.7x5", "CHS 168.3x6.3", "CHS 193.7x8"]):
        ok = LOG[f"iter_{i}"]["status"] == "pass"
        seq.append((captioned(f"iter_{i}", f"Iteration {i + 1}: {s}", fmt(f"iter_{i}"), GREEN if ok else RED,
                              "SIZING LOOP  //  span_m = 6.2 m, limit L/250 = 24.8 mm"), 2.6 if ok else 1.4))
    seq.append((captioned("section_fail", "Section A-A, as drawn", fmt("section_fail"), RED, "SECTION  //  display_guids"), 2.0))
    seq.append((captioned("section_pass", "Section A-A, resized", fmt("section_pass"), GREEN, "SECTION  //  display_guids"), 2.4))
    split = Image.new("RGB", (W, H), INK)
    for x0, n, head, sub, acc in ((0, "karamba_114", "Karamba3D 3.1", "183.0 mm  ·  u 3.59", GREY),
                                  (W // 2, "native_114", "Almond native", "182.3 mm  ·  u 3.50", RED)):
        split.paste(still(n, (W // 2, H // 2)), (x0, 300))
        d = ImageDraw.Draw(split)
        label(d, (x0 + 40, 200), head, sub, acc)
    ImageDraw.Draw(split).text((40, 80), "SAME FRAME  //  SAME RESULT", font=font("bold", 56), fill=WHITE)
    seq.append((split, 4.0))
    seq.append((bench(), 5.0))
    seq.append((card([("Next", "h"), ("loads from asset passports", "m"), ("automatic section sizing", "m"),
                      ("design option comparison", "m")], accent=CYAN), 3.5))

    tmp = SRC / "video_frames"
    tmp.mkdir(exist_ok=True)
    for f in tmp.glob("*.png"):
        f.unlink()
    lst = []
    for i, (im, secs) in enumerate(seq):
        p = tmp / f"s_{i:02d}.png"
        im.save(p)
        lst.append(f"file '{p.as_posix()}'\nduration {secs}\n")
    lst.append(f"file '{(tmp / f's_{len(seq) - 1:02d}.png').as_posix()}'\n")
    (tmp / "list.txt").write_text("".join(lst))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(tmp / "list.txt"),
                    "-vf", f"fps={FPS},format=yuv420p", "-c:v", "libx264", "-crf", "18", "-preset", "slow",
                    "-movflags", "+faststart", str(VID)], check=True)
    print("wrote", VID, VID.stat().st_size // 1024, "KB")


def asset_loads_image():
    """Furniture from the asset library as loads: overlay + the applied placements."""
    rows = {r["name"]: r for r in json.loads((SRC / "assets_log.json").read_text())}
    r114, r193 = rows["assets_114"], rows["assets_193"]
    im = grid(["assets_114", "assets_193"],
              [("CHS 114.3x4", f'{r114["max_mm"]:.1f} mm / u {r114["util"]:.2f} / {r114["status"].upper()}', CYAN),
               ("CHS 193.7x8", f'{r193["max_mm"]:.1f} mm / u {r193["util"]:.2f} / {r193["status"].upper()}', CYAN)], 2,
              title="LOADS FROM ASSET PASSPORTS  //  validate_structure(asset_loads=True), placed furniture only")
    rep = r114["asset_loads"]
    applied = [p for p in rep["placements"] if "carried_by" in p]
    agg = {}
    for p in applied:
        a = agg.setdefault(p["asset_id"], [0, 0.0])
        a[0] += 1
        a[1] += p["dead_kn"] + p["imposed_kn"]
    h = 70 + 34 * (len(agg) + 2)
    out = Image.new("RGB", (im.width, im.height + h), INK)
    out.paste(im, (0, 0))
    d = ImageDraw.Draw(out)
    y = im.height + 10
    d.text((24, y), f'APPLIED {rep["applied"]} / SKIPPED {rep["skipped"]}  //  DEAD {rep["dead_kn"]:.2f} kN + IMPOSED '
                    f'{rep["imposed_kn"]:.2f} kN = {rep["total_kn"]:.2f} kN', font=font("ocr", 20), fill=CYAN)
    y += 44
    for aid, (n, kn) in sorted(agg.items(), key=lambda kv: -kv[1][1]):
        e = next(p for p in applied if p["asset_id"] == aid)
        d.text((24, y), f'{n} x {aid}', font=font("mono", 24), fill=WHITE)
        d.text((720, y), f'{kn:5.2f} kN   ({e["self_kg"]:g} kg self + {e["use_kg"]:g} kg {e["use"] or "-"})',
               font=font("mono", 24), fill=GREY)
        y += 34
    d.text((24, y + 6), "Ground-floor items and the study wing are outside this frame and reported as skipped.",
           font=font("mono", 22), fill=GREY)
    save(out, "asset-loads.jpg")


def floor_loads_image():
    rows = {r["name"]: r for r in json.loads((SRC / "floor_log.json").read_text())}
    a, b = rows["floor_193"], rows["floor_219"]
    fr = a["floor_loads"]
    lv = fr["levels"][0]
    im = grid(["floor_193", "floor_219"],
              [("CHS 193.7x8", f'{a["max_mm"]:.1f} mm / u {a["util"]:.2f} / {a["status"].upper()}', RED if a["status"] == "fail" else GREEN),
               ("CHS 219.1x8", f'{b["max_mm"]:.1f} mm / u {b["util"]:.2f} / {b["status"].upper()}', GREEN if b["status"] == "pass" else RED)], 2,
              title="FLOOR AREA LOADS  //  floor_load_kn_m2=2.0, floor_dead_kn_m2=1.0, every enclosed bay")
    out = Image.new("RGB", (im.width, im.height + 120), INK)
    out.paste(im, (0, 0))
    d = ImageDraw.Draw(out)
    d.text((24, im.height + 10), f'{lv["bays"]} BAYS / {fr["area_m2"]:.0f} m2 / {lv["bearing_walls"]} BEARING-WALL EDGES  //  '
                                 f'{fr["total_kn"]:.0f} kN ({fr["wall_kn"]:.1f} kN STRAIGHT INTO THE WALL)', font=font("ocr", 20), fill=CYAN)
    d.text((24, im.height + 52), "45-degree two-way distribution; members split at the load kinks, linear loads solved exactly.",
           font=font("mono", 22), fill=GREY)
    save(out, "floor-loads.jpg")


def combinations_image():
    """EN 1990 combinations: the same floor load, SLS deflection and ULS utilization, two sections."""
    rows = json.loads((SRC / "combo_log.json").read_text())
    pick = lambda d, basis, uls="6.10": next(r for r in rows if r["d"] == d and r["basis"] == basis and r["uls"] == uls)
    heads = []
    for d in (193.7, 219.1):
        en, un = pick(d, "en1990"), pick(d, "unfactored")
        heads.append((f"CHS {d}x8", f'SLS {en["max_mm"]:.1f} mm / ULS u {en["util"]:.2f} (unfactored {un["util"]:.2f}) / '
                                    f'{en["status"].upper()}', GREEN if en["status"] == "pass" else RED))
    im = grid(["combo_193", "combo_219"], heads, 2,
              title="LOAD COMBINATIONS  //  EN 1990: deflection at SLS G + Q, members at ULS 1.35G + 1.5Q")
    out = Image.new("RGB", (im.width, im.height + 80 + 30 * 12), INK)
    out.paste(im, (0, 0))
    d = ImageDraw.Draw(out)
    y = im.height + 12
    d.text((24, y), "FLOOR 2.0 kN/m2 IMPOSED (Q) + 1.0 kN/m2 BUILD-UP (G) + STEEL SELF WEIGHT (G)  //  62 m2", font=font("ocr", 20), fill=CYAN)
    y += 44
    for r in rows:
        if r["d"] in (168.3, 193.7, 219.1, 244.5):
            d.text((24, y), f'CHS {r["d"]}x{r["w"]:<5} {r["basis"]:10s} {r["uls"]:7s} SLS {r["max_mm"]:6.2f} mm   u {r["util"]:.3f}   '
                            f'{r["status"].upper()}', font=font("mono", 24), fill=WHITE if r["basis"] == "en1990" else GREY)
            y += 30
    save(out, "load-combinations.jpg")


def connections_image():
    rows = json.loads((SRC / "conn_log.json").read_text())
    names = [f'conn_{r["conn"]}_{int(r["d"])}' for r in rows]
    heads = [(f'{r["conn"].upper()}  /  CHS {r["d"]}x{r["w"]:g}',
              f'{r["max_mm"]:.1f} mm / u {r["util"]:.2f} / {r["pinned"]} pinned ends / {r["status"].upper()}',
              GREEN if r["status"] == "pass" else RED) for r in rows]
    im = grid(names, heads, 3, cell=(640, 360),
              title="CONNECTIONS  //  rigid joints vs simple (pinned) beam connections, floor 2.0 Q + 1.0 G kN/m2, EN 1990")
    out = Image.new("RGB", (im.width, im.height + 80), INK)
    out.paste(im, (0, 0))
    d = ImageDraw.Draw(out)
    d.text((24, im.height + 10), "Rigid joints flatter the joists: with simple connections CHS 219.1x8 fails; the next size tried, CHS 244.5x10, passes.",
           font=font("mono", 20), fill=WHITE)
    d.text((24, im.height + 42), "Circles: pinned ends. Pieces drawn along one line stay continuous; secondary beams pin into primaries and walls.",
           font=font("mono", 20), fill=GREY)
    save(out, "connections.jpg")


def stability_image():
    rows = {r["d"]: r for r in json.loads((SRC / "buckle_log.json").read_text())}
    a, b = rows[244.5], rows[114.3]
    im = grid(["buckle_244", "buckle_114"],
              [("CHS 244.5x10  /  STABLE", f'alpha_cr {a["alpha"]:.0f} / first-order / u {a["util"]:.2f} / {a["status"].upper()}', GREEN),
               ("CHS 114.3x4  /  SWAY-SENSITIVE", f'alpha_cr {b["alpha"]:.2f} / second-order P-Delta ({b["iterations"]} it.) / '
                                                  f'{b["status"].upper()}', (255, 200, 0))], 2,
              title="STABILITY  //  EN 1993-1-1 5.2: buckling mode 1 under ULS 6.10, simple connections")
    out = Image.new("RGB", (im.width, im.height + 80), INK)
    out.paste(im, (0, 0))
    d = ImageDraw.Draw(out)
    d.text((24, im.height + 10), "alpha_cr >= 10: first-order. 1-10: second-order (P-Delta) ULS with sway imperfections phi = 1/200 a_h a_m. <= 1: unstable.",
           font=font("mono", 20), fill=WHITE)
    d.text((24, im.height + 42), "Compression members are split into 4 elements for the geometric stiffness (1 element overstates alpha_cr by ~22 %).",
           font=font("mono", 20), fill=GREY)
    save(out, "stability.jpg")


if __name__ == "__main__":
    if "--stability" in sys.argv:
        stability_image()
        sys.exit()
    if "--connections" in sys.argv:
        connections_image()
        sys.exit()
    if "--combos" in sys.argv:
        combinations_image()
        sys.exit()
    if "--floor" in sys.argv:
        floor_loads_image()
        sys.exit()
    if "--assets" in sys.argv:
        asset_loads_image()
        sys.exit()
    images()
    if "--video" in sys.argv:
        video()
