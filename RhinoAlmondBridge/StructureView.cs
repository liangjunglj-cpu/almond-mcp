using System;
using System.Collections.Generic;
using System.Drawing;
using System.Linq;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using Rhino;
using Rhino.Display;
using Rhino.Geometry;

namespace RhinoAlmondBridge
{
    /// <summary>
    /// Live structure view: runs Karamba on a line model and draws the result in every
    /// viewport through a display conduit - undeformed wireframe, exaggerated deformed shape
    /// coloured by displacement or utilization, supports, loads and a legend panel.
    /// Nothing is baked into the document.
    ///
    /// Bridge request: {"type": "structure_view", "guids": [...curves and support points...],
    ///   "load_kn": 20, "material": "Steel", "beam_diameter_mm": 168.3, "beam_wall_mm": 8,
    ///   "self_weight": true, "fixed_rotations": true, "deflection_limit_ratio": 250,
    ///   "scale": null (auto) | number, "color_by": "displacement"|"utilization",
    ///   "title": "...", "reanalyze": true, "reveal": 1.0, "clear": false}
    /// With "reanalyze": false only the display options change (scale, colouring, reveal),
    /// which is cheap enough to animate frame by frame.
    /// </summary>
    public class StructureViewRequest
    {
        [JsonProperty("guids")] public List<string> Guids { get; set; } = new List<string>();
        [JsonProperty("load_kn")] public double LoadKN { get; set; } = 10.0;
        [JsonProperty("material")] public string Material { get; set; } = "Steel";
        [JsonProperty("beam_diameter_mm")] public double? BeamDiameterMM { get; set; }
        [JsonProperty("beam_wall_mm")] public double? BeamWallMM { get; set; }
        [JsonProperty("self_weight")] public bool IncludeSelfWeight { get; set; } = true;
        [JsonProperty("fixed_rotations")] public bool FixedRotations { get; set; } = true;
        [JsonProperty("deflection_limit_ratio")] public double LimitRatio { get; set; } = 250;
        [JsonProperty("scale")] public double? Scale { get; set; }
        [JsonProperty("color_by")] public string ColorBy { get; set; } = "displacement";
        [JsonProperty("title")] public string Title { get; set; }
        [JsonProperty("reanalyze")] public bool Reanalyze { get; set; } = true;
        [JsonProperty("physics")] public bool Physics { get; set; } = true;
        [JsonProperty("span_m")] public double? SpanM { get; set; }
        [JsonProperty("reveal")] public double Reveal { get; set; } = 1.0;
        [JsonProperty("display_guids")] public List<string> DisplayGuids { get; set; }
        [JsonProperty("load_label")] public string LoadLabel { get; set; }
        [JsonProperty("show_legend")] public bool ShowLegend { get; set; } = true;
        [JsonProperty("clear")] public bool Clear { get; set; }
    }

    public static class StructureView
    {
        private static StructureConduit _conduit;
        private static readonly ModelConditioner Conditioner = new ModelConditioner();

