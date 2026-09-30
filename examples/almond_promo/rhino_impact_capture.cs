//LIB
// IMPACT: the bedroom wing as built WITHOUT simulation (CHS 114.3x4) vs WITH Almond + Karamba (CHS 193.7x8).
// For each design and load step: Karamba solve -> nodal displacement field -> bend the real mezzanine
// geometry by that field (x SCALE, same as the frame overlay) -> 4K capture -> restore.
var OUT = @"C:\Users\liang\Documents\almond_promo\impact"; Directory.CreateDirectory(OUT);
var jpg = System.Drawing.Imaging.ImageCodecInfo.GetImageEncoders().First(c => c.MimeType == "image/jpeg");
var ep = new System.Drawing.Imaging.EncoderParameters(1); ep.Param[0] = new System.Drawing.Imaging.EncoderParameter(System.Drawing.Imaging.Encoder.Quality, 95L);
const double SCALE = 5.0;
foreach (var c in doc.Objects.FindByObjectType(ObjectType.ClipPlane)) doc.Objects.Delete(c, true);
var st = doc.Layers.FindName("A07 / 16 Structure"); st.IsVisible = false; st.CommitChanges();
var light = doc.Layers.FindName("A07 / 15 Lighting");
var all = IDS("beams").Concat(IDS("columns")).Concat(IDS("wall")).Concat(IDS("bases")).ToList();

// mezzanine (bedroom wing) objects carried by the frame
var mezz = doc.Objects.Where(o => o.Visible && o.ObjectType != ObjectType.ClipPlane && o.Attributes.LayerIndex != st.Index
    && (light == null || o.Attributes.LayerIndex != light.Index)).Where(o => {
  var bb = o.Geometry.GetBoundingBox(true); var c = bb.Center;
  return bb.Min.Z >= 2900 && c.X >= 6650 && c.X <= 12800 && c.Y >= 0 && c.Y <= 10000; }).ToList();
var mp = MeshingParameters.Default; mp.MaximumEdgeLength = 250; mp.SimplePlanes = false;
var meshes = new Dictionary<Guid, Mesh>();
foreach (var o in mezz) {
  Mesh m = null;
  if (o.Geometry is Mesh gm) m = gm.DuplicateMesh();
  else {
    Brep b = o.Geometry as Brep ?? (o.Geometry as Extrusion)?.ToBrep();
    if (b != null) { var ms = Mesh.CreateFromBrep(b, mp); if (ms != null && ms.Length > 0) { m = new Mesh(); foreach (var x in ms) m.Append(x); } }
  }
  if (m != null) meshes[o.Id] = m;
}
log.AppendLine("mezzanine objects " + mezz.Count + ", meshed " + meshes.Count);

// bilinear field over the frame grid (nodes above 1 m); mm in, mm displacement out (x SCALE)
Func<List<double[]>, Func<double, double, Vector3d>> Field = nodes => {
  var top = nodes.Where(n => n[2] > 1.0).ToList();
  var xs = top.Select(n => Math.Round(n[0] * 1000)).Distinct().OrderBy(v => v).ToArray();
  var ys = top.Select(n => Math.Round(n[1] * 1000)).Distinct().OrderBy(v => v).ToArray();
  var grid = new Dictionary<string, Vector3d>();
  foreach (var n in top) grid[Math.Round(n[0] * 1000) + "," + Math.Round(n[1] * 1000)] = new Vector3d(n[3], n[4], n[5]) * 1000 * SCALE;
  Func<double[], double, int> Seg = (arr, v) => { int i = 0; while (i < arr.Length - 2 && v > arr[i + 1]) i++; return i; };
  return (x, y) => {
    x = Math.Max(xs[0], Math.Min(xs[xs.Length - 1], x)); y = Math.Max(ys[0], Math.Min(ys[ys.Length - 1], y));
    int i = Seg(xs, x), j = Seg(ys, y);
    double u = (x - xs[i]) / (xs[i + 1] - xs[i]), v = (y - ys[j]) / (ys[j + 1] - ys[j]);
    Func<int, int, Vector3d> G = (a, b) => { Vector3d d; return grid.TryGetValue(xs[a] + "," + ys[b], out d) ? d : Vector3d.Zero; };
    return G(i, j) * (1 - u) * (1 - v) + G(i + 1, j) * u * (1 - v) + G(i, j + 1) * (1 - u) * v + G(i + 1, j + 1) * u * v;
  };
};

