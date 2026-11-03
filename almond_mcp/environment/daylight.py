"""Daylight simulation: daylight coefficients, daylight factor, point-in-time and annual climate-based metrics.

Method (backward tracing, in the spirit of Radiance's rcontrib / five-phase method):

1. **Direct sky coefficients** ``D[g, s, p]``: for each sensor ``s``, every sky patch ``p`` is sampled
   with a few stratified shadow rays (plus the ground hemisphere); a ray passes clear glazing with its
   angular transmittance and is stopped by anything opaque. ``g`` is the aperture group the light
   came through (0 = none, e.g. an outdoor sensor or an unglazed opening).
2. **Interreflected coefficients** ``I[g, s, p]``: an irradiance-cache radiosity solve. Eye rays from
   each sensor find the surface cells it sees; cosine rays from those cells find the cells they see,
   a few levels deep, giving a sparse transport matrix; every cell's direct sky coefficients are
   computed deterministically; and E = Dc + F rho E is iterated once per bounce. Sensors gather
   rho x E at their first hit only, so they never rely on a random walk finding a small sky patch
   (or the sun's patch) by chance. Cells grow with bounce level and distance, and each is
   represented by a real hit point. Checked against an unbiased path tracer (``_indirect_paths``).
3. **Sun**: traced exactly for every hour (shadow ray from each sensor towards the sun through
   glazing), so sun patches and ASE are not smeared over a 12-degree patch. Its interreflected part
   uses ``I`` with the sun put into the patch that holds it.

Illuminance in hour h:  E = sum_g (D_g + I_g) . sky_h  +  I_g . sun_patch_h  +  sun_g,h x E_dn,h

Dynamic shading per IES LM-83-12: an aperture group's shade closes (a diffusing transmitter of
``shade_transmittance``) in any hour where more than 2 % of the sensors receive over 1000 lux of
direct sunlight through it; the closed state has its own coefficients (a second trace per group).

Metrics: daylight factor (CIE overcast), sDA300/50 % and ASE1000,250h (LM-83), DA, cDA, UDI
(Nabil & Mardaljevic bins), EN 17037 daylight provision (target / minimum target), simplified
daylight glare probability (DGPs, Wienold 2009) for view sensors.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

import numpy as np

from . import raytrace, sky as skymod
from .scene import Scene, SensorGrid, glazing_transmittance, pane_faces, principal_normal, thin_solid_panes

EPS = 2e-4                     # m: ray origin offset off surfaces


@dataclass(frozen=True)
class Quality:
    rays: int                  # eye paths per sensor (interreflections)
    bounces: int               # diffuse bounces
    patch_samples: int         # shadow rays per sky patch
    ground_samples: int        # shadow rays into the ground hemisphere
    cache_cell: float          # m, irradiance cache cell size
    mf: int                    # sky subdivision (1 = Tregenza 145)
    cache_rays: int = 32       # rays per cache cell for the interreflection transport


QUALITY = {
    "draft": Quality(rays=64, bounces=3, patch_samples=2, ground_samples=12, cache_cell=0.5, mf=1, cache_rays=32),
    "medium": Quality(rays=256, bounces=5, patch_samples=3, ground_samples=24, cache_cell=0.3, mf=1, cache_rays=128),
    "high": Quality(rays=1024, bounces=6, patch_samples=6, ground_samples=48, cache_cell=0.2, mf=2, cache_rays=256),
}


def quality(name: str | Quality) -> Quality:
    if isinstance(name, Quality):
        return name
    if name not in QUALITY:
        raise ValueError(f"quality must be one of {', '.join(QUALITY)}")
    return QUALITY[name]


# ── sampling helpers ─────────────────────────────────────────────────────────

def _basis(n: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    a = np.where(np.abs(n[:, :1]) < 0.9, np.array([[1.0, 0, 0]]), np.array([[0, 1.0, 0]]))
    t1 = np.cross(n, a)
    t1 /= np.linalg.norm(t1, axis=1, keepdims=True)
    return t1, np.cross(n, t1)


def cosine_directions(normals: np.ndarray, u1: np.ndarray, u2: np.ndarray) -> np.ndarray:
    """Cosine-weighted directions about ``normals`` (N, 3) from uniforms u1, u2 (N,)."""
    t1, t2 = _basis(normals)
    r = np.sqrt(u1)
    phi = 2 * np.pi * u2
    z = np.sqrt(np.maximum(0.0, 1 - u1))
    return (r * np.cos(phi))[:, None] * t1 + (r * np.sin(phi))[:, None] * t2 + z[:, None] * normals


def stratified_uniforms(n_points: int, r: int, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """(n_points * r) jittered pairs, stratified per point on a sqrt(r) grid (rest random)."""
    m = int(math.isqrt(r))
    gx, gy = np.meshgrid(np.arange(m), np.arange(m))
    base1 = gx.ravel() / m
    base2 = gy.ravel() / m
    u1 = (base1[None, :] + rng.random((n_points, m * m)) / m)
    u2 = (base2[None, :] + rng.random((n_points, m * m)) / m)
    extra = r - m * m
    if extra:
        u1 = np.concatenate([u1, rng.random((n_points, extra))], axis=1)
        u2 = np.concatenate([u2, rng.random((n_points, extra))], axis=1)
    return u1.ravel(), u2.ravel()


def patch_sample_directions(p: skymod.Patches, k: int, k_ground: int, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Shadow-ray directions for direct coefficients: k area-uniform stratified samples inside every
    sky patch and k_ground uniform samples of the lower hemisphere. Returns (dirs, patch, weight) with
    weight = solid angle per sample (so sum(weight * cos * V) is the patch's irradiance coefficient)."""
    dirs, pid, wts = [], [], []
    rh = p.row_height
    n_rows = len(p.row_count) - 1
    for r in range(n_rows + 1):
        n = p.row_count[r]
        a0 = r * rh
        a1 = 90.0 if r == n_rows else (r + 1) * rh
        s0, s1 = math.sin(math.radians(a0)), math.sin(math.radians(a1))
        width = 360.0 / n
        idx = p.row_start[r] + np.arange(n)
        # stratify each patch into k azimuth strips
        j = (np.arange(k)[None, :] + rng.random((n, k))) / k
        az = (idx - p.row_start[r])[:, None] * width - 0.5 * width + j * width
        if r == n_rows:
            az = rng.random((n, k)) * 360.0
        sz = s0 + rng.random((n, k)) * (s1 - s0)
        alt = np.degrees(np.arcsin(sz))
        ar, zr = np.radians(alt), np.radians(az)
        d = np.stack([np.cos(ar) * np.sin(zr), np.cos(ar) * np.cos(zr), np.sin(ar)], axis=-1).reshape(-1, 3)
        dirs.append(d)
        pid.append(np.repeat(idx, k))
        wts.append(np.repeat(p.solid_angle[idx] / k, k))
    if k_ground:
        m = int(math.isqrt(k_ground))
        u1, u2 = stratified_uniforms(1, max(k_ground, m * m), rng)
        z = -u1                                   # uniform in the lower hemisphere: -cos uniform on [0,1]
        rr = np.sqrt(np.maximum(0.0, 1 - z * z))
        phi = 2 * np.pi * u2
        d = np.stack([rr * np.cos(phi), rr * np.sin(phi), np.minimum(z, -1e-4)], axis=1)
        dirs.append(d)
        pid.append(np.full(len(d), p.n_sky))
        wts.append(np.full(len(d), 2 * np.pi / len(d)))
    return np.vstack(dirs), np.concatenate(pid), np.concatenate(wts)


