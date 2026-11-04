"""Environmental analysis: EPW parsing and repair, solar geometry, skies, comfort models, the ray
tracer, daylight / radiation / thermal engines against analytic cases, and the MCP tools (Rhino mocked)."""
import json
import math
import re
from pathlib import Path

import numpy as np
import pytest

from almond_mcp.environment import (climate, comfort, daylight as dl, epw, radiation, raytrace, scene as S, sky, solar,
                                    studies, thermal)
from tests.env_weather import synthetic_epw, synthetic_weather
from tests.test_capsules import BridgeMock, _call, _load_server


@pytest.fixture(scope="module")
def tropical(tmp_path_factory):
    return synthetic_epw(tmp_path_factory.mktemp("w") / "tropical.epw")


@pytest.fixture(scope="module")
def temperate(tmp_path_factory):
    return synthetic_epw(tmp_path_factory.mktemp("w") / "temperate.epw", latitude=40.0, longitude=-75.0, time_zone=-5.0,
                         mean_t=12.0, annual_amp=12.0, daily_amp=5.0, rh=65.0, cloudiness=0.5, city="Temperate")


@pytest.fixture(autouse=True)
def _runs_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv(studies.RUNS_ENV, str(tmp_path / "runs"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))


def _empty_scene():
    b = S.SceneBuilder()
    b.add_quad([[1000, 1000, -50], [1001, 1000, -50], [1001, 1001, -50], [1000, 1001, -50]], "black", {"name": "far"})
    return b.build()


# ── EPW ──────────────────────────────────────────────────────────────────────

def test_epw_round_trip_is_clean(tropical):
    w = tropical
    assert len(w["dry_bulb"]) == 8760 and np.isfinite(w["dry_bulb"]).all()
    assert w.location.city == "Synthetic" and w.location.time_zone == 8.0
    assert w.report["warnings"] == []
    assert w.report["radiation_closure_median_error"] < 0.02
    # the synthetic file has no illuminance: it is derived from irradiance (Perez 1990), plausibly
    assert w.report["filled"]["global_illuminance"]["perez_1990"] > 4000
    day = w["ghi"] > 200
    efficacy = w["global_illuminance"][day] / w["ghi"][day]
    assert 90 < np.median(efficacy) < 130
    assert "global_illuminance" in w.report["absent_columns"] and "dry_bulb" not in w.report.get("invalid_values", {})


def _rewrite(src: Path, dst: Path, edit) -> Path:
    lines = src.read_text().splitlines()
    head, rows = lines[:8], [r.split(",") for r in lines[8:]]
    rows = edit(rows)
    dst.write_text("\n".join(head + [",".join(r) for r in rows]) + "\n")
    return dst


def test_epw_repairs_gaps_sentinels_and_ranges(tmp_path, tropical):
    src = Path(tropical.source_path)

    def corrupt(rows):
        for i in range(100, 103):
            rows[i][6] = "99.9"                 # missing dry bulb (3 h gap -> interpolated)
        for i in range(2000, 2030):
            rows[i][6] = "99.9"                 # 30 h gap -> monthly-hour mean
        rows[500][13] = "9999"                  # missing GHI
        rows[600][8] = "150"                    # RH out of range
        return rows
    w = epw.read_epw(_rewrite(src, tmp_path / "bad.epw", corrupt))
    filled = w.report["filled"]["dry_bulb"]
    assert filled["interpolated"] == 3 and filled["monthly_hour_mean"] == 30
    assert np.isfinite(w["dry_bulb"]).all()
    assert abs(w["dry_bulb"][101] - 0.5 * (tropical["dry_bulb"][99] + tropical["dry_bulb"][103])) < 0.6
    assert w.report["invalid_values"]["dry_bulb"] == 33 and w.report["invalid_values"]["rel_humidity"] == 1
    assert 0 <= w["rel_humidity"][600] <= 100


def test_epw_leap_year_and_subhourly(tmp_path, tropical):
    src = Path(tropical.source_path)

    def leap(rows):
        feb28 = [r for r in rows if r[1] == "2" and r[2] == "28"]
        extra = [[*r[:2], "29", *r[3:]] for r in feb28]
        i = rows.index(feb28[-1]) + 1
        return rows[:i] + extra + rows[i:]
    w = epw.read_epw(_rewrite(src, tmp_path / "leap.epw", leap))
    assert any("29 February" in m for m in w.report["warnings"])
    assert np.allclose(w["dry_bulb"], tropical["dry_bulb"])

    def half_hourly(rows):
        out = []
        for r in rows:
            a, b = list(r), list(r)
            a[4], b[4] = "30", "60"
            a[6] = f"{float(r[6]) - 1:.1f}"
            b[6] = f"{float(r[6]) + 1:.1f}"
            out += [a, b]
        return out
    w2 = epw.read_epw(_rewrite(src, tmp_path / "sub.epw", half_hourly))
    assert np.allclose(w2["dry_bulb"], tropical["dry_bulb"], atol=0.051)


def test_epw_rejects_non_weather(tmp_path):
    p = tmp_path / "x.epw"
    p.write_text("hello\n1,2,3\n")
    with pytest.raises(epw.EPWError, match="LOCATION"):
        epw.read_epw(p)
    p.write_text("LOCATION,A,B,C,D,0,10,10,1,0\n" + "\n".join(
        ",".join(["2019", "1", "1", str(h), "60", "x"] + ["10"] * 29) for h in range(1, 25)))
    with pytest.raises(epw.EPWError, match="hours are present"):
        epw.read_epw(p)
    z = tmp_path / "w.zip"
    z.write_bytes(b"PK")
    with pytest.raises(epw.EPWError, match="zip"):
        epw.read_epw(z)


def test_epw_weekday_from_data_periods(tmp_path, tropical):
    src = Path(tropical.source_path)
    text = src.read_text().replace("DATA PERIODS,1,1,Data,Tuesday", "DATA PERIODS,1,1,Data,Sunday")
    p = tmp_path / "sun.epw"
    p.write_text(text)
    w = epw.read_epw(p)
    assert w.weekday()[0] == 6 and w.weekday()[24] == 0


# ── solar and sky ────────────────────────────────────────────────────────────

def test_sun_position_known_geometry():
    t = np.arange(0, 24, 0.01)
    for lat in (40.0, -33.9, 1.35):
        sp = solar.sun_position(lat, 0.0, 0.0, np.full_like(t, 172), t)
        noon_alt = sp["altitude"].max()
        decl = float(sp["declination"][0])
        assert abs(noon_alt - (90 - abs(lat - decl))) < 0.05
    eq = solar.sun_position(0.0, 0.0, 0.0, np.array([80]), np.array([6.2]))
    assert abs(eq["azimuth"][0] - 90) < 2                  # morning sun in the east at the equator
    assert solar.day_events(78.0, 15.0, 1.0, 172)["polar"] == "day"
    assert solar.day_events(78.0, 15.0, 1.0, 355)["polar"] == "night"
    ev = solar.day_events(51.5, 0.0, 0.0, 172)
    assert 16.3 < ev["day_length_h"] < 16.8


