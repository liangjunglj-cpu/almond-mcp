using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading;
using Grasshopper.Kernel;
using Grasshopper.Kernel.Data;
using Grasshopper.Kernel.Types;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using Rhino;
using Rhino.Geometry;

namespace RhinoAlmondBridge
{
    // ── Capsule manifest model (mirrors capsules/capsule.schema.json) ────────

    public class CapsuleManifest
    {
        [JsonProperty("capsule_id")]
        public string CapsuleId { get; set; }

        [JsonProperty("version")]
        public int Version { get; set; } = 1;

        [JsonProperty("capability")]
        public string Capability { get; set; }

        /// <summary>Optional archetype key used by validate_structure (beam, truss, ...).</summary>
        [JsonProperty("structure_type")]
        public string StructureType { get; set; }

        [JsonProperty("plugin_dependencies")]
        public List<CapsulePluginDependency> PluginDependencies { get; set; }
            = new List<CapsulePluginDependency>();

        [JsonProperty("definition_file")]
        public string DefinitionFile { get; set; }

        [JsonProperty("title")]
        public string Title { get; set; }

        [JsonProperty("description_for_llm")]
        public string DescriptionForLlm { get; set; }

        [JsonProperty("inputs")]
        public List<CapsulePort> Inputs { get; set; } = new List<CapsulePort>();

        [JsonProperty("outputs")]
        public List<CapsulePort> Outputs { get; set; } = new List<CapsulePort>();

        [JsonProperty("binding")]
        public string Binding { get; set; } = "reserved_nicknames";

        [JsonProperty("confidence")]
        public string Confidence { get; set; } = "template";

        [JsonProperty("audited")]
        public bool Audited { get; set; }
    }

    public class CapsulePluginDependency
    {
        [JsonProperty("name")]
        public string Name { get; set; }

        [JsonProperty("min_version")]
        public string MinVersion { get; set; }
    }

    public class CapsulePort
    {
        [JsonProperty("name")]
        public string Name { get; set; }

        [JsonProperty("type")]
        public string Type { get; set; }

        [JsonProperty("units")]
        public string Units { get; set; }

        /// <summary>Schema default is true; only meaningful for inputs.</summary>
        [JsonProperty("required")]
        public bool Required { get; set; } = true;

        [JsonProperty("default")]
        public JToken Default { get; set; }

        [JsonProperty("semantics")]
        public string Semantics { get; set; }

        [JsonProperty("description")]
        public string Description { get; set; }
    }

    /// <summary>Result of a contract-bound definition run.</summary>
    public class DefinitionRunResult
    {
        public string Status { get; set; } = "error";   // "ok" | "error"
        public string CapsuleId { get; set; }
        public Dictionary<string, object> Outputs { get; set; }
            = new Dictionary<string, object>();
        public List<string> BakedGuids { get; set; } = new List<string>();
        public List<string> Warnings { get; set; } = new List<string>();
        public string Error { get; set; }
    }

    /// <summary>
    /// Contract-bound GHX execution for audited capsules. Inputs bind by EXACT
    /// NickName match on reserved ALMOND_IN_* params; outputs extract from
    /// ALMOND_OUT_* params typed per the manifest. No keyword scraping.
    /// Refuses manifests with audited == false.
    /// </summary>
    public class GhDefinitionRunner
    {
        private readonly string _libraryDir;   // Grasshopperfiles root (recursive search)
        private readonly string _capsuleDir;   // capsules/ folder with *.capsule.json

        public GhDefinitionRunner(string libraryDir, string capsuleDir)
        {
            _libraryDir = libraryDir;
            _capsuleDir = capsuleDir;
        }

        // ── Manifest loading / lookup ────────────────────────────────────────

        public static CapsuleManifest LoadManifest(string manifestPath, out string error)
        {
            error = null;
            try
            {
                if (string.IsNullOrEmpty(manifestPath) || !File.Exists(manifestPath))
                {
                    error = $"Manifest not found: {manifestPath}";
                    return null;
                }
                var manifest = JsonConvert.DeserializeObject<CapsuleManifest>(
                    File.ReadAllText(manifestPath));
                if (manifest == null || string.IsNullOrEmpty(manifest.CapsuleId) ||
                    string.IsNullOrEmpty(manifest.DefinitionFile))
                {
                    error = $"Manifest {manifestPath} is missing capsule_id or definition_file.";
                    return null;
                }
                return manifest;
            }
            catch (Exception ex)
            {
                error = $"Failed to parse manifest {manifestPath}: {ex.Message}";
                return null;
            }
        }

