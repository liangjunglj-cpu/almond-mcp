var __h = typeof(RhinoAlmondBridge.StructureView).GetMethod("Handle");
var __parse = __h.GetParameters()[0].ParameterType.GetMethod("Parse", new[] { typeof(string) });
Func<string, string> SV = json => (string)__h.Invoke(null, new[] { __parse.Invoke(null, new object[] { json }) });
Func<Rhino.Display.ViewCapture> VC = () => new Rhino.Display.ViewCapture { Width = 3840, Height = 2160, ScaleScreenItems = false, DrawAxes = false, DrawGrid = false, DrawGridAxes = false, TransparentBackground = false };
var FRAME = File.ReadAllText(@"C:\Users\liang\Documents\almond_promo\frame_ids.json");
Func<string, List<string>> IDS = key => { var m = System.Text.RegularExpressions.Regex.Match(FRAME, "\"" + key + @""": \[([^\]]*)\]"); return System.Text.RegularExpressions.Regex.Matches(m.Groups[1].Value, "[0-9a-f-]{36}").Cast<System.Text.RegularExpressions.Match>().Select(x => x.Value).ToList(); };
Func<IEnumerable<string>, string> JA = xs => "[" + string.Join(",", xs.Select(x => "\"" + x + "\"")) + "]";
