"""Curved members and member spans on real Grasshopper geometry (2026-10-20 GH stress test, findings 1-2).

The bridge polylines every curve to the document tolerance, so a gently curved diagonal arrives as dozens
of vertices. The analysis discretises each curved piece to chords within 1/CURVE_SAGITTA_RATIO of its
length instead, refuses models beyond the dense solver with a clear error, and checks every member's
deflection against its own span (the drawn member between its supports), not the longest piece."""
import math
import time

import numpy as np
import pytest

from almond_mcp import frame_solver as fs
from almond_mcp import native_structure as ns

DIAGONAL = {"shape": "circular_hollow", "diameter": 0.1683, "wall": 0.008}
RIB = DIAGONAL
PURLIN = {"shape": "circular_hollow", "diameter": 0.1143, "wall": 0.005}


def diagrid_vault(per_piece, R=5.2, length=6.0, nu=6, nv=6):
    """A diagrid on a half cylinder (span 2R): helical diagonals, cut into pieces at their crossings as
    the bridge exports them, each piece polylined with ``per_piece`` chords."""
    def P(u, v):
        th = math.pi * (u - 0.5)
        return [R * math.sin(th), length * v, R * math.cos(th)]
    members = []
    for i in range(nu):
        for j in range(0, nv + 1):
            if (i + j) % 2:
                continue
            for dj, tag in ((1, f"p{j - i}"), (-1, f"m{j + i}")):
                if 0 <= j + dj <= nv:
                    pts = [P((i + t) / nu, (j + dj * t) / nv) for t in np.linspace(0, 1, per_piece + 1)]
                    members.append({"source_guids": [tag], "points": pts, "section": DIAGONAL})
    piece = max(math.dist(m["points"][0], m["points"][-1]) for m in members)
    return {"members": members, "tolerance_m": 0.001, "max_member_span_m": piece, "max_span_m": 2 * R, "warnings": []}


def rib_vault(per_piece, span=10.4, rise=3.0, length=12.0, ribs=7, panels=6):
    """Barrel vault: circular ribs, each one curve cut into pieces at the purlins, and straight purlins."""
    R = (span ** 2 / 4 + rise ** 2) / (2 * rise)
    half = math.asin(span / 2 / R)
    th_j = np.linspace(-half, half, panels + 1)
    arc = lambda t, y: [R * math.sin(t), y, R * math.cos(t) - (R - rise)]
    members = []
    for r in range(ribs):
        y = length * r / (ribs - 1)
        for k in range(panels):
            members.append({"source_guids": [f"rib{r}"], "section": RIB,
                            "points": [arc(t, y) for t in np.linspace(th_j[k], th_j[k + 1], per_piece + 1)]})
    for k in range(panels + 1):
        for r in range(ribs - 1):
            members.append({"source_guids": [f"purlin{k}"], "section": PURLIN,
                            "points": [arc(th_j[k], length * r / (ribs - 1)), arc(th_j[k], length * (r + 1) / (ribs - 1))]})
    piece = max(math.dist(m["points"][0], m["points"][-1]) for m in members)
    return {"members": members, "tolerance_m": 0.001, "max_member_span_m": piece, "max_span_m": span, "warnings": []}


def _numbers(out):
    r = out["results"]
    return (r["max_displacement_mm"], r["largest_deflection_mm"], r["utilization_ratio"], r["stability"]["min_alpha_cr"])


# --- finding 1: curved members --------------------------------------------------------------------------

def test_curved_diagrid_matches_the_finely_discretised_reference_with_far_fewer_nodes():
    model = diagrid_vault(12)
    load = 1.5 * 10.4 * 6.0
    fine = ns.validate(model, "frame", load, curve_ratio=None)
    coarse = ns.validate(model, "frame", load)
    assert fine["status"] == coarse["status"] == "pass"
    for a, b in zip(_numbers(coarse), _numbers(fine)):
        assert a == pytest.approx(b, rel=0.01)
    assert coarse["results"]["nodes"] < fine["results"]["nodes"] / 2
    assert any("curved member piece" in w for w in coarse["warnings"])