        /// <summary>Find the sidecar manifest for a capsule_id in the capsule dir.</summary>
        public string FindManifestPath(string capsuleId)
        {
            if (string.IsNullOrEmpty(_capsuleDir) || !Directory.Exists(_capsuleDir))
                return null;

            // Fast path: conventional <capsule_id>.capsule.json filename.
            string direct = Path.Combine(_capsuleDir, capsuleId + ".capsule.json");
            if (File.Exists(direct)) return direct;

            foreach (var path in Directory.GetFiles(_capsuleDir, "*.capsule.json",
                SearchOption.AllDirectories))
            {
                string err;
                var m = LoadManifest(path, out err);
                if (m != null && string.Equals(m.CapsuleId, capsuleId, StringComparison.Ordinal))
                    return path;
            }
            return null;
        }

        /// <summary>
        /// Enumerate all manifests, used by the orchestrator to find an audited
        /// capsule matching a structure_type.
        /// </summary>
        public IEnumerable<Tuple<string, CapsuleManifest>> EnumerateManifests()
        {
            if (string.IsNullOrEmpty(_capsuleDir) || !Directory.Exists(_capsuleDir))
                yield break;
            foreach (var path in Directory.GetFiles(_capsuleDir, "*.capsule.json",
                SearchOption.AllDirectories))
            {
                string err;
                var m = LoadManifest(path, out err);
                if (m != null)
                    yield return Tuple.Create(path, m);
            }
        }

        /// <summary>
        /// Resolve the GHX file: next to the manifest first (including a
        /// harnessed/ subfolder), then recursively under the library dir.
        /// </summary>
        public string FindDefinitionFile(CapsuleManifest manifest, string manifestPath)
        {
            string fileName = Path.GetFileName(manifest.DefinitionFile);

            string manifestDir = string.IsNullOrEmpty(manifestPath)
                ? null : Path.GetDirectoryName(manifestPath);
            if (manifestDir != null)
            {
                string local = Path.Combine(manifestDir, fileName);
                if (File.Exists(local)) return local;
                foreach (var f in Directory.GetFiles(manifestDir, fileName,
                    SearchOption.AllDirectories))
                    return f;
            }

            if (!string.IsNullOrEmpty(_libraryDir) && Directory.Exists(_libraryDir))
            {
                var hits = Directory.GetFiles(_libraryDir, fileName, SearchOption.AllDirectories);
                // Prefer harnessed copies (they carry the ALMOND_* params).
                var harnessed = hits.FirstOrDefault(h =>
                    h.IndexOf("harnessed", StringComparison.OrdinalIgnoreCase) >= 0);
                if (harnessed != null) return harnessed;
                if (hits.Length > 0) return hits[0];
            }
            return null;
        }

        // ── Execution ────────────────────────────────────────────────────────

