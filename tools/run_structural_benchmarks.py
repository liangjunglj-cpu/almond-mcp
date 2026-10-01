"""Print the native solver's benchmark table (closed-form + Karamba cross-check) as Markdown.

    uv run python tools/run_structural_benchmarks.py

The same cases are asserted in tests/test_frame_solver.py and tests/test_native_structure.py;
this script only renders the numbers for docs/native-solver.md."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from almond_mcp import frame_solver as fs          # noqa: E402
from almond_mcp import native_structure as ns      # noqa: E402

STEEL, SEC = fs.material("Steel"), fs.chs(114.3, 4.0)
EI, EA = STEEL.E * SEC.Iy, STEEL.E * SEC.A


def beam(n, L, supports, loads=(), udl=0.0):
    f = fs.Frame()
    ids = [f.add_node((L * i / n, 0, 0)) for i in range(n + 1)]
    for i in range(n):
        f.add_element(ids[i], ids[i + 1], SEC, STEEL)
        if udl:
            f.udl(i, (0, 0, -udl))
    for k, flags in supports:
        f.fix(ids[k if k >= 0 else n], flags)
    for k, fz in loads:
        f.load(ids[k if k >= 0 else n], fz=fz)
    return f, ids


def closed_form():
    pin, roll, fix = (True, True, True, True, False, False), (False, True, True, False, False, False), (True,) * 6
    rows = []
    f, ids = beam(1, 3.0, [(0, fix)], [(-1, -10.0)])
    rows.append(("Cantilever, tip load 10 kN, 3 m", "PL³/3EI", 10 * 27 / (3 * EI), -fs.solve(f).displacements[ids[-1], 2]))
    f, ids = beam(1, 4.0, [(0, fix)], udl=5.0)
    rows.append(("Cantilever, UDL 5 kN/m, 4 m (1 element)", "wL⁴/8EI", 5 * 256 / (8 * EI), -fs.solve(f).displacements[ids[-1], 2]))
    f, ids = beam(2, 6.0, [(0, pin), (-1, roll)], udl=8.0)
    rows.append(("Simply supported, UDL 8 kN/m, 6 m", "5wL⁴/384EI", 5 * 8 * 6 ** 4 / (384 * EI), -fs.solve(f).displacements[ids[1], 2]))
    f, ids = beam(2, 5.0, [(0, pin), (-1, roll)], [(1, -12.0)])
    rows.append(("Simply supported, midspan 12 kN, 5 m", "PL³/48EI", 12 * 125 / (48 * EI), -fs.solve(f).displacements[ids[1], 2]))
    f, ids = beam(2, 5.0, [(0, fix), (-1, fix)], udl=6.0)
    rows.append(("Fixed-fixed, UDL 6 kN/m, 5 m", "wL⁴/384EI", 6 * 625 / (384 * EI), -fs.solve(f).displacements[ids[1], 2]))
    f = fs.Frame(); a, b, c = f.add_node((0, 0, 0)), f.add_node((4, 0, 0)), f.add_node((2, 0, 1.5))
    f.add_element(a, c, SEC, STEEL, truss=True); f.add_element(c, b, SEC, STEEL, truss=True)
    f.pin(a); f.pin(b); f.fix(c, (False, True, False, False, False, False)); f.load(c, fz=-20.0)
    L = math.hypot(2, 1.5); sa = 1.5 / L
    rows.append(("Two-bar truss, apex 20 kN", "PL/2EA·sin²α", 20 * L / (2 * EA * sa ** 2), -fs.solve(f).displacements[c, 2]))
    return rows


def karamba():
    ref = json.loads((ROOT / "tests" / "data" / "karamba_reference.json").read_text())
    rows = []
    for case in ref["cases"]:
        mm = lambda p: [v / 1000 for v in p]
        spans = [math.dist(mm(m[0]), mm(m[1])) for m in case["members"]]
        model = {"members": [{"source_guids": [str(i)], "points": [mm(p) for p in m]} for i, m in enumerate(case["members"])],
                 "anchor_points": [mm(p) for p in case["anchors"]], "tolerance_m": 0.001,
                 "max_member_span_m": max(spans), "max_span_m": max(spans)}
        for run in case["runs"]:
            frame, _, _ = ns.build_frame(model, run["load_kn"], "Steel", case["fixed_supports"], True, *run["section"])
            r = fs.solve(frame)
            ku = run.get("max_utilization") or max(run["utilization"])
            rows.append((case["id"], "CHS %g×%g" % tuple(run["section"]), run["load_kn"], run["max_displacement_mm"],
                         r.max_displacement * 1000, ku, r.max_utilization))
    return rows, ref["provenance"]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    print("| Case | Closed form | Exact (mm) | Native (mm) | Error |\n| --- | --- | ---: | ---: | ---: |")
    for name, formula, exact, got in closed_form():
        print(f"| {name} | {formula} | {exact * 1000:.4f} | {got * 1000:.4f} | {abs(got / exact - 1):.1e} |")
    rows, prov = karamba()
    print(f"\nKaramba reference: {prov['engine']}, {prov['date']}.\n")
    print("| Model | Section | Load (kN) | Karamba δ (mm) | Native δ (mm) | Δ | Karamba u | Native u | Δ |")
    print("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for cid, sec, load, kd, nd, ku, nu in rows:
        print(f"| {cid} | {sec} | {load:g} | {kd:.2f} | {nd:.2f} | {100 * (nd / kd - 1):+.1f}% | {ku:.3f} | {nu:.3f} | {100 * (nu / ku - 1):+.1f}% |")


if __name__ == "__main__":
    main()
