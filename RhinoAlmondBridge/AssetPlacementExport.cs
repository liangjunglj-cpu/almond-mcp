using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using Rhino;
using Rhino.DocObjects;

namespace RhinoAlmondBridge
{
    /// <summary>
    /// "asset_placements": placed library assets in the document (objects tagged with an Almond
    /// asset id) as world bounding boxes in meters, for structural loads from asset passports.
    /// Optional "guids" limits the export; hidden objects are skipped unless "include_hidden".
    /// </summary>
    public static class AssetPlacementExport
    {
        private static readonly string[] IdKeys = { "Almond.AssetId", "almond:asset_id", "almond.asset_id" };
        private static readonly string[] ScaleKeys = { "Almond.UniformScale", "almond:scale" };

        public static string Handle(JObject jobj)
        {
            var doc = RhinoDoc.ActiveDoc;
            if (doc == null)
                return JsonConvert.SerializeObject(new { status = "error", message = "No active Rhino document." });
            var only = jobj["guids"]?.ToObject<List<string>>();
            var filter = only != null && only.Count > 0 ? new HashSet<string>(only, StringComparer.OrdinalIgnoreCase) : null;
            bool includeHidden = jobj["include_hidden"]?.Value<bool>() ?? false;
            double s = RhinoMath.UnitScale(doc.ModelUnitSystem, UnitSystem.Meters);

            var settings = new ObjectEnumeratorSettings { NormalObjects = true, LockedObjects = true, HiddenObjects = includeHidden };
            var placements = new List<object>();
            foreach (var o in doc.Objects.GetObjectList(settings))
            {
                if (!includeHidden && !o.Visible) continue;
                string id = IdKeys.Select(k => o.Attributes.GetUserString(k)).FirstOrDefault(v => !string.IsNullOrWhiteSpace(v));
                if (id == null) continue;
                if (filter != null && !filter.Contains(o.Id.ToString())) continue;
                var bb = o.Geometry.GetBoundingBox(true);
                if (!bb.IsValid) continue;
                double scale = 1.0;
                foreach (var k in ScaleKeys)
                {
                    var v = o.Attributes.GetUserString(k);
                    if (!string.IsNullOrWhiteSpace(v) && double.TryParse(v, NumberStyles.Float, CultureInfo.InvariantCulture, out var sc) && sc > 0)
                    { scale = sc; break; }
                }
                placements.Add(new
                {
                    id = o.Id.ToString(),
                    asset_id = id.Trim(),
                    min = new[] { bb.Min.X * s, bb.Min.Y * s, bb.Min.Z * s },
                    max = new[] { bb.Max.X * s, bb.Max.Y * s, bb.Max.Z * s },
                    scale,
                    layer = doc.Layers[o.Attributes.LayerIndex].FullPath,
                    source = "rhino",
                });
            }
            return JsonConvert.SerializeObject(new { status = "ok", placements });
        }
    }
}
