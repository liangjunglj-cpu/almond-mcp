"""Elastic critical moment M_cr for lateral-torsional buckling (EN 1993-1-1 6.3.2.2(2)), numerically.

A beam segment between lateral restraints is modelled with thin-walled beam elements (Vlasov), four
degrees of freedom per node: lateral displacement v, its slope v', twist phi and its rate phi' (warping).
Cubic Hermite shape functions for v and phi. The second variation of the total potential under the
segment's own moment diagram M(x) and transverse load q(x):

    Pi2 = 1/2 Int [ E Iz v''^2 + G It phi'^2 + E Iw phi''^2 ] dx          (elastic, K_e)
        + lambda Int M v'' phi dx                                       (coupling, K_c)
        - lambda/2 [ Int q z_g phi^2 dx + Sum P z_g phi^2 ]             (load height, Q)

with q, P the transverse loads (positive downward, i.e. against local z) applied z_g above the shear
centre: a load above the shear centre (top flange) is destabilising. The critical load factor is the
smallest positive lambda with K_e + lambda (K_c - Q) singular, and M_cr = lambda * max |M| in the
segment. Written from the textbook energy method (Trahair, Flexural-Torsional Buckling of Structures);
no third-party code is used. The sign of M does not matter (it flips with phi); the sign of the load
height does.

Supports: "fork" (v = phi = 0; lateral bending and warping free, k = kw = 1), "free" (nothing held: a
cantilever tip), and the root of a cantilever (v = v' = phi = 0, warping free). Units: m, kN, kNm."""
from __future__ import annotations

import math

import numpy as np

GAUSS = np.polynomial.legendre.leggauss(4)


def _shapes(xi: float, length: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Cubic Hermite N, dN/dx, d2N/dx2 at xi in [0, 1] for DOFs (w1, w1', w2, w2')."""
    L = length
    N = np.array([1 - 3 * xi ** 2 + 2 * xi ** 3, L * (xi - 2 * xi ** 2 + xi ** 3), 3 * xi ** 2 - 2 * xi ** 3,
                  L * (-xi ** 2 + xi ** 3)])
    d1 = np.array([(-6 * xi + 6 * xi ** 2) / L, 1 - 4 * xi + 3 * xi ** 2, (6 * xi - 6 * xi ** 2) / L, -2 * xi + 3 * xi ** 2])
    d2 = np.array([(-6 + 12 * xi) / L ** 2, (-4 + 6 * xi) / L, (6 - 12 * xi) / L ** 2, (-2 + 6 * xi) / L])
    return N, d1, d2


def critical_moment(E: float, G: float, Iz: float, It: float, Iw: float, pieces: list, points=(),
                    ends=("fork", "fork"), zg: float = 0.0, elements: int = 32) -> dict:
    """M_cr of one segment. ``pieces``: consecutive parts along the segment, each {"s0", "s1" (m from the
    segment start), "s": positions, "M": moments (kNm) at those positions, "q0", "q1": downward
    transverse load (kN/m) at s0 and s1, linear between}. ``points``: [(s, P downward kN)]. ``ends``:
    ("fork" | "free" | "root") at s = 0 and at the far end. ``zg``: load height above the shear centre (m).

    Returns {"m_cr": kNm (inf when the segment cannot buckle laterally under these loads),
    "load_factor": lambda, "m_max": max |M|}."""
    pieces = sorted(pieces, key=lambda p: p["s0"])
    total = pieces[-1]["s1"] - pieces[0]["s0"]
    m_max = max(float(np.max(np.abs(p["M"]))) for p in pieces) if pieces else 0.0
    out = {"m_cr": math.inf, "load_factor": math.inf, "m_max": m_max}
    if total <= 0 or (m_max < 1e-9 and not any(abs(P) > 1e-9 for _, P in points)):
        return out
    # mesh: every piece boundary is a node, each piece split in proportion to its length
    nodes, owner = [pieces[0]["s0"]], []
    for k, p in enumerate(pieces):
        n = max(2, math.ceil(elements * (p["s1"] - p["s0"]) / total))
        for j in range(1, n + 1):
            nodes.append(p["s0"] + (p["s1"] - p["s0"]) * j / n)
            owner.append(k)
    nodes = np.asarray(nodes)
    nn = len(nodes)
    ndof = 4 * nn                                               # per node: v, v', phi, phi'
    Ke, Kc, Q = np.zeros((ndof, ndof)), np.zeros((ndof, ndof)), np.zeros((ndof, ndof))
    xg, wg = GAUSS
    for e, k in enumerate(owner):
        p = pieces[k]
        a, b = nodes[e], nodes[e + 1]
        le = b - a
        iv = np.array([4 * e, 4 * e + 1, 4 * e + 4, 4 * e + 5])
        ip = iv + 2
        kb, kt, kc, kq = (np.zeros((4, 4)) for _ in range(4))
        for x0, w0 in zip(xg, wg):
            xi = (x0 + 1) / 2
            w = w0 * le / 2
            s = a + xi * le
            N, d1, d2 = _shapes(xi, le)
            M = float(np.interp(s, p["s"], p["M"]))
            q = p["q0"] + (p["q1"] - p["q0"]) * (s - p["s0"]) / ((p["s1"] - p["s0"]) or 1.0)
            kb += w * E * Iz * np.outer(d2, d2)
            kt += w * (G * It * np.outer(d1, d1) + E * Iw * np.outer(d2, d2))
            kc += w * M * np.outer(d2, N)                       # rows v'', columns phi
            kq += w * q * zg * np.outer(N, N)
        Ke[np.ix_(iv, iv)] += kb
        Ke[np.ix_(ip, ip)] += kt
        Kc[np.ix_(iv, ip)] += kc
        Kc[np.ix_(ip, iv)] += kc.T
        Q[np.ix_(ip, ip)] += kq
    for s, P in points:                                          # point loads at the load height
        i = int(np.argmin(np.abs(nodes - s)))
        Q[4 * i + 2, 4 * i + 2] += P * zg
    fixed = set()
    for node, kind in ((0, ends[0]), (nn - 1, ends[1])):
        if kind == "fork":
            fixed |= {4 * node, 4 * node + 2}
        elif kind == "root":
            fixed |= {4 * node, 4 * node + 1, 4 * node + 2}
    if not fixed or all(k == "free" for k in ends):
        return out
    free = np.array([i for i in range(ndof) if i not in fixed])
    Kf = Ke[np.ix_(free, free)]
    Gf = (Kc - Q)[np.ix_(free, free)]
    try:
        Li = np.linalg.inv(np.linalg.cholesky(Kf))
    except np.linalg.LinAlgError:
        return out
    A = Li @ (-Gf) @ Li.T                                        # K_e x = -lambda G x  ->  A y = (1/lambda) y
    mu = np.linalg.eigvalsh((A + A.T) / 2)
    top = float(mu.max())
    if top <= 1e-12:
        return out
    lam = 1.0 / top
    out.update({"load_factor": lam, "m_cr": lam * m_max if m_max > 1e-9 else math.inf})
    return out