@pytest.mark.parametrize("mf,n", [(1, 145), (2, 577), (4, 2305)])
def test_patches(mf, n):
    p = sky.patches(mf)
    assert p.n_sky == n
    assert abs(p.solid_angle[:n].sum() - 2 * math.pi) < 1e-9
    assert abs(p.projected.sum() - math.pi) < 1e-9
    assert (p.index(p.direction[:n]) == np.arange(n)).all()
    assert p.index(np.array([[0, 0, -1.0]]))[0] == n


def test_sky_matrix_reproduces_diffuse_and_is_positive(tropical):
    sm = sky.sky_matrix(tropical)
    p = sm.patches
    rec = sm.sky[:, :p.n_sky] @ p.projected
    assert np.allclose(rec, sm.diffuse_horizontal, rtol=1e-9, atol=1e-6)
    assert (sm.sky >= 0).all()
    assert np.allclose(sm.sky[:, p.n_sky], 0.2 * sm.global_horizontal / math.pi)


def test_perez_luminance_every_bin_is_physical():
    p = sky.patches(1)
    for b in range(8):
        for z in (10.0, 45.0, 80.0):
            params = sky.perez_parameters(np.array([b]), np.array([0.2]), np.array([z]))
            s = solar.direction_vector(np.array([90 - z]), np.array([180.0]))
            rel = sky._gradation_indicatrix(params, p.direction[:p.n_sky], s, cie=False)
            assert np.isfinite(rel).all() and (np.maximum(rel, 0) @ p.projected) > 0


def test_cie_overcast_is_brighter_at_zenith():
    p = sky.patches(1)
    L = sky.cie_overcast(p, 1.0)
    assert abs(L @ p.projected - 1.0) < 1e-12
    assert L[p.n_sky - 1] / L[0] == pytest.approx(3.0 / (1 + 2 * math.sin(math.radians(p.altitude[0]))), rel=1e-6)


# ── comfort ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("args,expected", [
    ((22, 22, 0.1, 60, 1.2, 0.5), -0.75), ((27, 27, 0.1, 60, 1.2, 0.5), 0.77), ((27, 27, 0.3, 60, 1.2, 0.5), 0.43),
    ((23.5, 25.5, 0.1, 60, 1.2, 0.5), -0.01), ((23.5, 25.5, 0.3, 60, 1.2, 0.5), -0.55), ((19, 18, 0.1, 40, 1.2, 1.0), -0.70),
    ((23.5, 23.5, 0.1, 40, 1.2, 1.0), 0.36), ((28, 28, 0.6, 50, 1.6, 0.3), 0.67)])
def test_pmv_matches_iso7730_reference(args, expected):
    """Reference values from the ISO 7730 algorithm as implemented in pythermalcomfort (CBE)."""
    assert float(comfort.pmv_ppd(*args)["pmv"]) == pytest.approx(expected, abs=0.011)


def test_ppd_at_neutral_is_five_percent():
    r = comfort.pmv_ppd(np.linspace(18, 30, 200), np.linspace(18, 30, 200), 0.1, 50, 1.2, 0.5)
    assert r["ppd"].min() == pytest.approx(5.0, abs=0.05)


def test_psychrometrics():
    assert float(comfort.dew_point(25.0, 100.0)) == pytest.approx(25.0, abs=0.01)
    assert float(comfort.wet_bulb(30.0, 100.0)) == pytest.approx(30.0, abs=0.02)
    assert float(comfort.wet_bulb(25.0, 50.0)) == pytest.approx(17.9, abs=0.2)
    assert float(comfort.humidity_ratio(20.0, 50.0)) == pytest.approx(0.00726, abs=0.0001)
    t, rh = np.array([5.0, 20.0, 35.0]), np.array([30.0, 60.0, 90.0])
    assert np.allclose(comfort.rh_from_dew_point(t, comfort.dew_point(t, rh)), rh, atol=0.01)


def test_adaptive_models():
    e = comfort.adaptive_en16798(np.full(24, 25.0), np.array([20.0]), "II")
    assert e["neutral"][0] == pytest.approx(25.4) and e["upper"][0] == pytest.approx(28.4) and e["lower"][0] == pytest.approx(21.4)
    a = comfort.adaptive_ashrae55(np.full(24, 25.0), np.array([20.0]), air_speed=0.1)
    assert a["neutral"][0] == pytest.approx(24.0) and a["upper_80"][0] == pytest.approx(27.5) and a["upper_90"][0] == pytest.approx(26.5)
    fast = comfort.adaptive_ashrae55(np.full(24, 29.0), np.array([20.0]), air_speed=0.9)
    assert fast["upper_80"][0] == pytest.approx(27.5 + 1.8) and fast["comfortable_80"][0]
    rm = comfort.running_mean_outdoor(np.full(365, 15.0))
    assert np.allclose(rm, 15.0)


def test_tm52_criteria():
    month = np.repeat(np.repeat(np.arange(1, 13), epw.MONTH_DAYS), 24)
    occ = np.ones(8760, dtype=bool)
    t_rm = np.full(365, 20.0)                  # T_max = 0.33*20 + 21.8 = 28.4
    assert comfort.tm52(np.full(8760, 26.0), t_rm, occ, month)["pass"]
    hot = np.full(8760, 26.0)
    hot[(month == 7)] = 31.0                   # dT = round(2.6) = 3 all July: C1 and C2 fail
    r = comfort.tm52(hot, t_rm, occ, month)
    assert not r["pass"] and r["failed_criteria"] == [1, 2]


# ── ray tracing ──────────────────────────────────────────────────────────────

def test_bvh_matches_brute_force():
    rng = np.random.default_rng(1)
    v0 = rng.uniform(-5, 5, (300, 3))
    v1, v2 = v0 + rng.normal(0, 0.8, (300, 3)), v0 + rng.normal(0, 0.8, (300, 3))
    o = rng.uniform(-6, 6, (500, 3))
    d = rng.normal(size=(500, 3))
    t, tri = raytrace.BVH(v0, v1, v2).intersect(o, d)
    e1, e2 = v1 - v0, v2 - v0
    for i in range(0, 500, 7):
        p = np.cross(d[i], e2)
        det = (e1 * p).sum(1)
        with np.errstate(all="ignore"):
            inv = 1 / det
            tv = o[i] - v0
            u = (tv * p).sum(1) * inv
            q = np.cross(tv, e1)
            v = (q @ d[i]) * inv
            tt = (e2 * q).sum(1) * inv
        ok = (np.abs(det) > 1e-14) & (u >= 0) & (v >= 0) & (u + v <= 1) & (tt > 1e-6)
        best = np.min(np.where(ok, tt, np.inf))
        assert (np.isinf(best) and tri[i] == -1) or (best == pytest.approx(t[i]) and ok[tri[i]])