        public static string Handle(JObject jobj)
        {
            var req = jobj.ToObject<StructureViewRequest>();
            var doc = RhinoDoc.ActiveDoc;
            if (doc == null) return Error("No active Rhino document.");
            if (_conduit == null) _conduit = new StructureConduit();

            if (req.Clear)
            {
                _conduit.Enabled = false;
                _conduit.Data = null;
                doc.Views.Redraw();
                return JsonConvert.SerializeObject(new { status = "cleared" });
            }

            if (req.Reanalyze || _conduit.Data == null)
            {
                var cond = Conditioner.Condition(doc, req.Guids);
                if (cond.Beams.Count == 0) return Error("No curve members found for the given GUIDs.");
                if (req.BeamDiameterMM.HasValue)
                {
                    double toDoc = RhinoMath.UnitScale(UnitSystem.Millimeters, doc.ModelUnitSystem);
                    foreach (var b in cond.Beams)
                        b.Section = new SectionSpec
                        {
                            Shape = "circular_hollow", Source = "user",
                            Diameter = req.BeamDiameterMM.Value * toDoc,
                            WallThickness = (req.BeamWallMM ?? req.BeamDiameterMM.Value / 20) * toDoc,
                        };
                }
                var res = KarambaAdapter.BuildAndAnalyze(new KarambaModelSpec
                {
                    Conditioned = cond, MaterialName = req.Material, ImposedLoadKN = req.LoadKN,
                    IncludeSelfWeight = req.IncludeSelfWeight, FixedRotations = req.FixedRotations,
                    ReturnGeometry = true,
                });
                if (!res.Available) return Error(res.FailureReason ?? "Karamba analysis unavailable.", res.Warnings);
                if (!res.GeometryAvailable) return Error("Karamba solved but returned no displacement field.", res.Warnings);
                // reference span for the L/limit check: the member length unless the caller
                // names the structural span (members split at every node are shorter than it)
                double spanM = Math.Max(1e-3, req.SpanM ?? cond.MaxMemberSpan * cond.UnitScaleToMeters);
                _conduit.Data = new StructureData
                {
                    Result = res, ToDoc = 1.0 / cond.UnitScaleToMeters, SpanM = spanM,
                    LimitMM = spanM * 1000.0 / Math.Max(1, req.LimitRatio), LimitRatio = req.LimitRatio,
                    Material = req.Material, LoadKN = req.LoadKN, SelfWeight = req.IncludeSelfWeight,
                    Engine = "api", DefaultTitle = "ALMOND  //  KARAMBA LIVE ANALYSIS",
                };
            }
            return Present(doc, req);
        }

        /// <summary>
        /// "structure_draw": display results computed elsewhere (Almond's native solver in the
        /// MCP server) through the same conduit. "result" carries elements with start/end points
        /// and sampled global displacements (meters), utilization, supports and loads; without
        /// "result" only the display options of the current overlay change.
        /// </summary>
        public static string HandleDraw(JObject jobj)
        {
            var req = jobj.ToObject<StructureViewRequest>();
            var doc = RhinoDoc.ActiveDoc;
            if (doc == null) return Error("No active Rhino document.");
            if (_conduit == null) _conduit = new StructureConduit();
            var result = jobj["result"] as JObject;
            if (result != null)
            {
                var res = new KarambaResults { Available = true, GeometryAvailable = true, DisplacementAvailable = true };
                foreach (var e in (result["elements"] as JArray) ?? new JArray())
                    res.Elements.Add(new ElementDeflection
                    {
                        SourceGuids = e["source_guids"]?.ToObject<List<string>>() ?? new List<string>(),
                        StartM = e["start_m"].ToObject<double[]>(),
                        EndM = e["end_m"].ToObject<double[]>(),
                        SampleDispM = e["samples_m"].ToObject<List<double[]>>(),
                        Utilization = e["utilization"] != null && (e["utilization"].Type == JTokenType.Float || e["utilization"].Type == JTokenType.Integer)
                            ? e["utilization"].Value<double>() : double.NaN,
                        Hinges = e["hinges"]?.ToObject<bool[]>(),
                    });
                if (res.Elements.Count == 0 || res.Elements.Any(x => x.SampleDispM == null || x.SampleDispM.Count < 2))
                    return Error("structure_draw needs elements with at least two displacement samples.");
                res.SupportPointsM = result["support_points_m"]?.ToObject<List<double[]>>() ?? new List<double[]>();
                res.LoadedPointsM = result["loaded_points_m"]?.ToObject<List<double[]>>() ?? new List<double[]>();
                res.MaxDisplacementMM = result["max_displacement_mm"]?.Value<double>()
                    ?? res.Elements.Max(x => x.SampleDispM.Max(d => Len(d))) * 1000.0;
                res.Warnings = result["warnings"]?.ToObject<List<string>>() ?? new List<string>();
                double spanM = Math.Max(1e-3, req.SpanM ?? 5.0);
                _conduit.Data = new StructureData
                {
                    Result = res, ToDoc = RhinoMath.UnitScale(UnitSystem.Meters, doc.ModelUnitSystem), SpanM = spanM,
                    LimitMM = spanM * 1000.0 / Math.Max(1, req.LimitRatio), LimitRatio = req.LimitRatio,
                    Material = req.Material, LoadKN = req.LoadKN, SelfWeight = req.IncludeSelfWeight,
                    Engine = jobj["engine"]?.ToString() ?? "native", DefaultTitle = "ALMOND  //  NATIVE FEA",
                };
            }
            else if (_conduit.Data == null)
                return Error("Nothing to display yet: send a result first.");
            return Present(doc, req);
        }

