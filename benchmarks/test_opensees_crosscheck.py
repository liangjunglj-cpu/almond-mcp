"""Native frame solver vs OpenSees on twelve building typologies (linear, buckling, P-Delta).

Skipped unless OpenSeesPy is installed (``uv sync --group bench``); see benchmarks/README.md."""
import pytest

pytest.importorskip("openseespy.opensees", reason="OpenSeesPy not installed (uv sync --group bench)")

import numpy as np  # noqa: E402

from almond_mcp import frame_solver as fs  # noqa: E402
from benchmarks import opensees_ref as ref  # noqa: E402
from tests import structural_typologies as T  # noqa: E402

# (case id, builder, kwargs, combination, tolerance). Models with member end releases use penalty links
# in OpenSees (zeroLength, k = 1e12), which costs a few significant figures.
LINEAR = [
    ("moment frame", T.moment_frame, {}, "ULS wind", 1e-9),
    ("braced tower", T.braced_tower, {"storeys": 6}, "ULS wind", 1e-3),
    ("Pratt truss", T.pratt_truss, {}, "Q", 1e-9),
    ("portal", T.portal_2d, {}, "Q", 1e-9),
    ("warehouse", T.warehouse, {}, "ULS snow", 1e-3),
    ("space grid", T.space_grid, {}, "ULS", 1e-9),
    ("arch", T.arch, {}, "Q", 1e-9),
    ("L-bracket", T.l_bracket, {}, "Q", 1e-9),
    ("canopy", T.canopy, {}, "ULS", 1e-9),
    ("diagrid", T.diagrid, {}, "ULS wind", 1e-9),
    ("Vierendeel", T.vierendeel, {}, "ULS", 1e-9),
    ("mixed supports", T.mixed_supports, {}, "ULS wind", 1e-9),
]


@pytest.mark.parametrize("cid,build,kw,combo,tol", LINEAR, ids=[c[0] for c in LINEAR])
def test_linear_matches_opensees(cid, build, kw, combo, tol):
    c = build(**kw)
    f, k = c["frame"], c["combos"][combo]
    a, o = ref.almond_linear(f, k), ref.linear(f, k)
    errors = ref.compare(a, o, f)
    assert max(errors.values()) < tol, errors
    assert a["result"].equilibrium_error() < 1e-6


# (case id, builder, kwargs, combination, Almond elements per member, OpenSees elements per member,
#  bars as PDelta beams in OpenSees). OpenSees' PDelta transformation has no in-member P-delta term, so
# it needs a finer mesh than Almond's consistent geometric stiffness for the same accuracy.
BUCKLING = [
    ("portal", T.portal_2d, {}, "Q", 8, 32, False),
    ("Vierendeel", T.vierendeel, {}, "ULS", 8, 32, False),
    ("arch pinned", T.arch, {}, "Q", 4, 4, False),
    ("arch fixed", T.arch, {"ends": "fixed"}, "Q", 4, 4, False),
    ("canopy", T.canopy, {}, "ULS", 8, 16, False),
    ("diagrid", T.diagrid, {"levels": 4, "nseg": 8}, "ULS wind", 4, 8, False),
    ("moment frame", T.moment_frame, {"bx": 2, "by": 1, "storeys": 3}, "ULS wind", 4, 8, False),
    ("Pratt truss", T.pratt_truss, {}, "Q", 1, 1, True),
    ("space grid", T.space_grid, {"nx": 8}, "ULS", 1, 1, True),
    ("mixed supports", T.mixed_supports, {}, "ULS wind", 8, 16, False),
]


@pytest.mark.parametrize("cid,build,kw,combo,n_alm,n_ops,bars", BUCKLING, ids=[c[0] for c in BUCKLING])
def test_critical_load_factor_matches_opensees(cid, build, kw, combo, n_alm, n_ops, bars):
    c = build(**kw)
    f, k = c["frame"], c["combos"][combo]
    a, _ = fs.critical_load_factor(T.refined(f, n_alm), k)
    o = ref.alpha_cr(T.refined(ref.bars_as_beams(f) if bars else f, n_ops), k)
    assert a == pytest.approx(o, rel=0.01)


@pytest.mark.xfail(strict=True, reason="known: the torsional (Wagner) geometric stiffness has no warping term, so "
                   "open I-sections show a spurious low torsional mode; the Rhino bridge exports hollow/solid sections only")
def test_open_section_frame_buckling_matches_opensees():
    c = T.moment_frame(bx=2, by=1, storeys=2, open_sections=True)
    f, k = c["frame"], c["combos"]["ULS wind"]
    a, _ = fs.critical_load_factor(T.refined(f, 4), k)
    assert a == pytest.approx(ref.alpha_cr(T.refined(f, 8), k), rel=0.02)


def _arch_with_lateral():
    c = T.arch()
    for nd in c["nodes"][1:-1]:
        c["frame"].load(nd, fx=2.0, case="W")
    c["combos"] = {"near buckling": {"Q": 1.6, "W": 1.0}}
    return c


PDELTA = [
    ("moment frame", lambda: T.moment_frame(bx=2, by=1, storeys=4), "ULS wind"),
    ("canopy", T.canopy, "ULS"),
    ("arch near buckling", _arch_with_lateral, "near buckling"),
    ("portal x6 load", lambda: T.portal_2d(w=36.0), "Q"),
    ("mixed supports", T.mixed_supports, "ULS wind"),
]


@pytest.mark.parametrize("cid,build,combo", PDELTA, ids=[c[0] for c in PDELTA])
def test_second_order_matches_opensees(cid, build, combo):
    c = build()
    f, k = T.refined(c["frame"], 4), c["combos"][combo]
    a = fs.solve_second_order(f, k)
    o = ref.p_delta(f, k)
    assert a.converged
    du = np.max(np.abs(a.displacements[:, :3] - o["U"][:, :3])) / np.max(np.abs(o["U"][:, :3]))
    EF = np.array([er.end_forces for er in a.elements])
    m = [i for i, e in enumerate(f.elements) if not e.truss]
    dm = np.max(np.abs(EF[m][:, [4, 5, 10, 11]] - o["EF"][m][:, [4, 5, 10, 11]])) / np.max(np.abs(o["EF"][m][:, [4, 5, 10, 11]]))
    assert du < 0.01 and dm < 0.01, (du, dm)