def test_numpy_and_compiled_paths_agree(monkeypatch):
    if raytrace.backend() != "numba":
        pytest.skip("numba not installed")
    rng = np.random.default_rng(2)
    v0 = rng.uniform(-5, 5, (200, 3))
    bvh = raytrace.BVH(v0, v0 + rng.normal(0, 1, (200, 3)), v0 + rng.normal(0, 1, (200, 3)))
    o, d = rng.uniform(-6, 6, (2000, 3)), rng.normal(size=(2000, 3))
    t1, i1 = bvh.intersect(o, d)
    monkeypatch.setattr(raytrace, "_kernels", None)
    t2, i2 = bvh.intersect(o, d)
    assert (i1 == i2).all() and np.allclose(np.nan_to_num(t1, posinf=0), np.nan_to_num(t2, posinf=0))


# ── daylight: analytic cases ─────────────────────────────────────────────────

def test_glazing_transmittance_angle_dependence():
    cos = np.cos(np.radians([0.0, 30, 60, 80, 89.9]))
    t = S.glazing_transmittance(0.7, cos)
    assert t[0] == pytest.approx(0.7, abs=1e-9)
    assert (np.diff(t) < 0).all() and t[-1] < 0.01
    assert np.allclose(S.glazing_transmittance(1.0, cos), 1.0)
    assert S.glazing_transmittance(0.95, np.array([1.0]))[0] == pytest.approx(0.95)


def test_unobstructed_sensor_sees_the_whole_sky():
    p = sky.patches(1)
    c = dl.compute_coefficients(dl.Tracer(_empty_scene()), S.grid_from_points([[0, 0, 0]]),
                                dl.Quality(rays=16, bounces=0, patch_samples=16, ground_samples=8, cache_cell=0.3, mf=1))
    assert float(c.D[0, 0, :p.n_sky] @ sky.uniform_sky(p, 1.0)) == pytest.approx(1.0, abs=0.01)
    assert float(c.D[0, 0, :p.n_sky] @ sky.cie_overcast(p, 1.0)) == pytest.approx(1.0, abs=0.01)


def test_skylight_view_factor_matches_analytic():
    h, a, R = 1.0, 0.5, 500.0
    b = S.SceneBuilder()
    for q in ([[-R, -R, h], [R, -R, h], [R, -a, h], [-R, -a, h]], [[-R, a, h], [R, a, h], [R, R, h], [-R, R, h]],
              [[-R, -a, h], [-a, -a, h], [-a, a, h], [-R, a, h]], [[a, -a, h], [R, -a, h], [R, a, h], [a, a, h]]):
        b.add_quad(q, "black", {"name": "roof"})
    tr = dl.Tracer(b.build())
    p = sky.patches(1)
    vals = [float(dl.compute_coefficients(tr, S.grid_from_points([[0, 0, 0]]),
                                          dl.Quality(rays=4, bounces=0, patch_samples=16, ground_samples=4, cache_cell=0.3, mf=1),
                                          seed=s).D[0, 0, :p.n_sky] @ sky.uniform_sky(p, 1.0)) for s in range(4)]

    def corner(X, Y):
        return (X / math.sqrt(1 + X * X) * math.atan(Y / math.sqrt(1 + X * X))
                + Y / math.sqrt(1 + Y * Y) * math.atan(X / math.sqrt(1 + Y * Y))) / (2 * math.pi)
    assert np.mean(vals) == pytest.approx(4 * corner(a / h, a / h), rel=0.03)


def test_one_bounce_off_infinite_ground():
    b = S.SceneBuilder()
    b.add_quad([[-500, -500, 0], [500, -500, 0], [500, 500, 0], [-500, 500, 0]], S.Material("g", reflectance=0.5), {"name": "ground"})
    p = sky.patches(1)
    c = dl.compute_coefficients(dl.Tracer(b.build()), S.grid_from_points([[0, 0, 1.0]], normals=[[0, 0, -1]]),
                                dl.Quality(rays=256, bounces=2, patch_samples=4, ground_samples=16, cache_cell=0.3, mf=1))
    L = np.concatenate([sky.uniform_sky(p, 1.0), [0.0]])
    assert float(c.total[0, 0] @ L) == pytest.approx(0.5, abs=0.015)


def test_sun_through_glass_is_cosine_times_transmittance():
    b = S.SceneBuilder()
    b.add_quad([[-50, -50, 2], [50, -50, 2], [50, 50, 2], [-50, 50, 2]], "glazing_double_clear", {"name": "roof glass"})
    sc = b.build()
    grid = S.grid_from_points([[0, 0, 0]])
    alt = np.array([30.0, 60.0, 89.0])
    dirs = solar.direction_vector(alt, np.array([180.0, 90.0, 0.0]))
    Sv, G = dl.sun_coefficients(dl.Tracer(sc, np.ones(2, dtype=int)), grid, dirs)
    cos = np.sin(np.radians(alt))
    assert np.allclose(Sv[:, 0], cos * S.glazing_transmittance(0.8, cos), rtol=1e-4)
    assert (G[:, 0] == 1).all()


def test_shoebox_daylight_factor_is_plausible():
    box = S.Shoebox(width=6, depth=8, height=3, wwr=0.4)
    sc = box.build()
    grid = box.floor_grid(sc, 0.75)
    groups, desc = dl.aperture_groups(sc)
    assert [d["label"] for d in desc] == ["S"]
    c = dl.compute_coefficients(dl.Tracer(sc, groups), grid, dl.quality("draft"))
    df = dl.daylight_factor(c)
    avg = float(df["df"].mean())
    assert 2.0 < avg < 6.0
    # interreflected part vs the BRE split-flux formula (0.85 W / (A (1-R)) (C R_fw + 5 R_cw) x tau)
    assert 0.4 < float(df["interreflected"].mean()) < 1.1
    # daylight falls off with depth
    depth = grid.points[:, 1]
    assert df["df"][depth < np.percentile(depth, 20)].mean() > 3 * df["df"][depth > np.percentile(depth, 80)].mean()


def test_cache_solve_agrees_with_unbiased_path_tracing():
    box = S.Shoebox(width=5, depth=6, height=3, wwr=0.4)
    sc = box.build()
    grid = box.floor_grid(sc, 1.0)
    tr = dl.Tracer(sc, dl.aperture_groups(sc)[0])
    p = sky.patches(1)
    L = np.concatenate([sky.cie_overcast(p, 1.0), [0.2 / math.pi]])
    q = dl.Quality(rays=256, bounces=4, patch_samples=3, ground_samples=24, cache_cell=0.3, mf=1, cache_rays=128)
    ref, _ = tr._indirect_paths(grid.points, grid.normals, p, dl.Quality(**{**q.__dict__, "rays": 2048}), np.random.default_rng(9))
    got = np.mean([tr.indirect_coefficients(grid.points, grid.normals, p, q, np.random.default_rng(s))[0].sum(0) @ L
                   for s in range(2)], axis=0)
    r = ref.sum(0) @ L
    # the cache's cell discretisation costs a few percent (measured +2..+5 % across rooms)
    assert got.mean() == pytest.approx(r.mean(), rel=0.07)
    assert np.median(np.abs(got - r) / r) < 0.1


