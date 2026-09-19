# Architectural detail libraries and a drawing workflow for Almond

Research checked: 19 September 2026. Status: research and proposed development scope; the tools and metadata additions below are not implemented by this document. No external drawing library was downloaded or added to a release.

## Recommended sources

Free access and permission to redistribute assets in a plugin are separate questions. Preserve source-specific notices and review the selected files before packaging.

| Source | Available material and access | Best use in Almond | Packaging position |
| --- | --- | --- | --- |
| [dataholz](https://www.dataholz.eu/en/index.htm) | Public timber material and assembly catalogue with thermal, acoustic, fire and ecological information; PDF datasheets. The German site includes [wall junctions](https://www.dataholz.eu/bauteilfuegungen/wandknoten-aussenwand.htm); the English page currently says component connections are being revised. | Find wall, roof and floor assemblies; retain layer descriptions and source references for section drafting. | Reference first. [Terms](https://www.dataholz.eu/allgemeine-nutzungsbedingungen.htm) permit specified uses of datasheets but reserve broader reproduction/distribution. Do not bundle a copied catalogue without permission. |
| [Lignumdata](https://www.lignumdata.ch/) | Public Swiss timber construction database. Its homepage advertises IFC and API capabilities; the [assembly catalogue](https://lignumdata.ch/system/bauteile?locale=en) includes walls, floors and roofs. | Particularly relevant to Swiss timber assembly selection and structured material descriptions. | API authentication, export availability and redistribution terms still need verification. Public catalogue access does not establish an open licence. Some repeat page requests timed out. |
| [ARCAT CAD details](https://www.arcat.com/content-type/cad) | Free manufacturer detail drawings in DWG and PDF, arranged by construction category. | Product-specific openings, roof interfaces, fixtures and installation references in individual projects. | [Terms](https://www.arcat.com/terms) allow limited construction-document use and restrict redistribution. Treat as external project references, not a bundled asset pack. |
| [CADdetails](https://www.caddetails.com/) | Manufacturer CAD/BIM models and technical material, with registration/sign-in flows. | Additional product-specific drawing references and compatible BIM objects. | File downloads and redistribution permissions were not tested. Verify each selected source. |
| [WikiHouse blocks](https://www.wikihouse.cc/blocks) and [Skylark repository](https://github.com/wikihouseproject/Skylark) | Downloadable modular timber blocks, 3D models, cutting files and metadata. The repository identifies CC BY-SA 4.0. | Strong candidate for a reusable assembly pack that connects geometry, parts, fabrication and documentation. | Candidate for an optional, separately attributed pack under the applicable share-alike terms. Preserve file notices, review exceptions and avoid implying endorsement. |
| [LibreCAD community part libraries](https://dokuwiki.librecad.org/doku.php/community%3Apartlibs) | A directory of DXF parts, including architectural interior content. | Simple 2D furniture, fixtures and drafting symbols that complement dense generated meshes. | Review the licence of each linked library; LibreCAD's software licence does not license every contributed drawing. |

The [GSStnb/dxfBlocks repository](https://github.com/GSStnb/dxfBlocks) is relevant for architectural plans, elevations and symbols, but has conflicting notices: its [README](https://raw.githubusercontent.com/GSStnb/dxfBlocks/master/README.md) specifies CC BY-NC-SA 4.0, while its [LICENSE](https://raw.githubusercontent.com/GSStnb/dxfBlocks/master/LICENSE) contains CC0. Hold it out of a distributed pack until clarified. Its README also specifies full-size inch geometry, so ingestion would require explicit unit conversion.

### If “DETAIL” means the publisher

[DETAIL Inspiration](https://inspiration.detail.de/en) is a subscription reference collection, rather than a generally free downloadable CAD repository. EPFL currently lists it among its [subscribed databases](https://www.epfl.ch/campus/library/collections/databases/), accessible on campus or through VPN for eligible users. Authenticated access for this user was not tested. This could provide valuable project drawings and construction references, but institutional reading access is not permission to redistribute them in Almond.

## Product direction: one asset, several useful representations

The distinctive feature should be a model that knows how it should appear in drawings and which references support its use.

1. **Presentation geometry:** preserve the Meshy mesh, materials, generation provenance and asset passport.
2. **Drawing geometry:** attach clean plan, elevation and section representations at declared scales. Choose between projected mesh outlines and authored or parametric proxies according to the object and required fidelity.
3. **Construction references:** attach a sourced assembly or installation detail where relevant, with its applicability and review status. A reference attached to a generated object does not establish that the object matches a manufactured product.

For example, a custom washbasin could carry a textured mesh, a clean 1:50 plan symbol, a front elevation and declared installation clearances. A manufacturer installation drawing should only become an exact product reference after the product match is established. A visually generated wall cannot supply hidden insulation, fasteners or certified performance; those require separately specified assembly information.

## Extend the existing passport

Proposed fields should separate measured geometry, user declarations, generated approximations and sourced specifications:

| Metadata group | Fields and purpose |
| --- | --- |
| Representation | Parent asset ID and geometry hash; representation file, format, view, method, revision and author. Detect stale drawings when the source changes. |
| Coordinate system | Explicit units, up/front directions, insertion anchor and local-to-model transform. Normalize custom imports before dimensioning. |
| Drawing policy | Supported scales, cut-plane height, silhouette/visible/hidden/overhead roles, hatch policy and simplification tolerance with declared units. |
| Dimensions | Geometric bounds separately from nominal product dimensions; evidence and review status for each. |
| Detail reference | Source URL, source revision/date, publisher, assembly or product ID, material layers, relevant region and relationship such as reference-only or verified match. |
| Rights | Licence identifier or terms URL, attribution, redistribution decision and review date. Unknown rights should not silently become redistributable. |
| Validation | Open mesh/section-loop diagnostics, orientation review, scale verification and drawing quality review. |

Keep detailed drawing metadata in versioned sidecars and embed a compact, resolvable representation index in the GLB passport. Hash derived geometry against the source geometry content rather than a whole-file hash that changes when metadata is embedded.

## Build on Almond's current drawing features

The repository already has drawing asset search/placement, hatch-pattern import and drawing recipes. `DrawingRecipes/technical_axon.json` defines separate cut, profile, visible, detail, hidden, overhead, entourage, hatch and annotation layers. Reuse those roles across new plan/elevation/section recipes, with weights reviewed at the target paper scale.

Rhino 8 provides the necessary starting points: [Make2D](https://docs.mcneel.com/rhino/8/help/en-us/commands/make2d.htm) supports projected curves, hidden-line handling and source-layer organization; [MeshOutline](https://docs.mcneel.com/rhino/8/help/en-us/commands/meshoutline.htm) supplies mesh outlines. [Clipping drawing commands](https://docs.mcneel.com/rhino/8/help/en-us/commands/clippingplane.htm) support section drawing creation, updating and export. Generated meshes still need quality checks: raw triangle edges do not make useful architectural linework, and open meshes can produce incomplete section boundaries.

Potential MCP additions, explicitly proposed:

- `import_custom_mesh_asset`: normalize units and orientation, calculate bounds, preserve supplied provenance and create a passport.
- `generate_asset_drawing_views`: produce named views, apply drawing roles and record derivation/revision data.
- `search_construction_details`: query a curated source index and permitted local libraries by assembly, material, region and available format.
- `attach_detail_reference`: associate evidence and applicability without inventing construction information.
- `create_drawing_sheet`: compose selected views, dimensions, labels, scale and source references for vector export.
- `audit_drawing_output`: flag stale representations, missing units, unclosed hatch boundaries and unsupported dimensions.

## Suggested first development increment

Start with ten representative assets from the existing 47-model catalogue: furniture, planting, lighting and sanitary fixtures, plus one user-supplied custom mesh. Produce 1:50 and 1:100 plans and 1:50 elevations. Review the results on an A3 sheet; use this to decide which categories need authored proxies rather than direct projection.

In parallel with that future implementation, curate a small reference index for timber walls, floors, roof junctions and window interfaces using dataholz and Lignumdata. Author original example assembly diagrams with explicit layer inputs. Link applicable external evidence and keep any performance values attached to the exact source assembly and conditions.

Acceptance checks: correct unit conversion and a known dimension; legible printed linework; no unwanted triangulation; correct cut/overhead separation; closed hatch boundaries where required; traceability from every view to its asset and revision; stale views detected after model edits. Rhino execution and exported-sheet inspection remain necessary before claiming this workflow works end to end.

## Release packaging

Ship the drawing tools, schema, original templates and rights-cleared assets in the core release. Distribute any confirmed share-alike library as a separately identified optional pack with its own notices. Keep restricted reference drawings in user-managed project libraries, with links and provenance in the catalogue where permitted. A pack manifest should record asset hashes, dependency/schema versions, attribution and the redistribution decision for every included file.

This would extend the current semantic model library into a traceable drawing workflow: select a model, obtain an appropriate drawing representation, attach relevant evidence and regenerate the documentation when the design changes.
