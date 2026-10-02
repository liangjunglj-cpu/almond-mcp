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
         "tests/test_validate_engines.py", "tests/test_visualize_native.py", "tests/test_hand_calculations.py"]

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
    ("deflection limit ratio ignored by the overlay", "almond_mcp/structure_study.py",
     '"deflection_limit_ratio": limit_ratio}', '"deflection_limit_ratio": 250.0}'),
]


def run_tests():
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *TESTS],
                       cwd=ROOT, capture_output=True, text=True, timeout=900)
    return p.returncode, (p.stdout.strip().splitlines() or [""])[-1]


def main():
    code, tail = run_tests()
    print(f"baseline: exit {code} | {tail}", flush=True)
    if code != 0:
        sys.exit("baseline must pass")
    survived = []
    for name, rel, old, new in MUTANTS:
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
    print(f"\n{len(MUTANTS) - len(survived)}/{len(MUTANTS)} planted errors caught")


if __name__ == "__main__":
    main()
