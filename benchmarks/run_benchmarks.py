"""Benchmark report: native solver vs OpenSees on every typology, plus validate() run time and memory.

    uv run --group bench python -m benchmarks.run_benchmarks [--scaling] [--json report.json]

Prints one table per check (linear, buckling, P-Delta) and, with ``--scaling``, the end-to-end
``validate()`` time and peak memory on moment frames of growing size (dense solver: time grows with
the cube of the degrees of freedom; the stability check splits compressed members in four)."""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from almond_mcp import frame_solver as fs  # noqa: E402
from almond_mcp import native_structure as ns  # noqa: E402
from benchmarks import opensees_ref as ref  # noqa: E402
from benchmarks.test_opensees_crosscheck import BUCKLING, LINEAR, PDELTA  # noqa: E402
from tests import structural_typologies as T  # noqa: E402

import numpy as np  # noqa: E402


def _ms(fn):
    t = time.perf_counter()
    out = fn()
    return out, (time.perf_counter() - t) * 1000.0


def linear_table():
    rows = []
    for cid, build, kw, combo, tol in LINEAR:
        c = build(**kw)
        f, k = c["frame"], c["combos"][combo]
        a, ta = _ms(lambda: ref.almond_linear(f, k))
        o, to = _ms(lambda: ref.linear(f, k))
        err = ref.compare(a, o, f)
        rows.append({"case": cid, "nodes": len(f.nodes), "elements": len(f.elements), "max_rel_error": max(err.values()),
                     "tolerance": tol, "almond_ms": ta, "opensees_ms": to, **err})
    return rows


def buckling_table():
    rows = []
    for cid, build, kw, combo, n_alm, n_ops, bars in BUCKLING:
        c = build(**kw)
        f, k = c["frame"], c["combos"][combo]
        a = fs.critical_load_factor(T.refined(f, n_alm), k)[0]
        o = ref.alpha_cr(T.refined(ref.bars_as_beams(f) if bars else f, n_ops), k)
        rows.append({"case": cid, "almond": a, "opensees": o, "diff_pct": (a / o - 1) * 100})
    return rows


def pdelta_table():
    rows = []
    for cid, build, combo in PDELTA:
        c = build()
        f, k = T.refined(c["frame"], 4), c["combos"][combo]
        a, o = fs.solve_second_order(f, k), ref.p_delta(f, k)
        first = fs.solve_linear(f, k)
        du = float(np.max(np.abs(a.displacements[:, :3] - o["U"][:, :3])) / np.max(np.abs(o["U"][:, :3])))
        rows.append({"case": cid, "amplification": a.max_displacement / first.max_displacement, "disp_rel_error": du,
                     "iterations": a.iterations})
    return rows


def _spec(sec):
    if sec.shape == "chs":
        d, t = sec.dims_mm
        return {"shape": "circular_hollow", "diameter": d / 1000, "wall": t / 1000}
    h, b, t = sec.dims_mm
    return {"shape": "box", "height": h / 1000, "width": b / 1000, "wall": t / 1000}


def to_model(frame) -> dict:
    """The bridge's conditioned-model JSON for a frame of hollow sections (supports = anchor points)."""
    X = np.asarray(frame.nodes)
    members = [{"points": [X[e.n1].tolist(), X[e.n2].tolist()], "section": _spec(e.section), "source_guids": [f"g{i}"]}
               for i, e in enumerate(frame.elements)]
    spans = [math.dist(*m["points"]) for m in members]
    return {"members": members, "anchor_points": [X[n].tolist() for n, f in frame.supports.items() if f[2]],
            "tolerance_m": 0.001, "max_member_span_m": max(spans), "max_span_m": float(np.max(np.ptp(X, axis=0))),
            "warnings": []}


def scaling_table(sizes):
    rows = []
    for bx, by, st in sizes:
        f = T.moment_frame(bx, by, st)["frame"]
        tracemalloc.start()
        out, t = _ms(lambda: ns.validate(to_model(f), "frame", 0, "S355", floor_loads={"imposed": 3.0, "dead": 4.0}))
        peak = tracemalloc.get_traced_memory()[1] / 1e6
        tracemalloc.stop()
        r = out["results"]
        rows.append({"frame": f"{bx}x{by} bays x {st} storeys", "members": len(f.elements), "solved_nodes": r.get("nodes"),
                     "validate_s": t / 1000, "peak_mb": peak, "method": (r.get("stability") or {}).get("method")})
        print(f"  {rows[-1]}", flush=True)
    return rows


def _print(title, rows, cols):
    print(f"\n{title}")
    print("  " + " | ".join(f"{c:>14s}" for c in cols))
    for r in rows:
        print("  " + " | ".join(f"{r[c]:>14.3e}" if isinstance(r[c], float) else f"{str(r[c]):>14s}" for c in cols))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scaling", action="store_true", help="also time validate() on growing moment frames")
    ap.add_argument("--json", type=Path, help="write the report as JSON")
    args = ap.parse_args(argv)
    report = {"linear": linear_table()}
    _print("Linear vs OpenSees (largest difference / largest value)", report["linear"],
           ["case", "nodes", "elements", "max_rel_error", "almond_ms", "opensees_ms"])
    report["buckling"] = buckling_table()
    _print("Elastic critical load factor alpha_cr", report["buckling"], ["case", "almond", "opensees", "diff_pct"])
    report["p_delta"] = pdelta_table()
    _print("Second order (P-Delta)", report["p_delta"], ["case", "amplification", "disp_rel_error", "iterations"])
    if args.scaling:
        print("\nvalidate() run time and peak memory")
        report["scaling"] = scaling_table([(1, 1, 2), (2, 1, 3), (2, 2, 4), (3, 2, 6)])
    if args.json:
        args.json.write_text(json.dumps(report, indent=1, default=float))
    bad = [r["case"] for r in report["linear"] if r["max_rel_error"] > r["tolerance"]]
    bad += [r["case"] for r in report["buckling"] if abs(r["diff_pct"]) > 1.0]
    print("\nAll checks within tolerance." if not bad else f"\nOutside tolerance: {', '.join(bad)}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
