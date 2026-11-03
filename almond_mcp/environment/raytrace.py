"""Vectorised ray casting against a triangle scene (numpy only).

A binary bounding-volume hierarchy (median split on the longest centroid axis, at most ``LEAF_SIZE``
triangles per leaf) is traversed depth-first by every ray of a batch in lock step: each ray keeps its
own small stack, pops one node per iteration, and pushes the children front to back, so the closest
hit found so far prunes the rest of its traversal (memory stays proportional to the batch, whatever
the scene). Leaves are resolved with the Moller-Trumbore test. Triangles are two-sided.

This is not Embree, but a building-scale model (thousands of triangles) handles about a million rays
in seconds, with no compiled dependency.
"""
from __future__ import annotations

import os

import numpy as np

LEAF_SIZE = 4
STACK_DEPTH = 64
T_MIN = 1e-6

_kernels = None
_kernel_error = ""
if not os.environ.get("ALMOND_NO_NUMBA"):
    if "NUMBA_CACHE_DIR" not in os.environ:
        # numba caches next to the module by default; inside a uv/pip environment that path can pass
        # Windows' 260-character limit and crash the save. Keep the cache in the short user data dir.
        try:
            from .. import paths
            cache = paths.user_data_dir() / "numba-cache"
            cache.mkdir(parents=True, exist_ok=True)
            os.environ["NUMBA_CACHE_DIR"] = str(cache)
        except Exception:
            pass
    try:                                   # optional accelerator: pip install almond-mcp[fast]
        from . import _kernels
    except Exception as exc:               # numba missing or broken: the numpy path is complete
        _kernels = None
        _kernel_error = type(exc).__name__


def backend() -> str:
    return "numba" if _kernels is not None else "numpy"