def test_curved_ribs_match_the_reference_and_check_against_the_rib_span():
    model = rib_vault(24)
    load = 1.5 * 10.4 * 12.0
    fine = ns.validate(model, "frame", load, curve_ratio=None, detail=True)
    coarse = ns.validate(model, "frame", load, detail=True)
    a, b = _numbers(coarse), _numbers(fine)
    assert a[0] == pytest.approx(b[0], rel=0.01) and a[1] == pytest.approx(b[1], rel=0.01)
    assert a[2] == pytest.approx(b[2], rel=0.02) and a[3] == pytest.approx(b[3], rel=0.01)
    assert coarse["results"]["nodes"] < fine["results"]["nodes"] / 3
    ribs = [m for m in coarse["members"] if m["source_guids"][0].startswith("rib")]
    assert ribs and all(m["deflection_span_m"] == pytest.approx(10.4, rel=1e-3) for m in ribs)   # not the 1.9 m piece


def test_lone_arch_load_is_spread_along_it_and_matches_the_reference():
    """An arch drawn as one curve between its supports has no free joint: load_kn runs along it."""
    R, rise = 12.5, 5.0
    half = math.asin(10.0 / R)
    pts = [[R * math.sin(t), 0.0, R * math.cos(t) - (R - rise)] for t in np.linspace(-half, half, 481)]
    model = {"members": [{"source_guids": ["arch"], "points": pts,
                          "section": {"shape": "circular_hollow", "diameter": 0.3239, "wall": 0.010}}],
             "anchor_points": [pts[0], pts[-1]], "tolerance_m": 0.001, "max_member_span_m": 20.0,
             "max_span_m": 20.0, "warnings": []}
    frame, info, _ = ns.build_frame(model, 50.0, "Steel")
    assert len(frame.nodes) <= ns.MAX_CURVE_SEGMENTS + 1
    assert sum(w[2] * math.dist(frame.nodes[frame.elements[ei].n1], frame.nodes[frame.elements[ei].n2])
               for ei, w, _, c in frame.member_loads if c == "Q") == pytest.approx(-50.0)
    fine = ns.validate(model, "frame", 50.0, curve_ratio=None)
    coarse = ns.validate(model, "frame", 50.0)
    assert coarse["results"]["max_displacement_mm"] == pytest.approx(fine["results"]["max_displacement_mm"], rel=0.01)
    assert coarse["results"]["stability"]["min_alpha_cr"] == pytest.approx(fine["results"]["stability"]["min_alpha_cr"], rel=0.01)


def test_simplify_curve_resamples_smooth_runs_and_keeps_joints_corners_and_drawn_nodes():
    arc = [[math.cos(t), math.sin(t), 0.0] for t in np.linspace(0, math.pi / 2, 91)]
    out, joints = ns.simplify_curve(arc, ratio=500)
    assert out[0] is arc[0] and out[-1] is arc[-1] and not joints
    chords = [math.dist(a, b) for a, b in zip(out, out[1:])]
    assert max(chords) == pytest.approx(min(chords), rel=1e-3)                  # equal arc length
    assert 2 < len(out) - 1 <= math.ceil((math.pi / 2) / ns.MAX_CURVE_TURN) + 1
    out, joints = ns.simplify_curve(arc, keep={45}, ratio=500)
    assert arc[45] in out and joints == {out.index(arc[45])}                   # a member lands there
    straight = [[0, 0, 0], [3, 0, 0], [6, 0, 0]]                                 # a node drawn on purpose
    assert ns.simplify_curve(straight)[0] == straight
    portal = [[0, 0, 0], [0, 0, 4], [6, 0, 5], [12, 0, 4], [12, 0, 0]]          # corners
    assert ns.simplify_curve(portal)[0] == portal
    assert ns.simplify_curve(arc, ratio=None)[0] == arc


def test_curved_run_is_one_member_for_the_checks_and_is_not_split_again():
    frame, _, _ = ns.build_frame(rib_vault(24), 10.0, max_curve_segments=2)
    ribs = [e for e in frame.elements if e.tag[0].startswith("rib")]
    purlins = [e for e in frame.elements if e.tag[0].startswith("purlin")]
    assert len(ribs) == 7 * 6 * 2 and all(e.group is not None for e in ribs) and all(e.group is None for e in purlins)
    assert len({e.group for e in ribs}) == 7 * 6                                # one member per rib piece
    plan = ns._split_plan(frame, ns.STABILITY_SUBDIVISION)
    # each chord of a 2-chord piece splits in 2 (4 elements per piece, like a straight member); purlins in 4
    assert {k for ei, k in plan.items() if frame.elements[ei].group is not None} == {2}
    assert {k for ei, k in plan.items() if frame.elements[ei].group is None} == {4}