        /// <summary>
        /// Run a capsule. inputs holds the payload-contract value forms:
        /// {"guids": [...]}, number, string, bool, [numbers].
        /// Must be called on the Rhino UI thread.
        /// </summary>
        public DefinitionRunResult Run(string manifestPath, JObject inputs,
            double timeoutSeconds, int? seed)
        {
            var result = new DefinitionRunResult();

            string loadError;
            var manifest = LoadManifest(manifestPath, out loadError);
            if (manifest == null)
            {
                result.Error = loadError;
                return result;
            }
            result.CapsuleId = manifest.CapsuleId;

            // Refuse unaudited capsules. Loud, by contract.
            if (!manifest.Audited)
            {
                result.Error = $"Capsule '{manifest.CapsuleId}' has audited=false. It is " +
                    "retrieval context only; run_definition refuses to execute it. Add the " +
                    "ALMOND_IN_*/ALMOND_OUT_* harness params in Grasshopper, verify a manual " +
                    "run, then set audited=true in the manifest.";
                return result;
            }

            string ghxPath = FindDefinitionFile(manifest, manifestPath);
            if (ghxPath == null)
            {
                result.Error = $"Definition file '{manifest.DefinitionFile}' for capsule " +
                    $"'{manifest.CapsuleId}' was not found near the manifest or in the library.";
                return result;
            }

            // Validate the supplied inputs against the manifest BEFORE opening GH.
            inputs = inputs ?? new JObject();
            var missingRequired = manifest.Inputs
                .Where(p => p.Required && inputs[p.Name] == null && p.Default == null)
                .Select(p => p.Name)
                .ToList();
            if (missingRequired.Count > 0)
            {
                result.Error = "Missing required input(s): " +
                    string.Join(", ", missingRequired) + ". No solve attempted.";
                return result;
            }

            foreach (var prop in inputs.Properties())
            {
                if (!manifest.Inputs.Any(p => p.Name == prop.Name))
                    result.Warnings.Add($"Input '{prop.Name}' is not declared in the " +
                        "manifest and was ignored.");
            }

            // Open the GHX.
            var io = new GH_DocumentIO();
            if (!io.Open(ghxPath))
            {
                result.Error = $"GH_DocumentIO could not open '{ghxPath}'.";
                return result;
            }
            var ghDoc = io.Document;
            if (ghDoc == null)
            {
                result.Error = $"GH_DocumentIO opened '{ghxPath}' but produced no document.";
                return result;
            }

            try
            {
                // Index every top-level param by exact NickName.
                var paramsByNick = new Dictionary<string, IGH_Param>(StringComparer.Ordinal);
                foreach (var obj in ghDoc.Objects)
                {
                    if (obj is IGH_Param p && !string.IsNullOrEmpty(p.NickName) &&
                        !paramsByNick.ContainsKey(p.NickName))
                        paramsByNick[p.NickName] = p;
                }

                // Every manifest input must have its harness param present.
                var unboundParams = new List<string>();
                foreach (var port in manifest.Inputs)
                {
                    bool supplied = inputs[port.Name] != null || port.Default != null;
                    if (!supplied) continue; // optional, no default: leave GHX value
                    if (!paramsByNick.ContainsKey(port.Name))
                    {
                        if (port.Required) unboundParams.Add(port.Name);
                        else result.Warnings.Add($"Optional input param '{port.Name}' not " +
                            "found in the definition; skipped.");
                    }
                }
                if (unboundParams.Count > 0)
                {
                    result.Error = "The definition has no params with these required " +
                        "NickNames: " + string.Join(", ", unboundParams) +
                        ". The capsule contract is broken; refusing to solve.";
                    return result;
                }

                // Bind inputs (manifest defaults fill unsupplied optional ports).
                foreach (var port in manifest.Inputs)
                {
                    JToken value = inputs[port.Name] ?? port.Default;
                    if (value == null) continue;
                    if (!paramsByNick.ContainsKey(port.Name)) continue;

                    var goos = ConvertInputValue(value, port, result.Warnings);
                    if (goos == null)
                    {
                        result.Error = $"Input '{port.Name}': could not convert supplied " +
                            $"value to declared type '{port.Type}'.";
                        return result;
                    }
                    BindParam(paramsByNick[port.Name], goos, result.Warnings);
                }

                // Optional seed: binds only when the definition carries ALMOND_IN_SEED.
                if (seed.HasValue)
                {
                    IGH_Param seedParam;
                    if (paramsByNick.TryGetValue("ALMOND_IN_SEED", out seedParam))
                        BindParam(seedParam,
                            new List<IGH_Goo> { new GH_Integer(seed.Value) },
                            result.Warnings);
                    else
                        result.Warnings.Add("Seed supplied but the definition has no " +
                            "ALMOND_IN_SEED param; seed ignored.");
                }

                // Solve silently with a best-effort timeout. The solve runs on
                // this (UI) thread; a background timer requests an abort when
                // the budget is exceeded.
                double budget = timeoutSeconds > 0 ? timeoutSeconds : 60.0;
                var sw = Stopwatch.StartNew();
                ghDoc.Enabled = true;

                using (var abortTimer = new Timer(
                    _ => { try { ghDoc.RequestAbortSolution(); } catch { } },
                    null, TimeSpan.FromSeconds(budget), TimeSpan.FromMilliseconds(-1)))
                {
                    ghDoc.NewSolution(true, GH_SolutionMode.Silent);
                }
                sw.Stop();

                // The abort timer fires exactly at the budget, so an elapsed
                // time beyond it means the solve ran long (aborted or not).
                if (sw.Elapsed.TotalSeconds > budget)
                {
                    result.Error = $"Definition solve exceeded the {budget:F0}s timeout " +
                        "and was aborted.";
                    return result;
                }

                // Surface component-level runtime errors loudly.
                foreach (var obj in ghDoc.Objects)
                {
                    if (!(obj is IGH_ActiveObject active)) continue;
                    foreach (var msg in active.RuntimeMessages(GH_RuntimeMessageLevel.Error))
                        result.Warnings.Add($"[GH error] {obj.NickName}: {msg}");
                    foreach (var msg in active.RuntimeMessages(GH_RuntimeMessageLevel.Warning))
                        result.Warnings.Add($"[GH warning] {obj.NickName}: {msg}");
                }

                // Extract outputs typed per the manifest.
                var missingOutputs = new List<string>();
                foreach (var port in manifest.Outputs)
                {
                    IGH_Param outParam;
                    if (!paramsByNick.TryGetValue(port.Name, out outParam))
                    {
                        missingOutputs.Add(port.Name);
                        continue;
                    }
                    result.Outputs[port.Name] = ExtractOutput(outParam, port, result);
                }
                if (missingOutputs.Count > 0)
                {
                    result.Error = "The definition has no params with these output " +
                        "NickNames: " + string.Join(", ", missingOutputs) +
                        ". The capsule contract is broken.";
                    return result;
                }

                result.Status = "ok";
                result.Error = null;
                return result;
            }
            catch (Exception ex)
            {
                result.Status = "error";
                result.Error = $"Definition run failed: {ex.Message}";
                return result;
            }
            finally
            {
                try { ghDoc.Dispose(); } catch { }
            }
        }

