using System;
using System.Collections.Generic;
using System.Linq;
using Rhino;
using Rhino.DocObjects;
using Rhino.Geometry;
using Rhino.Geometry.Intersect;

namespace RhinoAlmondBridge
{
    // ── Conditioned element shapes (consumed by KarambaAdapter) ──────────────
    //
    // UNIT POLICY: ModelConditioner works entirely in RHINO DOCUMENT UNITS.
    // No unit conversion happens in this file. All conversion to Karamba
    // units (meters, kN, cm sections) happens in exactly one place:
    // KarambaAdapter.Units.

    /// <summary>
    /// Cross-section specification in DOCUMENT UNITS.
    /// Source is "inferred" when read from drawn geometry, "default" otherwise.
    /// </summary>
    public class SectionSpec
    {
        /// <summary>"circular_hollow" | "box" | "shell_const"</summary>
        public string Shape { get; set; } = "circular_hollow";

        /// <summary>Outer diameter for circular sections, document units.</summary>
        public double Diameter { get; set; }

        /// <summary>Wall thickness for hollow sections, document units.</summary>
        public double WallThickness { get; set; }

        /// <summary>Width for box sections, document units.</summary>
        public double Width { get; set; }

        /// <summary>Height/depth for box sections, document units.</summary>
        public double Height { get; set; }

        /// <summary>Thickness for shell sections, document units.</summary>
        public double ShellThickness { get; set; }

        /// <summary>"inferred" | "default"</summary>
        public string Source { get; set; } = "default";

        /// <summary>
        /// Default beam section: circular hollow, expressed in document units
        /// via the given scale (docUnit → meters). Physical default is
        /// 114.3 mm outer diameter, 4 mm wall (a common CHS).
        /// </summary>
        public static SectionSpec DefaultBeam(double unitScaleToMeters)
        {
            double s = unitScaleToMeters <= 0 ? 1.0 : unitScaleToMeters;
            return new SectionSpec
            {
                Shape = "circular_hollow",
                Diameter = 0.1143 / s,       // 114.3 mm in doc units
                WallThickness = 0.004 / s,   // 4 mm in doc units
                Source = "default",
            };
        }

        /// <summary>Default shell section: 100 mm constant thickness.</summary>
        public static SectionSpec DefaultShell(double unitScaleToMeters)
        {
            double s = unitScaleToMeters <= 0 ? 1.0 : unitScaleToMeters;
            return new SectionSpec
            {
                Shape = "shell_const",
                ShellThickness = 0.1 / s,    // 100 mm in doc units
                Source = "default",
            };
        }
    }

    /// <summary>A beam axis curve plus its Rhino GUID lineage and section.</summary>
    public class ConditionedBeam
    {
        public Curve Axis { get; set; }
        public List<string> SourceGuids { get; set; } = new List<string>();
        public SectionSpec Section { get; set; }
    }

    /// <summary>A shell mesh plus its Rhino GUID lineage and section.</summary>
    public class ConditionedShell
    {
        public Mesh Mesh { get; set; }
        public List<string> SourceGuids { get; set; } = new List<string>();
        public SectionSpec Section { get; set; }
    }

    /// <summary>Output of ModelConditioner.Condition: analysis-ready geometry.</summary>
    public class ConditionedModel
    {
        public List<ConditionedBeam> Beams { get; set; } = new List<ConditionedBeam>();
        public List<ConditionedShell> Shells { get; set; } = new List<ConditionedShell>();

        /// <summary>Declared anchor/support points (Rhino point objects in the GUID set).</summary>
        public List<Point3d> AnchorPoints { get; set; } = new List<Point3d>();

        public List<string> Warnings { get; set; } = new List<string>();

        /// <summary>Document tolerance used during conditioning (document units).</summary>
        public double Tolerance { get; set; }

        /// <summary>Scale factor from document units to meters.</summary>
        public double UnitScaleToMeters { get; set; } = 1.0;

        /// <summary>Largest span found (document units), for L/250 checks.</summary>
        public double MaxSpan { get; set; }
    }