# ── the tracer ───────────────────────────────────────────────────────────────

class Tracer:
    """Ray tracing services over one scene with one shading state."""

    def __init__(self, scene: Scene, groups: np.ndarray | None = None, closed: set[int] | frozenset = frozenset()):
        scene = scene.clean()
        self.scene = scene
        a, b, c = scene.corners()
        self.bvh = raytrace.BVH(a, b, c)
        self.normal, self.area = scene.normals()
        mats = scene.materials
        kinds = np.array([m.kind for m in mats])
        self.glazing = kinds[scene.tri_material] == "glazing"
        self.rho = np.array([m.reflectance if m.kind == "opaque" else 0.0 for m in mats])[scene.tri_material]
        self.tau = np.array([m.transmittance for m in mats])[scene.tri_material]
        self.tau_shade = np.array([m.shade_transmittance for m in mats])[scene.tri_material]
        self.group = np.zeros(len(scene.triangles), dtype=np.int64) if groups is None else np.asarray(groups, dtype=np.int64)
        if len(self.group) != len(scene.triangles):
            raise ValueError("aperture group array does not match the cleaned scene")
        self.n_groups = int(self.group.max()) + 1 if len(self.group) else 1
        self.closed = self.glazing & np.isin(self.group, list(closed))
        self.half = thin_solid_panes(scene)          # faces of panes modelled as thin solids
        self.tau_shade = np.where(self.half, np.sqrt(self.tau_shade), self.tau_shade)
        self._planes = None

    def glass_T(self, tri: np.ndarray, cos: np.ndarray) -> np.ndarray:
        """Directional transmittance of crossing glazing triangle(s); a face of a thin-solid pane
        carries the square root, so crossing both faces gives the pane's value."""
        t = glazing_transmittance(self.tau[tri], cos)
        return np.where(self.half[tri], np.sqrt(t), t)

    # -- straight-line transmission (shadow rays) --
    def transmit(self, origins: np.ndarray, dirs: np.ndarray, max_crossings: int = 8) -> tuple[np.ndarray, np.ndarray]:
        """Fraction of light arriving along each ray from infinity (through clear glazing), and the
        last aperture group crossed. Opaque surfaces and closed shades block it."""
        n = len(origins)
        T = np.ones(n)
        grp = np.zeros(n, dtype=np.int64)
        o = np.array(origins, dtype=float)
        alive = np.arange(n)
        for _ in range(max_crossings):
            if not alive.size:
                break
            t, tri = self.bvh.intersect(o[alive], dirs[alive])
            hit = tri >= 0
            alive, t, tri = alive[hit], t[hit], tri[hit]
            if not alive.size:
                break
            block = ~self.glazing[tri] | self.closed[tri]
            T[alive[block]] = 0.0
            keep = ~block
            alive, t, tri = alive[keep], t[keep], tri[keep]
            if not alive.size:
                break
            d = dirs[alive]
            cos = np.abs(np.einsum("ij,ij->i", self.normal[tri], d))
            T[alive] *= self.glass_T(tri, cos)
            grp[alive] = self.group[tri]
            o[alive] = o[alive] + d * (t + EPS)[:, None]
            dead = T[alive] < 1e-6
            T[alive[dead]] = 0.0
            alive = alive[~dead]
        if alive.size:   # still crossing glazing after max_crossings: treat as blocked
            hit = self.bvh.intersect(o[alive], dirs[alive])[1] >= 0
            T[alive[hit]] = 0.0
        return T, grp

    # -- direct coefficients --
    def direct_coefficients(self, points: np.ndarray, normals: np.ndarray, p: skymod.Patches, q: Quality,
                            rng: np.random.Generator, max_rays: int = 2_000_000) -> np.ndarray:
        """(groups, N, n_patches) float32 direct irradiance coefficients."""
        N = len(points)
        G = self.n_groups
        out = np.zeros(G * N * p.n, dtype=np.float64)
        sdirs, spid, sw = patch_sample_directions(p, q.patch_samples, q.ground_samples, rng)
        per_point = len(sdirs)
        step = max(1, max_rays // per_point)
        for s in range(0, N, step):
            e = min(N, s + step)
            P, Nn = points[s:e], normals[s:e]
            cos = Nn @ sdirs.T                                       # (n, S)
            pi, si = np.nonzero(cos > 1e-6)
            if not pi.size:
                continue
            d = sdirs[si]
            o = P[pi] + Nn[pi] * EPS
            T, grp = self.transmit(o, d)
            w = sw[si] * cos[pi, si] * T
            nz = w > 0
            key = (grp[nz] * N + (pi[nz] + s)) * p.n + spid[si[nz]]
            out += np.bincount(key, weights=w[nz], minlength=G * N * p.n)
        return out.reshape(G, N, p.n).astype(np.float32)

    # -- plane groups for the irradiance cache --
    def _plane_ids(self) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        if self._planes is None:
            n = self.normal
            a = self.scene.corners()[0]
            dd = np.einsum("ij,ij->i", n, a)
            keys = np.concatenate([np.round(n * 200).astype(np.int64), np.round(dd / 0.005).astype(np.int64)[:, None]], axis=1)
            uniq, inv = np.unique(keys, axis=0, return_inverse=True)
            inv = inv.reshape(-1)
            pn = np.zeros((len(uniq), 3))
            np.add.at(pn, inv, n)
            pn /= np.maximum(np.linalg.norm(pn, axis=1, keepdims=True), 1e-12)
            t1, t2 = _basis(pn)
            self._planes = (inv, pn, t1, t2)
        return self._planes

    # -- interreflected coefficients --
    def _first_scatter(self, O: np.ndarray, D: np.ndarray, T: np.ndarray, eg: np.ndarray, max_crossings: int = 8):
        """Follow rays through clear glazing to their first scattering surface (opaque, or a closed
        diffusing shade). Returns (ray index, position, triangle, cache-side normal, factor, T incl.
        glazing, aperture group after the vertex)."""
        O = O.copy()
        T = T.copy()
        eg = eg.copy()
        alive = np.arange(len(O))
        out = {k: [] for k in ("idx", "pos", "tri", "side", "fac", "T", "eg")}
        for _ in range(max_crossings + 1):
            if not alive.size:
                break
            t, tri = self.bvh.intersect(O[alive], D[alive])
            hit = tri >= 0
            alive, t, tri = alive[hit], t[hit], tri[hit]
            if not alive.size:
                break
            d = D[alive]
            pos = O[alive] + d * t[:, None]
            n_t = self.normal[tri]
            cosd = np.einsum("ij,ij->i", n_t, d)
            shade = self.glazing[tri] & self.closed[tri]
            clear = self.glazing[tri] & ~shade
            if clear.any():
                ci = alive[clear]
                T[ci] *= self.glass_T(tri[clear], np.abs(cosd[clear]))
                eg[ci] = self.group[tri[clear]]
                O[ci] = pos[clear] + d[clear] * EPS
            scat = ~clear
            if scat.any():
                si, ts = alive[scat], tri[scat]
                towards = np.where(cosd[scat][:, None] < 0, n_t[scat], -n_t[scat])     # faces the arriving ray
                is_shade = shade[scat]
                out["idx"].append(si)
                out["pos"].append(pos[scat])
                out["tri"].append(ts)
                out["side"].append(np.where(is_shade[:, None], -towards, towards))       # side the light comes from
                out["fac"].append(np.where(is_shade, self.tau_shade[ts], self.rho[ts]))
                out["T"].append(T[si])
                out["eg"].append(np.where(is_shade, self.group[ts], eg[si]))
            alive = alive[clear]
            alive = alive[T[alive] > 1e-7]
        if not out["idx"]:
            e = np.zeros(0)
            return (e.astype(np.int64), np.zeros((0, 3)), e.astype(np.int64), np.zeros((0, 3)), e, e, e.astype(np.int64))
        return tuple(np.concatenate(out[k]) for k in ("idx", "pos", "tri", "side", "fac", "T", "eg"))

    def _cell_keys(self, pos: np.ndarray, tri: np.ndarray, side_n: np.ndarray, cell: float, level: int,
                   centre: np.ndarray, radius: float) -> np.ndarray:
        """One int64 per irradiance-cache cell: plane id, side, a size exponent, and the square cell on
        the plane. Cells double in size per bounce level and with distance beyond 10 m from the sensors
        (light reaching a sensor through more bounces, or from far away, varies more smoothly)."""
        plane, pn, t1, t2 = self._plane_ids()
        pid = plane[tri].astype(np.int64)
        side = (np.einsum("ij,ij->i", side_n, pn[pid]) >= 0).astype(np.int64)
        dist = np.maximum(np.linalg.norm(pos - centre, axis=1) - radius, 0.0)
        exp = np.clip(min(level, 2) + np.floor(np.log2(np.maximum(1.0, dist / 10.0))).astype(np.int64), 0, 15)
        size = cell * (2.0 ** exp)
        half = 1 << 17
        ix = np.clip(np.floor(np.einsum("ij,ij->i", pos, t1[pid]) / size).astype(np.int64) + half, 0, (1 << 18) - 1)
        iy = np.clip(np.floor(np.einsum("ij,ij->i", pos, t2[pid]) / size).astype(np.int64) + half, 0, (1 << 18) - 1)
        if pid.size and pid.max() >= (1 << 22):
            raise ValueError("Too many distinct surface planes for the irradiance cache (over 4 million)")
        return ((((pid << 1 | side) << 4 | exp) << 18 | ix) << 18) | iy

    def indirect_coefficients(self, points: np.ndarray, normals: np.ndarray, p: skymod.Patches, q: Quality,
                              rng: np.random.Generator, max_cells: int = 150_000) -> tuple[np.ndarray, dict]:
        """Interreflected coefficients by an irradiance-cache radiosity solve.

        Eye rays find the surface cells each sensor sees first. From those cells, cosine rays
        discover the cells they see (``q.bounces - 1`` levels deep) and record a sparse transport
        matrix. Each cell's direct sky coefficients are computed deterministically, and the cells'
        total irradiance is solved by Jacobi iteration, E = Dc + F rho E, keeping track of the
        aperture group the light entered through. Sensors gather rho x E at their first hits only,
        so their noise comes from one well-sampled bounce instead of a random walk."""
        N, G, R = len(points), self.n_groups, q.rays
        u1, u2 = stratified_uniforms(N, R, rng)
        nn = np.repeat(normals, R, axis=0)
        D = cosine_directions(nn, u1, u2)
        O = np.repeat(points, R, axis=0) + nn * EPS
        idx, pos, tri, side, fac, Tg, eg = self._first_scatter(O, D, np.full(N * R, 1.0 / R), np.zeros(N * R, dtype=np.int64))
        info = {"paths": N * R, "eye_hits": int(len(idx)), "cache_points": 0, "transport_entries": 0}
        I = np.zeros((G, N, p.n), dtype=np.float32)
        if not len(idx):
            return I, info
        eye_s = idx // R
        eye_w = Tg * fac
        eye_eg = eg
        centre = points.mean(axis=0)
        radius = float(np.linalg.norm(points - centre, axis=1).max()) if N else 0.0
        eye_key = self._cell_keys(pos, tri, side, q.cache_cell, 0, centre, radius)
        # cell registry (sorted keys), with summed positions / normals for each cell
        reg_keys = np.unique(eye_key)
        def _means(keys_sorted, k, ps, ns):
            """Each cell is represented by its hit nearest the hits' centroid - a point on the real
            surface (a centroid alone can fall into a window opening in the same plane)."""
            j = np.searchsorted(keys_sorted, k)
            M_ = len(keys_sorted)
            cnt = np.bincount(j, minlength=M_).astype(float)
            mp = np.stack([np.bincount(j, weights=ps[:, a], minlength=M_) for a in range(3)], 1) / np.maximum(cnt, 1)[:, None]
            d2 = ((ps - mp[j]) ** 2).sum(axis=1)
            order = np.lexsort((d2, j))
            first = order[np.concatenate([[True], j[order][1:] != j[order][:-1]])]
            rep_pos = np.zeros((M_, 3))
            rep_nrm = np.zeros((M_, 3))
            rep_pos[j[first]] = ps[first]
            rep_nrm[j[first]] = ns[first]
            return rep_pos, rep_nrm
        reg_pos, reg_nrm = _means(reg_keys, eye_key, pos, side)
        frontier = np.arange(len(reg_keys))
        ent_src, ent_dst_key, ent_w, ent_eg = [], [], [], []
        truncated = False
        for level in range(1, q.bounces):
            if not frontier.size:
                break
            # the first transport level carries most of the interreflected light; deeper ones are smoother
            Rc = max(4, q.cache_rays if level == 1 else q.cache_rays // 4)
            fu1, fu2 = stratified_uniforms(len(frontier), Rc, rng)
            fn = np.repeat(reg_nrm[frontier], Rc, axis=0)
            fd = cosine_directions(fn, fu1, fu2)
            fo = np.repeat(reg_pos[frontier], Rc, axis=0) + fn * EPS
            fidx, fpos, ftri, fside, ffac, fT, feg = self._first_scatter(fo, fd, np.full(len(fo), 1.0 / Rc),
                                                                        np.zeros(len(fo), dtype=np.int64))
            if not len(fidx):
                break
            fkey = self._cell_keys(fpos, ftri, fside, q.cache_cell, level, centre, radius)
            ent_src.append(frontier[fidx // Rc])
            ent_dst_key.append(fkey)
            ent_w.append(fT * ffac)
            ent_eg.append(feg)
            new_keys = np.setdiff1d(np.unique(fkey), reg_keys, assume_unique=True)
            if len(reg_keys) + len(new_keys) > max_cells:
                truncated = True
                # keep entries whose destination already exists; drop the rest (their light is lost)
                break
            if new_keys.size:
                npos, nnrm = _means(new_keys, fkey[np.isin(fkey, new_keys)], fpos[np.isin(fkey, new_keys)],
                                    fside[np.isin(fkey, new_keys)])
                merged = np.concatenate([reg_keys, new_keys])
                order = np.argsort(merged, kind="stable")
                # remap: positions of old cells change after sorting
                old_to_new = np.empty(len(merged), dtype=np.int64)
                old_to_new[order] = np.arange(len(merged))
                frontier_new = old_to_new[len(reg_keys):]
                ent_src = [old_to_new[s] for s in ent_src]
                reg_pos = np.vstack([reg_pos, npos])[order]
                reg_nrm = np.vstack([reg_nrm, nnrm])[order]
                reg_keys = merged[order]
                frontier = np.sort(frontier_new)
            else:
                frontier = np.zeros(0, dtype=np.int64)
        M = len(reg_keys)
        info["cache_points"] = M
        info["cache_truncated"] = truncated
        # cells seen directly by sensors get the full sky sampling; coarser (deeper / far) cells less
        fine = ((reg_keys >> 36) & 0xF) == 0
        Dc = np.zeros((G, M, p.n), dtype=np.float32)
        if fine.any():
            Dc[:, fine] = self.direct_coefficients(reg_pos[fine], reg_nrm[fine], p, q, rng)
        if (~fine).any():
            q_coarse = Quality(rays=q.rays, bounces=q.bounces, patch_samples=1, ground_samples=max(6, q.ground_samples // 3),
                               cache_cell=q.cache_cell, mf=q.mf, cache_rays=q.cache_rays)
            Dc[:, ~fine] = self.direct_coefficients(reg_pos[~fine], reg_nrm[~fine], p, q_coarse, rng)
        E = Dc.copy()
        if ent_src:
            src = np.concatenate(ent_src)
            dkey = np.concatenate(ent_dst_key)
            w = np.concatenate(ent_w)
            c = np.concatenate(ent_eg)
            j = np.searchsorted(reg_keys, dkey)
            ok = (j < M) & (reg_keys[np.minimum(j, M - 1)] == dkey)
            src, dst, w, c = src[ok], j[ok], w[ok], c[ok]
            info["transport_entries"] = int(len(src))
            for _ in range(q.bounces - 1):
                E_new = Dc.copy()
                for cg in np.unique(c):
                    sel = c == cg
                    for a_src in range(G):
                        if not E[a_src].any():
                            continue
                        a_dst = a_src if (cg == 0 or a_src > 0) else int(cg)
                        _accumulate(E_new[a_dst], src[sel], dst[sel], w[sel], E[a_src])
                E = E_new
        cell = np.searchsorted(reg_keys, eye_key)
        for cg in np.unique(eye_eg):
            sel = eye_eg == cg
            for a_src in range(G):
                if not E[a_src].any():
                    continue
                a_dst = a_src if (cg == 0 or a_src > 0) else int(cg)
                _accumulate(I[a_dst], eye_s[sel], cell[sel], eye_w[sel], E[a_src])
        return I, info

    def _indirect_paths(self, points: np.ndarray, normals: np.ndarray, p: skymod.Patches, q: Quality,
                        rng: np.random.Generator) -> tuple[np.ndarray, dict]:
        """Reference estimator (unbiased, noisier): full random-walk paths with next-event estimation
        against the cached direct coefficients at every vertex. Kept to cross-check the cache solve."""
        N = len(points)
        G = self.n_groups
        R = q.rays
        u1, u2 = stratified_uniforms(N, R, rng)
        sid = np.repeat(np.arange(N), R)
        nn = np.repeat(normals, R, axis=0)
        D = cosine_directions(nn, u1, u2)
        O = np.repeat(points, R, axis=0) + nn * EPS
        T = np.full(N * R, 1.0 / R)
        eg = np.zeros(N * R, dtype=np.int64)
        vertices = 0
        rec = {"sid": [], "pos": [], "tri": [], "side": [], "w": [], "eg": []}
        depth = np.zeros(N * R, dtype=np.int64)
        alive = np.arange(N * R)
        steps = 0
        while alive.size and steps < q.bounces * 2 + 6:
            steps += 1
            t, tri = self.bvh.intersect(O[alive], D[alive])
            hit = tri >= 0
            alive, t, tri = alive[hit], t[hit], tri[hit]
            if not alive.size:
                break
            d = D[alive]
            pos = O[alive] + d * t[:, None]
            n_t = self.normal[tri]
            cosd = np.einsum("ij,ij->i", n_t, d)
            glass = self.glazing[tri]
            shade = glass & self.closed[tri]
            clear = glass & ~shade
            # clear glazing: pass straight through
            if clear.any():
                ci = alive[clear]
                T[ci] *= self.glass_T(tri[clear], np.abs(cosd[clear]))
                eg[ci] = self.group[tri[clear]]
                O[ci] = pos[clear] + d[clear] * EPS
            # scattering vertices: opaque (reflect) or closed shade (diffuse transmission)
            scat = ~clear
            if scat.any():
                si = alive[scat]
                tri_s = tri[scat]
                towards = np.where(cosd[scat][:, None] < 0, n_t[scat], -n_t[scat])   # faces the eye ray
                is_shade = shade[scat]
                out_n = np.where(is_shade[:, None], -towards, towards)                 # side light arrives from
                factor = np.where(is_shade, self.tau_shade[tri_s], self.rho[tri_s])
                T[si] *= factor
                eg[si] = np.where(is_shade, self.group[tri_s], eg[si])
                live = T[si] > 1e-7
                rec["sid"].append(sid[si[live]])
                rec["pos"].append(pos[scat][live])
                rec["tri"].append(tri_s[live])
                rec["side"].append(out_n[live])
                rec["w"].append(T[si[live]])
                rec["eg"].append(eg[si[live]])
                vertices += int(live.sum())
                depth[si] += 1
                more = live & (depth[si] < q.bounces)
                nd = cosine_directions(out_n, rng.random(len(si)), rng.random(len(si)))
                D[si] = nd
                O[si] = pos[scat] + out_n * EPS
                dead = si[~more]
                T[dead] = 0.0
            alive = alive[T[alive] > 1e-7]
        I = np.zeros((G, N, p.n), dtype=np.float32)
        info = {"paths": N * R, "vertices": vertices, "cache_points": 0}
        if not vertices:
            return I, info
        v_sid = np.concatenate(rec["sid"])
        v_pos = np.vstack(rec["pos"])
        v_tri = np.concatenate(rec["tri"])
        v_side = np.vstack(rec["side"])
        v_w = np.concatenate(rec["w"])
        v_eg = np.concatenate(rec["eg"])
        plane, pn, t1, t2 = self._plane_ids()
        pid = plane[v_tri]
        side = np.where(np.einsum("ij,ij->i", v_side, pn[pid]) >= 0, 1, -1)
        ix = np.floor(np.einsum("ij,ij->i", v_pos, t1[pid]) / q.cache_cell).astype(np.int64)
        iy = np.floor(np.einsum("ij,ij->i", v_pos, t2[pid]) / q.cache_cell).astype(np.int64)
        keys = np.stack([pid, side, ix, iy], axis=1)
        _, m = np.unique(keys, axis=0, return_inverse=True)
        m = m.reshape(-1)
        M = int(m.max()) + 1
        cnt = np.bincount(m, minlength=M).astype(float)
        cpos = np.stack([np.bincount(m, weights=v_pos[:, k], minlength=M) for k in range(3)], axis=1) / cnt[:, None]
        cnrm = np.stack([np.bincount(m, weights=v_side[:, k], minlength=M) for k in range(3)], axis=1)
        cnrm /= np.maximum(np.linalg.norm(cnrm, axis=1, keepdims=True), 1e-12)
        info["cache_points"] = M
        Dc = self.direct_coefficients(cpos, cnrm, p, q, rng)              # (G, M, P)
        # aggregate path weights per (eye group, sensor, cache point)
        key = (v_eg * N + v_sid) * M + m
        uk, inv = np.unique(key, return_inverse=True)
        wsum = np.bincount(inv.reshape(-1), weights=v_w)
        k_eg = uk // (N * M)
        k_s = (uk // M) % N
        k_m = uk % M
        for g in np.unique(k_eg):
            sel = k_eg == g
            s_g, m_g, w_g = k_s[sel], k_m[sel], wsum[sel]
            for h in range(G):
                if not Dc[h].any():
                    continue
                attr = h if h > 0 else int(g)
                _accumulate(I[attr], s_g, m_g, w_g, Dc[h])
        return I, info


def _accumulate(target: np.ndarray, s: np.ndarray, m: np.ndarray, w: np.ndarray, Dh: np.ndarray, chunk: int = 100_000) -> None:
    """target[s] += w * Dh[m], summed per sensor (s sorted internally)."""
    order = np.argsort(s, kind="stable")
    s, m, w = s[order], m[order], w[order]
    for a in range(0, len(s), chunk):
        b = min(len(s), a + chunk)
        ss = s[a:b]
        contrib = Dh[m[a:b]] * w[a:b, None].astype(np.float32)
        starts = np.concatenate([[0], np.flatnonzero(np.diff(ss)) + 1])
        target[ss[starts]] += np.add.reduceat(contrib, starts, axis=0)


# ── aperture groups ──────────────────────────────────────────────────────────

SECTORS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def outward_side(bvh, glass: np.ndarray, probes: tuple[np.ndarray, np.ndarray], n: np.ndarray, seed: int = 0,
                 rays: int = 96) -> float:
    """+1 if the side of a surface that ``n`` points to is the outside, -1 if it is the other side.

    The outside is the side from which more rays escape straight to the sky (glass counts as a hit:
    a room seen through a window is still a room). On a dense street the outside is mostly blocked
    by the ground and the buildings opposite, but its upper hemisphere still escapes, while inside the
    ceiling catches everything. When neither side sees any sky (an interior glass partition), the
    side with fewer opaque hits wins."""
    rng = np.random.default_rng(seed)
    esc, opaque = [], []
    for sgn, p in zip((1.0, -1.0), probes):
        nn = np.repeat((sgn * n)[None], rays, axis=0)
        u1, u2 = stratified_uniforms(1, rays, rng)
        dirs = cosine_directions(nn, u1, u2)
        _, tri = bvh.intersect(np.repeat(np.asarray(p, dtype=float)[None], rays, axis=0), dirs)
        esc.append(float((tri < 0).mean()))
        opaque.append(float(((tri >= 0) & ~glass[np.maximum(tri, 0)]).mean()))
    if max(esc) > 0.02 and abs(esc[0] - esc[1]) > 0.01:
        return 1.0 if esc[0] > esc[1] else -1.0
    return 1.0 if opaque[0] <= opaque[1] else -1.0


def aperture_groups(scene: Scene, mode: str = "orientation") -> tuple[np.ndarray, list[dict]]:
    """Aperture group per triangle of the *cleaned* scene (0 = not glazing) and a description list.
    mode: "orientation" (one group per facade direction, LM-83 practice), "object", "single"."""
    sc = scene.clean()
    kinds = np.array([m.kind for m in sc.materials])
    glass = kinds[sc.tri_material] == "glazing"
    groups = np.zeros(len(sc.triangles), dtype=np.int64)
    if not glass.any():
        return groups, []
    if mode not in ("orientation", "object", "single"):
        raise ValueError("aperture grouping must be orientation, object or single")
    normal, area = sc.normals()
    a, b, c = sc.corners()
    cen = (a + b + c) / 3.0
    # outward side of each glazing object: the side from which more of the sky is visible
    bvh = raytrace.BVH(a, b, c)
    labels: dict[str, int] = {}
    desc: list[dict] = []
    for obj in np.unique(sc.tri_object[glass]):
        sel = np.flatnonzero(glass & (sc.tri_object == obj))
        n_avg = principal_normal(normal[sel], area[sel])     # also right for a pane modelled as a thin solid
        # probe from just beyond the pane's own thickness, on each side
        pts = sc.vertices[sc.triangles[sel]].reshape(-1, 3)
        depth = pts @ n_avg
        probe = cen[sel[np.argmax(area[sel])]]
        probe = probe - (probe @ n_avg) * n_avg
        probes = (probe + (depth.max() + 5 * EPS) * n_avg, probe + (depth.min() - 5 * EPS) * n_avg)
        outward = n_avg if outward_side(bvh, glass, probes, n_avg, int(obj)) > 0 else -n_avg
        if mode == "single":
            label = "all glazing"
        elif mode == "object":
            o = sc.objects[int(obj)] if int(obj) < len(sc.objects) else {}
            label = f"{o.get('name') or o.get('guid') or 'window'} #{int(obj)}"
        elif abs(outward[2]) > 0.7:
            label = "skylight" if outward[2] > 0 else "downward"
        else:
            az = (math.degrees(math.atan2(outward[0], outward[1])) + sc.north_deg) % 360.0
            label = SECTORS[int(((az + 22.5) % 360) // 45)]
        if label not in labels:
            labels[label] = len(labels) + 1
            desc.append({"group": labels[label], "label": label, "area_m2": 0.0, "objects": []})
        gi = labels[label]
        groups[sel] = gi
        d = desc[gi - 1]
        d["area_m2"] = round(d["area_m2"] + float(area[sel][pane_faces(normal[sel], area[sel])].sum()), 3)
        o = sc.objects[int(obj)] if int(obj) < len(sc.objects) else {}
        d["objects"].append(o.get("guid") or o.get("name") or int(obj))
    return groups, desc


# ── coefficient sets ─────────────────────────────────────────────────────────

@dataclass
class Coefficients:
    D: np.ndarray                  # (G, N, P) direct sky
    I: np.ndarray                  # (G, N, P) interreflected
    patches: skymod.Patches
    info: dict = field(default_factory=dict)

    @property
    def total(self) -> np.ndarray:
        return self.D + self.I


def compute_coefficients(tracer: Tracer, grid: SensorGrid, q: Quality, seed: int = 0) -> Coefficients:
    p = skymod.patches(q.mf)
    rng = np.random.default_rng(seed)
    t0 = time.time()
    D = tracer.direct_coefficients(grid.points, grid.normals, p, q, rng)
    I, info = tracer.indirect_coefficients(grid.points, grid.normals, p, q, rng) if q.bounces > 0 else (np.zeros_like(D), {})
    info["seconds"] = round(time.time() - t0, 2)
    return Coefficients(D=D, I=I, patches=p, info=info)


def sun_coefficients(tracer: Tracer, grid: SensorGrid, sun_dirs: np.ndarray, max_rays: int = 2_000_000) -> tuple[np.ndarray, np.ndarray]:
    """(H, N) cos(incidence) x transmittance towards each sun direction, and (H, N) aperture group."""
    H, N = len(sun_dirs), grid.n
    S = np.zeros((H, N), dtype=np.float32)
    Gp = np.zeros((H, N), dtype=np.int16)
    if H == 0:
        return S, Gp
    cos = sun_dirs @ grid.normals.T                         # (H, N)
    hi, si = np.nonzero(cos > 1e-6)
    for a in range(0, len(hi), max_rays):
        b = min(len(hi), a + max_rays)
        h, s = hi[a:b], si[a:b]
        T, g = tracer.transmit(grid.points[s] + grid.normals[s] * EPS, sun_dirs[h])
        S[h, s] = (cos[h, s] * T).astype(np.float32)
        Gp[h, s] = g
    return S, Gp


# ── studies ──────────────────────────────────────────────────────────────────

def daylight_factor(coeff: Coefficients, ground_reflectance: float = 0.2) -> dict[str, np.ndarray]:
    """DF (%) under the CIE overcast sky, split into the direct sky part (sky component, through
    glazing, including externally reflected light from the ground patch) and the interreflected part."""
    p = coeff.patches
    sky = skymod.single_sky(p, 1.0, 1.0, ground_reflectance, "cie_overcast")
    direct = coeff.D.sum(axis=0) @ sky * 100.0
    inter = coeff.I.sum(axis=0) @ sky * 100.0
    return {"df": direct + inter, "direct": direct, "interreflected": inter}


def point_in_time(coeff: Coefficients, sky_vec: np.ndarray, sun_dir: np.ndarray | None, sun_normal: float,
                  tracer: Tracer | None = None, grid: SensorGrid | None = None) -> np.ndarray:
    """Illuminance (lux) for one sky (all shades open)."""
    E = coeff.total.sum(axis=0) @ sky_vec
    if sun_dir is not None and sun_normal > 0 and tracer is not None and grid is not None:
        sunsky = np.zeros(coeff.patches.n)
        idx = int(coeff.patches.index(sun_dir[None])[0])
        sunsky[idx] = sun_normal / coeff.patches.solid_angle[idx]
        E = E + coeff.I.sum(axis=0) @ sunsky
        S, _ = sun_coefficients(tracer, grid, sun_dir[None])
        E = E + S[0] * sun_normal
    return E


@dataclass
class Annual:
    illuminance: np.ndarray        # (N, H) lux, with dynamic shading
    direct_sun: np.ndarray         # (N, H) lux, direct sunlight only, shades open (for ASE)
    hours: np.ndarray              # (H,) hour-of-year indices
    shade_closed: np.ndarray       # (G, H) bool
    groups: list[dict]


def annual_illuminance(open_c: Coefficients, closed_c: dict[int, Coefficients], sm: skymod.SkyMatrix,
                       sun_S: np.ndarray, sun_G: np.ndarray, groups: list[dict], dynamic_shading: bool = True,
                       sun_threshold: float = 1000.0, sensor_fraction: float = 0.02, chunk: int = 512,
                       closed_override: np.ndarray | None = None) -> Annual:
    """Hourly illuminance for the hours in ``sm`` (rows of sun_S/sun_G must match sm.hours).
    ``closed_override`` (G, H) imposes the shade schedule (e.g. one decided by the floor grid, for
    glare views) instead of deciding it from these sensors."""
    G = open_c.D.shape[0]
    N = open_c.D.shape[1]
    H = len(sm.hours)
    E = np.zeros((N, H), dtype=np.float32)
    E_sun = np.zeros((N, H), dtype=np.float32)
    closed = np.zeros((G, H), dtype=bool)
    sun_sky = sm.sun_patch_sky()
    tot_o = open_c.total
    for a in range(0, H, chunk):
        b = min(H, a + chunk)
        skyc = sm.sky[a:b].T.astype(np.float32)                  # (P, h)
        sunc = sun_sky[a:b].T.astype(np.float32)
        edn = sm.sun_normal[a:b].astype(np.float32)
        Sdir = sun_S[a:b] * edn[:, None]                         # (h, N) lux direct sun, all groups
        E_sun[:, a:b] = Sdir.T
        for g in range(G):
            e_open = tot_o[g] @ skyc + open_c.I[g] @ sunc         # (N, h)
            sun_g = np.where(sun_G[a:b] == g, Sdir, 0.0).T        # (N, h)
            e_open = e_open + sun_g
            if g > 0 and dynamic_shading and g in closed_c:
                if closed_override is not None:
                    shut = closed_override[g, a:b]
                else:
                    shut = (sun_g > sun_threshold).mean(axis=0) > sensor_fraction
                closed[g, a:b] = shut
                if shut.any():
                    cc = closed_c[g]
                    e_cl = cc.total[g] @ skyc[:, shut] + cc.I[g] @ sunc[:, shut]
                    e_open[:, shut] = e_cl
            E[:, a:b] += e_open
    return Annual(illuminance=E, direct_sun=E_sun, hours=sm.hours, shade_closed=closed, groups=groups)


# ── metrics ──────────────────────────────────────────────────────────────────

def _area_fraction(mask: np.ndarray, area: np.ndarray) -> float:
    return float((area * mask).sum() / area.sum()) if area.sum() > 0 else 0.0


def annual_metrics(E: np.ndarray, E_sun: np.ndarray, area: np.ndarray, da_threshold: float = 300.0,
                   sda_fraction: float = 0.5, ase_threshold: float = 1000.0, ase_hours: int = 250,
                   udi: tuple[float, float, float] = (100.0, 300.0, 3000.0)) -> tuple[dict, dict]:
    """(summary, per-sensor arrays) for occupied-hour illuminance E (N, H)."""
    H = E.shape[1]
    if H == 0:
        raise ValueError("No occupied hours to evaluate")
    da = (E >= da_threshold).mean(axis=1)
    cda = np.minimum(E / da_threshold, 1.0).mean(axis=1)
    lo, mid, hi = udi
    udi_n = (E < lo).mean(axis=1)
    udi_s = ((E >= lo) & (E < mid)).mean(axis=1)
    udi_a = ((E >= mid) & (E <= hi)).mean(axis=1)
    udi_e = (E > hi).mean(axis=1)
    sun_hours = (E_sun > ase_threshold).sum(axis=1)
    per = {"da": da, "cda": cda, "udi_fell_short": udi_n, "udi_supplementary": udi_s, "udi_autonomous": udi_a,
           "udi_exceeded": udi_e, "udi_useful": udi_s + udi_a, "ase_hours": sun_hours.astype(float),
           "mean_lux": E.mean(axis=1)}
    summary = {
        "sda_pct": round(100 * _area_fraction(da >= sda_fraction, area), 1),
        "ase_pct": round(100 * _area_fraction(sun_hours > ase_hours, area), 1),
        "mean_da_pct": round(100 * float(np.average(da, weights=area)), 1),
        "mean_cda_pct": round(100 * float(np.average(cda, weights=area)), 1),
        "udi_pct": {"fell_short_below_%g" % lo: round(100 * float(np.average(udi_n, weights=area)), 1),
                    "supplementary_%g_%g" % (lo, mid): round(100 * float(np.average(udi_s, weights=area)), 1),
                    "autonomous_%g_%g" % (mid, hi): round(100 * float(np.average(udi_a, weights=area)), 1),
                    "exceeded_above_%g" % hi: round(100 * float(np.average(udi_e, weights=area)), 1),
                    "useful_%g_%g" % (lo, hi): round(100 * float(np.average(udi_s + udi_a, weights=area)), 1)},
        "mean_illuminance_lux": round(float(np.average(E.mean(axis=1), weights=area)), 1),
        "occupied_hours": int(H),
        "definitions": {
            "sda": f"share of floor area with >= {da_threshold:g} lux for >= {sda_fraction:.0%} of occupied hours (IES LM-83 sDA{da_threshold:g}/{sda_fraction:.0%})",
            "ase": f"share of floor area with > {ase_threshold:g} lux of direct sunlight for more than {ase_hours} occupied hours, shades open (LM-83 ASE{ase_threshold:g},{ase_hours}h)",
            "udi": "useful daylight illuminance bins (Nabil & Mardaljevic 2005), share of occupied hours",
        },
    }
    return summary, per


def en17037_provision(E_daylight_hours: np.ndarray, area: np.ndarray) -> dict:
    """EN 17037:2018 daylight provision (illuminance method) over the daylight hours of a year:
    a level is met when the target illuminance is reached on 50 % of the reference plane and the
    minimum target on 95 % of it, each for at least 50 % of daylight hours."""
    levels = {"minimum": (300.0, 100.0), "medium": (500.0, 300.0), "high": (750.0, 500.0)}
    out = {}
    met_level = "not met"
    for name, (target, minimum) in levels.items():
        f_t = (E_daylight_hours >= target).mean(axis=1)
        f_m = (E_daylight_hours >= minimum).mean(axis=1)
        a_t = _area_fraction(f_t >= 0.5, area)
        a_m = _area_fraction(f_m >= 0.5, area)
        ok = a_t >= 0.5 and a_m >= 0.95
        out[name] = {"target_lux": target, "minimum_target_lux": minimum, "area_meeting_target_pct": round(100 * a_t, 1),
                     "area_meeting_minimum_pct": round(100 * a_m, 1), "met": ok}
        if ok:
            met_level = name
    out["level"] = met_level
    out["daylight_hours"] = int(E_daylight_hours.shape[1])
    return out


def dgp_simplified(Ev: np.ndarray) -> np.ndarray:
    """Simplified daylight glare probability from vertical eye illuminance (Wienold 2009):
    DGPs = 6.22e-5 Ev + 0.184. Valid without direct sun or specular reflections in view; it
    underestimates glare from small bright sources. Clipped to [0, 1]: it is a probability."""
    return np.clip(6.22e-5 * np.asarray(Ev, dtype=float) + 0.184, 0.0, 1.0)


def glare_summary(dgp: np.ndarray) -> dict:
    classes = {"imperceptible_lt_0.35": (0.0, 0.35), "perceptible_0.35_0.40": (0.35, 0.40),
               "disturbing_0.40_0.45": (0.40, 0.45), "intolerable_ge_0.45": (0.45, np.inf)}
    dgp = np.asarray(dgp, dtype=float)
    if dgp.size == 0:
        return {k: None for k in classes}
    return {k: round(100 * float(((dgp >= lo) & (dgp < hi)).mean()), 1) for k, (lo, hi) in classes.items()}