def test_grid_follows_a_rotated_room_and_keeps_off_walls():
    box = S.Shoebox(width=6, depth=4, orientation=200)
    sc = box.build()
    grid = box.floor_grid(sc, 0.5)
    assert grid.n == 12 * 8                                     # rows parallel to the walls, no part cells
    tri = sc.triangles[box.part_mask(sc, "wall") | box.part_mask(sc, "facade") | box.part_mask(sc, "window")]
    v = sc.vertices
    for t in tri:                                               # every sensor at least 10 cm from every wall
        a, b, c = v[t]
        n = np.cross(b - a, c - a)
        n /= np.linalg.norm(n)
        assert (np.abs((grid.points[:, :2] - a[:2]) @ n[:2]) > 0.099).all()


@pytest.mark.parametrize("orientation,label", [(0, "N"), (90, "E"), (225, "SW")])
def test_aperture_groups_follow_true_orientation(orientation, label):
    sc = S.Shoebox(orientation=orientation).build()
    assert [d["label"] for d in dl.aperture_groups(sc)[1]] == [label]


def test_single_surface_facade_walls_are_interior_walls():
    """A zero-thickness facade surface faces the room too: a name like 'facade below' must not turn
    it into a dark exterior finish (found in the first live Rhino run)."""
    assert S.classify(["Building::Walls", "facade below", ""])[0] == "wall"
    assert S.classify(["Envelope", "facade panel", ""])[0] is None          # falls back to orientation


def test_radiation_grid_drops_surfaces_enclosed_on_both_sides():
    b = S.SceneBuilder()
    b.add_quad([[-50, -50, -0.01], [50, -50, -0.01], [50, 50, -0.01], [-50, 50, -0.01]], "ground", {"name": "ground"})
    v = np.array([[0, 0, 0], [4, 0, 0], [4, 4, 0], [0, 4, 0], [0, 0, 3], [4, 0, 3], [4, 4, 3], [0, 4, 3]], float)
    f = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]])
    b.add_mesh(v, f, "context", {"name": "block"})
    sc = b.build()
    g0 = S.grid_from_triangles(v, f, 1.0, 0.0, 0.0, face_up=False)
    grid, dropped = studies.orient_outward(g0, sc, 0.05)
    assert dropped == 16                                        # the 4 x 4 m base on the ground
    assert (grid.points[:, 2] > 0).all()
    roof = grid.points[:, 2] > 2.9
    assert np.allclose(grid.normals[roof], [0, 0, 1])           # every kept sensor faces out
    sides = ~roof
    centre = np.array([2.0, 2.0])
    assert (np.einsum("ij,ij->i", grid.normals[sides][:, :2], grid.points[sides][:, :2] - centre) > 0).all()


def test_floor_of_separate_boards_gets_a_continuous_grid():
    """Boards 37 cm wide with 1 cm seams (Atelier 07's oak floor) must grid like one floor."""
    v, t = [], []
    for i in range(16):
        y0 = i * 0.37
        y1 = y0 + 0.36
        b = len(v)
        v += [[0, y0, 0], [6, y0, 0], [6, y1, 0], [0, y1, 0]]
        t += [[b, b + 1, b + 2], [b, b + 2, b + 3]]
    g = S.grid_from_triangles(np.array(v, float), np.array(t), 0.5, 0.76)
    whole = S.grid_from_triangles(np.array([[0, 0, 0], [6, 0, 0], [6, 5.91, 0], [0, 5.91, 0]], float), np.array([[0, 1, 2], [0, 2, 3]]), 0.5, 0.76)
    assert g.n == whole.n


def test_sensors_inside_joinery_are_dropped():
    """A 1.2 m cube of cabinetry on the floor of a shoebox: the work-plane sensors inside it go."""
    box = S.Shoebox(width=6, depth=6, height=3)
    sc = box.build()
    b = S.SceneBuilder()
    v = np.array([[-0.6, 2.4, 0], [0.6, 2.4, 0], [0.6, 3.6, 0], [-0.6, 3.6, 0], [-0.6, 2.4, 1.0], [0.6, 2.4, 1.0], [0.6, 3.6, 1.0], [-0.6, 3.6, 1.0]], float)
    f = [[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]]
    b.add_mesh(v, f, "furniture", {"name": "island"})
    sc = sc.merged(b.build())
    grid = box.floor_grid(sc, 0.4)
    kept, dropped = studies.drop_enclosed_sensors(sc, grid)
    inside = (np.abs(grid.points[:, 0]) < 0.6) & (grid.points[:, 1] > 2.4) & (grid.points[:, 1] < 3.6)
    assert dropped == int(inside.sum()) > 0
    assert kept.n == grid.n - dropped


def test_window_spanning_two_zones_is_split_between_them():
    def box(z0, z1):
        v = np.array([[0, 0, z0], [4, 0, z0], [4, 4, z0], [0, 4, z0], [0, 0, z1], [4, 0, z1], [4, 4, z1], [0, 4, z1]], float)
        f = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]])
        return v, f
    lo, up = box(0, 3), box(3, 6)
    # a 2 m wide pane from 1 m to 5 m high, set back 15 cm inside the south face
    win = {"vertices": [[1, 0.15, 1], [3, 0.15, 1], [3, 0.15, 5], [1, 0.15, 5]], "triangles": [[0, 1, 2], [0, 2, 3]],
           "name": "tall", "g_value": 0.5, "u_value": 1.0}
    zl = thermal.zone_from_mesh("lower", *lo, [win], other_zones=[up])
    zu = thermal.zone_from_mesh("upper", *up, [win], other_zones=[lo])
    assert zl.areas()["window"] == pytest.approx(4.0) and zu.areas()["window"] == pytest.approx(4.0)
    assert zl.areas()["wall"] == pytest.approx(4 * 4 * 3 - 4.0)


def _pane_solid(x0, x1, z0, z1, y0=0.0, thickness=0.012):
    y1 = y0 + thickness
    v = np.array([[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0], [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]], float)
    f = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]])
    return v, f


def test_glass_modelled_as_a_thin_solid_counts_once():
    """Real models often model a pane as a 12 mm box: light must cross it at the pane's transmittance,
    not twice (found on the Atelier 07 house)."""
    b = S.SceneBuilder()
    v, f = _pane_solid(-50, 50, -50, 50)
    rot = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], float)         # lay it flat, 2 m up
    b.add_mesh(v @ rot.T + [0, 0, 2.0], f, "glazing_double_clear", {"name": "roof pane"})
    sc = b.build()
    assert S.thin_solid_panes(sc).all()
    alt = np.array([60.0])
    dirs = solar.direction_vector(alt, np.array([180.0]))
    Sv, _ = dl.sun_coefficients(dl.Tracer(sc, np.ones(len(sc.triangles), dtype=int)), S.grid_from_points([[0, 0, 0]]), dirs)
    cos = np.sin(np.radians(alt))
    assert Sv[0, 0] == pytest.approx(cos[0] * S.glazing_transmittance(0.8, cos)[0], rel=1e-3)
    groups, desc = dl.aperture_groups(sc)
    assert desc[0]["label"] == "skylight" and desc[0]["area_m2"] == pytest.approx(100 * 100, rel=1e-3)