        // ── Input conversion (payload contract value forms) ──────────────────

        /// <summary>
        /// Convert one payload value into GH goo list per the declared port type.
        /// Forms: {"guids": [...]} resolve from RhinoDoc; raw number; string;
        /// bool; [numbers]. Returns null when conversion is impossible.
        /// </summary>
        private List<IGH_Goo> ConvertInputValue(JToken value, CapsulePort port,
            List<string> warnings)
        {
            string baseType = (port.Type ?? "number").Replace("[]", "");

            // GUID reference form.
            if (value.Type == JTokenType.Object && value["guids"] != null)
            {
                var doc = RhinoDoc.ActiveDoc;
                if (doc == null) return null;

                var goos = new List<IGH_Goo>();
                foreach (var g in (JArray)value["guids"])
                {
                    Guid guid;
                    if (!Guid.TryParse(g.ToString(), out guid))
                    {
                        warnings.Add($"Input '{port.Name}': malformed GUID '{g}'.");
                        continue;
                    }
                    var obj = doc.Objects.FindId(guid);
                    if (obj == null)
                    {
                        warnings.Add($"Input '{port.Name}': GUID {g} not in document.");
                        continue;
                    }
                    var goo = GeometryToGoo(obj.Geometry, baseType, warnings, port.Name);
                    if (goo != null) goos.AddRange(goo);
                }
                return goos.Count > 0 ? goos : null;
            }

            // Scalar / array forms.
            try
            {
                switch (baseType)
                {
                    case "number":
                        if (value.Type == JTokenType.Array)
                            return ((JArray)value)
                                .Select(t => (IGH_Goo)new GH_Number(t.Value<double>()))
                                .ToList();
                        return new List<IGH_Goo> { new GH_Number(value.Value<double>()) };

                    case "integer":
                        if (value.Type == JTokenType.Array)
                            return ((JArray)value)
                                .Select(t => (IGH_Goo)new GH_Integer(t.Value<int>()))
                                .ToList();
                        return new List<IGH_Goo> { new GH_Integer(value.Value<int>()) };

                    case "string":
                        if (value.Type == JTokenType.Array)
                            return ((JArray)value)
                                .Select(t => (IGH_Goo)new GH_String(t.Value<string>()))
                                .ToList();
                        return new List<IGH_Goo> { new GH_String(value.Value<string>()) };

                    case "bool":
                        return new List<IGH_Goo> { new GH_Boolean(value.Value<bool>()) };

                    case "point":
                        // Accept [x,y,z] arrays for point ports.
                        if (value.Type == JTokenType.Array && ((JArray)value).Count == 3)
                        {
                            var a = (JArray)value;
                            return new List<IGH_Goo>
                            {
                                new GH_Point(new Point3d(a[0].Value<double>(),
                                    a[1].Value<double>(), a[2].Value<double>()))
                            };
                        }
                        return null;

                    default:
                        // Geometry types must arrive as {"guids": [...]}.
                        warnings.Add($"Input '{port.Name}': type '{port.Type}' requires " +
                            "the {\"guids\": [...]} value form.");
                        return null;
                }
            }
            catch
            {
                return null;
            }
        }

