using System;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Linq;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using Rhino;
using Rhino.Display;
using Rhino.DocObjects;
using Rhino.Geometry;

namespace RhinoAlmondBridge
{
    /// <summary>Bounded, read-only inventory of explicit objects. Measurements are physical mm.</summary>
    public static class SceneMetadata
    {
        public const int MaxObjects = 500;
        private static MetadataConduit _overlay;

        private static string Error(string message) => JsonConvert.SerializeObject(new { status = "error", message });

        // String entry points also allow development smoke checks without replacing the installed plugin.
        public static string InventoryJson(string json) => Inventory(JObject.Parse(json));
        public static string InventoryForDocumentJson(RhinoDoc doc, string json) => InventoryForDocument(doc, JObject.Parse(json));
        public static string OverlayJson(string json) => Overlay(JObject.Parse(json));

        public static string DocumentKey(RhinoDoc doc) => !string.IsNullOrWhiteSpace(doc.Path)
            ? "file:" + Path.GetFullPath(doc.Path).ToLowerInvariant()
            : "session:" + System.Diagnostics.Process.GetCurrentProcess().Id + ":" + doc.RuntimeSerialNumber;

        public static string Inventory(JObject request)
            => InventoryForDocument(RhinoDoc.ActiveDoc, request);

        private static string InventoryForDocument(RhinoDoc doc, JObject request)
        {
            if (doc == null) return Error("No active Rhino document.");
            var ids = request["guids"]?.ToObject<List<string>>();
            if (ids == null || ids.Count < 1 || ids.Count > MaxObjects)
                return Error($"Provide 1 to {MaxObjects} explicit Rhino GUIDs.");
            var parsed = new List<Guid>();
            foreach (var value in ids)
            {
                if (!Guid.TryParse(value, out var id) || id == Guid.Empty) return Error("Invalid Rhino object GUID.");
                parsed.Add(id);
            }
            if (parsed.Distinct().Count() != parsed.Count) return Error("Duplicate Rhino GUIDs are not allowed.");
            double mm = RhinoMath.UnitScale(doc.ModelUnitSystem, UnitSystem.Millimeters);
            if (doc.ModelUnitSystem == UnitSystem.None || doc.ModelUnitSystem == UnitSystem.CustomUnits ||
                double.IsNaN(mm) || double.IsInfinity(mm) || mm <= 0)
                return Error("Set a supported physical Rhino unit system before auditing.");
            var objects = new List<object>();
            var missing = new List<string>();
            foreach (var id in parsed)
            {
                var obj = doc.Objects.FindId(id);
                if (obj == null || obj.IsDeleted) { missing.Add(id.ToString()); continue; }
                if (obj.Geometry == null) return Error("An object has no readable geometry: " + id);
                var bounds = obj.Geometry.GetBoundingBox(true);
                if (!bounds.IsValid) return Error("An object has no valid world bounding box: " + id);
                var text = obj.Attributes.GetUserStrings();
                var metadata = new SortedDictionary<string, string>(StringComparer.Ordinal);
                foreach (var key in text.AllKeys)
                    if (key != null && (key.StartsWith("almond:", StringComparison.OrdinalIgnoreCase) ||
                        key.StartsWith("Almond.", StringComparison.OrdinalIgnoreCase))) metadata[key] = text[key] ?? "";
                var quantities = new Dictionary<string, object>();
                if (obj.Geometry is Curve curve) quantities["length_mm"] = curve.GetLength() * mm;
                if (obj.Geometry is Brep brep)
                {
                    using (var area = AreaMassProperties.Compute(brep)) quantities["area_mm2"] = area == null ? (object)null : area.Area * mm * mm;
                    if (brep.IsSolid)
                        using (var volume = VolumeMassProperties.Compute(brep)) quantities["volume_mm3"] = volume == null ? (object)null : volume.Volume * mm * mm * mm;
                }
                double[] transform = null;
                string crc;
                if (obj is InstanceObject instance)
                {
                    var t = instance.InstanceXform;
                    transform = new[] { t.M00, t.M01, t.M02, t.M03 * mm, t.M10, t.M11, t.M12, t.M13 * mm, t.M20, t.M21, t.M22, t.M23 * mm };
                    var visiting = new HashSet<Guid>();
                    // Definition geometry is separate from placement, including nested definitions.
                    crc = DefinitionCrc(instance.InstanceDefinition, visiting, 0, refCount: new int[] { 0 });
                }
                else crc = obj.Geometry.DataCRC(0).ToString("x8", CultureInfo.InvariantCulture);
                objects.Add(new
                {
                    id = id.ToString(), name = obj.Attributes.Name ?? "", kind = obj.ObjectType.ToString(),
                    bounds_mm = new[] { bounds.Min.X * mm, bounds.Min.Y * mm, bounds.Min.Z * mm, bounds.Max.X * mm, bounds.Max.Y * mm, bounds.Max.Z * mm },
                    metadata, quantities, transform, geometry_crc = crc,
                    visible = obj.Visible, locked = obj.IsLocked,
                });
            }
            return JsonConvert.SerializeObject(new
            {
                status = "ok", schema = 1, complete = true, document_key = DocumentKey(doc),
                units = doc.ModelUnitSystem.ToString(), unit_scale_to_mm = mm,
                requested_ids = parsed.Select(g => g.ToString()).ToArray(), missing_ids = missing, objects,
                fingerprint_method = "native GeometryBase.DataCRC; block definitions traversed, instance transform separate",
                quantity_scope = "Curve length and Brep area/closed volume. Block quantities are not aggregated.",
            });
        }

