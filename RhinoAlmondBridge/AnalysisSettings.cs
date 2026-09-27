using System;
using System.IO;
using System.Linq;
using Newtonsoft.Json.Linq;

namespace RhinoAlmondBridge
{
    // Shared, bounded panel contract. Parsing never invokes Rhino or the solver.
    internal sealed class AnalysisSettings
    {
        public string Structure = "frame";
        public string Material = "Steel";
        public double LoadKN = 10;
        public bool SelfWeight = true;
        public bool FixedRotations = true;
        public bool ExplicitSupports;
        public double? DiameterMM;
        public double? WallMM;
        internal static AnalysisSettings Parse(string json)
        {
            if (json == null || json.Length > 4096) throw new InvalidDataException("Invalid analysis settings.");
            var data = JObject.Parse(json);
            string[] allowed = {"structure","material","load_kn","self_weight","fixed_rotations","explicit_supports","diameter_mm","wall_mm"};
            if (data.Properties().Any(p => !allowed.Contains(p.Name))) throw new InvalidDataException("Unknown analysis setting.");
            var value = new AnalysisSettings {
                Structure=(string)data["structure"] ?? "frame", Material=(string)data["material"] ?? "Steel",
                LoadKN=(double?)data["load_kn"] ?? 10, SelfWeight=(bool?)data["self_weight"] ?? true,
                FixedRotations=(bool?)data["fixed_rotations"] ?? true, ExplicitSupports=(bool?)data["explicit_supports"] ?? false,
                DiameterMM=(double?)data["diameter_mm"], WallMM=(double?)data["wall_mm"]
            };
            if (!new[]{"beam","frame","truss","shell","canopy","gridshell","membrane","highrise"}.Contains(value.Structure) ||
                !new[]{"Steel","S235","S355","Concrete","C30/37","Wood","C24","Aluminium","Aluminum"}.Contains(value.Material))
                throw new InvalidDataException("Choose a supported structure and material.");
            if (!Finite(value.LoadKN) || value.LoadKN < 0 || value.LoadKN > 100000)
                throw new InvalidDataException("Total load must be between 0 and 100,000 kN.");
            if (value.DiameterMM.HasValue != value.WallMM.HasValue ||
                (value.DiameterMM.HasValue && (!Finite(value.DiameterMM.Value) || !Finite(value.WallMM.Value) ||
                value.DiameterMM <= 0 || value.DiameterMM > 5000 || value.WallMM <= 0 || value.WallMM >= value.DiameterMM/2)))
                throw new InvalidDataException("CHS wall thickness must be positive and less than half the diameter (maximum diameter 5,000 mm).");
            return value;
        }
        private static bool Finite(double value) => !double.IsNaN(value) && !double.IsInfinity(value);
        internal JObject ToJson() => new JObject {
            ["structure"]=Structure,["material"]=Material,["load_kn"]=LoadKN,["self_weight"]=SelfWeight,
            ["fixed_rotations"]=FixedRotations,["explicit_supports"]=ExplicitSupports,
            ["diameter_mm"]=DiameterMM,["wall_mm"]=WallMM
        };
    }
}
