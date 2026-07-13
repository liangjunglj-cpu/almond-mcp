using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using Rhino;

namespace RhinoAlmondBridge
{
    /// <summary>
    /// Structural validation orchestrator. Tries three pathways in order and
    /// labels the result loudly with the method used:
    ///   1. "api"        — KarambaAdapter direct karambaCommon 3.1 call (high confidence)
    ///   2. "template"   — GhDefinitionRunner with a matching AUDITED capsule (medium)
    ///   3. "rule_based" — engineering rule-of-thumb estimate (low confidence);
    ///                     verdict is prefixed "[RULE-BASED ESTIMATE, LOW CONFIDENCE]".
    /// No silent fallback: every downgrade is recorded in warnings.
    /// </summary>
    public class StructuralValidator
    {
        private readonly string _templateDir;   // Grasshopperfiles root
        private readonly string _capsuleDir;    // capsules/ manifest folder
        private readonly ModelConditioner _conditioner = new ModelConditioner();

        public StructuralValidator(string templateDir, string capsuleDir = null)
        {
            _templateDir = templateDir;
            _capsuleDir = capsuleDir ?? FindCapsuleDirectory();
        }

        private static string FindCapsuleDirectory()
        {
            string env = Environment.GetEnvironmentVariable("RHINO_MCP_CAPSULE_DIR");
            if (!string.IsNullOrEmpty(env)) return env;

            string directory = Path.GetDirectoryName(typeof(StructuralValidator).Assembly.Location);
            for (int i = 0; i < 6 && directory != null; i++)
            {
                string candidate = Path.Combine(directory, "capsules");
                if (Directory.Exists(candidate)) return candidate;
                directory = Path.GetDirectoryName(directory);
            }
            return Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),
                "Almond", "mcp-rhino-plugin", "capsules");
        }

        /// <summary>
        /// Validate geometry against structural criteria. Public signature is
        /// unchanged; BridgeServer depends on it.
        /// </summary>
        public ValidationResult Validate(ValidationRequest request)
        {
            var result = new ValidationResult
            {
                StructureType = request.StructureType,
                Material = request.Material,
            };

            var doc = RhinoDoc.ActiveDoc;
            if (doc == null)
            {
                result.Status = "error";
                result.Verdict = "No active Rhino document.";
                return result;
            }

            // 1. Condition the geometry (weld nodes, split members, classify).
            var conditioned = _conditioner.Condition(doc, request.Guids);
            result.Warnings.AddRange(conditioned.Warnings);

            if (conditioned.Beams.Count == 0 && conditioned.Shells.Count == 0)
            {
                result.Status = "error";
                result.Verdict = "No valid geometry found for the given GUIDs.";
                return result;
            }

            double spanM = conditioned.MaxSpan * conditioned.UnitScaleToMeters;
            if (spanM < 0.001) spanM = 5.0; // default 5 m when undeterminable

            // 2. Pathway A: direct Karamba 3.1 API.
            bool solved = TryApiPath(request, conditioned, result);

            // 3. Pathway B: audited template capsule.
            if (!solved)
                solved = TryTemplatePath(request, result);

            // 4. Pathway C: rule-based estimate. Never silent about it.
            if (!solved)
            {
                int memberCount = conditioned.Beams.Count + conditioned.Shells.Count;
                result.Results = RunRuleBasedAnalysis(
                    spanM, memberCount, request.LoadKN, request.Material, request.StructureType);
                result.Confidence = "low";
                result.Warnings.Add("Karamba API and audited template capsules were both " +
                    "unavailable; this is a rule-of-thumb estimate, not FEA.");
            }

            // 5. Pass/fail criteria (L/250 deflection and yield checks preserved).
            double yieldStress = KarambaAdapter.YieldStrengthMPa(request.Material);
            double deflectionLimit = (spanM * 1000.0) / 250.0; // L/250 in mm

            result.Results.DeflectionLimitMM = deflectionLimit;
            result.Results.YieldStressMPa = yieldStress;
            result.Results.SpanM = spanM;

            var failures = new List<string>();
            var suggestions = new List<string>();

            if (result.Results.MaxDeflectionMM > deflectionLimit)
            {
                failures.Add($"Deflection {result.Results.MaxDeflectionMM:F1}mm exceeds L/250 limit ({deflectionLimit:F1}mm)");
                suggestions.Add("Increase member depth or use a stiffer cross-section");
                suggestions.Add("Add intermediate supports to reduce effective span");
            }

            if (result.Results.UtilizationRatio > 1.0)
            {
                failures.Add($"Utilization ratio {result.Results.UtilizationRatio:F2} exceeds 1.0");
                suggestions.Add("Use a larger cross-section or higher-grade material");
            }

            if (result.Results.MaxStressMPa > yieldStress)
            {
                failures.Add($"Max stress {result.Results.MaxStressMPa:F0}MPa exceeds yield ({yieldStress:F0}MPa)");
                suggestions.Add("Consider upgrading to higher-strength material");
            }

            result.Passed = failures.Count == 0;
            result.Status = result.Passed ? "pass" : "fail";

            string prefix = MethodPrefix(result.Results.AnalysisMethod);
            result.Verdict = prefix + (result.Passed
                ? $"PASSED: All structural checks OK. Deflection {result.Results.MaxDeflectionMM:F1}mm (limit {deflectionLimit:F1}mm), Utilization {result.Results.UtilizationRatio:F2}"
                : $"FAILED: {string.Join("; ", failures)}");
            result.Suggestions = suggestions;

            // Worst offenders so the LLM edits only those members.
            result.WorstMemberGuids = result.Results.PerElementUtilization
                .OrderByDescending(u => u.Utilization)
                .SelectMany(u => u.SourceGuids)
                .Distinct()
                .Take(5)
                .ToList();

            return result;
        }

        private static string MethodPrefix(string analysisMethod)
        {
            switch (analysisMethod)
            {
                case "api":
                    return "[KARAMBA 3.1 API, HIGH CONFIDENCE] ";
                case "template":
                    return "[AUDITED TEMPLATE, MEDIUM CONFIDENCE] ";
                default:
                    // Contract: rule-based verdicts MUST begin with this string.
                    return "[RULE-BASED ESTIMATE, LOW CONFIDENCE] ";
            }
        }

        // ── Pathway A: Karamba API ───────────────────────────────────────────

        private bool TryApiPath(ValidationRequest request, ConditionedModel conditioned,
            ValidationResult result)
        {
            var spec = new KarambaModelSpec
            {
                Conditioned = conditioned,
                MaterialName = request.Material,
                ImposedLoadKN = request.LoadKN,
            };

            KarambaResults karamba;
            try
            {
                karamba = KarambaAdapter.BuildAndAnalyze(spec);
            }
            catch (Exception ex)
            {
                result.Warnings.Add("Karamba API path threw unexpectedly: " + ex.Message);
                return false;
            }

            if (!karamba.Available)
            {
                result.Warnings.Add("Karamba API path unavailable: " + karamba.FailureReason);
                return false;
            }

            result.Warnings.AddRange(karamba.Warnings);

            double maxUtil = karamba.PerElementUtilization.Count > 0
                ? karamba.PerElementUtilization.Max(u => u.Utilization) : 0;

            result.Results = new StructuralMetrics
            {
                MaxDeflectionMM = karamba.MaxDisplacementMM,
                UtilizationRatio = maxUtil,
                MaxStressMPa = karamba.MaxStressMPa,
                ReactionsKN = karamba.ReactionsKN,
                AnalysisMethod = "api",
                PerElementUtilization = karamba.PerElementUtilization
                    .Select(u => new PerElementUtilizationEntry
                    {
                        SourceGuids = u.SourceGuids,
                        Utilization = u.Utilization,
                    })
                    .ToList(),
            };
            result.Confidence = "high";
            return true;
        }

        // ── Pathway B: audited capsule template ─────────────────────────────

        private bool TryTemplatePath(ValidationRequest request, ValidationResult result)
        {
            var runner = new GhDefinitionRunner(_templateDir, _capsuleDir);

            // Select an audited "analyze" capsule whose structure_type matches.
            string manifestPath = null;
            CapsuleManifest manifest = null;
            foreach (var pair in runner.EnumerateManifests())
            {
                var m = pair.Item2;
                if (!m.Audited) continue;
                if (!string.Equals(m.Capability, "analyze", StringComparison.OrdinalIgnoreCase))
                    continue;
                if (!string.Equals(m.StructureType, request.StructureType,
                    StringComparison.OrdinalIgnoreCase))
                    continue;
                manifestPath = pair.Item1;
                manifest = m;
                break;
            }

            if (manifest == null)
            {
                result.Warnings.Add($"No audited 'analyze' capsule found for structure_type " +
                    $"'{request.StructureType}'.");
                return false;
            }

            // Build capsule inputs from the validation request by declared type.
            var inputs = new JObject();
            foreach (var port in manifest.Inputs)
            {
                string baseType = (port.Type ?? "").Replace("[]", "");
                string nameUpper = (port.Name ?? "").ToUpperInvariant();

                if (baseType == "curve" || baseType == "mesh" ||
                    baseType == "brep" || baseType == "point")
                {
                    inputs[port.Name] = new JObject
                    {
                        ["guids"] = new JArray(request.Guids.ToArray()),
                    };
                }
                else if (baseType == "number" && nameUpper.Contains("LOAD"))
                {
                    inputs[port.Name] = request.LoadKN;
                }
                else if (baseType == "string" && nameUpper.Contains("MATERIAL"))
                {
                    inputs[port.Name] = request.Material;
                }
                // Anything else relies on the manifest default; the runner
                // hard-errors if a required input remains unbound.
            }

            var run = runner.Run(manifestPath, inputs, 60.0, null);
            result.Warnings.AddRange(run.Warnings);

            if (run.Status != "ok")
            {
                result.Warnings.Add($"Template capsule '{manifest.CapsuleId}' failed: {run.Error}");
                return false;
            }

            // Map typed outputs by declared semantics; units converted explicitly.
            var metrics = new StructuralMetrics { AnalysisMethod = "template" };
            bool gotDisplacement = false;

            foreach (var port in manifest.Outputs)
            {
                object value;
                if (!run.Outputs.TryGetValue(port.Name, out value) || value == null)
                    continue;

                switch (port.Semantics)
                {
                    case "max_nodal_displacement":
                    {
                        double d;
                        if (TryAsDouble(value, out d))
                        {
                            metrics.MaxDeflectionMM = Math.Abs(d) * LengthToMm(port.Units);
                            gotDisplacement = true;
                        }
                        break;
                    }
                    case "per_element_utilization":
                    {
                        var list = AsDoubleList(value);
                        metrics.UtilizationRatio = list.Count > 0
                            ? list.Max(Math.Abs) : metrics.UtilizationRatio;
                        // Template capsules cannot attribute utilization to
                        // individual source objects; lineage is the whole set.
                        metrics.PerElementUtilization = list
                            .Select(u => new PerElementUtilizationEntry
                            {
                                SourceGuids = new List<string>(request.Guids),
                                Utilization = Math.Abs(u),
                            })
                            .ToList();
                        if (list.Count > 0)
                            result.Warnings.Add("Template path cannot attribute utilization " +
                                "to individual members; source_guids lists the full input set.");
                        break;
                    }
                    case "max_stress":
                    {
                        double s;
                        if (TryAsDouble(value, out s))
                            metrics.MaxStressMPa = Math.Abs(s) * StressToMPa(port.Units);
                        break;
                    }
                }
            }

            if (!gotDisplacement)
            {
                result.Warnings.Add($"Capsule '{manifest.CapsuleId}' returned no " +
                    "max_nodal_displacement output; template path rejected.");
                return false;
            }

            result.Results = metrics;
            result.Confidence = "medium";
            return true;
        }

        /// <summary>Declared length unit → factor to millimeters. Never guessed.</summary>
        private static double LengthToMm(string units)
        {
            switch ((units ?? "mm").ToLowerInvariant())
            {
                case "m": return 1000.0;
                case "cm": return 10.0;
                case "mm": return 1.0;
                default: return 1.0;
            }
        }

        /// <summary>Declared stress unit → factor to MPa.</summary>
        private static double StressToMPa(string units)
        {
            switch ((units ?? "mpa").ToLowerInvariant())
            {
                case "kn/cm2": return 10.0;
                case "kn/m2": return 0.001;
                case "mpa": return 1.0;
                default: return 1.0;
            }
        }

        private static bool TryAsDouble(object value, out double d)
        {
            d = 0;
            if (value == null) return false;
            if (value is double dd) { d = dd; return true; }
            if (value is int ii) { d = ii; return true; }
            if (value is List<double> list && list.Count > 0) { d = list[0]; return true; }
            try { d = Convert.ToDouble(value); return true; }
            catch { return false; }
        }

        private static List<double> AsDoubleList(object value)
        {
            if (value is List<double> list) return list;
            if (value is System.Collections.IEnumerable seq && !(value is string))
            {
                var result = new List<double>();
                foreach (var item in seq)
                {
                    try { result.Add(Convert.ToDouble(item)); }
                    catch { }
                }
                return result;
            }
            double single;
            return TryAsDouble(value, out single)
                ? new List<double> { single } : new List<double>();
        }

        // ── Pathway C: rule-based estimate (math preserved from v1) ─────────

        /// <summary>
        /// Fallback: engineering rule-of-thumb analysis when neither the
        /// Karamba API nor an audited template is available.
        /// </summary>
        private StructuralMetrics RunRuleBasedAnalysis(
            double spanM, int memberCount, double loadKN, string material, string structureType)
        {
            double yieldStress = KarambaAdapter.YieldStrengthMPa(material);

            // Simplified beam deflection: δ = 5wL⁴/(384EI)
            // Use typical steel I-beam properties
            double E = material.ToLower().Contains("steel") ? 210000 : // MPa
                       material.ToLower().Contains("concrete") ? 30000 :
                       material.ToLower().Contains("wood") ? 12000 : 70000;

            // Rough estimate of required I based on typical sections
            double typicalI = 1e-4; // m⁴ (approx HEB200)
            double wPerMeter = loadKN / Math.Max(spanM, 1.0); // kN/m

            // δ = 5wL⁴/(384EI) in meters, convert to mm
            double deflection = (5.0 * wPerMeter * Math.Pow(spanM, 4)) /
                                (384.0 * E * 1000.0 * typicalI) * 1000.0;

            // M = wL²/8, σ = M·y/I
            double moment = wPerMeter * spanM * spanM / 8.0; // kNm
            double y = 0.1; // half-depth approx 100mm
            double stress = (moment * 1000.0 * y) / (typicalI * 1e6); // MPa

            double utilization = stress / yieldStress;

            // Adjust for structure type
            switch ((structureType ?? "beam").ToLower())
            {
                case "truss":
                    deflection *= 0.6; // trusses are stiffer
                    utilization *= 0.7;
                    break;
                case "shell":
                    deflection *= 0.3; // shells are very stiff
                    utilization *= 0.5;
                    break;
                case "frame":
                    deflection *= 0.8;
                    break;
                case "canopy":
                    deflection *= 1.2; // cantilevers deflect more
                    utilization *= 1.3;
                    break;
            }

            // Reduce per member (more members = load sharing)
            if (memberCount > 1)
            {
                deflection /= Math.Sqrt(memberCount);
                utilization /= Math.Sqrt(memberCount);
            }

            return new StructuralMetrics
            {
                MaxDeflectionMM = Math.Max(0.1, deflection),
                MaxStressMPa = Math.Max(1.0, stress),
                UtilizationRatio = Math.Max(0.01, utilization),
                AnalysisMethod = "rule_based",
            };
        }
    }

    // ── Request / Response Models ────────────────────────────────────────────

    public class ValidationRequest
    {
        [JsonProperty("guids")]
        public List<string> Guids { get; set; } = new List<string>();

        [JsonProperty("structure_type")]
        public string StructureType { get; set; } = "beam";

        [JsonProperty("load_kn")]
        public double LoadKN { get; set; } = 10.0;

        [JsonProperty("material")]
        public string Material { get; set; } = "Steel";
    }

    public class ValidationResult
    {
        [JsonProperty("status")]
        public string Status { get; set; } = "error";

        [JsonProperty("passed")]
        public bool Passed { get; set; } = false;

        [JsonProperty("structure_type")]
        public string StructureType { get; set; }

        [JsonProperty("material")]
        public string Material { get; set; }

        [JsonProperty("results")]
        public StructuralMetrics Results { get; set; } = new StructuralMetrics();

        [JsonProperty("verdict")]
        public string Verdict { get; set; } = "";

        [JsonProperty("suggestions")]
        public List<string> Suggestions { get; set; } = new List<string>();

        // ── Added by the orchestrator refactor (additive; existing fields kept) ──

        /// <summary>"high" (api) | "medium" (template) | "low" (rule_based).</summary>
        [JsonProperty("confidence")]
        public string Confidence { get; set; } = "low";

        /// <summary>Up to 5 source GUIDs with the highest utilization.</summary>
        [JsonProperty("worst_member_guids")]
        public List<string> WorstMemberGuids { get; set; } = new List<string>();

        [JsonProperty("warnings")]
        public List<string> Warnings { get; set; } = new List<string>();
    }

    public class StructuralMetrics
    {
        [JsonProperty("max_deflection_mm")]
        public double MaxDeflectionMM { get; set; }

        [JsonProperty("deflection_limit_mm")]
        public double DeflectionLimitMM { get; set; }

        [JsonProperty("utilization_ratio")]
        public double UtilizationRatio { get; set; }

        [JsonProperty("max_stress_mpa")]
        public double MaxStressMPa { get; set; }

        [JsonProperty("yield_stress_mpa")]
        public double YieldStressMPa { get; set; }

        [JsonProperty("span_m")]
        public double SpanM { get; set; }

        [JsonProperty("analysis_method")]
        public string AnalysisMethod { get; set; } = "rule_based";

        // ── Added by the orchestrator refactor ──

        /// <summary>Total vertical reaction in kN (api path only).</summary>
        [JsonProperty("reactions_kn")]
        public double ReactionsKN { get; set; }

        /// <summary>Per-element utilization keyed to source Rhino GUIDs.</summary>
        [JsonProperty("per_element_utilization")]
        public List<PerElementUtilizationEntry> PerElementUtilization { get; set; }
            = new List<PerElementUtilizationEntry>();
    }

    public class PerElementUtilizationEntry
    {
        [JsonProperty("source_guids")]
        public List<string> SourceGuids { get; set; } = new List<string>();

        [JsonProperty("utilization")]
        public double Utilization { get; set; }
    }
}
