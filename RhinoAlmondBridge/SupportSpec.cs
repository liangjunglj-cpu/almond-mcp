using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Rhino.DocObjects;
using Rhino.Geometry;

namespace RhinoAlmondBridge
{
    /// <summary>A declared support: a Rhino point object, its <c>almond:support</c> text and GUID.</summary>
    public class SupportPoint
    {
        public Point3d Location { get; set; }
        /// <summary>The designer's support type, verbatim (null = the analysis default).</summary>
        public string Spec { get; set; }
        public string SourceGuid { get; set; }
    }

    /// <summary>
    /// <c>almond:support</c> user text on a support point: <c>"&lt;type&gt; [key=value ...]"</c> with type
    /// fixed | pinned | pin | roller | roller-x | roller-y | spring and springs kx ky kz (kN/m),
    /// rx ry rz (kNm/rad) in global axes. The native engine (almond_mcp.native_structure.parse_support)
    /// is the reference reading; this C# copy only serves the Karamba route and the overlay symbols.
    /// </summary>
    public static class SupportSpec
    {
        public static readonly string[] Keys = { "almond:support", "Almond.Support" };
        private static readonly string[] SpringKeys = { "kx", "ky", "kz", "rx", "ry", "rz" };
        private static readonly Dictionary<string, bool[]> Types = new Dictionary<string, bool[]>(StringComparer.OrdinalIgnoreCase)
        {
            ["fixed"] = new[] { true, true, true, true, true, true },
            ["pinned"] = new[] { true, true, true, false, false, false },
            ["pin"] = new[] { true, true, true, false, false, false },
            ["roller"] = new[] { false, false, true, false, false, false },
            ["roller-x"] = new[] { false, true, true, false, false, false },
            ["roller-y"] = new[] { true, false, true, false, false, false },
            ["spring"] = new[] { false, false, false, false, false, false },
        };

        /// <summary>The support text on a Rhino object, trimmed; null when there is none.</summary>
        public static string Read(RhinoObject obj)
        {
            if (obj == null) return null;
            return Keys.Select(k => obj.Attributes.GetUserString(k)).FirstOrDefault(v => !string.IsNullOrWhiteSpace(v))?.Trim();
        }

        /// <summary>
        /// Restrained DOFs (Tx Ty Tz Rx Ry Rz) and whether springs were given. A spring direction is free here
        /// (the native engine adds the spring). Returns false with <paramref name="error"/> set when the text is
        /// not a support specification.
        /// </summary>
        public static bool TryParse(string text, out bool[] restraint, out bool[] sprung, out string label, out string error)
        {
            restraint = new bool[6];
            sprung = new bool[6];
            label = null;
            error = null;
            var words = (text ?? "").Replace(',', ' ').Split((char[])null, StringSplitOptions.RemoveEmptyEntries);
            if (words.Length == 0 || !Types.ContainsKey(words[0]))
            {
                error = $"unknown support type '{text}'";
                return false;
            }
            restraint = (bool[])Types[words[0]].Clone();
            var springs = new List<string>();
            foreach (var w in words.Skip(1))
            {
                var kv = w.Replace(':', '=').Split('=');
                int d = kv.Length == 2 ? Array.IndexOf(SpringKeys, kv[0].ToLowerInvariant()) : -1;
                double k;
                if (d < 0 || !double.TryParse(kv[1], NumberStyles.Float, CultureInfo.InvariantCulture, out k) || k < 0 || double.IsInfinity(k))
                {
                    error = $"unknown support setting '{w}'";
                    return false;
                }
                restraint[d] = false;
                sprung[d] = k > 0;
                springs.Add($"{SpringKeys[d]}={k.ToString("G", CultureInfo.InvariantCulture)}");
            }
            if (!restraint.Any(b => b) && !sprung.Any(b => b))
            {
                error = "a spring support needs at least one stiffness, e.g. 'spring kz=50000'";
                return false;
            }
            var type = words[0].ToLowerInvariant();
            label = string.Join(" ", new[] { type == "pin" ? "pinned" : type }.Concat(springs));
            return true;
        }

        /// <summary>The overlay glyph family of a support label: fixed, pinned, roller or spring.</summary>
        public static string Glyph(string label)
        {
            var t = (label ?? "").Trim().ToLowerInvariant();
            if (t.StartsWith("spring") || t.Contains("=")) return "spring";       // any spring, e.g. a semi-rigid base
            if (t.StartsWith("roller")) return "roller";
            return t.StartsWith("fixed") ? "fixed" : "pinned";
        }
    }
}