        private static string DefinitionCrc(InstanceDefinition definition, HashSet<Guid> visiting, int depth, int[] refCount)
        {
            if (definition == null) throw new InvalidOperationException("Block definition unavailable.");
            if (depth > 16 || !visiting.Add(definition.Id)) throw new InvalidOperationException("Cyclic or excessively deep block definition.");
            var parts = new List<string>();
            foreach (var member in definition.GetObjects())
            {
                if (++refCount[0] > 10000) throw new InvalidOperationException("Block definition exceeds the audit traversal limit.");
                if (member is InstanceObject nested)
                    parts.Add(member.Geometry.DataCRC(0).ToString("x8") + ":" + DefinitionCrc(nested.InstanceDefinition, visiting, depth + 1, refCount));
                else parts.Add(member.Geometry.DataCRC(0).ToString("x8"));
            }
            visiting.Remove(definition.Id);
            // Stable compact digest of component CRCs, not a claim of cryptographic geometry identity.
            using (var sha = System.Security.Cryptography.SHA256.Create())
                return BitConverter.ToString(sha.ComputeHash(System.Text.Encoding.UTF8.GetBytes(string.Join("|", parts)))).Replace("-", "").ToLowerInvariant();
        }

        public static string Overlay(JObject request)
        {
            var doc = RhinoDoc.ActiveDoc;
            if (doc == null) return Error("No active Rhino document.");
            if (request.Value<bool?>("clear") == true)
            {
                if (_overlay != null) { _overlay.Enabled = false; _overlay = null; }
                doc.Views.Redraw();
                return JsonConvert.SerializeObject(new { status = "cleared" });
            }
            if (request.Value<string>("document_key") != DocumentKey(doc)) return Error("Audit overlay belongs to a different Rhino document.");
            var items = request["issues"] as JArray;
            if (items == null || items.Count > MaxObjects) return Error("Provide at most 500 audit issues.");
            double scale = RhinoMath.UnitScale(UnitSystem.Millimeters, doc.ModelUnitSystem);
            var boxes = new List<MetadataBox>();
            foreach (var item in items)
            {
                var b = item["bounds_mm"]?.ToObject<double[]>();
                if (b == null || b.Length != 6 || b.Any(x => double.IsNaN(x) || double.IsInfinity(x)) ||
                    Enumerable.Range(0, 3).Any(i => b[i] > b[i + 3])) return Error("Invalid audit bounding box.");
                var codes = ((item["reasons"] as JArray) ?? new JArray()).Select(r => r.Value<string>("code") ?? "issue").Distinct().ToArray();
                string label = string.Join(", ", codes.Select(code => code.Replace('_', ' ')));
                var box = new BoundingBox(new Point3d(b[0] * scale, b[1] * scale, b[2] * scale), new Point3d(b[3] * scale, b[4] * scale, b[5] * scale));
                box.Inflate(Math.Max(scale, doc.ModelAbsoluteTolerance));
                boxes.Add(new MetadataBox { Bounds = box, Label = label, Missing = codes.Contains("missing_object") });
            }
            if (_overlay != null) _overlay.Enabled = false;
            _overlay = new MetadataConduit { DocumentSerial = doc.RuntimeSerialNumber, Boxes = boxes, Enabled = true };
            doc.Views.Redraw();
            return JsonConvert.SerializeObject(new { status = "shown", issues = boxes.Count, scope = "Temporary boxes and labels; geometry, attributes and selection unchanged." });
        }

        private class MetadataBox { public BoundingBox Bounds; public string Label; public bool Missing; }
        private class MetadataConduit : DisplayConduit
        {
            public uint DocumentSerial;
            public List<MetadataBox> Boxes;
            protected override void DrawForeground(DrawEventArgs e)
            {
                if (e.RhinoDoc == null || e.RhinoDoc.RuntimeSerialNumber != DocumentSerial) return;
                foreach (var item in Boxes)
                {
                    var colour = item.Missing ? Color.IndianRed : Color.DarkOrange;
                    e.Display.DrawBox(item.Bounds, colour, 3);
                    var screen = e.Viewport.WorldToClient(item.Bounds.Center);
                    double top = item.Bounds.GetCorners().Min(p => e.Viewport.WorldToClient(p).Y);
                    e.Display.DrawDot((float)screen.X, (float)top - 24, item.Label, colour, Color.White);
                }
            }
        }
    }
}
