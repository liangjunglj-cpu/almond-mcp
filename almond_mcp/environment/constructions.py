"""Building constructions: layered assemblies and their thermal and optical properties.

An assembly is a list of layers from outside to inside (materials from ``data/materials.json``), or a
window (glazing panes, gas gaps and a frame). Everything here is computed from the layers by published
methods, implemented from their procedures - no standard's tables are copied:

* U-value of a plane element: layer resistances in series with the surface resistances for the
  direction of heat flow (the EN ISO 6946 procedure; R_si 0.13 / 0.10 / 0.17 m2K/W for horizontal /
  upward / downward flow, R_se 0.04). Unventilated air layers: R = 1 / (h_a + h_r) with convection
  h_a by flow direction and radiation h_r = 4 sigma T^3 / (1/e1 + 1/e2 - 1).
* Areal heat capacity kappa (J/m2K) seen from each side: the EN ISO 13786 periodic method - the product
  of the layers' heat transfer matrices with the surface resistances, kappa = T / 2 pi |(Z11 - 1) / Z12|
  for a 24 h period. It sets the zone thermal mass C_m and A_m (ISO 13790 12.3.1.2).
* Glazing, centre of glass: gas gaps by convection (Nusselt number of a vertical cavity) plus long-wave
  radiation between the facing emissivities, panes by conduction, h_e = 25 and h_i = 3.6 + 4.4 e/0.837
  W/m2K (the EN 673 procedure). Solar and visible transmittance and reflectance of the pane stack by the
  net-radiation (multiple reflection) method; g = tau_e + the inward-flowing share of the heat each pane
  absorbs, split by the resistance network (the EN 410 procedure).
* Window: U_w = (A_g U_g + A_f U_f + l_g psi_g) / A_w (the EN ISO 10077-1 procedure), with the frame
  fraction and a glazing-edge length per unit window area.

Material properties come from openly licensed sources recorded per value (``data/sources.json``);
frame U-values, edge psi-values and surface finishes that no open dataset provides are marked as
Almond's own engineering assumptions. Ground floors report the element U-value; coupling to the ground
is the thermal model's job (EPW ground temperature).
"""
from __future__ import annotations

import copy
import json
import math

import numpy as np
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).with_name("data")
SIGMA = 5.670374419e-8
T_MEAN = 283.15                                  # K, mean temperature for radiative coefficients
R_SI = {"horizontal": 0.13, "up": 0.10, "down": 0.17}
R_SE = 0.04
H_E_GLAZING = 25.0
INSULATION_LAMBDA = 0.08                         # W/mK: reported as insulation layers

KINDS = ("wall_external", "wall_internal", "roof", "floor_ground", "floor_exposed", "floor_internal",
         "ceiling_internal", "window", "door")
# heat-flow direction for the U-value (EN ISO 6946 convention: heating case for roofs and floors)
FLOW = {"wall_external": "horizontal", "wall_internal": "horizontal", "door": "horizontal",
        "roof": "up", "ceiling_internal": "up", "floor_ground": "down", "floor_exposed": "down",
        "floor_internal": "down"}
INTERNAL = {"wall_internal", "floor_internal", "ceiling_internal"}

# Physical properties of fill gases at 10 degC (standard reference data): conductivity W/mK,
# dynamic viscosity kg/ms, density kg/m3, specific heat J/kgK.
GASES = {
    "air": (0.02496, 1.761e-5, 1.232, 1008.0),
    "argon": (0.01684, 2.164e-5, 1.699, 519.0),
    "krypton": (0.00900, 2.400e-5, 3.560, 245.0),
}