    /// <summary>
    /// Pure-RhinoCommon geometry conditioning: welds nodes, splits members at
    /// intersections, classifies beams vs shells, infers cross-sections from
    /// drawn geometry. No Karamba dependency. Every conditioned element keeps
    /// the list of source Rhino GUIDs it came from.
    /// </summary>
    public class ModelConditioner
    {
        /// <summary>
        /// Full conditioning pipeline: resolve GUIDs from the document,
        /// classify, weld, split, infer sections.
        /// </summary>
        public ConditionedModel Condition(RhinoDoc doc, IEnumerable<string> guidStrings)
        {
            var model = new ConditionedModel
            {
                Tolerance = doc.ModelAbsoluteTolerance,
                UnitScaleToMeters = RhinoMath.UnitScale(doc.ModelUnitSystem, UnitSystem.Meters),
            };

            var rawBeams = new List<ConditionedBeam>();

            foreach (var guidStr in guidStrings ?? Enumerable.Empty<string>())
            {
                Guid guid;
                if (!Guid.TryParse(guidStr, out guid))
                {
                    model.Warnings.Add($"Ignored malformed GUID '{guidStr}'.");
                    continue;
                }

                var obj = doc.Objects.FindId(guid);
                if (obj == null)
                {
                    model.Warnings.Add($"GUID {guidStr} not found in document.");
                    continue;
                }

                Classify(obj, guidStr, model, rawBeams);
            }

            // Weld beam endpoints, then split members that cross each other.
            if (rawBeams.Count > 0)
            {
                var welded = MergeNodes(rawBeams, model.Tolerance);
                var split = SplitAtIntersections(welded, model.Tolerance);
                model.Beams.AddRange(split);
            }

            // Longest single member = span estimate; fall back to bbox diagonal.
            double span = 0;
            var bbox = BoundingBox.Empty;
            foreach (var b in model.Beams)
            {
                span = Math.Max(span, b.Axis.GetLength());
                bbox.Union(b.Axis.GetBoundingBox(true));
            }
            foreach (var s in model.Shells)
                bbox.Union(s.Mesh.GetBoundingBox(true));
            if (bbox.IsValid)
            {
                var d = bbox.Diagonal;
                span = Math.Max(span, Math.Max(d.X, Math.Max(d.Y, d.Z)));
            }
            model.MaxSpan = span;

            return model;
        }

        /// <summary>
        /// Classify one Rhino object into beams (curves; brep edges only when
        /// the brep is NOT shell-like) or shells (meshes; closed or planar
        /// breps meshed with RhinoCommon), or an anchor point.
        /// </summary>
        public void Classify(RhinoObject obj, string guidStr, ConditionedModel model,
            List<ConditionedBeam> rawBeams)
        {
            double scale = model.UnitScaleToMeters;
            var geom = obj.Geometry;

            if (geom is Point pt)
            {
                model.AnchorPoints.Add(pt.Location);
                return;
            }

            if (geom is Curve crv)
            {
                rawBeams.Add(new ConditionedBeam
                {
                    Axis = crv.DuplicateCurve(),
                    SourceGuids = new List<string> { guidStr },
                    Section = InferSection(obj, scale) ?? SectionSpec.DefaultBeam(scale),
                });
                return;
            }

            if (geom is Mesh mesh)
            {
                model.Shells.Add(new ConditionedShell
                {
                    Mesh = mesh.DuplicateMesh(),
                    SourceGuids = new List<string> { guidStr },
                    Section = SectionSpec.DefaultShell(scale),
                });
                return;
            }

            Brep brep = null;
            if (geom is Extrusion ext)
            {
                // Extrusions that encode a member (compact profile, long path)
                // become beams along their path with an inferred section.
                var inferred = InferSection(obj, scale);
                var path = ext.PathLineCurve();
                if (inferred != null && inferred.Source == "inferred" && path != null)
                {
                    rawBeams.Add(new ConditionedBeam
                    {
                        Axis = path,
                        SourceGuids = new List<string> { guidStr },
                        Section = inferred,
                    });
                    return;
                }
                brep = ext.ToBrep();
            }
            else if (geom is Brep b)
            {
                brep = b;
            }

            if (brep == null)
            {
                model.Warnings.Add($"GUID {guidStr}: unsupported geometry type " +
                    $"{geom.GetType().Name}, skipped.");
                return;
            }

            if (IsShellLike(brep))
            {
                var meshes = Mesh.CreateFromBrep(brep, MeshingParameters.FastRenderMesh);
                if (meshes != null && meshes.Length > 0)
                {
                    var joined = new Mesh();
                    foreach (var m in meshes) joined.Append(m);
                    joined.Weld(Math.PI);
                    joined.Compact();
                    model.Shells.Add(new ConditionedShell
                    {
                        Mesh = joined,
                        SourceGuids = new List<string> { guidStr },
                        Section = SectionSpec.DefaultShell(scale),
                    });
                }
                else
                {
                    model.Warnings.Add($"GUID {guidStr}: brep meshing failed, skipped.");
                }
            }
            else
            {
                // Not shell-like: use edges as beam axes (e.g. drawn wireframes).
                var section = InferSection(obj, scale) ?? SectionSpec.DefaultBeam(scale);
                foreach (var edge in brep.Edges)
                {
                    rawBeams.Add(new ConditionedBeam
                    {
                        Axis = edge.DuplicateCurve(),
                        SourceGuids = new List<string> { guidStr },
                        Section = section,
                    });
                }
            }
        }

