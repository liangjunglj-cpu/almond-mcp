using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;
using Rhino;
using Rhino.Commands;
using Rhino.DocObjects;
using Rhino.Input;
using Rhino.Input.Custom;

namespace RhinoAlmondBridge
{
    /// <summary>
    /// The Environment workspace of the Almond panel: site (EPW), rooms, constructions, study and results.
    /// Rooms and constructions are user text on Rhino objects (almond:room, almond:construction ...), written here
    /// with one undo record per action. Analyses run out of process (<c>almond-mcp environment</c>, see
    /// NativeSolver): the export and draw scripts come from the Python package, so the panel and the MCP tools
    /// share one implementation.
    /// </summary>
    internal sealed class EnvironmentWorkspace
    {
        private static readonly Regex Id = new Regex("^[a-z0-9_]{1,64}$");
        private static readonly string[] RoomKeys = { "room", "room_use", "room_set", "room_heat_c", "room_cool_c", "room_height" };
        private static readonly Regex RunId = new Regex("^[a-z]{2,16}-[0-9]{8}-[0-9]{6}-[0-9a-f]{6}$");
        private static readonly HashSet<string> Studies = new HashSet<string> { "thermal", "daylight", "view_out", "sunlight", "shadows" };
        private readonly Action<JObject> _send;
        private static Action<RhinoDoc> _pending;
        internal bool Busy { get; private set; }
        private string _epw = "";

        internal EnvironmentWorkspace(Action<JObject> send) { _send = send; }

        internal void Request(string action, string json)
        {
            if (Busy) { Send("error", "The environment workspace is still working. Wait for it to finish."); return; }
            JObject input;
            try { input = string.IsNullOrWhiteSpace(json) ? new JObject() : JObject.Parse(json); }
            catch (Exception ex) { Send("error", "Bad request: " + ex.Message); return; }
            try { if (EngineRequest(action, input)) return; }
            catch (InvalidOperationException ex) { Send("error", ex.Message); return; }
            if (Rhino.Commands.Command.InCommand()) { Send("error", "Finish the current Rhino command first."); return; }
            Busy = true;
            Eto.Forms.Application.Instance.AsyncInvoke(() => {
                try
                {
                    _pending = doc => Execute(doc, action, input);
                    RhinoApp.RunScript("_AlmondEnvironmentAction", false);
                    if (_pending != null) { _pending = null; Busy = false; Send("error", "Rhino was busy. Try again."); }
                }
                catch (Exception ex) { Busy = false; Send("error", ex.Message); }
            });
        }

        // Requests the engine answers without the document. Returns false for document actions.
        private bool EngineRequest(string action, JObject input)
        {
            switch (action)
            {
                case "catalogue": Engine(new JObject { ["action"] = "catalogue" }, "catalogue"); return true;
                case "construction":
                    if (!Id.IsMatch((string)input["id"] ?? "")) { Send("error", "Pick a construction from the list."); return true; }
                    Engine(new JObject { ["action"] = "construction", ["id"] = input["id"] }, "construction"); return true;
                case "browse_epw": BrowseEpw(); return true;
                case "site":
                    _epw = (string)input["epw_path"] ?? _epw;
                    if (!File.Exists(_epw)) { Send("error", "Choose an EnergyPlus weather file (.epw) first."); return true; }
                    Engine(new JObject { ["action"] = "site", ["epw_path"] = _epw }, "site"); return true;
                case "climate":
                    if (!File.Exists(_epw)) { Send("error", "Choose an EnergyPlus weather file (.epw) first."); return true; }
                    Engine(new JObject { ["action"] = "climate", ["epw_path"] = _epw }, "climate"); return true;
                case "setpoints":
                    {
                        var req = new JObject { ["action"] = "setpoints", ["category"] = Category(input["category"]) };
                        foreach (var k in new[] { "met", "clo_heating", "clo_cooling", "rh", "air_speed" }) req[k] = Number(input[k]);
                        Engine(req, "setpoints"); return true;
                    }
                case "charts":
                    if (!RunId.IsMatch((string)input["run_id"] ?? "") || !File.Exists(_epw)) { Send("error", "Run a thermal study first."); return true; }
                    Engine(new JObject { ["action"] = "charts", ["run_id"] = input["run_id"], ["epw_path"] = _epw, ["room"] = Clean(input["room"]) }, "charts"); return true;
                case "compare":
                    {
                        var kept = new JArray();
                        foreach (var c in (input["cases"] as JArray) ?? new JArray())
                        {
                            if (!RunId.IsMatch((string)c["run_id"] ?? "")) { Send("error", "A kept case has no valid run."); return true; }
                            kept.Add(new JObject { ["name"] = Clean(c["name"], 40), ["run_id"] = c["run_id"] });
                        }
                        Engine(new JObject { ["action"] = "compare", ["cases"] = kept, ["room"] = Clean(input["room"]),
                            ["epw_path"] = File.Exists(_epw) ? _epw : "" }, "compare"); return true;
                    }
                case "open_folder":
                    if (!RunId.IsMatch((string)input["run_id"] ?? "")) { Send("error", "Run a study first."); return true; }
                    Engine(new JObject { ["action"] = "run_dir", ["run_id"] = input["run_id"] }, "notice", reply => {
                        string dir = (string)reply["run_dir"] ?? "";
                        if (!Directory.Exists(dir)) { Send("error", "The run folder is gone."); return; }
                        System.Diagnostics.Process.Start("explorer.exe", "\"" + dir + "\"");
                        Send("notice", "Opened " + dir);
                    }); return true;
            }
            return false;
        }

