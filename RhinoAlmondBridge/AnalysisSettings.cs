using System;
using System.IO;
using System.Linq;
using Newtonsoft.Json.Linq;

namespace RhinoAlmondBridge
{
    // Shared, bounded panel contract. Parsing never invokes Rhino or the solver.
    internal sealed class AnalysisSettings
    {
        public string Engine = "native";
        public string Structure = "frame";
        public string Material = "Steel";
        public double LoadKN = 10;
        public bool SelfWeight = true;
        public bool FixedRotations = true;
        public bool ExplicitSupports;
        public double? DiameterMM;
        public double? WallMM;
        // native engine only
        public string Connections = "rigid";
        public double FloorImposed;
        public double FloorDead;
        public bool AssetLoads;
        public string DesignBasis = "en1990";
        public string UlsCombination = "";          // "" = the design code's choice
        public string DesignCode = "eurocode";      // a design code profile id, or "off"
        public double? LimitRatio;                  // span / ratio; null = the design code's limit
        public string Fabrication = "cold_formed";  // hollow sections: cold_formed (curve c) | hot_finished (curve a)
        public string Stability = "auto";
        public string View = "deflection";
        public double? SpanM;

        internal static AnalysisSettings Parse(string json)
        {
            if (json == null || json.Length > 4096) throw new InvalidDataException("Invalid analysis settings.");
            var data = JObject.Parse(json);
            string[] allowed = {"engine","structure","material","load_kn","self_weight","fixed_rotations","explicit_supports","diameter_mm","wall_mm",
                "connections","floor_imposed_kn_m2","floor_dead_kn_m2","asset_loads","design_basis","uls_combination","stability","view","span_m",
                "design_code","deflection_limit_ratio","fabrication"};
            if (data.Properties().Any(p => !allowed.Contains(p.Name))) throw new InvalidDataException("Unknown analysis setting.");
            var value = new AnalysisSettings {
                Engine=(string)data["engine"] ?? "native",
                Structure=(string)data["structure"] ?? "frame", Material=(string)data["material"] ?? "Steel",
                LoadKN=(double?)data["load_kn"] ?? 10, SelfWeight=(bool?)data["self_weight"] ?? true,
                FixedRotations=(bool?)data["fixed_rotations"] ?? true, ExplicitSupports=(bool?)data["explicit_supports"] ?? false,
                DiameterMM=(double?)data["diameter_mm"], WallMM=(double?)data["wall_mm"],
                Connections=(string)data["connections"] ?? "rigid",
                FloorImposed=(double?)data["floor_imposed_kn_m2"] ?? 0, FloorDead=(double?)data["floor_dead_kn_m2"] ?? 0,
                AssetLoads=(bool?)data["asset_loads"] ?? false,
                DesignBasis=(string)data["design_basis"] ?? "en1990", UlsCombination=(string)data["uls_combination"] ?? "",
                DesignCode=(string)data["design_code"] ?? "eurocode", LimitRatio=(double?)data["deflection_limit_ratio"],
                Fabrication=(string)data["fabrication"] ?? "cold_formed",
                Stability=(string)data["stability"] ?? "auto", View=(string)data["view"] ?? "deflection",
                SpanM=(double?)data["span_m"]
            };
            if (!new[]{"native","karamba"}.Contains(value.Engine)) throw new InvalidDataException("Choose the native or Karamba engine.");
            if (!new[]{"beam","frame","truss","shell","canopy","gridshell","membrane","highrise"}.Contains(value.Structure) ||
                !new[]{"Steel","S235","S355","Concrete","C30/37","Wood","C24","Aluminium","Aluminum"}.Contains(value.Material))
                throw new InvalidDataException("Choose a supported structure and material.");
            if (value.Engine=="native" && !new[]{"beam","frame","truss"}.Contains(value.Structure))
                throw new InvalidDataException("The native engine analyses line members (beam, frame, truss). Choose Karamba for shells.");
            if (!Finite(value.LoadKN) || value.LoadKN < 0 || value.LoadKN > 100000)
                throw new InvalidDataException("Total load must be between 0 and 100,000 kN.");
            if (value.DiameterMM.HasValue != value.WallMM.HasValue ||
                (value.DiameterMM.HasValue && (!Finite(value.DiameterMM.Value) || !Finite(value.WallMM.Value) ||
                value.DiameterMM <= 0 || value.DiameterMM > 5000 || value.WallMM <= 0 || value.WallMM >= value.DiameterMM/2)))
                throw new InvalidDataException("CHS wall thickness must be positive and less than half the diameter (maximum diameter 5,000 mm).");
            if (!new[]{"rigid","simple"}.Contains(value.Connections) || !new[]{"en1990","unfactored"}.Contains(value.DesignBasis) ||
                !new[]{"","6.10","6.10ab"}.Contains(value.UlsCombination) || !new[]{"auto","off"}.Contains(value.Stability) ||
                !new[]{"deflection","buckling"}.Contains(value.View))
                throw new InvalidDataException("Choose supported connection, design basis, stability and view options.");
            foreach (double load in new[]{value.FloorImposed, value.FloorDead})
                if (!Finite(load) || load < 0 || load > 1000) throw new InvalidDataException("Floor loads must be between 0 and 1,000 kN/m².");
            if (!new[]{"cold_formed","hot_finished"}.Contains(value.Fabrication))
                throw new InvalidDataException("Choose cold-formed or hot-finished hollow sections.");
            if (!System.Text.RegularExpressions.Regex.IsMatch(value.DesignCode, "^[a-z0-9][a-z0-9-]{0,39}$"))
                throw new InvalidDataException("Choose a design code profile.");
            if (value.LimitRatio.HasValue && (!Finite(value.LimitRatio.Value) || value.LimitRatio < 100 || value.LimitRatio > 1000))
                throw new InvalidDataException("The deflection limit must be span/100 to span/1000.");
            if (value.SpanM.HasValue && (!Finite(value.SpanM.Value) || value.SpanM <= 0 || value.SpanM > 1000))
                throw new InvalidDataException("The deflection span must be a positive length up to 1,000 m.");
            return value;
        }
        private static bool Finite(double value) => !double.IsNaN(value) && !double.IsInfinity(value);
        internal JObject ToJson() => new JObject {
            ["engine"]=Engine,["structure"]=Structure,["material"]=Material,["load_kn"]=LoadKN,["self_weight"]=SelfWeight,
            ["fixed_rotations"]=FixedRotations,["explicit_supports"]=ExplicitSupports,
            ["diameter_mm"]=DiameterMM,["wall_mm"]=WallMM,
            ["connections"]=Connections,["floor_imposed_kn_m2"]=FloorImposed,["floor_dead_kn_m2"]=FloorDead,
            ["asset_loads"]=AssetLoads,["design_basis"]=DesignBasis,["uls_combination"]=UlsCombination,
            ["stability"]=Stability,["view"]=View,["span_m"]=SpanM,
            ["design_code"]=DesignCode,["deflection_limit_ratio"]=LimitRatio,["fabrication"]=Fabrication
        };
        // what `almond-mcp solve` reads (explicit_supports is a Rhino-side capture rule; the export carries anchors)
        internal JObject SolverSettings() {
            var s = ToJson();
            s.Remove("engine"); s.Remove("explicit_supports");
            if (UlsCombination == "") s["uls_combination"] = null;
            return s;
        }
    }
}