var designs = new[] { new { key = "without", d = 114.3, w = 4.0 }, new { key = "with", d = 193.7, w = 8.0 } };
var loads = new[] { 0.001, 50.0, 100.0, 150.0 };
var cond = new RhinoAlmondBridge.ModelConditioner().Condition(doc, all);
var report = new StringBuilder();
foreach (var ds in designs) foreach (var L in loads) {
  foreach (var bm in cond.Beams) bm.Section = new RhinoAlmondBridge.SectionSpec { Shape = "circular_hollow", Source = "user", Diameter = ds.d, WallThickness = ds.w };
  var res = RhinoAlmondBridge.KarambaAdapter.BuildAndAnalyze(new RhinoAlmondBridge.KarambaModelSpec {
    Conditioned = cond, MaterialName = "Steel", ImposedLoadKN = L, IncludeSelfWeight = true, FixedRotations = false, ReturnGeometry = false });
  var F = Field(res.NodeDispM);
  var made = new List<Guid>();
  foreach (var o in mezz) {
    if (o.ObjectType == ObjectType.InstanceReference) {
      var c = o.Geometry.GetBoundingBox(true).Center; double h = 400;
      var d = F(c.X, c.Y);
      double dzdx = (F(c.X + h, c.Y).Z - F(c.X - h, c.Y).Z) / (2 * h), dzdy = (F(c.X, c.Y + h).Z - F(c.X, c.Y - h).Z) / (2 * h);
      var xf = Transform.Translation(d) * Transform.Rotation(Vector3d.ZAxis, new Vector3d(-dzdx, -dzdy, 1), c);
      var id = doc.Objects.Transform(o.Id, xf, false); if (id != Guid.Empty) made.Add(id);
    } else if (meshes.ContainsKey(o.Id)) {
      var m = meshes[o.Id].DuplicateMesh();
      for (int i = 0; i < m.Vertices.Count; i++) { var p = m.Vertices[i]; var d = F(p.X, p.Y); m.Vertices.SetVertex(i, p.X + d.X, p.Y + d.Y, p.Z + d.Z); }
      m.Normals.ComputeNormals();
      made.Add(doc.Objects.AddMesh(m, o.Attributes.Duplicate()));
    }
    doc.Objects.Hide(o.Id, true);
  }
  var reply = SV("{\"type\":\"structure_view\",\"guids\":" + JA(all) + ",\"load_kn\":" + L + ",\"fixed_rotations\":false,\"span_m\":6.2,\"color_by\":\"utilization\",\"scale\":" + SCALE + ",\"show_legend\":false,\"beam_diameter_mm\":" + ds.d + ",\"beam_wall_mm\":" + ds.w + "}");
  doc.Views.Redraw(); RhinoApp.Wait();
  var name = string.Format("{0}_{1:000}", ds.key, Math.Round(L));
  using (var bmp = VC().CaptureToBitmap(doc.Views.ActiveView)) bmp.Save(Path.Combine(OUT, name + ".jpg"), jpg, ep);
  report.AppendLine(name + "\t" + (reply.Length > 300 ? reply.Substring(0, 300) : reply));
  foreach (var id in made) doc.Objects.Delete(id, true);
  foreach (var o in mezz) doc.Objects.Show(o.Id, true);
}
File.WriteAllText(Path.Combine(OUT, "report.tsv"), report.ToString());
doc.Modified = false;
log.AppendLine("impact done");