def test_oversize_model_returns_an_error_result_instead_of_raising():
    n = 56                                                                      # a 56 x 56 grillage: 3136 nodes
    members = [{"source_guids": [f"x{j}"], "points": [[i, j, 3.0] for i in range(n)]} for j in range(n)]
    members += [{"source_guids": [f"y{i}"], "points": [[i, j, 3.0] for j in range(n)]} for i in range(n)]
    model = {"members": members, "anchor_points": [[0, 0, 3.0], [n - 1, 0, 3.0], [0, n - 1, 3.0]],
             "tolerance_m": 0.001, "max_member_span_m": 1.0, "max_span_m": n, "warnings": []}
    out = ns.validate(model, "frame", 100.0)
    assert out["status"] == "error" and out["passed"] is False
    assert "too large for the dense solver" in out["verdict"] and "3136 nodes" in out["verdict"]
    size = out["results"]["model_size"]
    assert size["dof"] == 6 * 3136 > ns.max_dof("linear") and size["memory_gb"] > 1
    with pytest.raises(ns.ModelTooLargeError):
        ns.view_result(model, 100.0)


def test_size_gate_is_a_fixed_budget_not_the_free_memory(monkeypatch):
    """The same model is analysed or refused whatever else is open; low free memory only warns."""
    assert ns.max_dof("stability") < ns.max_dof("linear")
    nodes = ns.max_dof("stability") // 6
    for free in (1e9, 1e12):
        monkeypatch.setattr(ns, "_available_memory", lambda free=free: free)
        size = ns.check_size(nodes, nodes, "stability")
        assert size["dof"] <= ns.max_dof("stability")
        assert bool(ns._memory_warning(size)) == (free == 1e9)
        with pytest.raises(ns.ModelTooLargeError, match="added to refine compressed members"):
            ns.check_size(nodes + 10, nodes, "stability", added=10)


def test_out_of_memory_is_an_error_result_not_an_exception(monkeypatch):
    def boom(*_a, **_k):
        raise MemoryError
    monkeypatch.setattr(fs, "prepare", boom)
    monkeypatch.setattr(fs, "solve_combinations", boom)
    model = rib_vault(4)
    out = ns.validate(model, "frame", 10.0)
    assert out["status"] == "error" and "ran out of memory" in out["verdict"]
    with pytest.raises(ns.ModelTooLargeError):
        ns.view_result(model, 10.0)


def test_node_welding_scales_to_dense_exports():
    """15,000 polyline vertices weld through a grid, not a scan of every node per point."""
    model = diagrid_vault(45, nu=12, nv=28, length=22.0)
    t0 = time.perf_counter()
    frame, _, _ = ns.build_frame(model, 10.0, curve_ratio=None)
    assert time.perf_counter() - t0 < 20.0
    assert len(frame.nodes) == sum(len(m["points"]) - 2 for m in model["members"]) + 189    # interior + joints
    t0 = time.perf_counter()
    frame, _, _ = ns.build_frame(model, 10.0)
    assert time.perf_counter() - t0 < 10.0 and len(frame.nodes) < 2500


# --- finding 2: deflection span per member ---------------------------------------------------------------

def test_beam_drawn_in_pieces_is_checked_against_its_whole_span():
    """A 10 m beam drawn as five 2 m pieces of one curve: limit 10 m / 250, not the 2 m piece."""
    sec = {"shape": "circular_hollow", "diameter": 0.2191, "wall": 0.008}
    members = [{"source_guids": ["beam"], "points": [[2.0 * k, 0, 0], [2.0 * (k + 1), 0, 0]], "section": sec}
               for k in range(5)]
    model = {"members": members, "anchor_points": [[0, 0, 0], [10, 0, 0]], "tolerance_m": 0.001,
             "max_member_span_m": 2.0, "max_span_m": 10.0, "warnings": []}
    out = ns.validate(model, "beam", 10.0, fixed_supports=False, detail=True)
    r = out["results"]
    assert r["span_basis"] == "member" and r["span_m"] == pytest.approx(10.0)
    assert r["deflection_limit_mm"] == pytest.approx(40.0)
    assert r["governing_deflection"]["member"] == "M1" and "in member M1 (span 10.00 m)" in out["verdict"]
    assert 8.0 < r["max_deflection_mm"] < 40.0 and out["status"] == "pass"   # failed on the old 2 m-piece limit (8 mm)
    assert out["members"][0]["deflection_span_m"] == pytest.approx(10.0)