        /// <summary>
        /// A brep is shell-like when it is a closed solid, a single face,
        /// or all faces are planar (plate/slab assemblies).
        /// </summary>
        public static bool IsShellLike(Brep brep)
        {
            if (brep == null || brep.Faces.Count == 0) return false;
            if (brep.IsSolid) return true;
            if (brep.Faces.Count == 1) return true;

            foreach (var face in brep.Faces)
            {
                if (!face.IsPlanar(RhinoMath.SqrtEpsilon)) return false;
            }
            return true;
        }

        /// <summary>
        /// Weld beam endpoints that lie within tolerance of each other so
        /// Karamba sees shared nodes. Greedy clustering; endpoints snap to
        /// the first endpoint seen in their cluster. GUID lineage preserved.
        /// </summary>
        public List<ConditionedBeam> MergeNodes(List<ConditionedBeam> beams, double tolerance)
        {
            if (beams == null || beams.Count == 0) return new List<ConditionedBeam>();
            double tol = tolerance > 0 ? tolerance : 0.001;

            var clusterCenters = new List<Point3d>();

            Point3d Snap(Point3d p)
            {
                for (int i = 0; i < clusterCenters.Count; i++)
                {
                    if (clusterCenters[i].DistanceTo(p) <= tol)
                        return clusterCenters[i];
                }
                clusterCenters.Add(p);
                return p;
            }

            var result = new List<ConditionedBeam>();
            foreach (var beam in beams)
            {
                var crv = beam.Axis.DuplicateCurve();
                var start = Snap(crv.PointAtStart);
                var end = Snap(crv.PointAtEnd);

                if (start.DistanceTo(end) <= tol)
                    continue; // degenerate after welding, drop it

                bool moved = true;
                if (crv.PointAtStart.DistanceTo(start) > RhinoMath.ZeroTolerance)
                    moved &= crv.SetStartPoint(start);
                if (crv.PointAtEnd.DistanceTo(end) > RhinoMath.ZeroTolerance)
                    moved &= crv.SetEndPoint(end);

                if (!moved)
                {
                    // Some curve types refuse endpoint edits; rebuild as a line
                    // when the curve is essentially straight, else keep as-is.
                    if (crv.IsLinear(tol))
                        crv = new LineCurve(start, end);
                }

                result.Add(new ConditionedBeam
                {
                    Axis = crv,
                    SourceGuids = new List<string>(beam.SourceGuids),
                    Section = beam.Section,
                });
            }
            return result;
        }