def test_thin_solid_window_attaches_once_to_its_zone():
    def box(z0, z1):
        v = np.array([[0, 0, z0], [4, 0, z0], [4, 4, z0], [0, 4, z0], [0, 0, z1], [4, 0, z1], [4, 4, z1], [0, 4, z1]], float)
        f = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]])
        return v, f
    pv, pf = _pane_solid(1, 3, 0.5, 2.5, y0=0.05)
    z = thermal.zone_from_mesh("room", *box(0, 3), [{"vertices": pv, "triangles": pf, "name": "pane", "g_value": 0.5, "u_value": 0.7}])
    assert z.areas()["window"] == pytest.approx(4.0)
    win = [s for s in z.surfaces if s.kind == "window"][0]
    assert np.allclose(win.normal, (0, -1, 0)) and (win.samples[:, 1] < 0.05).all()   # outside the glass


def test_facade_glazing_on_a_dense_street_still_faces_out():
    """The outside of a street facade is mostly blocked (the ground, a tall block opposite) - more than
    a room interior seen past a side window - but only the outside sees sky (found on Atelier 07)."""
    box = S.Shoebox(width=6, depth=6, height=3, wwr=0.9, orientation=180, obstruction_height=40, obstruction_distance=6)
    sc = box.build()
    assert [d["label"] for d in dl.aperture_groups(sc)[1]] == ["S"]


def test_radiation_sensors_on_a_thin_solid_are_not_doubled():
    sc = _empty_scene()
    v, f = _pane_solid(0, 4, 0, 3)
    g0 = S.grid_from_triangles(v, f, 0.5, 0.0, 0.0, face_up=False)
    grid, _ = studies.orient_outward(g0, sc, 0.05)
    big = np.abs(grid.normals[:, 1]) > 0.9
    assert int(big.sum()) == 2 * 8 * 6                         # front and back once each, not twice


def test_legend_stands_up_beside_a_3d_grid():
    from almond_mcp.environment import render
    cells = np.array([[[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1]], [[0, 0, 1], [1, 0, 1], [1, 0, 2], [0, 0, 2]]], float)
    quads, labels = render.legend_geometry(cells, 0, 1, "kWh/m2", "x", normals=np.array([[0, -1.0, 0]] * 2))
    zs = np.array([q[0] for q in quads])[:, :, 2]
    assert zs.max() > zs.min() and np.ptp(np.array([q[0] for q in quads])[:, :, 1]) == 0
    flat, _ = render.legend_geometry(cells, 0, 1, "lux", "x", normals=np.array([[0, 0, 1.0]] * 2))
    assert np.ptp(np.array([q[0] for q in flat])[:, :, 2]) == 0


def test_window_on_uncut_wall_is_reported():
    b = S.SceneBuilder()
    b.add_quad([[0, 0, 0], [0, 0, 3], [5, 0, 3], [5, 0, 0]], "wall", {"name": "wall", "guid": "w"})
    b.add_quad([[1, 0, 1], [1, 0, 2], [4, 0, 2], [4, 0, 1]], "glazing_double_clear", {"name": "win", "guid": "g", "layer": "Glazing"})
    covered = studies.covered_glazing(b.build())
    assert covered and covered[0]["object"] == "g" and covered[0]["covered_pct"] > 90
    assert studies.covered_glazing(S.Shoebox().build()) == []


# ── annual studies ───────────────────────────────────────────────────────────

def test_annual_daylight_run_and_lm83_shading(temperate):
    results = {}
    for orient in (0, 180):
        box = S.Shoebox(width=6, depth=6, height=3, wwr=0.5, orientation=orient)
        sc = box.build()
        grid = box.floor_grid(sc, 1.0)
        results[orient] = studies.run_daylight(sc, grid, temperate, "annual", "draft", label=f"o{orient}")
    north, south = results[0], results[180]
    assert south["metrics"]["ase_pct"] > north["metrics"]["ase_pct"]
    assert north["metrics"]["ase_pct"] < 5
    assert south["metrics"]["shades"][0]["closed_occupied_hours_pct"] > north["metrics"]["shades"][0]["closed_occupied_hours_pct"]
    for r in results.values():
        assert 0 <= r["metrics"]["sda_pct"] <= 100
        assert r["metrics"]["en17037"]["level"] in ("not met", "minimum", "medium", "high")
        assert all(Path(p).is_file() for p in r["images"])
        loaded, arrays = studies.load_run(r["run_id"])
        assert loaded["metrics"]["sda_pct"] == r["metrics"]["sda_pct"] and arrays["da"].shape == (36,)
    assert {r["run_id"] for r in studies.list_runs()} == {north["run_id"], south["run_id"]}


def test_glare_views_and_point_in_time(temperate):
    box = S.Shoebox(width=5, depth=5, height=3, wwr=0.5, orientation=180)
    sc = box.build()
    grid = box.floor_grid(sc, 1.0)
    views = [{"position": [0.0, -1.0, 1.2], "direction": [0.0, -1.0, 0.0]}, {"position": [0.0, -1.0, 1.2], "direction": [0.0, 1.0, 0.0]}]
    r = studies.run_daylight(sc, grid, temperate, "annual", "draft", views=views, en17037=False)
    g = r["metrics"]["glare_dgps"]
    assert g[0]["max_dgps"] > g[1]["max_dgps"]                  # facing the window is glarier
    pit = studies.run_daylight(sc, grid, temperate, "point_in_time", "draft", point_time={"month": 12, "day": 21, "hour": 12})
    cie = studies.run_daylight(sc, grid, temperate, "point_in_time", "draft",
                               point_time={"month": 12, "day": 21, "hour": 12, "sky": "cie_overcast", "horizontal_illuminance": 10000})
    df = studies.run_daylight(sc, grid, None, "daylight_factor", "draft", seed=0)
    assert cie["metrics"]["mean_lux"] == pytest.approx(df["metrics"]["average_df_pct"] * 100, rel=0.15)
    assert pit["metrics"]["mean_lux"] > 0


# ── radiation ────────────────────────────────────────────────────────────────

def test_open_horizontal_sensor_receives_global_horizontal(temperate):
    sc = _empty_scene()
    grid = S.grid_from_points([[0, 0, 0]])
    res = radiation.irradiation(sc, grid, temperate, dl.Quality(rays=4, bounces=0, patch_samples=6, ground_samples=8, cache_cell=0.3, mf=2))
    assert res["kwh_m2"][0] == pytest.approx(temperate["ghi"].sum() / 1000, rel=0.03)


def test_south_facade_gets_more_than_north_at_mid_latitude(temperate):
    sc = _empty_scene()
    grid = S.grid_from_points([[0, 0, 1], [0, 0, 1]], normals=[[0, -1, 0], [0, 1, 0]])
    res = radiation.irradiation(sc, grid, temperate, dl.quality("draft"))
    south, north = res["kwh_m2"]
    assert south > 2 * north and res["sun_hours"][1] < res["sun_hours"][0]


# ── thermal ──────────────────────────────────────────────────────────────────

def _constant_weather(w, t=0.0):
    import copy
    c = copy.deepcopy(w)
    c.data["dry_bulb"][:] = t
    c.ground_temperatures = [{"monthly_c": [t] * 12}]
    return c