def test_each_member_is_checked_against_its_own_span():
    """A stiff long girder and a soft short beam: the short one governs although it deflects less."""
    stiff = {"shape": "circular_hollow", "diameter": 0.6096, "wall": 0.020}
    soft = {"shape": "circular_hollow", "diameter": 0.0603, "wall": 0.003}
    members = [{"source_guids": ["girder"], "name": "G1", "points": [[0, 0, 0], [12, 0, 0]], "section": stiff},
               {"source_guids": ["joist"], "name": "J1", "points": [[0, 5, 0], [3, 5, 0]], "section": soft}]
    model = {"members": members, "anchor_points": [[0, 0, 0], [12, 0, 0], [0, 5, 0], [3, 5, 0]],
             "tolerance_m": 0.001, "max_member_span_m": 12.0, "max_span_m": 13.0, "warnings": []}
    out = ns.validate(model, "beam", 0.0)
    g = out["results"]["governing_deflection"]
    assert g["member"] == "J1" and g["span_m"] == pytest.approx(3.0) and g["limit_mm"] == pytest.approx(12.0)
    assert out["results"]["largest_deflection_mm"] >= g["deflection_mm"]


def test_cantilever_span_is_twice_the_overhang():
    sec = {"shape": "circular_hollow", "diameter": 0.2191, "wall": 0.008}
    model = {"members": [{"source_guids": ["c"], "points": [[0, 0, 3], [2.5, 0, 3]], "section": sec}],
             "anchor_points": [[0, 0, 3]], "tolerance_m": 0.001, "max_member_span_m": 2.5, "max_span_m": 2.5,
             "warnings": []}
    out = ns.validate(model, "beam", 5.0)
    assert out["results"]["span_m"] == pytest.approx(5.0) and out["results"]["deflection_limit_mm"] == pytest.approx(20.0)


def test_user_span_still_overrides():
    out = ns.validate(rib_vault(4), "frame", 10.0, span_m=6.2)
    assert out["results"]["span_basis"] == "user" and out["results"]["deflection_limit_mm"] == pytest.approx(24.8)


def test_curved_vault_over_the_budget_is_coarsened_and_validates(monkeypatch):
    """Over budget, curves are coarsened (deterministically) before anything is assembled, instead of refusing."""
    model = diagrid_vault(12)
    full, _, _ = ns.build_frame(model, 10.0)
    monkeypatch.setattr(ns, "DENSE_BUDGET_GB", ns.DENSE_COPIES["stability"] * 8.0 * (6 * 150) ** 2 / 1e9)
    assert ns._worst_dof(full, ns.STABILITY_SUBDIVISION) > ns.max_dof("stability")                  # the default chords do not fit
    out = ns.validate(model, "frame", 1.5 * 10.4 * 6.0)
    assert out["status"] == "pass", out["verdict"]
    assert any("coarsened to at most" in w for w in out["warnings"])
    assert out["results"]["nodes"] * 6 <= ns.max_dof("stability")
    assert out["results"]["stability"]["elements_per_member"] == ns.STABILITY_SUBDIVISION


def test_stability_refinement_is_reduced_before_refusing(monkeypatch):
    """Straight members cannot be coarsened: their stability split drops to 3 or 2 elements to fit."""
    lines = [((0, 0, 0), (0, 0, 4)), ((6, 0, 0), (6, 0, 4)), ((0, 0, 4), (6, 0, 4)), ((0, 0, 0), (6, 0, 4))]
    sec = {"shape": "circular_hollow", "diameter": 0.2191, "wall": 0.008}
    model = {"members": [{"source_guids": [f"m{i}"], "points": [list(a), list(b)], "section": sec}
                         for i, (a, b) in enumerate(lines)],
             "anchor_points": [[0, 0, 0], [6, 0, 0]], "tolerance_m": 0.001, "max_member_span_m": 6,
             "max_span_m": 6, "warnings": []}
    full = ns.validate(model, "frame", 50.0)
    monkeypatch.setattr(ns, "DENSE_BUDGET_GB", ns.DENSE_COPIES["stability"] * 8.0 * (6 * 8) ** 2 / 1e9)
    small = ns.validate(model, "frame", 50.0)
    assert full["results"]["stability"]["elements_per_member"] == 4
    assert small["results"]["stability"]["elements_per_member"] in (2, 3)
    assert any("refined into" in w for w in small["warnings"])
    a, b = small["results"]["stability"]["min_alpha_cr"], full["results"]["stability"]["min_alpha_cr"]
    assert a == pytest.approx(b, rel=0.05)