        /// <summary>
        /// Split beam axes wherever they intersect another beam axis, so
        /// crossing members become connected at a shared node after welding.
        /// GUID lineage is inherited by every fragment.
        /// </summary>
        public List<ConditionedBeam> SplitAtIntersections(List<ConditionedBeam> beams, double tolerance)
        {
            if (beams == null || beams.Count < 2)
                return beams ?? new List<ConditionedBeam>();

            double tol = tolerance > 0 ? tolerance : 0.001;
            var splitParams = new List<List<double>>();
            for (int i = 0; i < beams.Count; i++)
                splitParams.Add(new List<double>());

            for (int i = 0; i < beams.Count; i++)
            {
                for (int j = i + 1; j < beams.Count; j++)
                {
                    var events = Intersection.CurveCurve(
                        beams[i].Axis, beams[j].Axis, tol, tol);
                    if (events == null) continue;

                    foreach (var ev in events)
                    {
                        if (!ev.IsPoint) continue;
                        splitParams[i].Add(ev.ParameterA);
                        splitParams[j].Add(ev.ParameterB);
                    }
                }
            }

            var result = new List<ConditionedBeam>();
            for (int i = 0; i < beams.Count; i++)
            {
                var crv = beams[i].Axis;
                var domain = crv.Domain;

                // Keep only interior parameters, deduplicated.
                var ts = splitParams[i]
                    .Where(t => t > domain.Min + RhinoMath.SqrtEpsilon &&
                                t < domain.Max - RhinoMath.SqrtEpsilon)
                    .Distinct()
                    .OrderBy(t => t)
                    .ToList();

                if (ts.Count == 0)
                {
                    result.Add(beams[i]);
                    continue;
                }

                var pieces = crv.Split(ts);
                if (pieces == null || pieces.Length == 0)
                {
                    result.Add(beams[i]);
                    continue;
                }

                foreach (var piece in pieces)
                {
                    if (piece == null || piece.GetLength() <= tol) continue;
                    result.Add(new ConditionedBeam
                    {
                        Axis = piece,
                        SourceGuids = new List<string>(beams[i].SourceGuids),
                        Section = beams[i].Section,
                    });
                }
            }
            return result;
        }

        /// <summary>
        /// Infer a cross-section from the drawn geometry when it encodes one:
        /// pipe/cylinder radius from breps, profile dimensions from extrusions.
        /// Returns null when nothing can be inferred (caller applies default).
        /// Dimensions returned in DOCUMENT UNITS with Source = "inferred".
        /// </summary>
        public SectionSpec InferSection(RhinoObject obj, double unitScaleToMeters)
        {
            var geom = obj?.Geometry;
            if (geom == null) return null;

            if (geom is Extrusion ext)
            {
                var profile = ext.Profile3d(new ComponentIndex(ComponentIndexType.ExtrusionBottomProfile, 0));
                if (profile == null) profile = ext.Profile3d(0, 0.0);
                if (profile != null)
                {
                    Circle circle;
                    if (profile.TryGetCircle(out circle, RhinoMath.SqrtEpsilon))
                    {
                        return new SectionSpec
                        {
                            Shape = "circular_hollow",
                            Diameter = circle.Diameter,
                            WallThickness = Math.Max(circle.Diameter * 0.1, 1e-6),
                            Source = "inferred",
                        };
                    }

                    var pbox = profile.GetBoundingBox(true);
                    if (pbox.IsValid)
                    {
                        var d = pbox.Diagonal;
                        // Two largest extents of the profile bbox = width x height.
                        var dims = new[] { d.X, d.Y, d.Z }.OrderByDescending(v => v).ToArray();
                        if (dims[0] > RhinoMath.ZeroTolerance && dims[1] > RhinoMath.ZeroTolerance)
                        {
                            return new SectionSpec
                            {
                                Shape = "box",
                                Width = dims[1],
                                Height = dims[0],
                                WallThickness = Math.Max(dims[1] * 0.1, 1e-6),
                                Source = "inferred",
                            };
                        }
                    }
                }
                return null;
            }

            if (geom is Brep brep)
            {
                // A drawn pipe shows up as one or more cylindrical faces.
                double outerRadius = 0;
                double innerRadius = double.MaxValue;
                int cylinderCount = 0;

                foreach (var face in brep.Faces)
                {
                    Cylinder cyl;
                    if (face.TryGetCylinder(out cyl, RhinoMath.SqrtEpsilon))
                    {
                        cylinderCount++;
                        outerRadius = Math.Max(outerRadius, cyl.Radius);
                        innerRadius = Math.Min(innerRadius, cyl.Radius);
                    }
                }

                if (cylinderCount > 0 && outerRadius > RhinoMath.ZeroTolerance)
                {
                    double wall = (cylinderCount >= 2 && innerRadius < outerRadius)
                        ? (outerRadius - innerRadius)   // hollow pipe: two cylinders
                        : outerRadius * 0.5;            // solid rod: treat as thick-walled
                    return new SectionSpec
                    {
                        Shape = "circular_hollow",
                        Diameter = outerRadius * 2.0,
                        WallThickness = Math.Max(wall, 1e-6),
                        Source = "inferred",
                    };
                }
            }

            return null;
        }
    }
}