def test_thermal_steady_state_matches_network(temperate):
    w = _constant_weather(temperate, 0.0)
    z = thermal.Zone("box", 48.0, 144.0, [thermal.Surface("window", 7.2, (0, -1, 0), u_value=1.6, g_value=0.4),
                                          thermal.Surface("wall", 10.8, (0, -1, 0)), thermal.Surface("adiabatic", 162, (0, 0, 1))])
    st = thermal.Settings(heating_setpoint=20, cooling_setpoint=None, setback=False, schedule="always", occupancy_w_m2=0,
                          equipment_w_m2=0, lighting_w_m2=0, infiltration_ach=0.5, ventilation_ach=0)
    thermal.apply_construction(z, st)
    r = thermal.simulate(z, w, st)
    m = r["model"]
    h_ve = 1200 * 0.5 * 144 / 3600
    expected = 20 * (h_ve + 1 / (1 / m["H_tr_is_w_k"] + 1 / (m["H_tr_w_w_k"] + m["H_tr_op_w_k"])))
    assert r["heating_w"][-1] == pytest.approx(expected, rel=1e-4)
    free = thermal.Settings(heating_setpoint=None, cooling_setpoint=None, schedule="always", occupancy_w_m2=0, equipment_w_m2=0, lighting_w_m2=0)
    assert np.allclose(thermal.simulate(z, w, free)["t_air"][-48:], 0.0, atol=1e-6)


def test_zone_from_mesh_areas_windows_and_adjacency():
    def box(x0, y0, z0, x1, y1, z1):
        v = np.array([[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0], [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]], float)
        f = [[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]]
        return v, np.array(f)
    v1, t1 = box(0, 0, 0, 4, 5, 3)
    v2, t2 = box(0, 0, 3, 4, 5, 6)
    win = {"vertices": [[1, 0, 1], [3, 0, 1], [3, 0, 2], [1, 0, 2]], "triangles": [[0, 1, 2], [0, 2, 3]], "name": "w", "g_value": 0.4, "u_value": 1.4}
    z = thermal.zone_from_mesh("ground", v1, t1, [win], other_zones=[(v2, t2)])
    assert z.floor_area == pytest.approx(20) and z.volume == pytest.approx(60)
    a = z.areas()
    assert a["window"] == pytest.approx(2.0) and a["ground_floor"] == pytest.approx(20) and a["adiabatic"] == pytest.approx(20)
    assert a["wall"] == pytest.approx(2 * (4 + 5) * 3 - 2.0)
    win_s = [s for s in z.surfaces if s.kind == "window"][0]
    assert np.allclose(win_s.normal, (0, -1, 0)) and (win_s.samples[:, 1] < 0).all()
    upper = thermal.zone_from_mesh("upper", v2[::-1], t2, [], other_zones=[(v1, t1)])
    assert upper.areas()["roof"] == pytest.approx(20) and upper.areas()["adiabatic"] == pytest.approx(20)


def test_thermal_run_tropical_overheats_free_running(tropical):
    box = S.Shoebox(orientation=270)
    sc = box.build()
    z = thermal.zone_from_shoebox(box, sc, S.LIBRARY["glazing_double_lowe"])
    free = studies.run_thermal([z], sc, tropical, thermal.Settings(heating_setpoint=None, cooling_setpoint=None, natural_ventilation_ach=4))
    s = free["zones"][0]
    assert free["mode"] == "free-running" and s["tm52"]["applicable"] and not s["tm52"]["pass"]
    cooled = studies.run_thermal([z], sc, tropical, thermal.Settings(heating_setpoint=20, cooling_setpoint=26))
    c = cooled["zones"][0]
    assert c["cooling_kwh_m2"] > 30 and c["heating_kwh_m2"] == 0
    assert len(c["monthly"]) == 12


# ── climate ──────────────────────────────────────────────────────────────────

def test_climate_summary(temperate, tropical):
    t = climate.summarize(temperate)
    assert t["annual"]["hdd_18"] > 1000 and t["monthly"][0]["dry_bulb_mean"] < t["monthly"][6]["dry_bulb_mean"]
    assert abs(sum(r["total_pct"] for r in t["wind_rose"]["sectors"]) + t["wind_rose"]["calm_pct"] - 100) < 0.5
    tr = climate.summarize(tropical)
    assert tr["annual"]["hdd_18"] == 0 and tr["strategies"]["hours_pct"]["active_heating"] == 0
    assert tr["strategies"]["hours_pct"]["natural_ventilation"] > t["strategies"]["hours_pct"]["natural_ventilation"]
    bins = climate.psychrometric_bins(tropical)["bins"]
    assert sum(b[2] for b in bins) == 8760


# ── MCP tools ────────────────────────────────────────────────────────────────

@pytest.fixture()
def server(monkeypatch, tmp_path):
    caps = tmp_path / "capsules"
    caps.mkdir()
    return _load_server(monkeypatch, tmp_path, caps)


def _export_of(scene: S.Scene, layers: dict[str, str], guid_of: dict[str, str]) -> dict:
    objs = []
    for i, o in enumerate(scene.objects):
        sel = scene.tri_object == i
        t = scene.triangles[sel]
        used, inv = np.unique(t, return_inverse=True)
        objs.append({"guid": guid_of[o["part"] + str(i)], "layer": layers[o["part"]], "name": o["name"], "material": "",
                     "transparency": 0.0, "env_material": "", "vertices": (scene.vertices[used] * 1000).reshape(-1).tolist(),
                     "faces": inv.reshape(-1).tolist()})
    return {"units_to_m": 0.001, "units": "Millimeters", "rhino_north_deg": 90.0, "objects": objs, "missing": [], "skipped": []}


class ExportingBridge(BridgeMock):
    """Answers the export script by writing ``export`` to the path the script names."""

    def __init__(self, export: dict):
        super().__init__(json.dumps({"status": "success", "guids": ["11111111-2222-3333-4444-555555555555"]}))
        self.export = export

    def __call__(self, payload_bytes, timeout=60.0):
        msg = json.loads(payload_bytes.decode("utf-8"))
        m = re.search(r'File\.WriteAllText\(@"([^"]+)"', msg.get("script", ""))
        if m:
            Path(m.group(1)).write_text(json.dumps(self.export), encoding="utf-8")
        return super().__call__(payload_bytes, timeout)


