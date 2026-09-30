//LIB
// PHYSICS section: drive the Almond structure view through phys_req/*.json and capture each state at 4K.
// Batched (BSTART..BEND file indices); existing captures are skipped, un-captured solves always run.
var OUT = @"C:\Users\liang\Documents\almond_promo\phys"; Directory.CreateDirectory(OUT);
var jpg = System.Drawing.Imaging.ImageCodecInfo.GetImageEncoders().First(c => c.MimeType == "image/jpeg");
var ep = new System.Drawing.Imaging.EncoderParameters(1); ep.Param[0] = new System.Drawing.Imaging.EncoderParameter(System.Drawing.Imaging.Encoder.Quality, 95L);
var lay = doc.Layers.FindName("A07 / 16 Structure"); lay.IsVisible = false; lay.CommitChanges();
var report = new StringBuilder();
var files = Directory.GetFiles(@"C:\Users\liang\Documents\almond_promo\phys_req", "*.json").OrderBy(x => x).ToList();
for (int fi = 0; fi < files.Count && fi < BEND; fi++) {
  var f = files[fi];
  var stem = Path.GetFileNameWithoutExtension(f);
  bool cap = !stem.EndsWith("__nocap");
  var name = stem.Substring(3).Replace("__nocap", "");
  var outFile = Path.Combine(OUT, name + ".jpg");
  if (cap && (fi < BSTART || File.Exists(outFile))) continue;
  var reply = SV(File.ReadAllText(f));
  report.AppendLine(name + "\t" + (reply.Length > 300 ? reply.Substring(0, 300) : reply));
  if (!cap) continue;
  doc.Views.Redraw(); RhinoApp.Wait();
  using (var bmp = VC().CaptureToBitmap(doc.Views.ActiveView)) bmp.Save(outFile, jpg, ep);
}
File.AppendAllText(Path.Combine(OUT, "report.tsv"), report.ToString());
log.AppendLine("batch done " + BSTART + "-" + BEND);