        private List<IGH_Goo> GeometryToGoo(GeometryBase geom, string baseType,
            List<string> warnings, string portName)
        {
            var goos = new List<IGH_Goo>();
            switch (baseType)
            {
                case "curve":
                    if (geom is Curve c) goos.Add(new GH_Curve(c.DuplicateCurve()));
                    else if (geom is Brep cb)
                        foreach (var e in cb.Edges) goos.Add(new GH_Curve(e.DuplicateCurve()));
                    break;
                case "mesh":
                    if (geom is Mesh m) goos.Add(new GH_Mesh(m.DuplicateMesh()));
                    else if (geom is Brep mb)
                    {
                        var meshes = Mesh.CreateFromBrep(mb, MeshingParameters.FastRenderMesh);
                        if (meshes != null)
                        {
                            var joined = new Mesh();
                            foreach (var piece in meshes) joined.Append(piece);
                            goos.Add(new GH_Mesh(joined));
                        }
                    }
                    break;
                case "brep":
                    if (geom is Brep b) goos.Add(new GH_Brep(b.DuplicateBrep()));
                    else if (geom is Extrusion ex) goos.Add(new GH_Brep(ex.ToBrep()));
                    break;
                case "point":
                    if (geom is Rhino.Geometry.Point pt) goos.Add(new GH_Point(pt.Location));
                    break;
                default:
                    warnings.Add($"Input '{portName}': cannot map geometry to '{baseType}'.");
                    break;
            }
            if (goos.Count == 0)
                warnings.Add($"Input '{portName}': a referenced object did not yield " +
                    $"'{baseType}' geometry.");
            return goos;
        }

        // ── Param binding ────────────────────────────────────────────────────