        /// <summary>Apply the display options, enable the conduit and report the shown result.</summary>
        private static string Present(RhinoDoc doc, StructureViewRequest req)
        {
            var data = _conduit.Data;
            data.Title = req.Title ?? data.Title ?? data.DefaultTitle;
            data.ColorBy = (req.ColorBy ?? "displacement").ToLowerInvariant();
            data.Reveal = Math.Max(0, Math.Min(1, req.Reveal));
            data.ShowLegend = req.ShowLegend;
            data.Physics = req.Physics;
            if (req.LoadLabel != null) data.LoadLabel = req.LoadLabel;
            data.DisplaySet = req.DisplayGuids != null && req.DisplayGuids.Count > 0
                ? new HashSet<string>(req.DisplayGuids, StringComparer.OrdinalIgnoreCase) : null;
            double maxM = data.Result.MaxDisplacementMM / 1000.0;
            // auto exaggeration: largest deflection drawn at ~6% of the model span
            data.Scale = req.Scale ?? (maxM > 1e-9 ? 0.06 * data.SpanM / maxM : 1.0);
            _conduit.Enabled = true;
            doc.Views.Redraw();

            var r = data.Result;
            double maxUtil = r.Elements.Where(e => !double.IsNaN(e.Utilization)).Select(e => e.Utilization).DefaultIfEmpty(double.NaN).Max();
            return JsonConvert.SerializeObject(new
            {
                status = r.MaxDisplacementMM <= data.LimitMM && (double.IsNaN(maxUtil) || maxUtil <= 1.0) ? "pass" : "fail",
                analysis_method = data.Engine,
                max_displacement_mm = Math.Round(r.MaxDisplacementMM, 3),
                deflection_limit_mm = Math.Round(data.LimitMM, 3),
                span_m = Math.Round(data.SpanM, 3),
                max_utilization = double.IsNaN(maxUtil) ? (double?)null : Math.Round(maxUtil, 4),
                scale = data.Scale,
                elements = r.Elements.Select(e => new
                {
                    source_guids = e.SourceGuids,
                    max_displacement_mm = Math.Round(e.SampleDispM.Max(d => Len(d)) * 1000, 3),
                    utilization = double.IsNaN(e.Utilization) ? (double?)null : Math.Round(e.Utilization, 4),
                }),
                nodes = r.NodeDispM.Count,
                warnings = r.Warnings,
            });
        }