        internal static Result Run(RhinoDoc doc)
        {
            var action = _pending; _pending = null;
            if (action == null) return Result.Cancel;
            action(doc);
            return Result.Success;
        }

        private void Send(string kind, string message) => _send(new JObject { ["kind"] = kind, ["message"] = message });

        private static string Category(JToken t)
        {
            string c = ((string)t ?? "II").Trim();
            if (c != "I" && c != "II" && c != "III" && c != "IV") throw new InvalidOperationException("Pick a comfort category.");
            return c;
        }

        // Engine calls that need no document: run out of process and answer when done (to the panel, or to
        // `then` when the reply is for the workspace itself).
        private void Engine(JObject request, string kind, Action<JObject> then = null)
        {
            Busy = true;
            _send(new JObject { ["kind"] = "progress", ["message"] = "Working…" });
            Task.Run(async () => {
                JObject reply;
                try { reply = await NativeSolver.RunAsync(request, 120000, "environment").ConfigureAwait(false); }
                catch (Exception ex) { reply = new JObject { ["status"] = "error", ["message"] = ex.Message }; }
                Eto.Forms.Application.Instance.AsyncInvoke(() => {
                    Busy = false;
                    if ((string)reply["status"] != "ok") { Send("error", (string)reply["message"] ?? "The environment engine failed."); return; }
                    if (then != null)
                    {
                        try { then(reply); } catch (Exception ex) { Send("error", ex.Message); }
                        return;
                    }
                    reply["kind"] = kind;
                    _send(reply);
                });
            });
        }

        private void BrowseEpw()
        {
            var dialog = new Eto.Forms.OpenFileDialog { Title = "EnergyPlus weather file" };
            dialog.Filters.Add(new Eto.Forms.FileFilter("EnergyPlus weather (*.epw)", ".epw"));
            if (dialog.ShowDialog(Rhino.UI.RhinoEtoApp.MainWindow) != Eto.Forms.DialogResult.Ok) { Send("notice", "No weather file chosen."); return; }
            _epw = dialog.FileName;
            _send(new JObject { ["kind"] = "epw", ["epw_path"] = _epw });
            Engine(new JObject { ["action"] = "site", ["epw_path"] = _epw }, "site");
        }

        // Document actions run inside the AlmondEnvironmentAction command.
        private void Execute(RhinoDoc doc, string action, JObject input)
        {
            bool async = false;
            try
            {
                switch (action)
                {
                    case "define_room": DefineRoom(doc, input); break;
                    case "remove_room": Tag(doc, Pick(doc, "Select room objects to clear"), RoomKeys.ToDictionary(k => k, k => ""), "Almond: remove room"); Send("notice", "Room tags removed."); break;
                    case "assign": Assign(doc, input); break;
                    case "clear_construction": Tag(doc, Pick(doc, "Select elements to clear"), new Dictionary<string, string> { ["construction"] = "" }, "Almond: clear construction"); Send("notice", "Constructions cleared."); break;
                    case "select_room": SelectRoom(doc, (string)input["room"] ?? ""); break;
                    case "clear_view": ClearView(doc); break;
                    case "rooms": async = true; Export(doc, data => Engine(new JObject { ["action"] = "rooms", ["export"] = data }, "rooms")); break;
                    case "run": async = true; RunStudy(doc, input); break;
                    default: Send("error", "Unknown action " + action); break;
                }
            }
            catch (Exception ex) { Send("error", ex.Message); }
            finally { if (!async) Busy = false; }
        }

