using System;
using System.Collections.Generic;
using System.Linq;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using Rhino;
using Rhino.Geometry;

namespace RhinoAlmondBridge
{
    /// <summary>
    /// "structure_model": the conditioned line model as plain JSON (meters), for Almond's
    /// native solver in the MCP server. Uses the same ModelConditioner and the same
    /// straightening of curved axes as the Karamba path, so both engines analyse
    /// identical geometry. No Karamba dependency.
    /// </summary>
    public static class StructureModelExport
    {
        public static string Handle(JObject jobj)
        {
            var guids = jobj["guids"]?.ToObject<List<string>>() ?? new List<string>();
            var doc = RhinoDoc.ActiveDoc;
            if (doc == null)
                return JsonConvert.SerializeObject(new { status = "error", message = "No active Rhino document." });

            var cond = new ModelConditioner().Condition(doc, guids);
            try
            {
                double s = cond.UnitScaleToMeters;
                Func<Point3d, double[]> M = p => new[] { p.X * s, p.Y * s, p.Z * s };
                var warnings = new List<string>(cond.Warnings);
                var members = new List<object>();
                foreach (var beam in cond.Beams)
                {
                    List<Point3d> pts;
                    if (beam.Axis.IsLinear(cond.Tolerance))
                        pts = new List<Point3d> { beam.Axis.PointAtStart, beam.Axis.PointAtEnd };
                    else
                    {
                        var poly = beam.Axis.ToPolyline(cond.Tolerance, 0.1, 0, beam.Axis.GetLength())?.ToPolyline();
                        if (poly == null)
                        {
                            warnings.Add("A curved beam axis could not be polygonized; skipped. GUIDs: " +
                                string.Join(",", beam.SourceGuids));
                            continue;
                        }
                        pts = poly.ToList();
                    }
                    var sec = beam.Section ?? SectionSpec.DefaultBeam(s);
                    members.Add(new
                    {
                        source_guids = beam.SourceGuids,
                        points = pts.Select(M).ToList(),
                        section = new
                        {
                            shape = sec.Shape, source = sec.Source,
                            diameter = sec.Diameter * s, wall = sec.WallThickness * s,
                            width = sec.Width * s, height = sec.Height * s,
                        },
                    });
                }
                return JsonConvert.SerializeObject(new
                {
                    status = "ok",
                    members,
                    shells = cond.Shells.Count,
                    anchor_points = cond.AnchorPoints.Select(M).ToList(),
                    tolerance_m = cond.Tolerance * s,
                    max_span_m = cond.MaxSpan * s,
                    max_member_span_m = cond.MaxMemberSpan * s,
                    unit_scale_to_m = s,
                    warnings,
                });
            }
            finally
            {
                foreach (var b in cond.Beams) b.Axis.Dispose();
                foreach (var sh in cond.Shells) sh.Mesh.Dispose();
            }
        }
    }
}
