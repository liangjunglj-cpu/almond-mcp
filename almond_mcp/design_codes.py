"""Design code profiles: the numbers a design code (or a National Annex) sets, kept out of the solver.

A profile is a JSON file. Every parameter carries its value, the clause it comes from and whether that
value has been checked against the published document:

    {"schema_version": 1, "id": "sg", "name": "Singapore · SS EN + NA", "basis": "...",
     "parameters": {"gamma_G": {"value": 1.35, "source": "NA to SS EN 1990 Table NA.A1.2(B)",
                                "verified": false}, ...}}

Profiles load from the built-in ``almond_mcp/code_profiles`` folder and the user's folder
(``%LOCALAPPDATA%\\Almond\\design-codes``, or ``ALMOND_DESIGN_CODE_DIR``), so a practice can add a
National Annex without touching the solver. Unverified values are allowed but reported with every
result. ``off`` is the built-in "no code" choice: unfactored G + Q, material factors 1.0, an L/250
deflection screen.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from almond_mcp import paths

BUILT_IN = Path(__file__).resolve().parent / "code_profiles"
DEFAULT = "eurocode"
OFF = "off"
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")

# parameter -> (kind, low, high) for numbers; allowed strings otherwise
SCHEMA = {
    "gamma_G": ("number", 1.0, 2.0),
    "gamma_Q": ("number", 1.0, 2.0),
    "psi_0": ("number", 0.0, 1.0),
    "xi": ("number", 0.5, 1.0),
    "uls_expression": ("choice", ("either", "6.10", "6.10ab")),
    "uls_default": ("choice", ("6.10", "6.10ab")),
    "deflection_limit_ratio": ("number", 100.0, 1000.0),
    "gamma_M0": ("number", 1.0, 1.5),
    "gamma_M1": ("number", 1.0, 1.5),
    "imposed_floor_kn_m2": ("table", 0.0, 50.0),
}
REQUIRED = tuple(k for k in SCHEMA if k != "imposed_floor_kn_m2")


@dataclass(frozen=True)
class Profile:
    id: str
    name: str
    basis: str
    values: dict
    sources: dict = field(default_factory=dict)
    unverified: tuple = ()
    origin: str = "built-in"            # "built-in" | "user" | path of the file

    def __getattr__(self, key):
        values = object.__getattribute__(self, "values")
        if key in values:
            return values[key]
        raise AttributeError(key)

    @property
    def factored(self) -> bool:
        return self.id != OFF

    def uls(self, requested: str | None) -> tuple[str, str | None]:
        """The ULS expression to use and a note when the profile overrides the request."""
        fixed = self.values["uls_expression"]
        if fixed in ("6.10", "6.10ab"):
            note = (f"{self.name} prescribes ULS expression {fixed}; the requested {requested} was not used."
                    if requested and requested != fixed else None)
            return fixed, note
        return requested or self.values["uls_default"], None

    def summary(self) -> dict:
        return {"id": self.id, "name": self.name, "basis": self.basis, "origin": self.origin,
                "values": dict(self.values), "unverified": list(self.unverified)}

    def listing(self) -> dict:
        return {"id": self.id, "name": self.name, "basis": self.basis, "origin": self.origin,
                "verified": not self.unverified, "unverified": list(self.unverified),
                "uls_expression": self.values["uls_expression"], "uls_default": self.values["uls_default"],
                "deflection_limit_ratio": self.values["deflection_limit_ratio"],
                "imposed_floor_kn_m2": self.values.get("imposed_floor_kn_m2") or {}}


OFF_PROFILE = Profile(
    id=OFF, name="Off (unfactored mechanics)", basis="No design code: characteristic G + Q, no partial factors",
    values={"gamma_G": 1.0, "gamma_Q": 1.0, "psi_0": 1.0, "xi": 1.0, "uls_expression": "6.10", "uls_default": "6.10",
            "deflection_limit_ratio": 250.0, "gamma_M0": 1.0, "gamma_M1": 1.0, "imposed_floor_kn_m2": {}},
    sources={"deflection_limit_ratio": "Indicative span/250 screen, not a code limit"})


def user_dir() -> Path:
    explicit = os.environ.get("ALMOND_DESIGN_CODE_DIR")
    return Path(explicit) if explicit else paths.user_data_dir() / "design-codes"


def parse(data: dict, origin: str = "built-in") -> Profile:
    """Validate one profile document. Raises ValueError naming the first problem."""
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("schema_version must be 1")
    pid = str(data.get("id", ""))
    if not ID_PATTERN.match(pid) or pid == OFF:
        raise ValueError(f"id {pid!r} must be 1-40 lowercase letters, digits or hyphens (and not 'off')")
    name, basis = str(data.get("name") or "").strip(), str(data.get("basis") or "").strip()
    if not name or not basis:
        raise ValueError("name and basis are required")
    params = data.get("parameters")
    if not isinstance(params, dict):
        raise ValueError("parameters must be an object")
    unknown = sorted(set(params) - set(SCHEMA))
    if unknown:
        raise ValueError(f"unknown parameter(s): {', '.join(unknown)}")
    values, sources, unverified = {}, {}, []
    for key in SCHEMA:
        entry = params.get(key)
        if entry is None:
            if key in REQUIRED:
                raise ValueError(f"missing parameter {key}")
            continue
        if not isinstance(entry, dict) or "value" not in entry:
            raise ValueError(f"{key} must be an object with a value")
        if entry["value"] is None:
            raise ValueError(f"{key} has no value yet")
        values[key] = _check(key, entry["value"])
        sources[key] = str(entry.get("source") or "")
        if not sources[key]:
            raise ValueError(f"{key} needs a source (document and clause)")
        if entry.get("verified") is not True:
            unverified.append(key)
    values.setdefault("imposed_floor_kn_m2", {})
    return Profile(pid, name, basis, values, sources, tuple(unverified), origin)


def _check(key, value):
    kind = SCHEMA[key]
    if kind[0] == "choice":
        if value not in kind[1]:
            raise ValueError(f"{key} must be one of {', '.join(kind[1])}")
        return value
    if kind[0] == "table":
        if not isinstance(value, dict) or not all(
                isinstance(v, (int, float)) and kind[1] <= v <= kind[2] for v in value.values()):
            raise ValueError(f"{key} must map use categories to loads between {kind[1]:g} and {kind[2]:g} kN/m2")
        return {str(k): float(v) for k, v in value.items()}
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not kind[1] <= value <= kind[2]:
        raise ValueError(f"{key} must be a number between {kind[1]:g} and {kind[2]:g}")
    return float(value)


def discover() -> tuple[dict, list]:
    """({id: Profile}, [problems]) from the built-in and user folders. Built-in ids cannot be replaced."""
    found, problems = {}, []
    for folder, origin in ((BUILT_IN, "built-in"), (user_dir(), "user")):
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.json")):
            try:
                profile = parse(json.loads(path.read_text(encoding="utf-8")),
                                origin if origin == "built-in" else str(path))
            except (OSError, ValueError) as e:
                problems.append(f"{path.name}: {e}")
                continue
            if profile.id in found:
                problems.append(f"{path.name}: id {profile.id!r} is already defined by {found[profile.id].origin}")
                continue
            found[profile.id] = profile
    return found, problems


def load(code: str | Profile | None = None) -> Profile:
    """The profile for an id ('eurocode' when empty, 'off' for no code)."""
    if isinstance(code, Profile):
        return code
    pid = (code or DEFAULT).strip().lower()
    if pid == OFF:
        return OFF_PROFILE
    found, problems = discover()
    if pid not in found:
        hint = f" ({'; '.join(p for p in problems if p.startswith(pid))})" if problems else ""
        raise ValueError(f"Unknown design code {pid!r}{hint}. Available: {', '.join(sorted(found) + [OFF])}.")
    return found[pid]


def listing() -> dict:
    found, problems = discover()
    profiles = [found[k].listing() for k in sorted(found, key=lambda k: (k != DEFAULT, k))]
    return {"default": DEFAULT, "profiles": profiles + [OFF_PROFILE.listing()], "problems": problems,
            "user_dir": str(user_dir())}
