"""Rebuild the environment construction library's derived data files from pinned upstream sources.

    python -I tools/build_construction_library.py <download-dir>

<download-dir> must hold the files below, fetched from the pinned versions recorded in SOURCES
(the script never downloads anything itself):

  ASHRAE_2005_HOF_Materials.idf, WindowGlassMaterials.idf   EnergyPlus v26.2.0 datasets/  (BSD-style)
  hotmaps_building_stock.csv                                Hotmaps building-stock @ 9805473 (CC BY 4.0)

Writes almond_mcp/environment/data/{materials,glazing,sources}.json and codes/eu_hotmaps.json.
Hand-authored files - assemblies.json and the other code packs - are not touched. Only the values
listed in CURATED are taken over; visible reflectance and solar absorptance of finishes are Almond's
own engineering assumptions (no open dataset provides them per material) and are labelled so.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "almond_mcp" / "environment" / "data"
RETRIEVED = "2026-11-03"

SOURCES = [
    {"id": "energyplus-hof", "title": "EnergyPlus datasets/ASHRAE_2005_HOF_Materials.idf (thermal properties "
     "after the ASHRAE 2005 Handbook of Fundamentals)", "publisher": "EnergyPlus contributors (NREL, LBNL, ORNL et al.)",
     "version": "EnergyPlus v26.2.0", "url": "https://github.com/NREL/EnergyPlus/blob/v26.2.0/datasets/ASHRAE_2005_HOF_Materials.idf",
     "licence": "LicenseRef-EnergyPlus", "licence_url": "https://github.com/NREL/EnergyPlus/blob/v26.2.0/LICENSE.txt",
     "attribution": "Contains data from EnergyPlus, Copyright (c) 1996-present, The Board of Trustees of the University of "
     "Illinois, The Regents of the University of California through LBNL, ORNL (UT-Battelle), Alliance for Energy "
     "Innovation, LLC, and other contributors. All rights reserved. See LICENSES/EnergyPlus.txt.",
     "retrieved": RETRIEVED},
    {"id": "energyplus-glass", "title": "EnergyPlus datasets/WindowGlassMaterials.idf (spectral-average glass properties "
     "from the LBNL WINDOW glass library)", "publisher": "EnergyPlus contributors", "version": "EnergyPlus v26.2.0",
     "url": "https://github.com/NREL/EnergyPlus/blob/v26.2.0/datasets/WindowGlassMaterials.idf",
     "licence": "LicenseRef-EnergyPlus", "licence_url": "https://github.com/NREL/EnergyPlus/blob/v26.2.0/LICENSE.txt",
     "attribution": "Contains data from EnergyPlus (see energyplus-hof).", "retrieved": RETRIEVED},
    {"id": "honeybee-standards", "title": "honeybee-standards radiance_default.json generic modifiers "
     "(floor 0.20, wall 0.50, ceiling 0.80, exterior 0.35)", "publisher": "Ladybug Tools", "version": "v2.0.7",
     "url": "https://github.com/ladybug-tools/honeybee-standards/blob/v2.0.7/honeybee_standards/radiance_default.json",
     "licence": "MIT", "licence_url": "https://github.com/ladybug-tools/honeybee-standards/blob/v2.0.7/LICENSE",
     "attribution": "Default reflectances from honeybee-standards, MIT License, Copyright (c) 2020 Ladybug Tools. "
     "See LICENSES/honeybee-standards.txt.", "retrieved": RETRIEVED},
    {"id": "de-banz-2020", "title": "Bekanntmachung der Regeln zur Datenaufnahme und Datenverwendung im "
     "Wohngebaeudebestand, BAnz AT 04.12.2020 B1, Tables 2 and 3 (flat-rate U-values by age band)",
     "publisher": "Bundesministerium fuer Wirtschaft und Energie / Bundesministerium des Innern, fuer Bau und Heimat",
     "version": "8 October 2020", "url": "https://www.bundesanzeiger.de/pub/publication/qzQUGd8A3unSCCbVMcf/content/qzQUGd8A3unSCCbVMcf/BAnz%20AT%2004.12.2020%20B1.pdf",
     "licence": "LicenseRef-PublicDomain-DE-UrhG-5", "licence_url": "https://www.gesetze-im-internet.de/urhg/__5.html",
     "attribution": "Source: Bekanntmachung BAnz AT 04.12.2020 B1 (official work, Section 5 UrhG).", "retrieved": RETRIEVED},
    {"id": "hotmaps-building-stock", "title": "Hotmaps building-stock dataset: U-values by country, sector and "
     "construction period", "publisher": "Hotmaps project (H2020 grant 723677); residential values from IEE TABULA "
     "(www.episcope.eu); service values from Birchall et al. 2014",
     "version": "gitlab.com/hotmaps/building-stock @ 9805473f", "url": "https://gitlab.com/hotmaps/building-stock",
     "licence": "CC-BY-4.0", "licence_url": "https://creativecommons.org/licenses/by/4.0/",
     "attribution": "U-values from the Hotmaps building-stock dataset (CC BY 4.0), residential part based on the "
     "IEE TABULA project (www.episcope.eu). Reduced to element averages by Almond.", "retrieved": RETRIEVED},
    {"id": "uk-adl-2021", "title": "Approved Document L, Conservation of fuel and power, Volume 1: Dwellings (Table 1.1, "
     "Table 4.1) and Volume 2: Buildings other than dwellings (Table 4.1), 2021 edition incorporating 2023 amendments",
     "publisher": "HM Government (DLUHC)", "version": "2021 edition incorporating 2023 amendments",
     "url": "https://www.gov.uk/government/publications/conservation-of-fuel-and-power-approved-document-l",
     "licence": "OGL-UK-3.0", "licence_url": "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
     "attribution": "Contains public sector information licensed under the Open Government Licence v3.0 "
     "(Approved Document L 2021, Crown copyright).", "retrieved": RETRIEVED},
    {"id": "bca-envelope-code", "title": "BCA Code on Envelope Thermal Performance for Buildings (ETTV, RETV, RTTV "
     "formulas and maximum values) - cited for the method only; no tables reproduced", "publisher": "Building and "
     "Construction Authority, Singapore", "version": "2008 (R3b)", "url": "https://file.go.gov.sg/bca-envl-therm-code.pdf",
     "licence": "LicenseRef-Method-Cited", "licence_url": "https://www1.bca.gov.sg/terms-of-use",
     "attribution": "Formulas implemented from the BCA Code on Envelope Thermal Performance for Buildings; solar "
     "correction factors and shading coefficients are computed by Almond, not taken from the Code's tables. "
     "Indicative only; not a BCA Green Mark assessment.", "retrieved": RETRIEVED},
    {"id": "almond-own", "title": "Almond engineering assumptions (typical values; check against product data)",
     "publisher": "Almond", "version": "1", "url": "", "licence": "MIT", "licence_url": "", "attribution": "",
     "retrieved": RETRIEVED},
]

# id -> (HOF material name, display name, category, visible reflectance, solar absorptance)
# Finishes: reflectance/absorptance are Almond assumptions (typical, mid-tone unless stated).
CURATED = {
    "concrete_2400": ("Concrete: Sand and gravel or stone aggregate concretes - 2400 kg/m3 - 102mm", "Concrete, normal weight / reinforced (2400 kg/m3)", "concrete", 0.35, 0.65),
    "concrete_2240": ("Concrete: Sand and gravel or stone aggregate concretes - 2240 kg/m3 - 102mm", "Concrete, normal weight (2240 kg/m3)", "concrete", 0.35, 0.65),
    "concrete_light_1280": ("M11 100mm lightweight concrete", "Lightweight concrete (1280 kg/m3)", "concrete", 0.40, 0.60),
    "aac_640": ("Concrete: Foam concretes and cellular concretes - 640 kg/m3 - 102mm", "Aerated / cellular concrete block (640 kg/m3)", "masonry", 0.45, 0.55),
    "screed_cement": ("Concrete: Cement/lime - mortar - and stucco - 1920 kg/m3 - 102mm", "Cement screed or render (1920 kg/m3)", "finish", 0.35, 0.65),
    "plaster_lime_cement": ("Concrete: Cement/lime - mortar - and stucco - 1600 kg/m3 - 102mm", "Lime-cement plaster, painted white", "finish", 0.75, 0.30),
    "gypsum_board": ("G01 16mm gypsum board", "Gypsum plasterboard, painted white", "finish", 0.75, 0.30),
    "stucco": ("F07 25mm stucco", "External render / stucco, light", "finish", 0.60, 0.40),
    "brick_clay_2080": ("Brick - fired clay - 2080 kg/m3 - 102mm", "Clay brick, dense (2080 kg/m3)", "masonry", 0.30, 0.70),
    "brick_clay_1760": ("Brick - fired clay - 1760 kg/m3 - 102mm", "Clay brick (1760 kg/m3)", "masonry", 0.30, 0.70),
    "brick_clay_1280": ("Brick - fired clay - 1280 kg/m3 - 102mm", "Clay brick, perforated / lightweight (1280 kg/m3)", "masonry", 0.30, 0.70),
    "block_concrete_hollow": ("M05 200mm concrete block", "Concrete block, hollow (effective properties)", "masonry", 0.40, 0.60),
    "stone_limestone": ("Calcitic - dolomitic - limestone - marble - and granite - 2240 kg/m3 - 13mm", "Limestone (2240 kg/m3)", "stone", 0.50, 0.50),
    "stone_granite": ("Calcitic - dolomitic - limestone - marble - and granite - 2560 kg/m3 - 13mm", "Granite / marble (2560 kg/m3)", "stone", 0.40, 0.60),
    "terrazzo": ("F18 Terrazzo", "Terrazzo", "finish", 0.50, 0.50),
    "tile_ceramic": ("F14 Slate or tile", "Ceramic or slate tile", "finish", 0.40, 0.60),
    "timber_oak": ("Oak - 25mm", "Oak, solid", "timber", 0.30, 0.70),
    "timber_hardwood": ("Hardwood - 25mm", "Hardwood", "timber", 0.30, 0.70),
    "timber_softwood": ("Softwood - 25mm", "Softwood / cross-laminated timber", "timber", 0.40, 0.60),
    "timber_cladding": ("F11 Wood siding", "Timber cladding", "timber", 0.30, 0.70),
    "plywood": ("Plywood (Douglas Fir) - 15.9mm", "Plywood", "timber", 0.40, 0.60),
    "fibreboard": ("G03 13mm fiberboard sheathing", "Wood-fibre board", "timber", 0.40, 0.60),
    "insulation_eps": ("Insulation: Expanded polystyrene - molded beads - 20kg/m3 density", "Expanded polystyrene (EPS, 20 kg/m3)", "insulation", None, None),
    "insulation_eps_dense": ("Insulation: Expanded polystyrene - molded beads - 32 kg/m3 density", "Expanded polystyrene (EPS, 32 kg/m3)", "insulation", None, None),
    "insulation_xps": ("Insulation: Expanded polystyrene - extruded (smooth skin surface) (HCFC-142b exp.)", "Extruded polystyrene (XPS)", "insulation", None, None),
    "insulation_pir": ("Insulation: Cellular polyisocyanuratei (CFC-11 exp.) (gaspermeable facers)", "Polyisocyanurate board (PIR)", "insulation", None, None),
    "insulation_mineral_wool": ("Insulation: Glass fiber - organic bonded - 25mm", "Mineral / glass wool board", "insulation", None, None),
    "insulation_cellular_glass": ("Insulation: Cellular glass - 50mm", "Cellular glass", "insulation", None, None),
    "membrane_bitumen": ("F13 Built-up roofing", "Bituminous roofing membrane, dark", "membrane", 0.10, 0.90),
    "steel_sheet": ("F08 Metal surface", "Steel sheet, light-coloured coating", "metal", 0.50, 0.45),
    "spandrel_glass": ("F09 Opaque spandrel glass", "Opaque spandrel glass", "glass", 0.20, 0.80),
    "acoustic_tile": ("F16 Acoustic tile", "Acoustic ceiling tile, white", "finish", 0.75, 0.30),
}

# Glass panes from WindowGlassMaterials.idf: id -> (record name, display name)
PANES = {
    "clear_4": ("LOW IRON 4MM", "Clear float, low-iron 4 mm"),
    "clear_6": ("CLEAR 6MM", "Clear float 6 mm"),
    "lowe_6": ("LoE CLEAR 6MM", "Low-e 6 mm, coating face 2 (back)"),
    "lowe_6_rev": ("LoE CLEAR 6MM Rev", "Low-e 6 mm, coating face front"),
    "lowe_sel_6": ("LoE SPEC SEL CLEAR 6MM", "Spectrally selective low-e 6 mm, coating back"),
    "lowe_sel_6_rev": ("LoE SPEC SEL CLEAR 6MM Rev", "Spectrally selective low-e 6 mm, coating front"),
    "hard_lowe_6": ("PYR B CLEAR 6MM", "Pyrolytic (hard) low-e 6 mm"),
    "grey_6": ("GREY 6MM", "Grey tinted 6 mm"),
    "bronze_6": ("BRONZE 6MM", "Bronze tinted 6 mm"),
    "reflective_6": ("REF B CLEAR HI 6MM", "Reflective coated 6 mm"),
}

# Frames: Almond assumptions (typical ranges of current products; check manufacturer data).
FRAMES = [
    {"id": "timber", "name": "Timber frame, 68-78 mm", "u_f": 1.3, "fraction": 0.30, "psi_g": 0.04, "edge_m_per_m2": 2.5},
    {"id": "pvc", "name": "PVC-U multi-chamber frame", "u_f": 1.3, "fraction": 0.30, "psi_g": 0.04, "edge_m_per_m2": 2.5},
    {"id": "aluminium_tb", "name": "Aluminium, thermally broken", "u_f": 2.2, "fraction": 0.20, "psi_g": 0.06, "edge_m_per_m2": 2.5},
    {"id": "aluminium", "name": "Aluminium, no thermal break", "u_f": 5.9, "fraction": 0.20, "psi_g": 0.08, "edge_m_per_m2": 2.5},
    {"id": "steel_slim_tb", "name": "Slim steel, thermally broken", "u_f": 2.8, "fraction": 0.12, "psi_g": 0.06, "edge_m_per_m2": 2.0},
    {"id": "curtain_wall_tb", "name": "Curtain wall, thermally broken mullions", "u_f": 2.0, "fraction": 0.12, "psi_g": 0.06, "edge_m_per_m2": 1.6},
]


def _idf_objects(path: Path) -> list[list[str]]:
    text = re.sub(r"!.*", "", path.read_text(encoding="latin-1"))
    return [[f.strip() for f in o.split(",")] for o in text.split(";") if o.strip()]


def build_materials(dl: Path) -> dict:
    hof = {o[1]: o for o in _idf_objects(dl / "ASHRAE_2005_HOF_Materials.idf") if o[0] == "Material"}
    out = []
    for mid, (hof_name, name, cat, refl, absorb) in CURATED.items():
        o = hof[hof_name]
        m = {"id": mid, "name": name, "category": cat, "conductivity": float(o[4]), "density": float(o[5]),
             "specific_heat": float(o[6]), "source": "energyplus-hof", "source_record": hof_name}
        if refl is not None:
            m.update(reflectance_visible=refl, solar_absorptance=absorb, optical_source="almond-own")
        out.append(m)
    out.append({"id": "air_layer", "name": "Unventilated air layer", "category": "air", "kind": "air_layer",
                "conductivity": None, "density": 1.2, "specific_heat": 1006.0, "source": "almond-own",
                "note": "resistance computed from width and heat-flow direction"})
    return {"materials": out}


def build_glazing(dl: Path) -> dict:
    recs = {o[1]: o for o in _idf_objects(dl / "WindowGlassMaterials.idf") if o[0] == "WindowMaterial:Glazing"}
    panes = []
    for pid, (rec, name) in PANES.items():
        o = recs[rec]
        f = [float(x) if x not in ("", None) else 0.0 for x in o[4:15]]
        panes.append({"id": pid, "name": name, "thickness_m": f[0], "solar_transmittance": f[1],
                      "solar_reflectance_front": f[2], "solar_reflectance_back": f[3], "visible_transmittance": f[4],
                      "visible_reflectance_front": f[5], "visible_reflectance_back": f[6], "ir_transmittance": f[7],
                      "emissivity_front": f[8], "emissivity_back": f[9], "conductivity": f[10],
                      "source": "energyplus-glass", "source_record": rec})
    return {"panes": panes, "frames": [dict(fr, source="almond-own") for fr in FRAMES]}


def build_hotmaps(dl: Path) -> dict:
    rows = csv.DictReader(open(dl / "hotmaps_building_stock.csv", encoding="utf-8"), delimiter="|")
    ages = {"Before 1945": "<1945", "Berfore 1945": "<1945", "1945 - 1969": "1945-1969", "1970 - 1979": "1970-1979",
            "1980 - 1989": "1980-1989", "1990 - 1999": "1990-1999", "2000 - 2010": "2000-2010", "Post 2010": ">2010"}
    elements = {"Walls": "wall", "Roof": "roof", "Floor": "floor", "Windows": "window"}
    table: dict = {}
    for r in rows:
        if not r["feature"].startswith("Construction features (U-value") or r["btype"] != "Total":
            continue
        el, age = elements.get(r["type"].strip()), ages.get(r["bage"])
        if not el or not age or r["country_code"] == "eu27+UK":
            continue
        sector = "residential" if r["sector"].startswith("Residential") else "service"
        try:
            v = round(float(r["value"]), 3)
        except ValueError:
            continue
        table.setdefault(r["country_code"], {}).setdefault(sector, {}).setdefault(age, {})[el] = v
    return {"pack": "eu_hotmaps", "source": "hotmaps-building-stock", "relation": "bundled",
            "description": "Average U-values (W/m2K) of the existing building stock by country, sector and construction "
            "period. For reference cases and refurbishment baselines, not requirements.",
            "age_bands": list(dict.fromkeys(ages.values())), "values": table}


def main(dl: Path) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "codes").mkdir(exist_ok=True)
    def write(path: Path, obj: dict) -> None:
        path.write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print("wrote", path.relative_to(ROOT))
    write(DATA / "materials.json", build_materials(dl))
    write(DATA / "glazing.json", build_glazing(dl))
    write(DATA / "sources.json", {"sources": SOURCES})
    write(DATA / "codes" / "eu_hotmaps.json", build_hotmaps(dl))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]))