        private static double Len(double[] d) => Math.Sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2]);

        private static string Error(string msg, List<string> warnings = null) =>
            JsonConvert.SerializeObject(new { status = "error", message = msg, warnings = warnings ?? new List<string>() });
    }

    public class StructureData
    {
        public KarambaResults Result;
        public double ToDoc = 1000, SpanM, LimitMM, LimitRatio, Scale = 1, Reveal = 1;
        public double LoadKN;
        public bool SelfWeight, Physics = true;
        public HashSet<string> DisplaySet;
        public string LoadLabel;
        public string Title, ColorBy = "displacement", Material;
        public string Engine = "api", DefaultTitle = "ALMOND  //  KARAMBA LIVE ANALYSIS";
        public bool ShowLegend = true;
    }

    public class StructureConduit : DisplayConduit
    {
        public StructureData Data;
        private static readonly Color Ghost = Color.FromArgb(150, 150, 158);

        // Karamba-style ramp: blue -> cyan -> green -> yellow -> red
        public static Color Ramp(double t)
        {
            t = Math.Max(0, Math.Min(1, t));
            var stops = new[] { Color.FromArgb(30, 70, 255), Color.FromArgb(0, 210, 255), Color.FromArgb(40, 220, 90),
                                Color.FromArgb(255, 220, 0), Color.FromArgb(240, 40, 30) };
            double x = t * (stops.Length - 1); int i = Math.Min(stops.Length - 2, (int)x); double f = x - i;
            Color a = stops[i], b = stops[i + 1];
            return Color.FromArgb((int)(a.R + (b.R - a.R) * f), (int)(a.G + (b.G - a.G) * f), (int)(a.B + (b.B - a.B) * f));
        }

        private Point3d P(double[] m, double[] d, double s) =>
            new Point3d((m[0] + d[0] * s) * Data.ToDoc, (m[1] + d[1] * s) * Data.ToDoc, (m[2] + d[2] * s) * Data.ToDoc);

        protected override void CalculateBoundingBox(CalculateBoundingBoxEventArgs e)
        {
            if (Data?.Result == null) return;
            foreach (var el in Data.Result.Elements)
            {
                e.IncludeBoundingBox(new BoundingBox(new[] { P(el.StartM, new double[3], 0), P(el.EndM, new double[3], 0) }));
            }
        }

        protected override void DrawForeground(DrawEventArgs e)
        {
            if (Data?.Result == null) return;
            var r = Data.Result;
            int n = r.Elements.Count;
            int shown = (int)Math.Ceiling(n * Data.Reveal);
            double maxM = Math.Max(1e-9, r.MaxDisplacementMM / 1000.0);
            bool byUtil = Data.ColorBy == "utilization" && r.Elements.Any(x => !double.IsNaN(x.Utilization));
            float dpi = (float)e.Viewport.Bounds.Height / 1000f;
            int thick = Math.Max(3, (int)(7 * dpi));

            // display filter (e.g. one frame line for a section view); the solve still covers every member
            bool Visible(int k) => k < shown && (Data.DisplaySet == null ||
                r.Elements[k].SourceGuids.Any(g => Data.DisplaySet.Contains(g)));
            var endsM = Enumerable.Range(0, n).Where(Visible)
                .SelectMany(k => new[] { r.Elements[k].StartM, r.Elements[k].EndM }).ToList();
            bool NearShown(double[] p) => Data.DisplaySet == null ||
                endsM.Any(q => Math.Abs(q[0] - p[0]) + Math.Abs(q[1] - p[1]) + Math.Abs(q[2] - p[2]) < 1e-3);

            if (!Data.Physics)
            {
                // physics off: the same members as plain geometry, no analysis drawn
                for (int k = 0; k < shown; k++)
                {
                    if (!Visible(k)) continue;
                    var el = r.Elements[k];
                    e.Display.DrawLine(P(el.StartM, new double[3], 0), P(el.EndM, new double[3], 0), Color.FromArgb(245, 245, 240), thick);
                }
                if (Data.ShowLegend) DrawOffLegend(e, dpi, shown, n);
                return;
            }
            for (int k = 0; k < shown; k++)
            {
                if (!Visible(k)) continue;
                var el = r.Elements[k];
                // undeformed wireframe
                e.Display.DrawLine(P(el.StartM, new double[3], 0), P(el.EndM, new double[3], 0), Ghost, Math.Max(1, thick / 3));
                // deformed shape, coloured per station
                int m = el.SampleDispM.Count;
                for (int i = 0; i < m - 1; i++)
                {
                    double t0 = (double)i / (m - 1), t1 = (double)(i + 1) / (m - 1);
                    var a = Lerp(el.StartM, el.EndM, t0); var b = Lerp(el.StartM, el.EndM, t1);
                    var da = el.SampleDispM[i]; var db = el.SampleDispM[i + 1];
                    double v = byUtil ? el.Utilization : (Len(da) + Len(db)) / 2 / maxM;
                    e.Display.DrawLine(P(a, da, Data.Scale), P(b, db, Data.Scale), Ramp(byUtil ? v : v), thick);
                }
            }
            // pinned member ends: hollow circles just inside the member on the deformed shape
            for (int k = 0; k < shown; k++)
            {
                if (!Visible(k)) continue;
                var el = r.Elements[k];
                if (el.Hinges == null || el.SampleDispM.Count < 2) continue;
                for (int side = 0; side < 2; side++)
                {
                    if (side >= el.Hinges.Length || !el.Hinges[side]) continue;
                    double t = side == 0 ? 0.06 : 0.94;
                    double fi = t * (el.SampleDispM.Count - 1);
                    int i0 = Math.Min((int)fi, el.SampleDispM.Count - 2);
                    double fr = fi - i0;
                    var d0 = el.SampleDispM[i0]; var d1 = el.SampleDispM[i0 + 1];
                    var dd = new[] { d0[0] + (d1[0] - d0[0]) * fr, d0[1] + (d1[1] - d0[1]) * fr, d0[2] + (d1[2] - d0[2]) * fr };
                    var pt = P(Lerp(el.StartM, el.EndM, t), dd, Data.Scale);
                    e.Display.DrawPoint(pt, PointStyle.RoundControlPoint, Math.Max(5, (int)(7 * dpi)), Color.White);
                }
            }
            // supports (triangles) and loaded nodes (arrows)
            double arrow = Data.SpanM * 0.12 * Data.ToDoc;
            foreach (var s in r.SupportPointsM)
            {
                if (!NearShown(s)) continue;
                var p = new Point3d(s[0] * Data.ToDoc, s[1] * Data.ToDoc, s[2] * Data.ToDoc);
                double h = arrow * 0.22;
                var side = e.Viewport.CameraX; side.Z = 0;
                if (!side.Unitize()) side = Vector3d.XAxis;
                var down = new Vector3d(0, 0, -h);
                var tri = new[] { p, p + down + side * h * 0.8, p + down - side * h * 0.8 };
                e.Display.DrawPolygon(tri, Color.FromArgb(233, 68, 43), true);
                e.Display.DrawPolyline(new[] { tri[0], tri[1], tri[2], tri[0] }, Color.White, Math.Max(1, thick / 3));
                e.Display.DrawLine(p + down * 1.25 + side * h, p + down * 1.25 - side * h, Color.White, Math.Max(1, thick / 3));
            }
            if (Data.Reveal >= 0.999)
                foreach (var lp in r.LoadedPointsM)
                {
                    if (!NearShown(lp)) continue;
                    var p = new Point3d(lp[0] * Data.ToDoc, lp[1] * Data.ToDoc, lp[2] * Data.ToDoc);
                    e.Display.DrawArrow(new Line(p + new Vector3d(0, 0, arrow), p), Color.FromArgb(255, 70, 50), 0, 0.25);
                }
            if (Data.ShowLegend) DrawLegend(e, byUtil, dpi);
        }

        private void DrawLegend(DrawEventArgs e, bool byUtil, float dpi)
        {
            var r = Data.Result;
            var vp = e.Viewport.Bounds;
            int w = (int)(380 * dpi), h = (int)(300 * dpi);
            int x0 = vp.Width - w - (int)(30 * dpi), y0 = (int)(30 * dpi);
            double maxU = r.Elements.Where(x => !double.IsNaN(x.Utilization)).Select(x => x.Utilization).DefaultIfEmpty(double.NaN).Max();
            bool pass = r.MaxDisplacementMM <= Data.LimitMM && (double.IsNaN(maxU) || maxU <= 1.0);
            var accent = pass ? Color.FromArgb(40, 220, 90) : Color.FromArgb(233, 68, 43);
            e.Display.Draw2dRectangle(new Rectangle(x0, y0, w, h), Color.FromArgb(0, 0, 0, 0), 0, Color.FromArgb(215, 10, 10, 12));
            e.Display.Draw2dRectangle(new Rectangle(x0, y0, (int)(5 * dpi), h), Color.FromArgb(0, 0, 0, 0), 0, accent);
            int tx = x0 + (int)(24 * dpi);
            int fs = Math.Max(10, (int)(16 * dpi)), fb = Math.Max(14, (int)(30 * dpi));
            DrawTitle(e, accent, tx, y0 + 18 * dpi, w - (int)(40 * dpi), fs);
            e.Display.Draw2dText(byUtil ? "UTILIZATION" : "DISPLACEMENT", Color.White, new Point2d(tx, y0 + 50 * dpi), false, fs, "Consolas");
            e.Display.Draw2dText(string.Format("max δ {0:0.0} mm", r.MaxDisplacementMM), Color.White,
                new Point2d(tx, y0 + 76 * dpi), false, fb, "Arial Black");
            e.Display.Draw2dText(string.Format("limit L/{0:0} = {1:0.0} mm", Data.LimitRatio, Data.LimitMM), Color.FromArgb(200, 200, 205),
                new Point2d(tx, y0 + 122 * dpi), false, fs, "Consolas");
            if (!double.IsNaN(maxU))
                e.Display.Draw2dText(maxU > 10 ? "utilization > 10  (unstable)" : string.Format("utilization {0:0.00}", maxU), maxU > 1 ? Color.FromArgb(255, 120, 100) : Color.FromArgb(200, 200, 205),
                    new Point2d(tx, y0 + 146 * dpi), false, fs, "Consolas");
            e.Display.Draw2dText(Data.LoadLabel ?? string.Format("load {0:0} kN{1}  ·  {2}", Data.LoadKN, Data.SelfWeight ? " + self weight" : "", Data.Material),
                Color.FromArgb(200, 200, 205), new Point2d(tx, y0 + 170 * dpi), false, fs, "Consolas");
            e.Display.Draw2dText(pass ? "PASS" : "FAIL", pass ? Color.FromArgb(40, 220, 90) : Color.FromArgb(240, 40, 30),
                new Point2d(tx + 220 * dpi, y0 + 50 * dpi), false, fb, "Arial Black");
            // gradient bar
            int bx = tx, by = (int)(y0 + 206 * dpi), bw = w - (int)(48 * dpi), bh = (int)(16 * dpi);
            for (int i = 0; i < bw; i++)
                e.Display.Draw2dLine(new System.Drawing.Point(bx + i, by), new System.Drawing.Point(bx + i, by + bh), Ramp((double)i / bw), 1);
            string lo = byUtil ? "0" : "0 mm", hi = byUtil ? "1.0" : string.Format("{0:0.0} mm", r.MaxDisplacementMM);
            e.Display.Draw2dText(lo, Color.White, new Point2d(bx, by + bh + 16 * dpi), false, fs, "Consolas");
            var hiBox = e.Display.Measure2dText(hi, new Point2d(0, 0), false, 0, fs, "Consolas");
            e.Display.Draw2dText(hi, Color.White, new Point2d(bx + bw - hiBox.Width, by + bh + 16 * dpi), false, fs, "Consolas");
            e.Display.Draw2dText(string.Format("deformation shown x{0:0}", Data.Scale), Color.FromArgb(160, 160, 168),
                new Point2d(tx, by + bh + 44 * dpi), false, fs, "Consolas");
        }

        /// <summary>Legend title shrunk to fit the panel width (long stage/iteration titles).</summary>
        private void DrawTitle(DrawEventArgs e, Color c, int x, double y, int maxW, int fs)
        {
            int size = fs;
            while (size > 8 && e.Display.Measure2dText(Data.Title, new Point2d(0, 0), false, 0, size, "Consolas").Width > maxW) size--;
            e.Display.Draw2dText(Data.Title, c, new Point2d(x, y), false, size, "Consolas");
        }

        private void DrawOffLegend(DrawEventArgs e, float dpi, int shown, int n)
        {
            var vp = e.Viewport.Bounds;
            int w = (int)(380 * dpi), h = (int)(150 * dpi);
            int x0 = vp.Width - w - (int)(30 * dpi), y0 = (int)(30 * dpi), tx = x0 + (int)(24 * dpi);
            int fs = Math.Max(10, (int)(16 * dpi)), fb = Math.Max(14, (int)(30 * dpi));
            e.Display.Draw2dRectangle(new Rectangle(x0, y0, w, h), Color.FromArgb(0, 0, 0, 0), 0, Color.FromArgb(215, 10, 10, 12));
            e.Display.Draw2dRectangle(new Rectangle(x0, y0, (int)(5 * dpi), h), Color.FromArgb(0, 0, 0, 0), 0, Color.FromArgb(150, 150, 158));
            DrawTitle(e, Color.FromArgb(150, 150, 158), tx, y0 + 18 * dpi, w - (int)(40 * dpi), fs);
            e.Display.Draw2dText("PHYSICS OFF", Color.White, new Point2d(tx, y0 + 50 * dpi), false, fb, "Arial Black");
            e.Display.Draw2dText(string.Format("geometry only  ·  {0}/{1} members", shown, n), Color.FromArgb(200, 200, 205),
                new Point2d(tx, y0 + 100 * dpi), false, fs, "Consolas");
        }

        private static double[] Lerp(double[] a, double[] b, double t) =>
            new[] { a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t };

        private static double Len(double[] d) => Math.Sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2]);
    }
}
