"""Optional numba kernels for the ray caster. Imported by raytrace.py only when numba is installed
(``pip install almond-mcp[fast]``) and ALMOND_NO_NUMBA is not set; the numpy path gives identical
results, only slower."""
from __future__ import annotations

import numpy as np
from numba import njit, prange


@njit(cache=True, parallel=True, fastmath=False)
def intersect(o, d, t_max, bmin, bmax, left, right, axis, start, count, v0, e1, e2, t_min, out_t, out_tri):
    n = o.shape[0]
    for i in prange(n):
        stack = np.empty(128, np.int64)
        sp = 1
        stack[0] = 0
        best = t_max[i]
        best_tri = -1
        ox, oy, oz = o[i, 0], o[i, 1], o[i, 2]
        dx, dy, dz = d[i, 0], d[i, 1], d[i, 2]
        ix = 1.0 / dx if abs(dx) > 1e-300 else 1e300
        iy = 1.0 / dy if abs(dy) > 1e-300 else 1e300
        iz = 1.0 / dz if abs(dz) > 1e-300 else 1e300
        while sp > 0:
            sp -= 1
            node = stack[sp]
            tx1 = (bmin[node, 0] - ox) * ix
            tx2 = (bmax[node, 0] - ox) * ix
            tn = min(tx1, tx2)
            tf = max(tx1, tx2)
            ty1 = (bmin[node, 1] - oy) * iy
            ty2 = (bmax[node, 1] - oy) * iy
            tn = max(tn, min(ty1, ty2))
            tf = min(tf, max(ty1, ty2))
            tz1 = (bmin[node, 2] - oz) * iz
            tz2 = (bmax[node, 2] - oz) * iz
            tn = max(tn, min(tz1, tz2))
            tf = min(tf, max(tz1, tz2))
            if tf < max(tn, 0.0) or tn > best:
                continue
            c = count[node]
            if c > 0:
                s = start[node]
                for k in range(s, s + c):
                    ax, ay, az = e1[k, 0], e1[k, 1], e1[k, 2]
                    bx, by, bz = e2[k, 0], e2[k, 1], e2[k, 2]
                    px = dy * bz - dz * by
                    py = dz * bx - dx * bz
                    pz = dx * by - dy * bx
                    det = ax * px + ay * py + az * pz
                    if abs(det) <= 1e-14:
                        continue
                    inv_det = 1.0 / det
                    tvx, tvy, tvz = ox - v0[k, 0], oy - v0[k, 1], oz - v0[k, 2]
                    u = (tvx * px + tvy * py + tvz * pz) * inv_det
                    if u < -1e-12 or u > 1.0 + 1e-12:
                        continue
                    qx = tvy * az - tvz * ay
                    qy = tvz * ax - tvx * az
                    qz = tvx * ay - tvy * ax
                    v = (dx * qx + dy * qy + dz * qz) * inv_det
                    if v < -1e-12 or u + v > 1.0 + 1e-12:
                        continue
                    t = (bx * qx + by * qy + bz * qz) * inv_det
                    if t > t_min and t < best:
                        best = t
                        best_tri = k
            else:
                a = axis[node]
                if d[i, a] < 0:
                    near, far = right[node], left[node]
                else:
                    near, far = left[node], right[node]
                if sp + 2 > 128:
                    continue          # cannot happen for depth < 126; never write out of bounds
                stack[sp] = far
                stack[sp + 1] = near
                sp += 2
        out_t[i] = best if best_tri >= 0 else np.inf
        out_tri[i] = best_tri
