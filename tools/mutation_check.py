"""Mutation check of the structural test suite: does it catch real engineering mistakes?

Plants one known error at a time (a wrong factor, a dropped term, a wrong table column), runs the
structural tests, and reports CAUGHT (a test failed) or MISSED (every test passed). Every file is
restored from its original bytes after each run, also on failure. Run from the repo root:

    uv run python tools/mutation_check.py

Add a mutant whenever a new structural feature lands; a MISSED line means the tests need a case."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ["tests/test_frame_solver.py", "tests/test_native_structure.py", "tests/test_load_combinations.py",
         "tests/test_end_releases.py", "tests/test_stability.py", "tests/test_floor_loads.py",
         "tests/test_asset_loads.py", "tests/test_design_codes.py", "tests/test_structure_study.py",
         "tests/test_validate_engines.py", "tests/test_visualize_native.py", "tests/test_hand_calculations.py", "tests/test_ec3.py"]

MUTANTS = [
    ("load factor gamma_G 1.35 -> 1.30", "almond_mcp/code_profiles/eurocode.json", '"gamma_G": {"value": 1.35', '"gamma_G": {"value": 1.30'),
    ("6.10b reduction xi 0.85 -> 0.925", "almond_mcp/code_profiles/eurocode.json", '"xi": {"value": 0.85', '"xi": {"value": 0.925'),
    ("psi_0 0.7 -> 0.5", "almond_mcp/code_profiles/eurocode.json", '"psi_0": {"value": 0.7', '"psi_0": {"value": 0.5'),
    ("buckling curve a imperfection 0.21 -> 0.34", "almond_mcp/frame_solver.py", '"a": 0.21', '"a": 0.34'),
    ("gamma_M1 ignored in member buckling", "almond_mcp/frame_solver.py",
     "buck = ncomp / (chi * s.A * fy / gamma_m1)", "buck = ncomp / (chi * s.A * fy)"),
    ("geometric stiffness 36 -> 30 (wrong K_G)", "almond_mcp/frame_solver.py",
     "v = c * np.array([[36, 3 * L, -36, 3 * L]", "v = c * np.array([[30, 3 * L, -30, 3 * L]"),
    ("sway imperfection phi_0 1/200 -> 1/300", "almond_mcp/native_structure.py", "PHI_0 = 1 / 200", "PHI_0 = 1 / 300"),
    ("alpha_cr first-order threshold 10 -> 5", "almond_mcp/native_structure.py",
     "ALPHA_CR_FIRST_ORDER = 10.0", "ALPHA_CR_FIRST_ORDER = 5.0"),
    ("imperfection only in +x (no -x/+y/-y)", "almond_mcp/native_structure.py",
     'for label, axis, sign in (("+x", 0, 1), ("-x", 0, -1), ("+y", 1, 1), ("-y", 1, -1)):',
     'for label, axis, sign in (("+x", 0, 1),):'),
    ("two-way / one-way switch at 2:1 -> 3:1", "almond_mcp/floor_loads.py", "if l / s > 2.0:", "if l / s > 3.0:"),
    ("two-way 45-degree peak q*s/2 -> q*s/3", "almond_mcp/floor_loads.py",
     "pts = [(0.0, 0.0), (r, q * s / 2), (1 - r, q * s / 2), (1.0, 0.0)]",
     "pts = [(0.0, 0.0), (r, q * s / 3), (1 - r, q * s / 3), (1.0, 0.0)]"),
    ("results table: shear only at element start", "almond_mcp/native_structure.py",
     "V = max(max(math.hypot(ef[1], ef[2]), math.hypot(ef[7], ef[8]))", "V = max(max(math.hypot(ef[1], ef[2]), 0.0)"),
    ("results table: supports lose ULS reactions", "almond_mcp/native_structure.py",
     '"uls": {name: forces(r_, n) for name, _, r_ in ulss}}', '"uls": {}}'),
    ("results table: deflection = absolute movement", "almond_mcp/native_structure.py",
     "sag = float(np.max(np.linalg.norm(disp - (np.outer(1 - t, dA) + np.outer(t, dB)), axis=1)))",
     "sag = float(np.max(np.linalg.norm(disp, axis=1)))"),
    ("Annex B class-3 kyy 0.6 -> 0.3", "almond_mcp/ec3.py",
     "kyy = cm_y * min(1 + 0.6 * lam_y * n_y, 1 + 0.6 * n_y)", "kyy = cm_y * min(1 + 0.3 * lam_y * n_y, 1 + 0.3 * n_y)"),
    ("Table B.3 Cm floor 0.4 -> 0.2", "almond_mcp/ec3.py", "return max(0.4, 0.6 + 0.4 * psi)", "return max(0.2, 0.6 + 0.4 * psi)"),
    ("cold-formed tubes on the hot-finished curve", "almond_mcp/ec3.py",
     'if fabrication == "hot_finished":', "if True:"),
    ("CHS class-3 limit not scaled by fy", "almond_mcp/ec3.py",
     "3 if r <= 90 * eps ** 2 else 4", "3 if r <= 90 else 4"),
    ("buckling length = analysis element, not member", "almond_mcp/ec3.py",
     'out.setdefault(e.group if getattr(e, "group", None) is not None else i, []).append(i)',
     "out.setdefault(i, []).append(i)"),
    ("deflection limit ratio ignored by the overlay", "almond_mcp/structure_study.py",
     '"deflection_limit_ratio": limit_ratio}', '"deflection_limit_ratio": 250.0}'),
    # 6.2.6 shear, 6.2.8 bending and shear
    ("V_pl,Rd without the 1/sqrt(3)", "almond_mcp/ec3.py",
     "vpl_y, vpl_z = (a * fy / math.sqrt(3) / gamma_m0 for a in (av_y, av_z))",
     "vpl_y, vpl_z = (a * fy / gamma_m0 for a in (av_y, av_z))"),
    ("RHS shear areas swapped (h <-> b)", "almond_mcp/ec3.py",
     "return A * b / (b + h), A * h / (b + h)", "return A * h / (b + h), A * b / (b + h)"),
    ("I shear area loses the tw tf term", "almond_mcp/ec3.py",
     "max(A - 2 * b * tf + tw * tf, eta * hw * tw)", "max(A - 2 * b * tf, eta * hw * tw)"),
    ("CHS shear area 2A/pi -> A/pi", "almond_mcp/ec3.py",
     "return 2 * A / math.pi, 2 * A / math.pi", "return A / math.pi, A / math.pi"),
    ("shear buckling limit 72 eps -> 60 eps", "almond_mcp/ec3.py",
     "return r is not None and r > 72 * epsilon(fy) / eta", "return r is not None and r > 60 * epsilon(fy) / eta"),
    ("high-shear threshold 0.5 V_pl -> 0.6 V_pl", "almond_mcp/ec3.py",
     "np.where(r > 0.5, np.minimum((2 * r - 1) ** 2, 1.0), 0.0)", "np.where(r > 0.6, np.minimum((2 * r - 1) ** 2, 1.0), 0.0)"),
    ("rho not squared", "almond_mcp/ec3.py",
     "np.where(r > 0.5, np.minimum((2 * r - 1) ** 2, 1.0), 0.0)", "np.where(r > 0.5, np.minimum((2 * r - 1), 1.0), 0.0)"),
    ("(6.30) A_w^2/(4 tw) -> A_w^2/(6 tw)", "almond_mcp/ec3.py",
     "web = hw ** 2 * tw / 4 if use_plastic", "web = hw ** 2 * tw / 6 if use_plastic"),
    ("shear ignored: moment not reduced by 6.2.8", "almond_mcp/ec3.py",
     "        Wy, Wz = _reduced_moduli(s, Wy, Wz, use_plastic, rho_y, rho_z)\n", ""),
    ("shear diagram ignores the member load", "almond_mcp/frame_solver.py",
     "Vz = -(fl[2] + wa[2] * x + (wb[2] - wa[2]) * x ** 2 / (2 * L))", "Vz = -(fl[2] + 0.0 * x)"),
    # 5.3.2(6) local bow imperfections
    ("Table 5.1 curve c e0 L/200 -> L/250", "almond_mcp/ec3.py",
     'BOW_ELASTIC = {"a0": 350, "a": 300, "b": 250, "c": 200, "d": 150}',
     'BOW_ELASTIC = {"a0": 350, "a": 300, "b": 250, "c": 250, "d": 150}'),
    ("bow condition 0.5 sqrt(A fy/N) -> 0.25", "almond_mcp/ec3.py",
     "limit = 0.5 * math.sqrt(section.A * fy / n_ed)", "limit = 0.25 * math.sqrt(section.A * fy / n_ed)"),
    ("bow equivalent load 8 N e0/L^2 -> 4", "almond_mcp/native_structure.py",
     'w[ei] = w.get(ei, np.zeros(3)) + 8 * N * ax["e0"] / L ** 2 * v', 'w[ei] = w.get(ei, np.zeros(3)) + 4 * N * ax["e0"] / L ** 2 * v'),
    ("bow needs no moment-resistant end", "almond_mcp/native_structure.py",
     "if not any(_moment_resistant(frame, at, n, own, el, axis) for n, el in zip((A, B), ends)):",
     "if False:"),
    ("bows left out of the second-order analysis", "almond_mcp/native_structure.py",
     "            if bows and label:                                  # bows bulge the way the frame sways\n",
     "            if False:\n"),
    # 5.3.2(3)b sway imperfection m
    ("m counts every column (no 50 % rule)", "almond_mcp/native_structure.py",
     "ms.append(sum(1 for k in row if load[k] >= 0.5 * avg) if avg > 0 else len(row))",
     "ms.append(len(row))"),
    ("m over the whole plan, not per row", "almond_mcp/native_structure.py",
     "for row in _rows([k[1 - axis] for k in keys]):", "for row in [list(range(len(keys)))]:"),
    # floor loads above 2:1
    ("bays above 2:1: short beams unloaded again", "almond_mcp/floor_loads.py",
     "if r < 0.5 else [(0.0, 0.0), (0.5, q * L / 2), (1.0, 0.0)]", "if r < 0.5 else [(0.0, 0.0), (1.0, 0.0)]"),
]


def run_tests():
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *TESTS],
                       cwd=ROOT, capture_output=True, text=True, timeout=900)
    return p.returncode, (p.stdout.strip().splitlines() or [""])[-1]


def main():
    only = [a.lower() for a in sys.argv[1:]]          # optional: run only mutants whose name contains one of these
    code, tail = run_tests()
    print(f"baseline: exit {code} | {tail}", flush=True)
    if code != 0:
        sys.exit("baseline must pass")
    survived = []
    for name, rel, old, new in MUTANTS:
        if only and not any(o in name.lower() for o in only):
            continue
        path = ROOT / rel
        original = path.read_bytes()
        text = original.decode("utf-8")
        if text.count(old) != 1:
            print(f"SKIP {name}: target found {text.count(old)} times", flush=True)
            continue
        try:
            path.write_bytes(text.replace(old, new).encode("utf-8"))
            code, tail = run_tests()
        finally:
            path.write_bytes(original)
        caught = code != 0
        if not caught:
            survived.append(name)
        print(f"{'CAUGHT  ' if caught else 'MISSED  '} {name} | {tail}", flush=True)
    ran = [m for m in MUTANTS if not only or any(o in m[0].lower() for o in only)]
    print(f"\n{len(ran) - len(survived)}/{len(ran)} planted errors caught")


if __name__ == "__main__":
    main()
