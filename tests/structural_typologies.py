"""Compatibility shim: the typology builders live in ``almond_mcp.structural_references`` (the structural
reference library). The closed-form tests and the OpenSees benchmarks import them from here."""
from almond_mcp.structural_references import *  # noqa: F401,F403
from almond_mcp.structural_references import (  # noqa: F401
    ALL, Grid, S355, arch, braced_tower, canopy, diagrid, in_plane, l_bracket, mixed_supports, moment_frame,
    portal_2d, pratt_truss, refined, space_grid, vierendeel, warehouse,
)