def test_tools_shoebox_without_rhino(server, temperate, monkeypatch):
    def no_bridge(*_a, **_k):
        raise AssertionError("shoebox studies must not contact Rhino")
    monkeypatch.setattr(server, "_send_and_receive", no_bridge)
    epw_path = temperate.source_path
    r = _call(server.analyze_daylight, epw_path=epw_path, shoebox={"width": 5, "depth": 6, "orientation": 180}, quality="draft",
              grid_spacing_m=1.0)
    assert r["status"] == "success" and "sda_pct" in r["metrics"] and "rhino" not in r
    df = _call(server.analyze_daylight, study="daylight_factor", shoebox={"width": 5, "depth": 6}, quality="draft", grid_spacing_m=1.0)
    assert df["status"] == "success" and df["metrics"]["average_df_pct"] > 0
    rad = _call(server.analyze_solar_radiation, epw_path=epw_path, shoebox={"orientation": 180}, grid_spacing_m=1.5)
    assert rad["status"] == "success" and rad["metrics"]["mean_kwh_m2"] > 100
    th = _call(server.analyze_thermal, epw_path=epw_path, shoebox={"orientation": 180}, construction="insulated")
    assert th["status"] == "success" and th["zones"][0]["heating_kwh_m2"] >= 0
    cs = _call(server.climate_summary, epw_path=epw_path, include_psychrometric_bins=True)
    assert cs["status"] == "success" and len(cs["monthly"]) == 12 and cs["psychrometric_bins"]["bins"]
    sp = _call(server.sun_path, epw_path=epw_path, month=6, day=21, include_diagram=True)
    assert sp["status"] == "success" and 14 < sp["events"]["day_length_h"] < 16 and sp["diagram"]["months"]
    tc = _call(server.thermal_comfort, air_temperature_c=27, relative_humidity=60, air_speed=0.1, clothing=0.5,
               outdoor_running_mean_c=28)
    assert tc["pmv"] == pytest.approx(0.77, abs=0.02) and "II" in tc["adaptive_en16798"]
    runs = _call(server.list_environment_runs)["runs"]
    assert len(runs) == 4
    got = _call(server.get_environment_run, run_id=r["run_id"], include_values=True, metric="da")
    assert len(got["values"]["values"]) == r["grid"]["sensors"]
    assert _call(server.list_environment_materials)["materials"]


def test_tools_validate_inputs(server, monkeypatch):
    monkeypatch.setattr(server, "_send_and_receive", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no bridge")))
    assert _call(server.analyze_daylight, study="annual", shoebox={"width": 5})["status"] == "error"          # no EPW
    assert "grid_guids" in _call(server.analyze_daylight, study="daylight_factor")["message"]
    assert _call(server.analyze_daylight, study="daylight_factor", shoebox={"wwr": 2})["status"] == "error"
    assert "Unknown shoebox" in _call(server.analyze_daylight, study="daylight_factor", shoebox={"wdth": 5})["message"]
    assert _call(server.sun_path)["status"] == "error"
    assert _call(server.get_environment_run, run_id="../etc")["status"] == "error"
    assert _call(server.thermal_comfort, air_temperature_c=25, relative_humidity=150)["status"] == "error"


def test_tools_rhino_flow_classifies_by_layer_and_draws(server, temperate, monkeypatch):
    box = S.Shoebox(width=5, depth=5, height=3, orientation=180, ground=False)
    sc = box.build()
    guid_of = {f"{o['part']}{i}": f"{i:08d}-0000-0000-0000-000000000000" for i, o in enumerate(sc.objects)}
    layers = {"floor": "Building::Floor", "ceiling": "Building::Ceiling", "wall": "Building::Walls", "facade": "Building::Walls",
              "window": "Building::Glazing", "shading": "Building::Shading", "context": "Site::Context", "ground": "Site::Ground"}
    export = _export_of(sc, layers, guid_of)
    bridge = ExportingBridge(export)
    monkeypatch.setattr(server, "_send_and_receive", bridge)
    floor_guid = guid_of["floor0"]
    r = _call(server.analyze_daylight, epw_path=temperate.source_path, study="daylight_factor", grid_guids=[floor_guid],
              quality="draft", grid_spacing_m=1.0)
    assert r["status"] == "success", r
    mats = {c["material"] for c in r["scene"]["classification"]}
    assert {"floor", "ceiling", "wall", "glazing_double_lowe"} <= mats
    assert r["inputs"]["units_to_m"] == 0.001 and r["grid"]["sensors"] == 25
    assert r["rhino"]["status"] == "success" and r["rhino"]["metric"] == "df"
    scripts = [p[0]["script"] for p in bridge.payloads]
    assert len(scripts) == 2 and "Almond::Environment::" in scripts[1] and "almond:env_result" in scripts[1]
    # the drawing is in model units (mm): the legend and quads are scaled back up
    assert r["rhino"]["range"] == [0, 5]
    shown = _call(server.show_environment_result, run_id=r["run_id"], metric="df_direct")
    assert shown["status"] == "success"
    assert _call(server.show_environment_result, run_id=r["run_id"], metric="nope")["status"] == "error"
    assert _call(server.show_environment_result, clear=True)["status"] == "success"


# ── findings from the Fable test drive (2026-11-03) ──────────────────────────

def _box_mesh(x0, y0, z0, x1, y1, z1):
    v = np.array([[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0], [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]], float)
    f = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]])
    return v, f


def test_a_slab_solid_gets_one_work_plane_grid():
    v, f = _box_mesh(0, 0, 0, 4, 4, 0.024)
    g = S.grid_from_triangles(v, f, 0.5, 0.76)
    assert g.n == 64 and np.allclose(g.points[:, 2], 0.784)
    assert ((g.points[:, :2] >= 0) & (g.points[:, :2] <= 4)).all()
    wall_v, wall_f = _box_mesh(0, 0, 0, 4, 0.2, 3)
    with pytest.raises(ValueError, match="horizontal floor surfaces"):
        S.grid_from_triangles(wall_v[[0, 1, 5, 4]], np.array([[0, 1, 2], [0, 2, 3]]), 0.5, 0.76)


@pytest.mark.parametrize("name,expected", [("Roof slab", "roof"), ("Floor slab", "floor"), ("West window mullion", "frame"),
                                           ("Window transom", "frame"), ("Oak window sill", "frame"),
                                           ("Frameless glazing", "glazing_double_lowe"), ("Glazed facade pane", "glazing_double_lowe")])
def test_name_rules_read_real_model_names(name, expected):
    assert S.classify(["A07 / Model", name, ""])[0] == expected


# objects from the Atelier 07 model that the old "glass|curtain" rule sent to clear glazing (EN 17037 run)
@pytest.mark.parametrize("layer,name,material,expected", [
    ("A07 / 11 Architectural details", "Full-height linen curtain fold", "A07 / Linen", "shading"),
    ("A07 / 10 Objects and graphics", "Dining tumbler", "A07 / Glass", "ignore"),
    ("A07 / 09 Bathroom", "Shower screen", "A07 / Glass", "ignore"),
    ("A07 / 09 Bathroom", "Mirror", "A07 / Skyglass", "furniture"),
    ("A07 / 06 Kitchen", "Oven viewing glass", "A07 / Skyglass", "furniture"),
    ("A07 / 06 Kitchen", "Oven black glass", "A07 / Ink", "furniture"),
    ("A07 / 10 Objects and graphics", "Laptop lit display", "A07 / Skyglass", "furniture"),
    ("A07 / 03 Facade", "Glazed facade pane", "A07 / Glass", "glazing_double_lowe"),
    ("A07 / 13 Urban context", "City recessed window", "A07 / Skyglass", "glazing_double_lowe"),
])
def test_interior_glass_and_textiles_are_not_windows(layer, name, material, expected):
    assert S.classify([layer, name, material], transparency=0.9 if material.endswith("Glass") else 0.0)[0] == expected