class BVH:
    def __init__(self, v0: np.ndarray, v1: np.ndarray, v2: np.ndarray):
        v0 = np.asarray(v0, dtype=np.float64).reshape(-1, 3)
        v1 = np.asarray(v1, dtype=np.float64).reshape(-1, 3)
        v2 = np.asarray(v2, dtype=np.float64).reshape(-1, 3)
        self.n_tri = len(v0)
        self._empty = self.n_tri == 0
        if self._empty:
            self.order = np.zeros(0, dtype=np.int64)
            return
        tmin = np.minimum(np.minimum(v0, v1), v2)
        tmax = np.maximum(np.maximum(v0, v1), v2)
        cen = (tmin + tmax) * 0.5
        order = np.arange(self.n_tri)
        cap = 2 * self.n_tri + 1
        bmin = np.zeros((cap, 3))
        bmax = np.zeros((cap, 3))
        left = np.full(cap, -1, dtype=np.int64)
        right = np.full(cap, -1, dtype=np.int64)
        axis_of = np.zeros(cap, dtype=np.int64)
        start = np.zeros(cap, dtype=np.int64)
        count = np.zeros(cap, dtype=np.int64)
        n_nodes = 1
        stack = [(0, 0, self.n_tri, 0)]
        max_depth = 0
        while stack:
            node, s, e, depth = stack.pop()
            max_depth = max(max_depth, depth)
            idx = order[s:e]
            bmin[node] = tmin[idx].min(axis=0)
            bmax[node] = tmax[idx].max(axis=0)
            n = e - s
            if n <= LEAF_SIZE:
                start[node], count[node] = s, n
                continue
            c = cen[idx]
            ext = c.max(axis=0) - c.min(axis=0)
            axis = int(np.argmax(ext))
            mid = n // 2
            if ext[axis] > 1e-12:
                part = np.argpartition(c[:, axis], mid)
                order[s:e] = idx[part]
            # (coincident centroids: split by index; the halves overlap but leaves stay small)
            l, r = n_nodes, n_nodes + 1
            n_nodes += 2
            left[node], right[node], axis_of[node] = l, r, axis
            stack.append((l, s, s + mid, depth + 1))
            stack.append((r, s + mid, e, depth + 1))
        self.depth = max_depth
        self.bmin, self.bmax = bmin[:n_nodes], bmax[:n_nodes]
        self.left, self.right, self.axis = left[:n_nodes], right[:n_nodes], axis_of[:n_nodes]
        self.start, self.count = start[:n_nodes], count[:n_nodes]
        self.order = order                                # BVH slot -> original triangle index
        self.v0 = v0[order]
        self.e1 = (v1 - v0)[order]
        self.e2 = (v2 - v0)[order]
        self._stack_depth = max(STACK_DEPTH, max_depth + 4)

    def intersect(self, origins: np.ndarray, dirs: np.ndarray, t_max: np.ndarray | float | None = None,
                  chunk: int = 65536) -> tuple[np.ndarray, np.ndarray]:
        """Closest hit for each ray: (t, triangle index), t = inf and index = -1 for a miss.
        Directions need not be normalised; t is in units of the direction's length."""
        o_all = np.asarray(origins, dtype=np.float64).reshape(-1, 3)
        d_all = np.asarray(dirs, dtype=np.float64).reshape(-1, 3)
        n = len(o_all)
        t_out = np.full(n, np.inf)
        tri_out = np.full(n, -1, dtype=np.int64)
        if n == 0 or self._empty:
            return t_out, tri_out
        if t_max is None:
            tm_all = np.full(n, np.inf)
        else:
            tm_all = np.broadcast_to(np.asarray(t_max, dtype=np.float64), (n,)).copy()
        global _kernels, _kernel_error
        if _kernels is not None and self.depth < 120:
            try:
                slot = np.full(n, -1, dtype=np.int64)
                _kernels.intersect(np.ascontiguousarray(o_all), np.ascontiguousarray(d_all), tm_all,
                                   self.bmin, self.bmax, self.left, self.right, self.axis, self.start, self.count,
                                   self.v0, self.e1, self.e2, T_MIN, t_out, slot)
                hit = slot >= 0
                tri_out[hit] = self.order[slot[hit]]
                return t_out, tri_out
            except Exception as exc:       # compilation or cache failure: fall back for the session
                _kernels, _kernel_error = None, type(exc).__name__
                t_out[:] = np.inf
                tri_out[:] = -1
        for s in range(0, n, chunk):
            e = min(n, s + chunk)
            t_out[s:e], tri_out[s:e] = self._intersect_chunk(o_all[s:e], d_all[s:e], tm_all[s:e])
        return t_out, tri_out

    def _intersect_chunk(self, o: np.ndarray, d: np.ndarray, best_t: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        n = len(o)
        with np.errstate(divide="ignore"):
            inv = 1.0 / np.where(np.abs(d) < 1e-300, 1e-300, d)
        best_t = best_t.copy()
        best_tri = np.full(n, -1, dtype=np.int64)
        stack = np.zeros((n, self._stack_depth), dtype=np.int32)
        sp = np.ones(n, dtype=np.int64)                  # stack[:, 0] = root
        active = np.arange(n)
        k = np.arange(LEAF_SIZE)
        neg = d < 0
        while active.size:
            sp[active] -= 1
            node = stack[active, sp[active]].astype(np.int64)
            ob, ib = o[active], inv[active]
            t1 = (self.bmin[node] - ob) * ib
            t2 = (self.bmax[node] - ob) * ib
            tnear = np.minimum(t1, t2).max(axis=1)
            tfar = np.maximum(t1, t2).min(axis=1)
            hit = (tfar >= np.maximum(tnear, 0.0)) & (tnear <= best_t[active])
            a, nd = active[hit], node[hit]
            cnt = self.count[nd]
            leaf = cnt > 0
            if leaf.any():
                la, ln = a[leaf], nd[leaf]
                slots = self.start[ln][:, None] + k
                valid = k[None, :] < cnt[leaf][:, None]
                rr = np.broadcast_to(la[:, None], slots.shape)[valid]
                tt = slots[valid]
                t = self._moller(o[rr], d[rr], tt)
                ok = (t > T_MIN) & (t < best_t[rr])
                if ok.any():
                    rr, tt, t = rr[ok], tt[ok], t[ok]
                    np.minimum.at(best_t, rr, t)
                    win = t <= best_t[rr]
                    best_tri[rr[win]] = tt[win]
            inner = ~leaf
            if inner.any():
                ia, inn = a[inner], nd[inner]
                # front-to-back: visit the child on the ray's near side of the split first (push it last)
                flip = neg[ia, self.axis[inn]]
                near = np.where(flip, self.right[inn], self.left[inn])
                far = np.where(flip, self.left[inn], self.right[inn])
                if (sp[ia] + 2 > self._stack_depth).any():
                    raise RuntimeError("BVH traversal stack overflow")
                stack[ia, sp[ia]] = far
                sp[ia] += 1
                stack[ia, sp[ia]] = near
                sp[ia] += 1
            active = active[sp[active] > 0]
        hit = best_tri >= 0
        tri = np.full(n, -1, dtype=np.int64)
        tri[hit] = self.order[best_tri[hit]]
        return np.where(hit, best_t, np.inf), tri

    def _moller(self, o: np.ndarray, d: np.ndarray, tt: np.ndarray) -> np.ndarray:
        e1, e2 = self.e1[tt], self.e2[tt]
        px = d[:, 1] * e2[:, 2] - d[:, 2] * e2[:, 1]
        py = d[:, 2] * e2[:, 0] - d[:, 0] * e2[:, 2]
        pz = d[:, 0] * e2[:, 1] - d[:, 1] * e2[:, 0]
        det = e1[:, 0] * px + e1[:, 1] * py + e1[:, 2] * pz
        ok = np.abs(det) > 1e-14
        inv_det = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
        tv = o - self.v0[tt]
        u = (tv[:, 0] * px + tv[:, 1] * py + tv[:, 2] * pz) * inv_det
        qx = tv[:, 1] * e1[:, 2] - tv[:, 2] * e1[:, 1]
        qy = tv[:, 2] * e1[:, 0] - tv[:, 0] * e1[:, 2]
        qz = tv[:, 0] * e1[:, 1] - tv[:, 1] * e1[:, 0]
        v = (d[:, 0] * qx + d[:, 1] * qy + d[:, 2] * qz) * inv_det
        t = (e2[:, 0] * qx + e2[:, 1] * qy + e2[:, 2] * qz) * inv_det
        good = ok & (u >= -1e-12) & (v >= -1e-12) & (u + v <= 1.0 + 1e-12)
        return np.where(good, t, np.inf)