        /// <summary>
        /// Write data into a floating GH param. Prefers PersistentData (survives
        /// full-expire solves); falls back to volatile injection.
        /// </summary>
        private void BindParam(IGH_Param param, List<IGH_Goo> goos, List<string> warnings)
        {
            try
            {
                // GH_PersistentParam<T>.PersistentData is a GH_Structure<T>;
                // clear it and append matching goos via reflection so this works
                // for every param type without a compile-time cast per type.
                var pdProp = param.GetType().GetProperty("PersistentData");
                if (pdProp != null)
                {
                    var structure = pdProp.GetValue(param);
                    if (structure != null)
                    {
                        var clear = structure.GetType().GetMethod("ClearData", Type.EmptyTypes)
                                 ?? structure.GetType().GetMethod("Clear", Type.EmptyTypes);
                        clear?.Invoke(structure, null);

                        var appendMethods = structure.GetType().GetMethods()
                            .Where(mm => mm.Name == "Append" &&
                                         mm.GetParameters().Length == 1)
                            .ToList();

                        bool allAppended = goos.Count > 0;
                        foreach (var goo in goos)
                        {
                            var append = appendMethods.FirstOrDefault(mm =>
                                mm.GetParameters()[0].ParameterType.IsInstanceOfType(goo));
                            if (append == null) { allAppended = false; break; }
                            append.Invoke(structure, new object[] { goo });
                        }

                        if (allAppended)
                        {
                            param.ExpireSolution(false);
                            return;
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                warnings.Add($"Persistent bind failed on '{param.NickName}' " +
                    $"({ex.Message}); using volatile data.");
            }

            // Volatile fallback: works when the solve does not re-expire params.
            param.ClearData();
            param.AddVolatileDataList(new GH_Path(0), goos);
        }

        // ── Output extraction ────────────────────────────────────────────────

        /// <summary>
        /// Extract one output param's data per the declared manifest type.
        /// Numbers/strings/bools come back as JSON-ready values; geometry is
        /// baked into the active document and returned as GUID strings (which
        /// also land in BakedGuids).
        /// </summary>
        private object ExtractOutput(IGH_Param param, CapsulePort port,
            DefinitionRunResult result)
        {
            string baseType = (port.Type ?? "number").Replace("[]", "");
            bool isList = (port.Type ?? "").EndsWith("[]");

            var items = new List<IGH_Goo>();
            var data = param.VolatileData;
            if (data != null && !data.IsEmpty)
            {
                foreach (var item in data.AllData(true))
                    if (item != null) items.Add(item);
            }

            if (items.Count == 0)
            {
                result.Warnings.Add($"Output '{port.Name}' produced no data.");
                return isList ? (object)new List<object>() : null;
            }

            switch (baseType)
            {
                case "number":
                {
                    var vals = new List<double>();
                    foreach (var goo in items)
                    {
                        double d;
                        if (GH_Convert.ToDouble(goo, out d, GH_Conversion.Both))
                            vals.Add(d);
                    }
                    return isList ? (object)vals : (vals.Count > 0 ? (object)vals[0] : null);
                }
                case "integer":
                {
                    var vals = new List<int>();
                    foreach (var goo in items)
                    {
                        int v;
                        if (GH_Convert.ToInt32(goo, out v, GH_Conversion.Both))
                            vals.Add(v);
                    }
                    return isList ? (object)vals : (vals.Count > 0 ? (object)vals[0] : null);
                }
                case "string":
                {
                    var vals = new List<string>();
                    foreach (var goo in items)
                    {
                        string s;
                        if (GH_Convert.ToString(goo, out s, GH_Conversion.Both))
                            vals.Add(s);
                    }
                    return isList ? (object)vals : (vals.Count > 0 ? (object)vals[0] : null);
                }
                case "bool":
                {
                    var vals = new List<bool>();
                    foreach (var goo in items)
                    {
                        bool bl;
                        if (GH_Convert.ToBoolean(goo, out bl, GH_Conversion.Both))
                            vals.Add(bl);
                    }
                    return isList ? (object)vals : (vals.Count > 0 ? (object)vals[0] : null);
                }
                case "point":
                {
                    var vals = new List<double[]>();
                    foreach (var goo in items)
                    {
                        Point3d p = Point3d.Unset;
                        if (GH_Convert.ToPoint3d(goo, ref p, GH_Conversion.Both))
                            vals.Add(new[] { p.X, p.Y, p.Z });
                    }
                    return isList ? (object)vals : (vals.Count > 0 ? (object)vals[0] : null);
                }
                case "curve":
                case "mesh":
                case "brep":
                {
                    // Geometry outputs are baked; the outputs dict carries the
                    // new GUIDs and they are echoed in baked_guids.
                    var doc = RhinoDoc.ActiveDoc;
                    var baked = new List<string>();
                    if (doc != null)
                    {
                        foreach (var goo in items)
                        {
                            Guid id = BakeGoo(doc, goo);
                            if (id != Guid.Empty)
                            {
                                string s = id.ToString();
                                baked.Add(s);
                                result.BakedGuids.Add(s);
                            }
                        }
                        if (baked.Count > 0) doc.Views.Redraw();
                    }
                    if (baked.Count == 0)
                        result.Warnings.Add($"Output '{port.Name}': no geometry could " +
                            "be baked.");
                    return isList ? (object)baked
                                  : (baked.Count > 0 ? (object)baked[0] : null);
                }
                default:
                    result.Warnings.Add($"Output '{port.Name}': unsupported declared " +
                        $"type '{port.Type}'; returning string form.");
                    return items.Select(g => g.ToString()).ToList();
            }
        }

        private Guid BakeGoo(RhinoDoc doc, IGH_Goo goo)
        {
            try
            {
                Curve crv = null;
                if (GH_Convert.ToCurve(goo, ref crv, GH_Conversion.Both) && crv != null)
                    return doc.Objects.AddCurve(crv);

                Mesh mesh = null;
                if (GH_Convert.ToMesh(goo, ref mesh, GH_Conversion.Both) && mesh != null)
                    return doc.Objects.AddMesh(mesh);

                Brep brep = null;
                if (GH_Convert.ToBrep(goo, ref brep, GH_Conversion.Both) && brep != null)
                    return doc.Objects.AddBrep(brep);

                Point3d pt = Point3d.Unset;
                if (GH_Convert.ToPoint3d(goo, ref pt, GH_Conversion.Both))
                    return doc.Objects.AddPoint(pt);
            }
            catch { }
            return Guid.Empty;
        }
    }
}