@lru_cache(maxsize=None)
def _load(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def materials() -> dict[str, dict]:
    return {m["id"]: m for m in _load("materials.json")["materials"]}


def glass_panes() -> dict[str, dict]:
    return {p["id"]: p for p in _load("glazing.json")["panes"]}


def frames() -> dict[str, dict]:
    return {f["id"]: f for f in _load("glazing.json")["frames"]}


def sources() -> dict[str, dict]:
    return {s["id"]: s for s in _load("sources.json")["sources"]}


def library() -> dict[str, dict]:
    return {a["id"]: a for a in _load("assemblies.json")["assemblies"]}


def get(assembly: str | dict) -> dict:
    """An assembly by id, or validate and return one given inline (a custom build-up)."""
    if isinstance(assembly, dict):
        a = copy.deepcopy(assembly)
        a.setdefault("id", "custom")
        a.setdefault("name", "Custom assembly")
        a.setdefault("source", "user")
        validate(a)
        return a
    lib = library()
    if assembly not in lib:
        raise ValueError(f"Unknown construction '{assembly}'. Use list_constructions to see the library.")
    return lib[assembly]


def _number(value, what: str, lo: float, hi: float) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{what} must be a number") from None
    if not math.isfinite(x) or not lo <= x <= hi:
        raise ValueError(f"{what} must be between {lo:g} and {hi:g} (is {value})")
    return x


def validate(a: dict) -> None:
    if not isinstance(a, dict):
        raise ValueError("A construction is an object with kind and layers (or glazing and frame for a window)")
    kind = a.get("kind")
    name = a.get("id") or "custom"
    if kind not in KINDS:
        raise ValueError(f"Construction {name}: kind must be one of {', '.join(KINDS)}")
    if kind == "window":
        g = a.get("glazing") or {}
        if not isinstance(g, dict):
            raise ValueError(f"Window {name}: glazing must be an object with panes and gaps")
        panes = g.get("panes") or []
        gaps = g.get("gaps") or []
        if not isinstance(panes, list) or not isinstance(gaps, list) or not panes or len(gaps) != len(panes) - 1:
            raise ValueError(f"Window {name}: give 1-4 panes and one gap between each pair")
        if len(panes) > 4:
            raise ValueError(f"Window {name}: at most 4 panes")
        known = glass_panes()
        for p in panes:
            if not isinstance(p, str) or p not in known:
                raise ValueError(f"Window {name}: unknown pane '{p}'")
        for gap in gaps:
            if not isinstance(gap, dict) or gap.get("gas") not in GASES:
                raise ValueError(f"Window {name}: each gap is an object with gas air/argon/krypton and width_m")
            _number(gap.get("width_m"), f"Window {name}: gap width_m", 0.004, 0.03)
        fr = a.get("frame") or {}
        if not isinstance(fr, dict):
            raise ValueError(f"Window {name}: frame must be an object with a library id or u_f")
        if fr.get("id") not in frames() and "u_f" not in fr:
            raise ValueError(f"Window {name}: frame needs a library id or u_f")
        if "u_f" in fr:
            _number(fr["u_f"], f"Window {name}: frame u_f", 0.5, 10.0)
        for key, lo, hi in (("fraction", 0.0, 0.9), ("psi_g", 0.0, 0.2)):
            if key in fr:
                _number(fr[key], f"Window {name}: frame {key}", lo, hi)
        return
    layers = a.get("layers") or []
    if not isinstance(layers, list) or not layers:
        raise ValueError(f"Construction {name}: layers must be a list of {{material, thickness_m}}, outside to inside")
    mats = materials()
    for L in layers:
        if not isinstance(L, dict):
            raise ValueError(f"Construction {name}: each layer is an object {{material, thickness_m}}")
        if L.get("material") not in mats:
            raise ValueError(f"Construction {name}: unknown material '{L.get('material')}'")
        mat = mats[L["material"]]
        if mat.get("kind") == "air_layer":
            # EN ISO 6946 unventilated air layers: up to 300 mm
            if "thickness_m" in L:
                _number(L["thickness_m"], f"Construction {name}: air layer thickness_m", 0.005, 0.3)
            continue
        _number(L.get("thickness_m"), f"Construction {name}: layer {L['material']} thickness_m", 0.0005, 2.0)


# ── opaque elements ──────────────────────────────────────────────────────────

def _air_layer_r(width: float, flow: str, e1: float = 0.9, e2: float = 0.9) -> float:
    """Thermal resistance of an unventilated air layer (m2K/W), convection + radiation."""
    if flow == "horizontal":
        h_a = max(1.25, 0.025 / width)
    elif flow == "up":
        h_a = max(1.95, 0.025 / width)
    else:
        h_a = max(0.12 * width ** -0.44, 0.025 / width)
    h_r = 4 * SIGMA * T_MEAN ** 3 / (1 / e1 + 1 / e2 - 1)
    return 1.0 / (h_a + h_r)


def _layer_r(layer: dict, mat: dict, flow: str) -> float:
    if mat.get("kind") == "air_layer":
        return _air_layer_r(float(layer.get("thickness_m", 0.05)), flow)
    return float(layer["thickness_m"]) / float(mat["conductivity"])


def _kappa(layers: list[dict], mats: dict, flow: str = "horizontal", r_other: float = R_SE,
           period_h: float = 24.0) -> float:
    """Internal areal heat capacity J/m2K seen from the first layer of ``layers`` (the EN ISO 13786 periodic
    method: product of the layers' heat transfer matrices with the surface resistances, kappa_1 =
    T / 2 pi |(Z11 - 1) / Z12| for a 24 h period)."""
    T = period_h * 3600.0
    def surface(r):
        return np.array([[1.0, -r], [0.0, 1.0]], dtype=complex)
    Z = surface(R_SI[flow])                              # side 1: the surface the room sees
    for L in layers:
        m = mats[L["material"]]
        if m.get("kind") == "air_layer":
            Zl = surface(_air_layer_r(float(L.get("thickness_m", 0.05)), flow))
        else:
            lam, rho, c, d = float(m["conductivity"]), float(m["density"]), float(m["specific_heat"]), float(L["thickness_m"])
            delta = math.sqrt(lam * T / (math.pi * rho * c))
            x = d / delta
            ch, sh, co, si = math.cosh(x), math.sinh(x), math.cos(x), math.sin(x)
            z11 = complex(ch * co, sh * si)
            z12 = -delta / (2 * lam) * complex(sh * co + ch * si, ch * si - sh * co)
            z21 = -lam / delta * complex(sh * co - ch * si, sh * co + ch * si)
            Zl = np.array([[z11, z12], [z21, z11]])
        Z = Zl @ Z
    Z = surface(r_other) @ Z
    return float(T / (2 * math.pi) * abs((Z[0, 0] - 1.0) / Z[0, 1]))


def opaque_properties(a: dict) -> dict:
    mats = materials()
    flow = FLOW[a["kind"]]
    layers = a["layers"]
    r_si = R_SI[flow]
    r_se = R_SI[flow] if a["kind"] in INTERNAL else R_SE
    rows, r_layers = [], 0.0
    for L in layers:
        m = mats[L["material"]]
        r = _layer_r(L, m, flow)
        r_layers += r
        rows.append({"material": m["id"], "name": m["name"], "thickness_mm": round(float(L.get("thickness_m", 0)) * 1000, 1),
                     "conductivity": m.get("conductivity"), "density": m.get("density"),
                     "specific_heat": m.get("specific_heat"), "r_m2k_w": round(r, 4),
                     "insulation": m.get("kind") != "air_layer" and float(m.get("conductivity") or 1) <= INSULATION_LAMBDA,
                     "source": m.get("source")})
    r_total = r_si + r_layers + r_se
    inside, outside = mats[layers[-1]["material"]], mats[layers[0]["material"]]
    mass = sum(float(mats[L["material"]].get("density") or 0) * float(L.get("thickness_m", 0))
               for L in layers if mats[L["material"]].get("kind") != "air_layer")
    return {
        "u_value": round(1.0 / r_total, 3),
        "r_total": round(r_total, 3),
        "r_si": r_si, "r_se": r_se, "heat_flow": flow,
        "thickness_mm": round(sum(float(L.get("thickness_m", 0)) for L in layers) * 1000, 1),
        "mass_kg_m2": round(mass, 1),
        "kappa_inside_kj_m2k": round(_kappa(list(reversed(layers)), mats, flow, r_se) / 1000, 1),
        "kappa_outside_kj_m2k": round(_kappa(layers, mats, flow, r_si) / 1000, 1),
        "inside_reflectance": inside.get("reflectance_visible"),
        "outside_reflectance": outside.get("reflectance_visible"),
        "outside_solar_absorptance": outside.get("solar_absorptance"),
        "layers": rows,
    }


# ── glazing ──────────────────────────────────────────────────────────────────

def _gap_h(gas: str, width: float, e1: float, e2: float, dt: float = 15.0) -> tuple[float, float]:
    """(convective, radiative) conductance W/m2K of a vertical sealed gas gap."""
    lam, mu, rho, cp = GASES[gas]
    gr = 9.81 * width ** 3 * dt * rho ** 2 / (T_MEAN * mu ** 2)
    pr = mu * cp / lam
    nu = max(1.0, 0.035 * (gr * pr) ** 0.38)
    h_g = nu * lam / width
    h_r = 4 * SIGMA * T_MEAN ** 3 / (1 / e1 + 1 / e2 - 1)
    return h_g, h_r


def _stack(panes: list[dict], prefix: str) -> tuple[float, float, list[float]]:
    """Net-radiation method: (transmittance, front reflectance, absorptance per pane) for light
    arriving from outside. ``prefix`` is "solar" or "visible"."""
    t = [p[f"{prefix}_transmittance"] for p in panes]
    rf = [p[f"{prefix}_reflectance_front"] for p in panes]
    rb = [p[f"{prefix}_reflectance_back"] for p in panes]
    n = len(panes)
    # forward recursion: combined T and R of panes 0..k seen from outside, and back reflectance of 0..k
    T, R, Rb = t[0], rf[0], rb[0]
    for k in range(1, n):
        denom = 1 - Rb * rf[k]
        T_new = T * t[k] / denom
        R_new = R + T * T * rf[k] / denom
        Rb = rb[k] + t[k] * t[k] * Rb / denom
        T, R = T_new, R_new
    # flux balance: incident 1 from outside; forward flux f_k arriving at pane k, backward b_k leaving it
    absorb = []
    # solve with the standard approach: build reflectance of the stack behind each pane
    behind = [0.0] * (n + 1)              # reflectance of panes k..n-1 seen from the front
    for k in range(n - 1, -1, -1):
        r_rest = behind[k + 1]
        behind[k] = rf[k] + t[k] * t[k] * r_rest / (1 - rb[k] * r_rest)
    f = 1.0                                # flux arriving at pane 0 from outside
    for k in range(n):
        r_rest = behind[k + 1]
        # inside pane k: forward f hits it; light reflected back from the rest returns as b
        through = f * t[k] / (1 - rb[k] * r_rest)          # forward flux leaving pane k
        back = through * r_rest                             # flux coming back onto pane k from behind
        a_k = 1 - t[k] - rf[k]
        a_kb = 1 - t[k] - rb[k]
        absorb.append(f * a_k + back * a_kb)
        f = through
    return T, R, absorb


def _thicknesses(panes: list[dict]) -> list[float]:
    return [p["thickness_m"] for p in panes]


def glazing_properties(a: dict) -> dict:
    pl = glass_panes()
    panes = [pl[p] for p in a["glazing"]["panes"]]
    gaps = a["glazing"]["gaps"]
    eps_in = panes[-1]["emissivity_back"]
    h_i = 3.6 + 4.4 * eps_in / 0.837
    resistances = [1 / H_E_GLAZING]                    # outside film, then per pane and per gap
    for i, p in enumerate(panes):
        resistances.append(p["thickness_m"] / p["conductivity"])
        if i < len(gaps):
            g = gaps[i]
            h_g, h_r = _gap_h(g["gas"], float(g["width_m"]), p["emissivity_back"], panes[i + 1]["emissivity_front"])
            resistances.append(1 / (h_g + h_r))
    resistances.append(1 / h_i)
    r_total = sum(resistances)
    u_g = 1 / r_total
    tau_e, rho_e, absorb = _stack(panes, "solar")
    tau_v, rho_v, _ = _stack(panes, "visible")
    # inside visible reflectance: reverse the stack
    rev = [{**p, "visible_reflectance_front": p["visible_reflectance_back"],
            "visible_reflectance_back": p["visible_reflectance_front"]} for p in reversed(panes)]
    _, rho_v_in, _ = _stack(rev, "visible")
    # secondary heat: a pane's absorbed heat flows inward in proportion to the resistance on its outside
    q_in, r_out = 0.0, resistances[0]
    for i in range(len(panes)):
        pane_mid = r_out + resistances[1 + 2 * i] / 2
        q_in += absorb[i] * pane_mid / r_total
        r_out += resistances[1 + 2 * i] + (resistances[2 + 2 * i] if i < len(gaps) else 0.0)
    return {"u_g": round(u_g, 3), "g_value": round(tau_e + q_in, 3), "tau_e": round(tau_e, 3),
            "tau_v": round(tau_v, 3), "rho_v_out": round(rho_v, 3), "rho_v_in": round(rho_v_in, 3),
            "pane_absorptance": [round(x, 3) for x in absorb], "h_i": round(h_i, 2)}


def window_properties(a: dict) -> dict:
    gl = glazing_properties(a)
    fr = dict(frames().get(a["frame"].get("id"), {}))
    fr.update({k: v for k, v in a["frame"].items() if k != "id"})
    f = float(fr.get("fraction", 0.25))
    u_f = float(fr["u_f"])
    psi = float(fr.get("psi_g", 0.05))
    edge = float(fr.get("edge_m_per_m2", 2.5))          # glazing perimeter per m2 of window
    u_w = (1 - f) * gl["u_g"] + f * u_f + edge * psi
    panes = glass_panes()
    return {**gl, "u_value": round(u_w, 3), "u_f": u_f, "frame_fraction": f, "psi_g": psi,
            "edge_m_per_m2": edge, "frame": fr.get("name", fr.get("id", "frame")),
            "frame_source": fr.get("source"),
            "panes": [{"id": p, "name": panes[p]["name"], "source": panes[p]["source"]} for p in a["glazing"]["panes"]],
            "gaps": a["glazing"]["gaps"],
            "thickness_mm": round((sum(panes[p]["thickness_m"] for p in a["glazing"]["panes"]) +
                                   sum(float(g["width_m"]) for g in a["glazing"]["gaps"])) * 1000, 1)}


def properties(assembly: str | dict) -> dict:
    a = get(assembly)
    props = window_properties(a) if a["kind"] == "window" else opaque_properties(a)
    return {"id": a["id"], "name": a["name"], "kind": a["kind"], "regions": a.get("regions", []),
            "description": a.get("description", ""), "source": a.get("source", "almond-own"), **props}


def summary(assembly: str | dict) -> dict:
    """The few numbers the analyses need: U, g, tau_v, reflectances, kappa."""
    p = properties(assembly)
    out = {"id": p["id"], "name": p["name"], "kind": p["kind"], "u_value": p["u_value"]}
    if p["kind"] == "window":
        out.update(g_value=p["g_value"], tau_v=p["tau_v"], frame_fraction=p["frame_fraction"], rho_v_in=p["rho_v_in"])
    else:
        out.update(kappa_inside_kj_m2k=p["kappa_inside_kj_m2k"], kappa_outside_kj_m2k=p["kappa_outside_kj_m2k"],
                   inside_reflectance=p["inside_reflectance"], outside_reflectance=p["outside_reflectance"],
                   outside_solar_absorptance=p["outside_solar_absorptance"])
    return out


def catalogue(kind: str = "", region: str = "") -> list[dict]:
    out = []
    for a in library().values():
        if kind and a["kind"] != kind:
            continue
        if region and region not in a.get("regions", []) and "any" not in a.get("regions", []):
            continue
        out.append(summary(a["id"]) | {"regions": a.get("regions", []), "description": a.get("description", "")})
    return out