@pytest.mark.parametrize("name,expected", [
    ("Curtain wall", "glazing_double_lowe"), ("Curtainwall panel", "glazing_double_lowe"),
    ("Curtain_wall unit", "glazing_double_lowe"), ("Low-e curtain wall", "glazing_double_lowe"),
    ("Curtain wall mullion", "frame"), ("Sheer curtain", "shading"), ("Drapes", "shading"),
    ("Roller blind", "shading"), ("Venetian blinds", "shading"), ("Blind wall", "wall"),
    ("Mirror glass facade", "glazing_double_lowe"), ("Woven screen", "shading"), ("Shower screen shoe", "shading"),
])
def test_curtain_walls_stay_glazing_and_textiles_shade(name, expected):
    assert S.classify(["Model", name, ""])[0] == expected


def test_curtain_in_front_of_a_window_is_opaque_shading():
    """A curtain in front of a window used to be a second pane: light crossed it at tau 0.7."""
    def export(curtain_name):
        quad = lambda x0, x1, y, z0, z1: [x0, y, z0, x1, y, z0, x1, y, z1, x0, y, z1]
        return {"units_to_m": 1.0, "objects": [
            {"guid": "w", "layer": "Glazing", "name": "Window", "material": "", "transparency": 0, "env_material": "",
             "vertices": quad(0, 2, 0, 0, 2), "faces": [0, 1, 2, 0, 2, 3]},
            {"guid": "c", "layer": "Details", "name": curtain_name, "material": "Linen", "transparency": 0, "env_material": "",
             "vertices": quad(0, 2, 0.2, 0, 2), "faces": [0, 1, 2, 0, 2, 3]}]}
    sc = S.scene_from_export(export("Full-height linen curtain fold"))
    kinds = {o["guid"]: o["material"] for o in sc.objects}
    assert kinds == {"w": "glazing_double_lowe", "c": "shading"}
    assert [m.kind for m in sc.materials if m.name == "shading"] == ["opaque"]


def test_slab_solid_underside_is_a_ceiling():
    v, f = _box_mesh(0, 0, 3.0, 4, 4, 3.25)
    data = {"units_to_m": 1.0, "objects": [{"guid": "s", "layer": "Floors", "name": "Upper slab", "material": "", "transparency": 0,
                                            "env_material": "", "vertices": v.reshape(-1).tolist(), "faces": f.reshape(-1).tolist()}]}
    sc = S.scene_from_export(data)
    n, _ = sc.normals()
    names = np.array([m.name for m in sc.materials])[sc.tri_material]
    assert set(names[n[:, 2] < -0.7]) == {"ceiling"} and set(names[n[:, 2] > 0.7]) == {"floor"}


def test_radiation_counts_light_reflected_by_modelled_ground(temperate):
    out = {}
    for ground in (True, False):
        box = S.Shoebox(orientation=0, ground=ground)
        sc = box.build()
        sel = box.part_mask(sc, "facade") | box.part_mask(sc, "window")
        g0 = S.grid_from_triangles(sc.vertices, sc.triangles[sel], 1.0, 0.0, 0.0, face_up=False)
        grid, _ = studies.orient_outward(g0, sc, 0.05)
        for rho in (0.0, 0.4):
            out[(ground, rho)] = studies.run_radiation(sc, grid, temperate, "draft", ground_reflectance=rho)["metrics"]["mean_kwh_m2"]
    assert out[(True, 0.4)] > 1.15 * out[(True, 0.0)]                       # the parameter acts on modelled ground
    assert out[(True, 0.4)] == pytest.approx(out[(False, 0.4)], rel=0.12)   # modelled ground ~ ground patch


def test_glare_probability_is_bounded_and_sun_hours_flagged(temperate):
    assert float(dl.dgp_simplified(85000)) == 1.0
    box = S.Shoebox(width=5, depth=5, height=3, wwr=0.5, orientation=180)
    sc = box.build()
    r = studies.run_daylight(sc, box.floor_grid(sc, 1.0), temperate, "annual", "draft", en17037=False,
                             views=[{"position": [0.0, -2.0, 1.2], "direction": [0.0, -1.0, 0.0]}])
    g = r["metrics"]["glare_dgps"][0]
    assert g["sun_in_view_pct"] > 0 and (g["max_dgps"] is None or g["max_dgps"] <= 1.0)


def test_point_in_time_overcast_needs_no_weather():
    box = S.Shoebox(width=5, depth=5)
    sc = box.build()
    grid = box.floor_grid(sc, 1.0)
    r = studies.run_daylight(sc, grid, None, "point_in_time", "draft",
                             point_time={"sky": "cie_overcast", "horizontal_illuminance": 10000})
    assert r["metrics"]["mean_lux"] > 0
    with pytest.raises(ValueError, match="needs the site"):
        studies.run_daylight(sc, grid, None, "point_in_time", "draft", point_time={"sky": "cie_12"})


def test_a_wall_is_not_accepted_as_a_zone(temperate):
    v, f = _box_mesh(0, 0, 0, 13.2, 0.2, 6.25)
    z = thermal.zone_from_mesh("wall", v, f, [])
    st = thermal.Settings()
    thermal.apply_construction(z, st)
    with pytest.raises(ValueError, match="not a room|wide in plan"):
        thermal.simulate(z, temperate, st)


def test_ventilation_defaults_follow_floor_area_not_volume(temperate):
    def heating(h):
        v, f = _box_mesh(0, 0, 0, 10, 10, h)
        z = thermal.zone_from_mesh("room", v, f, [])
        st = thermal.Settings(schedule="residential", cooling_setpoint=None, infiltration_ach=0.0)
        thermal.apply_construction(z, st)
        r = thermal.simulate(z, temperate, st)
        assert r["model"]["ventilation_l_s_m2_occupied"] == pytest.approx(0.42)
        return r["model"]["H_ve_base_w_k"]
    assert heating(6.0) == pytest.approx(heating(3.0), rel=0.02)        # same floor, same fresh air


def test_climate_summary_does_not_call_dni_hours_sunshine(temperate):
    a = climate.summarize(temperate)
    assert "bright_sun_hours" in a["annual"] and "sunshine_hours" not in a["annual"]
    assert any("bright_sun_hours" in n for n in a["notes"])


def test_tools_background_study_returns_a_job(server, temperate, monkeypatch):
    import time as _time
    monkeypatch.setattr(server, "_send_and_receive", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no bridge")))
    job = _call(server.analyze_daylight, study="daylight_factor", shoebox={"width": 5, "depth": 5}, quality="draft",
                grid_spacing_m=1.0, background=True)
    assert job["status"] == "running" and job["job_id"].startswith("job-daylight-")
    for _ in range(600):
        r = _call(server.get_environment_run, run_id=job["job_id"])
        if r["status"] != "running":
            break
        _time.sleep(0.1)
    assert r["status"] == "success" and r["run_id"].startswith("daylight-"), r
    assert _call(server.analyze_daylight, study="foo", shoebox={"width": 5})["message"].startswith("study must be")
    ok = _call(server.analyze_daylight, study="point_in_time", shoebox={"width": 5, "depth": 5}, quality="draft",
               grid_spacing_m=1.0, point_in_time={"sky": "cie_overcast", "horizontal_illuminance": 10000})
    assert ok["status"] == "success"