        private static List<RhinoObject> Pick(RhinoDoc doc, string prompt)
        {
            var selected = doc.Objects.GetSelectedObjects(false, false).ToList();
            if (selected.Count > 0) return selected;
            using (var get = new GetObject())
            {
                get.SetCommandPrompt(prompt);
                get.SubObjectSelect = false;
                if (get.GetMultiple(1, 0) != GetResult.Object) throw new InvalidOperationException("Selection cancelled.");
                return get.Objects().Select(r => r.Object()).ToList();
            }
        }

        private static void Tag(RhinoDoc doc, List<RhinoObject> objects, Dictionary<string, string> tags, string undo)
        {
            uint record = doc.BeginUndoRecord(undo);
            try
            {
                foreach (var o in objects)
                {
                    var attr = o.Attributes.Duplicate();
                    foreach (var kv in tags)
                        if (string.IsNullOrEmpty(kv.Value)) attr.DeleteUserString("almond:" + kv.Key);
                        else attr.SetUserString("almond:" + kv.Key, kv.Value);
                    doc.Objects.ModifyAttributes(o, attr, true);
                }
            }
            finally { doc.EndUndoRecord(record); }
            doc.Views.Redraw();
        }

        private static string Clean(JToken t, int max = 60)
        {
            string s = ((string)t ?? "").Trim();
            if (s.Length > max || s.IndexOfAny(new[] { '"', '\\', '\n', '\r' }) >= 0) throw new InvalidOperationException("Use plain text of up to " + max + " characters.");
            return s;
        }

        private void DefineRoom(RhinoDoc doc, JObject input)
        {
            string name = Clean(input["name"]);
            if (name.Length == 0) throw new InvalidOperationException("Name the room first.");
            string use = Clean(input["use"]);
            string set = Clean(input["construction_set"]);
            if (use.Length > 0 && !Id.IsMatch(use)) throw new InvalidOperationException("Pick a room use from the list.");
            if (set.Length > 0 && !Id.IsMatch(set)) throw new InvalidOperationException("Pick a construction set from the list.");
            var objects = Pick(doc, "Select the room's volume, bounding surfaces, or boundary curve");
            var tags = new Dictionary<string, string> { ["room"] = name, ["room_use"] = use, ["room_set"] = set,
                ["room_heat_c"] = Number(input["heating_setpoint_c"]), ["room_cool_c"] = Number(input["cooling_setpoint_c"]),
                ["room_height"] = Number(input["height_m"]) };
            if (objects.Any(o => o.Geometry is Rhino.Geometry.Curve) && tags["room_height"].Length == 0)
                throw new InvalidOperationException("A boundary curve needs a room height.");
            Tag(doc, objects, tags, "Almond: define room " + name);
            _send(new JObject { ["kind"] = "notice", ["message"] = $"Room {name}: {objects.Count} object(s) tagged.", ["refresh"] = "rooms" });
        }

        private static string Number(JToken t)
        {
            if (t == null || t.Type == JTokenType.Null) return "";
            string s = ((string)t ?? "").Trim();
            if (s.Length == 0) return "";
            if (!double.TryParse(s, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out double v) || double.IsNaN(v) || Math.Abs(v) > 1000)
                throw new InvalidOperationException("Set-points and heights must be numbers.");
            return v.ToString("R", System.Globalization.CultureInfo.InvariantCulture);
        }

        private void Assign(RhinoDoc doc, JObject input)
        {
            string id = (string)input["construction"] ?? "";
            if (!Id.IsMatch(id)) throw new InvalidOperationException("Pick a construction from the list.");
            var objects = Pick(doc, "Select walls, slabs, roofs or windows for " + id);
            Tag(doc, objects, new Dictionary<string, string> { ["construction"] = id }, "Almond: construction " + id);
            Send("notice", $"{id} assigned to {objects.Count} element(s).");
        }

        private void SelectRoom(RhinoDoc doc, string room)
        {
            doc.Objects.UnselectAll();
            int n = 0;
            foreach (var o in doc.Objects.GetObjectList(new ObjectEnumeratorSettings { HiddenObjects = false }))
                if (o.Attributes.GetUserString("almond:room") == room) { o.Select(true); n++; }
            doc.Views.Redraw();
            Send("notice", n > 0 ? $"Selected {n} object(s) of {room}." : $"No objects tagged {room}.");
        }

