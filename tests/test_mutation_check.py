"""tools/mutation_check.py plants its mutants whatever the checkout's line endings: a multi-line target
written with LF must match a CRLF file (Windows, core.autocrlf), and the mutant keeps the file's endings."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("mutation_check", ROOT / "tools" / "mutation_check.py")
mc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mc)

SOURCE = "def f(x):\n    if x:\n        return 1\n    return 0\n"
OLD, NEW = "    if x:\n        return 1\n", "    if False:\n        return 1\n"


def test_multi_line_target_matches_a_crlf_file_and_keeps_crlf():
    count, out = mc.mutate(SOURCE.replace("\n", "\r\n").encode("utf-8"), OLD, NEW)
    assert count == 1
    assert out == SOURCE.replace(OLD, NEW).replace("\n", "\r\n").encode("utf-8")


def test_lf_file_stays_lf():
    count, out = mc.mutate(SOURCE.encode("utf-8"), OLD, NEW)
    assert count == 1 and out == SOURCE.replace(OLD, NEW).encode("utf-8") and b"\r" not in out


def test_missing_or_repeated_target_is_not_planted():
    assert mc.mutate(SOURCE.encode("utf-8"), "    while x:\n", "") == (0, None)
    assert mc.mutate((SOURCE * 2).encode("utf-8"), OLD, NEW) == (2, None)


def test_every_mutant_target_occurs_exactly_once_in_this_checkout():
    """The skip the CRLF bug caused: every mutant must be plantable on this checkout, LF or CRLF."""
    for name, rel, old, new in mc.MUTANTS:
        count, _ = mc.mutate((ROOT / rel).read_bytes(), old, new)
        assert count == 1, (name, count)