def test_vault_deflection_is_global_against_its_span_and_local_between_joints():
    """A diagrid vault carries load as a surface: its crown deflection is judged against the span between the
    supports either side (~2R), and each diagonal only on its own sag between joints."""
    out = ns.validate(diagrid_vault(12), "frame", 1.5 * 10.4 * 6.0, detail=True)
    r = out["results"]
    assert r["span_basis"] == "surface"
    g, sd = r["governing_deflection"], r["surface_deflection"]
    assert g["kind"] in ("global", "local") and ("global" in out["verdict"] or "local sag" in out["verdict"])
    assert sd["global"]["span_m"] == pytest.approx(2 * 5.2, rel=0.05)           # the vault span, not a piece
    assert sd["local"]["span_m"] < 3.0                                          # a diagonal between two joints
    assert r["max_deflection_mm"] == g["deflection_mm"] and r["deflection_limit_mm"] == g["limit_mm"]


def test_frames_with_columns_and_flat_grids_keep_the_member_check():
    sec = {"shape": "circular_hollow", "diameter": 0.2191, "wall": 0.008}
    lines = [((0, 0, 0), (0, 0, 4)), ((6, 0, 0), (6, 0, 4)), ((0, 0, 4), (6, 0, 4))]
    portal = {"members": [{"source_guids": [f"m{i}"], "points": [list(a), list(b)], "section": sec}
                          for i, (a, b) in enumerate(lines)],
              "anchor_points": [[0, 0, 0], [6, 0, 0]], "tolerance_m": 0.001, "max_member_span_m": 6,
              "max_span_m": 6, "warnings": []}
    assert ns.validate(portal, "frame", 20.0)["results"]["span_basis"] == "member"
    frame, _, _ = ns.build_frame(rib_vault(4), 10.0)
    assert ns.is_surface(frame)
    tower = [((0, 0, 0), (0, 0, 30)), ((8, 0, 0), (8, 0, 30)), ((0, 0, 30), (8, 0, 30))]
    frame, _, _ = ns.build_frame({"members": [{"source_guids": [f"t{i}"], "points": [list(a), list(b)]}
                                              for i, (a, b) in enumerate(tower)], "tolerance_m": 0.001}, 0.0)
    assert not ns.is_surface(frame)


def test_curved_member_moments_are_continuous_in_the_member_axes():
    """Each chord reports moments in its own turned axes; the member check reads them in the member's
    chord axes, where the moment vector is continuous through the joints between chords (no false kinks
    that would set Table B.3's Cm to 1.0)."""
    from almond_mcp import ec3
    frame, _, _ = ns.build_frame(rib_vault(24), 30.0, max_curve_segments=4)
    res = fs.solve(frame, combination={"G": 1.35, "Q": 1.5})
    X = np.asarray(frame.nodes)
    checked = 0
    for idx in ec3.groups(frame).values():
        if len(idx) < 2:
            continue
        ers = [res.elements[i] for i in idx]
        A, B = X[frame.elements[idx[0]].n1], X[frame.elements[idx[-1]].n2]
        My, Mz = ec3._member_moments(frame, idx, ers, A, B)
        n = len(ers[0].My)
        peak = max(float(np.max(np.abs(My))), float(np.max(np.abs(Mz))), 1e-9)
        for k in range(1, len(ers)):                    # end of one chord vs start of the next
            assert abs(My[k * n - 1] - My[k * n]) < 1e-6 * peak + 1e-9
            assert abs(Mz[k * n - 1] - Mz[k * n]) < 1e-6 * peak + 1e-9
        checked += 1
    assert checked >= 7 * 6