        private void ClearView(RhinoDoc doc)
        {
            int n = 0;
            foreach (var l in doc.Layers)
            {
                if (l.IsDeleted || !l.FullPath.StartsWith("Almond::Environment::Panel", StringComparison.OrdinalIgnoreCase)) continue;
                foreach (var o in doc.Objects.FindByLayer(l)) { doc.Objects.Delete(o, true); n++; }
            }
            doc.Views.Redraw();
            Send("notice", n > 0 ? "Viewport results cleared." : "Nothing to clear.");
        }

        private static string Temp(string ext)
        {
            string dir = Path.Combine(System.Environment.GetFolderPath(System.Environment.SpecialFolder.LocalApplicationData), "Almond", "environment", "panel");
            Directory.CreateDirectory(dir);
            return Path.Combine(dir, Guid.NewGuid().ToString("N") + ext);
        }

        // Export every visible object with the package's own export script, then continue with the JSON.
        private void Export(RhinoDoc doc, Action<JObject> next)
        {
            string outPath = Temp(".json");
            _send(new JObject { ["kind"] = "progress", ["message"] = "Exporting the model…" });
            Task.Run(async () => {
                var reply = await NativeSolver.RunAsync(new JObject { ["action"] = "export_script", ["guids"] = new JArray(), ["out"] = outPath },
                                                        120000, "environment").ConfigureAwait(false);
                Eto.Forms.Application.Instance.AsyncInvoke(() => {
                    try
                    {
                        if ((string)reply["status"] != "ok") throw new InvalidOperationException((string)reply["message"] ?? "Export failed.");
                        var result = new ScriptExecutor().Execute((string)reply["script"]);
                        if (result.Status != "success") throw new InvalidOperationException("Export: " + result.Message);
                        var data = JObject.Parse(File.ReadAllText(outPath));
                        next(data);
                    }
                    catch (Exception ex) { Busy = false; Send("error", ex.Message); }
                    finally { try { File.Delete(outPath); } catch { } }
                });
            });
        }

        private void RunStudy(RhinoDoc doc, JObject input)
        {
            string study = (string)input["study"] ?? "thermal";
            if (!Studies.Contains(study)) throw new InvalidOperationException("Pick a study.");
            if (!File.Exists(_epw) && study != "daylight" && study != "view_out") throw new InvalidOperationException("Choose a weather file on the Site tab first.");
            Export(doc, data => {
                string drawPath = Temp(".txt");
                var request = new JObject { ["action"] = "run", ["export"] = data, ["epw_path"] = _epw, ["study"] = input["study"] ?? "thermal",
                    ["settings"] = input["settings"] ?? new JObject(), ["envelope_pack"] = input["envelope_pack"] ?? "",
                    ["pack_options"] = input["pack_options"] ?? new JObject(), ["draw_path"] = drawPath };
                _send(new JObject { ["kind"] = "progress", ["message"] = "Simulating the rooms…" });
                Task.Run(async () => {
                    var reply = await NativeSolver.RunAsync(request, 1800000, "environment").ConfigureAwait(false);
                    Eto.Forms.Application.Instance.AsyncInvoke(() => {
                        Busy = false;
                        try
                        {
                            if ((string)reply["status"] != "ok") { Send("error", (string)reply["message"] ?? "The study failed."); return; }
                            if (reply["draw_script"] is JValue script && File.Exists(drawPath))
                            {
                                var drawn = new ScriptExecutor().Execute((string)script);
                                reply["drawn"] = drawn.Status == "success";
                                if (drawn.Status != "success") reply["draw_error"] = drawn.Message;
                            }
                            reply.Remove("draw_script");
                            reply["kind"] = "result";
                            _send(reply);
                        }
                        catch (Exception ex) { Send("error", ex.Message); }
                        finally { try { File.Delete(drawPath); } catch { } }
                    });
                });
            });
        }
    }

    public sealed class AlmondEnvironmentActionCommand : Command
    {
        public override string EnglishName => "AlmondEnvironmentAction";
        protected override Result RunCommand(RhinoDoc doc, RunMode mode) => EnvironmentWorkspace.Run(doc);
    }

    public sealed class AlmondEnvironmentCommand : Command
    {
        public override string EnglishName => "AlmondEnvironment";
        protected override Result RunCommand(RhinoDoc doc, RunMode mode)
        {
            try { AlmondLibraryCommand.OpenPanel(doc, "environment"); return Result.Success; }
            catch (Exception ex) { RhinoApp.WriteLine(ex.Message); return Result.Failure; }
        }
    }
}
