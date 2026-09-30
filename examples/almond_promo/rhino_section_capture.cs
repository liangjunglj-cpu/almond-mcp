//LIB
// SECTION A-A (y = 5000, the frame line through the mid column): physics off -> on, then a camera move
// from the parallel section into the promo axon (clipping plane kept, full frame drawn from mid-move).
var OUT = @"C:\Users\liang\Documents\almond_promo\section"; Directory.CreateDirectory(OUT);
var jpg = System.Drawing.Imaging.ImageCodecInfo.GetImageEncoders().First(c => c.MimeType == "image/jpeg");
var ep = new System.Drawing.Imaging.EncoderParameters(1); ep.Param[0] = new System.Drawing.Imaging.EncoderParameter(System.Drawing.Imaging.Encoder.Quality, 95L);
var st = doc.Layers.FindName("A07 / 16 Structure"); st.IsVisible = false; st.CommitChanges();
var vp = doc.Views.ActiveView.ActiveViewport;
foreach (var c in doc.Objects.FindByObjectType(ObjectType.ClipPlane)) doc.Objects.Delete(c, true);
doc.Objects.AddClippingPlane(new Plane(new Point3d(6400, 5000, 3000), -Vector3d.XAxis, Vector3d.ZAxis), 40000, 30000, vp.Id);
vp.DisplayMode = DisplayModeDescription.FindByName("Almond | Apartment Day");

var cols = IDS("columns"); var beams = IDS("beams");
var supports = IDS("wall").Concat(IDS("bases")).ToList();
var edge = beams.Take(4).ToList(); var south = beams.Skip(4).Take(2).ToList(); var joists = beams.Skip(6).Take(6).ToList();
var north = beams.Skip(12).Take(2).ToList(); var stringer = beams.Skip(14).Take(4).ToList();
var build = cols.Concat(edge).Concat(south).Concat(north).Concat(joists).Concat(stringer).ToList();
var line = new List<string> { cols[1], joists[2], joists[3] };          // column (6600,5000) + joists at y = 5000
Func<List<string>, double, string, string> Req = (mem, load, extra) =>
  "{\"type\":\"structure_view\",\"guids\":" + JA(mem.Concat(supports)) + ",\"load_kn\":" + load +
  ",\"fixed_rotations\":false,\"span_m\":6.2,\"color_by\":\"utilization\",\"scale\":5,\"show_legend\":false," +
  "\"beam_diameter_mm\":114.3,\"beam_wall_mm\":4.0" + extra + "}";
var report = new StringBuilder();
Action<string> Cap = name => { doc.Views.Redraw(); RhinoApp.Wait();
  using (var bmp = VC().CaptureToBitmap(doc.Views.ActiveView)) bmp.Save(Path.Combine(OUT, name + ".jpg"), jpg, ep); };
Action<string, string> Shot = (name, req) => { var r = SV(req); report.AppendLine(name + "\t" + (r.Length > 300 ? r.Substring(0, 300) : r)); Cap(name); };

// parallel section camera: section spans ~x 80..1360 of a 1920 frame, y 260..890
vp.ChangeToParallelProjection(true);
vp.SetCameraLocations(new Point3d(8883, 5000, 3354), new Point3d(8883, -60000, 3354));
// ViewCapture keeps the vertical extent and widens to 16:9, so fix the vertical extent: 11170 mm -> 1080 px
double VSEC = 11170, asp = (double)vp.Size.Width / vp.Size.Height;
{ double l, r, b, t, n, f; vp.GetFrustum(out l, out r, out b, out t, out n, out f);
  var vi = new ViewportInfo(vp); vi.SetFrustum(-VSEC / 2 * asp, VSEC / 2 * asp, -VSEC / 2, VSEC / 2, n, f); vp.SetViewProjection(vi, true); }
SV("{\"type\":\"structure_view\",\"clear\":true}"); Cap("sec_off_0");
SV(Req(build, 150, ""));   // one solve; physics-off states only change the display
Shot("sec_off_1", Req(build, 150, ",\"reanalyze\":false,\"physics\":false,\"display_guids\":" + JA(new[] { line[0] })));
Shot("sec_off_2", Req(build, 150, ",\"reanalyze\":false,\"physics\":false,\"display_guids\":" + JA(line.Take(2))));
Shot("sec_off_3", Req(build, 150, ",\"reanalyze\":false,\"physics\":false,\"display_guids\":" + JA(line)));
var stages = new[] { cols.Concat(edge).ToList(), cols.Concat(edge).Concat(south).Concat(north).Concat(joists).ToList(), build };
for (int i = 0; i < stages.Length; i++)
  Shot("sec_stage" + (i + 1), Req(stages[i], Math.Round(150.0 * stages[i].Count / 20), ",\"display_guids\":" + JA(line)));
foreach (var L in new[] { 0.001, 25, 50, 75, 100, 125, 150 })
  Shot(string.Format("sec_load{0:000}", Math.Round(L)), Req(build, L, ",\"display_guids\":" + JA(line)));

// camera move: telephoto "section" -> promo axon (LENS 42), eased; the other members join half way
var T0 = new Point3d(8883, 5000, 3354); var T1 = new Point3d(6500, 4700, 2400);
var C1 = new Point3d(18900, -18100, 15100);
var d0 = -Vector3d.YAxis; var d1 = C1 - T1; double D1 = d1.Length; d1.Unitize();
double L0 = 600, L1 = 42;
vp.ChangeToPerspectiveProjection(true, 50);
// vertical extent at the target for a given lens, from Rhino's own frustum (per unit distance)
Func<double, double> VPerD = lens => { vp.Camera35mmLensLength = lens; vp.SetCameraLocations(T1, T1 + d1 * 10000);
  vp.Camera35mmLensLength = lens; double l, r, b, t, n, f; vp.GetFrustum(out l, out r, out b, out t, out n, out f); return (t - b) / n; };
double V0 = VSEC, V1 = VPerD(L1) * D1;
int N = 36;
for (int k = 0; k <= N; k++) {
  double t = (double)k / N; t = t < 0.5 ? 4 * t * t * t : 1 - Math.Pow(-2 * t + 2, 3) / 2;
  double ang = Vector3d.VectorAngle(d0, d1); var ax = Vector3d.CrossProduct(d0, d1); ax.Unitize();
  var dir = d0; dir.Rotate(ang * t, ax);
  double lens = Math.Exp(Math.Log(L0) + (Math.Log(L1) - Math.Log(L0)) * t);
  double V = Math.Exp(Math.Log(V0) + (Math.Log(V1) - Math.Log(V0)) * t);
  double D = V / VPerD(lens);
  var T = T0 + (T1 - T0) * t;
  vp.Camera35mmLensLength = lens;
  vp.SetCameraLocations(T, T + dir * D);
  vp.Camera35mmLensLength = lens;
  if (k == 0 || k == N / 2) SV(Req(build, 150, k == 0 ? ",\"display_guids\":" + JA(line) : ""));
  Cap(string.Format("tr_{0:00}", k));
}
File.WriteAllText(Path.Combine(OUT, "report.tsv"), report.ToString());
foreach (var c in doc.Objects.FindByObjectType(ObjectType.ClipPlane)) doc.Objects.Delete(c, true);
SV("{\"type\":\"structure_view\",\"clear\":true}");
doc.Modified = false;
log.AppendLine("section done");
