# ProjectY2K library selection — 19 September 2026

The owner requested that only neutral, general-purpose architectural models
enter Almond's downloadable library. Futuristic assets used to style Y2K's
worlds are excluded even where their object category could be architectural.

## Reviewed sources

The local ProjectY2K project was inspected read-only. Relevant relative paths:

| Evidence | Finding | Library decision |
| --- | --- | --- |
| `twofronts/meshy/README.md`, `twofronts/world/assets.json`, `twofronts/meshy/models/` | Pod building, kiosk, planter pod, sign pod, vending unit, hover vehicles and stylized characters | Exclude the futuristic designs. The five trial derivatives and their catalogue records are removed from rc.11. |
| `twofronts/infrastructure/scripts/condition_meshy_assets_v016.py` | Meshy character, weapon and drone inventory | Outside the general architectural collection. |
| `twofronts/characters/r16_reconstruction/meshy_equipment_jobs.json`, `twofronts/combat_v016/drones/meshy_jobs_v020.json` | Character equipment and combat drones | Outside the general architectural collection. |
| `twofronts/infrastructure/scripts/build_district_kit_v016.py` | Authored Blender kit includes stairs, fences and air handlers | Possible future neutral additions; these are authored geometry, not Meshy outputs. Not bundled in this candidate. |
| `twofronts/infrastructure/world/reference_architecture_v001/README.md` | Detailed architecture art master with reusable modules and external visual references | Separate authored project; not imported as generated Meshy models. |

No qualifying neutral Meshy additions were identified in this review. The
current pack retains the existing 47 models. Source project geometry, textures
and records remain untouched. This inventory is a selection record, not
generation attribution for the existing Almond models.

Future additions must retain their actual authoring method, source revision and
checksums, dimensions and derivation history. Blender assets must not acquire
invented Meshy task IDs or prompts. Follow
[source documentation](generation-source-documentation.md) before packaging.
