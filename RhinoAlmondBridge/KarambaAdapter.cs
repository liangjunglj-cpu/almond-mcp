using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using Rhino;
using Rhino.Geometry;

namespace RhinoAlmondBridge
{
    // ─────────────────────────────────────────────────────────────────────────
    // KarambaAdapter: the ONLY file that talks to Karamba3D (karambaCommon).
    //
    // Binding strategy: reflection-based late binding. The project compiles
    // with NO reference to Karamba assemblies. At runtime the adapter loads
    // karambaCommon.dll (and Karamba.dll when present) from the Rhino 8
    // Karamba plugin folder via Assembly.LoadFrom. When Karamba is absent
    // or any reflection step fails, BuildAndAnalyze returns
    // Available = false with a reason, and the orchestrator falls through
    // to the template or rule-based path ("api_unavailable" behaviour).
    //
    // Target Karamba version: 3.1 (build 3.1.60519). Every reflection call
    // is commented with the karambaCommon 3.1 type/method it targets.
    // ─────────────────────────────────────────────────────────────────────────

    /// <summary>Input to KarambaAdapter.BuildAndAnalyze.</summary>
    public class KarambaModelSpec
    {
        /// <summary>Conditioned geometry (document units) from ModelConditioner.</summary>
        public ConditionedModel Conditioned { get; set; }

        /// <summary>Material name: Steel/S235, S355, Concrete/C30/37, Wood/C24, Aluminium.</summary>
        public string MaterialName { get; set; } = "Steel";

        /// <summary>Total imposed load in kN, split across free nodes, acting in -Z.</summary>
        public double ImposedLoadKN { get; set; } = 10.0;
        public bool IncludeSelfWeight { get; set; } = true;
        public bool FixedRotations { get; set; } = true;

        /// <summary>Also extract nodal and sampled member displacements (for the structure view).</summary>
        public bool ReturnGeometry { get; set; }
    }

    /// <summary>One analysed straight member with displacements sampled along it (meters).</summary>
    public class ElementDeflection
    {
        public List<string> SourceGuids { get; set; } = new List<string>();
        public double[] StartM { get; set; }
        public double[] EndM { get; set; }
        /// <summary>Translations at equally spaced stations from start to end, meters.</summary>
        public List<double[]> SampleDispM { get; set; } = new List<double[]>();
        public double Utilization { get; set; } = double.NaN;
    }

    /// <summary>Per-element utilization with Rhino GUID lineage.</summary>
    public class ElementUtilization
    {
        public List<string> SourceGuids { get; set; } = new List<string>();
        public double Utilization { get; set; }
    }

    /// <summary>Typed result facade returned by KarambaAdapter.BuildAndAnalyze.</summary>
    public class KarambaResults
    {
        /// <summary>False when Karamba is absent or the analysis failed.</summary>
        public bool Available { get; set; }

        /// <summary>Reason when Available is false (e.g. "api_unavailable: ...").</summary>
        public string FailureReason { get; set; }

        public double MaxDisplacementMM { get; set; }
        public bool DisplacementAvailable { get; set; }
        public bool UtilizationAvailable { get; set; }
        public List<double[]> SupportPointsM { get; set; } = new List<double[]>();
        public List<double[]> LoadedPointsM { get; set; } = new List<double[]>();

        /// <summary>Utilization per analyzed element, keyed to source Rhino GUIDs.</summary>
        public List<ElementUtilization> PerElementUtilization { get; set; } = new List<ElementUtilization>();

        /// <summary>Derived: max utilization x material yield strength (MPa).</summary>
        public double MaxStressMPa { get; set; }

        /// <summary>Total vertical reaction (kN) from statics: self weight + imposed load.</summary>
        public double ReactionsKN { get; set; }

        public List<string> Warnings { get; set; } = new List<string>();

        /// <summary>Per node: x, y, z, dx, dy, dz in meters (first load case).</summary>
        public List<double[]> NodeDispM { get; set; } = new List<double[]>();

        /// <summary>Per beam element: sampled displaced shape + utilization.</summary>
        public List<ElementDeflection> Elements { get; set; } = new List<ElementDeflection>();
        public bool GeometryAvailable { get; set; }
    }

    public static class KarambaAdapter
    {
        /// <summary>
        /// Settable override for the Karamba plugin folder (the directory that
        /// contains karambaCommon.dll). When null, standard Rhino 8 locations
        /// are probed. Set before the first BuildAndAnalyze call.
        /// </summary>
        public static string OverridePluginPath { get; set; }

        // ── UNITS: the single place where unit conversions are defined ──────
        //
        //  Rhino document units  →  meters:
        //      scale = RhinoMath.UnitScale(doc.ModelUnitSystem, UnitSystem.Meters)
        //      carried in ConditionedModel.UnitScaleToMeters; applied below to
        //      every coordinate and length before it reaches Karamba.
        //
        //  Karamba 3.1 SI conventions (assumed license setting "SI"):
        //      geometry (Point3/Line3/Mesh3 coords)  : meters  [m]
        //      forces (PointLoad)                    : kilonewtons [kN]
        //      material E, G, ft, fc                 : kN/cm^2  (1 kN/cm^2 = 10 MPa)
        //      material gamma (specific weight)      : kN/m^3
        //      cross-section dimensions              : centimeters [cm]
        //      AnalyzeThI max displacement out param : meters → we report mm (x1000)
        //      AssembleModel mass out param          : kilograms [kg]
        //
        //  Derived values reported by this adapter:
        //      MaxStressMPa  = maxUtilization x yieldStrengthMPa (documented proxy)
        //      ReactionsKN   = mass_kg x 9.81 / 1000 + imposedLoadKN (vertical
        //                      equilibrium; not extracted from the FE solver)
        private static class Units
        {
            public const double MetersToMillimeters = 1000.0;
            public const double MetersToCentimeters = 100.0;
            public const double KnPerCm2ToMPa = 10.0;
            public const double GravityMS2 = 9.81;

            /// <summary>Document-unit length → meters.</summary>
            public static double LenM(double docUnits, double unitScaleToMeters)
                => docUnits * unitScaleToMeters;

            /// <summary>Document-unit section dimension → centimeters.</summary>
            public static double SectionCm(double docUnits, double unitScaleToMeters)
                => docUnits * unitScaleToMeters * MetersToCentimeters;
        }

        // ── Material table ───────────────────────────────────────────────────
        // Values follow Karamba's own material library conventions:
        // E, G12, G3, ft, fc in kN/cm^2; gamma in kN/m^3; alphaT in 1/°C.
        private class MaterialDef
        {
            public string Family, Name;
            public double E, G12, G3, Gamma, Ft, Fc, AlphaT;
            public double YieldMPa;
        }

        private static readonly Dictionary<string, MaterialDef> MaterialMap =
            new Dictionary<string, MaterialDef>(StringComparer.OrdinalIgnoreCase)
        {
            { "Steel",     new MaterialDef { Family="Steel",    Name="S235",   E=21000, G12=8076, G3=8076, Gamma=78.5, Ft=23.5, Fc=-23.5, AlphaT=1.2e-5, YieldMPa=235 } },
            { "S235",      new MaterialDef { Family="Steel",    Name="S235",   E=21000, G12=8076, G3=8076, Gamma=78.5, Ft=23.5, Fc=-23.5, AlphaT=1.2e-5, YieldMPa=235 } },
            { "S355",      new MaterialDef { Family="Steel",    Name="S355",   E=21000, G12=8076, G3=8076, Gamma=78.5, Ft=35.5, Fc=-35.5, AlphaT=1.2e-5, YieldMPa=355 } },
            { "Concrete",  new MaterialDef { Family="Concrete", Name="C30/37", E=3300,  G12=1375, G3=1375, Gamma=25.0, Ft=0.29, Fc=-3.0,  AlphaT=1.0e-5, YieldMPa=30  } },
            { "C30/37",    new MaterialDef { Family="Concrete", Name="C30/37", E=3300,  G12=1375, G3=1375, Gamma=25.0, Ft=0.29, Fc=-3.0,  AlphaT=1.0e-5, YieldMPa=30  } },
            { "Wood",      new MaterialDef { Family="Wood",     Name="C24",    E=1100,  G12=69,   G3=69,   Gamma=4.2,  Ft=1.4,  Fc=-2.1,  AlphaT=5.0e-6, YieldMPa=24  } },
            { "C24",       new MaterialDef { Family="Wood",     Name="C24",    E=1100,  G12=69,   G3=69,   Gamma=4.2,  Ft=1.4,  Fc=-2.1,  AlphaT=5.0e-6, YieldMPa=24  } },
            { "Aluminium", new MaterialDef { Family="Aluminium", Name="AlMgSi", E=7000, G12=2700, G3=2700, Gamma=27.0, Ft=27.0, Fc=-27.0, AlphaT=2.3e-5, YieldMPa=270 } },
            { "Aluminum",  new MaterialDef { Family="Aluminium", Name="AlMgSi", E=7000, G12=2700, G3=2700, Gamma=27.0, Ft=27.0, Fc=-27.0, AlphaT=2.3e-5, YieldMPa=270 } },
        };

        /// <summary>Yield strength (MPa) for the given material name, for checks.</summary>
        public static double YieldStrengthMPa(string materialName)
        {
            MaterialDef def;
            return MaterialMap.TryGetValue(materialName ?? "Steel", out def)
                ? def.YieldMPa : 235.0;
        }

        // ── Assembly loading ─────────────────────────────────────────────────

        private static readonly object LoadLock = new object();
        private static bool _loadAttempted;
        private static string _loadFailure;
        [System.Runtime.InteropServices.DllImport("kernel32.dll", CharSet = System.Runtime.InteropServices.CharSet.Unicode, SetLastError = true)]
        private static extern bool SetDllDirectory(string lpPathName);

        private static Assembly _karambaCommonAsm;   // karambaCommon.dll
        private static Assembly _karambaAsm;         // Karamba.dll (optional)
        private static string _resolvedDir;

        /// <summary>True when karambaCommon could be located and loaded.</summary>
        public static bool IsAvailable(out string reason)
        {
            EnsureLoaded();
            reason = _loadFailure;
            return _karambaCommonAsm != null;
        }

        private static void EnsureLoaded()
        {
            lock (LoadLock)
            {
                if (_loadAttempted) return;
                _loadAttempted = true;

                // 0. Karamba may already be loaded into the AppDomain because
                //    the Karamba Grasshopper plugin loaded first. Prefer that.
                foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
                {
                    var n = asm.GetName().Name ?? "";
                    if (n.Equals("karambaCommon", StringComparison.OrdinalIgnoreCase) ||
                        n.Equals("KarambaCommon", StringComparison.OrdinalIgnoreCase))
                        _karambaCommonAsm = asm;
                    if (n.Equals("Karamba", StringComparison.OrdinalIgnoreCase))
                        _karambaAsm = asm;
                }
                if (_karambaCommonAsm != null) return;

                // 1. Probe candidate folders for karambaCommon.dll.
                var candidates = new List<string>();
                if (!string.IsNullOrEmpty(OverridePluginPath))
                    candidates.Add(OverridePluginPath);

                string envDir = Environment.GetEnvironmentVariable("ALMOND_KARAMBA_DIR");
                if (!string.IsNullOrEmpty(envDir))
                    candidates.Add(envDir);

                string programFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
                // Standard Karamba 3.x installer location for Rhino 8.
                candidates.Add(Path.Combine(programFiles, "Rhino 8", "Plug-ins", "Karamba"));
                candidates.Add(Path.Combine(programFiles, "Rhino 8", "Plug-ins", "Karamba3D"));
                // Karamba installed through the Rhino package manager (yak).
                string appData = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
                string yakRoot = Path.Combine(appData, "McNeel", "Rhinoceros", "packages", "8.0");
                foreach (var pkgName in new[] { "Karamba3D", "Karamba" })
                {
                    string pkgDir = Path.Combine(yakRoot, pkgName);
                    if (Directory.Exists(pkgDir))
                    {
                        // Pick the highest version subfolder.
                        var versions = Directory.GetDirectories(pkgDir)
                            .OrderByDescending(d => d, StringComparer.OrdinalIgnoreCase);
                        candidates.AddRange(versions);
                    }
                }

                // Karamba 3.1 yak packages nest assemblies per target framework
                // (<version>\net48\KarambaCommon.dll); probe those alongside
                // each candidate directory itself.
                foreach (var dir in candidates.ToArray())
                {
                    if (string.IsNullOrEmpty(dir)) continue;
                    candidates.Add(Path.Combine(dir, "net48"));
                }

                string dllDir = null;
                foreach (var dir in candidates)
                {
                    try
                    {
                        if (!string.IsNullOrEmpty(dir) &&
                            File.Exists(Path.Combine(dir, "karambaCommon.dll")))
                        {
                            dllDir = dir;
                            break;
                        }
                    }
                    catch { /* inaccessible path, keep probing */ }
                }

                if (dllDir == null)
                {
                    // Do not latch the failure: Karamba may be installed (or
                    // ALMOND_KARAMBA_DIR set) later in the session, so the
                    // next analysis call should probe again.
                    _loadAttempted = false;
                    _loadFailure = "api_unavailable: karambaCommon.dll not found. Probed: " +
                        string.Join("; ", candidates.Where(c => !string.IsNullOrEmpty(c)));
                    return;
                }

                try
                {
                    _resolvedDir = dllDir;
                    // Serve Karamba's own dependency loads from the same folder.
                    AppDomain.CurrentDomain.AssemblyResolve += ResolveFromKarambaDir;

                    // Karamba's FE core (karambafeb) is native code behind
                    // P/Invoke; side-loading the managed assemblies is not
                    // enough because Windows won't search this folder for the
                    // native DLLs. Put it on both native search paths before
                    // anything touches feb.karambafebPINVOKE - a failed type
                    // initializer is poisoned for the rest of the session.
                    SetDllDirectory(dllDir);
                    string path = Environment.GetEnvironmentVariable("PATH") ?? "";
                    if (path.IndexOf(dllDir, StringComparison.OrdinalIgnoreCase) < 0)
                        Environment.SetEnvironmentVariable("PATH", dllDir + ";" + path);

                    _karambaCommonAsm = Assembly.LoadFrom(Path.Combine(dllDir, "karambaCommon.dll"));

                    string karambaDll = Path.Combine(dllDir, "Karamba.dll");
                    if (File.Exists(karambaDll))
                        _karambaAsm = Assembly.LoadFrom(karambaDll);
                }
                catch (Exception ex)
                {
                    _karambaCommonAsm = null;
                    _loadAttempted = false; // allow a re-probe next call
                    _loadFailure = "api_unavailable: failed to load Karamba assemblies from " +
                        dllDir + ": " + ex.Message;
                }
            }
        }

        private static Assembly ResolveFromKarambaDir(object sender, ResolveEventArgs args)
        {
            if (_resolvedDir == null) return null;
            try
            {
                string name = new AssemblyName(args.Name).Name + ".dll";
                string candidate = Path.Combine(_resolvedDir, name);
                if (File.Exists(candidate)) return Assembly.LoadFrom(candidate);
            }
            catch { }
            return null;
        }

        // ── Reflection plumbing ──────────────────────────────────────────────

        private static Type FindType(params string[] fullNames)
        {
            var assemblies = new List<Assembly>();
            if (_karambaCommonAsm != null) assemblies.Add(_karambaCommonAsm);
            if (_karambaAsm != null) assemblies.Add(_karambaAsm);
            assemblies.AddRange(AppDomain.CurrentDomain.GetAssemblies()
                .Where(a => (a.GetName().Name ?? "").IndexOf("aramba", StringComparison.OrdinalIgnoreCase) >= 0));

            foreach (var name in fullNames)
            {
                foreach (var asm in assemblies.Distinct())
                {
                    Type t = null;
                    try { t = asm.GetType(name, false); } catch { }
                    if (t != null) return t;
                }
            }
            throw new InvalidOperationException(
                "Karamba type not found: " + string.Join(" | ", fullNames));
        }

        private static string NormalizeName(string s)
            => (s ?? "").Replace("_", "").ToLowerInvariant();

        /// <summary>
        /// Invoke a method by name with named arguments, tolerant of overload
        /// and parameter-name drift between karambaCommon builds. Unmatched
        /// optional parameters take their declared defaults; out/ref params
        /// are captured into outValues keyed by parameter name.
        /// </summary>
        private static object InvokeNamed(object target, Type type, string methodName,
            Dictionary<string, object> namedArgs, Dictionary<string, object> outValues)
        {
            var flags = BindingFlags.Public |
                (target == null ? BindingFlags.Static : BindingFlags.Instance);

            var candidates = type.GetMethods(flags)
                .Where(m => string.Equals(m.Name, methodName, StringComparison.OrdinalIgnoreCase))
                .OrderByDescending(m => CountNameMatches(m, namedArgs))
                .ThenBy(m => m.GetParameters().Length)
                .ToList();

            if (candidates.Count == 0)
                throw new InvalidOperationException(
                    $"Karamba method not found: {type.FullName}.{methodName}");

            Exception last = null;
            foreach (var method in candidates)
            {
                var pars = method.GetParameters();
                var args = new object[pars.Length];
                bool buildable = true;

                for (int i = 0; i < pars.Length; i++)
                {
                    var p = pars[i];
                    var pType = p.ParameterType.IsByRef
                        ? p.ParameterType.GetElementType() : p.ParameterType;

                    object matched;
                    if (TryMatchArg(p.Name, namedArgs, out matched))
                    {
                        object coerced;
                        if (TryCoerce(matched, pType, out coerced))
                        {
                            args[i] = coerced;
                            continue;
                        }
                    }

                    if (p.IsOut || p.ParameterType.IsByRef)
                    {
                        args[i] = pType.IsValueType ? Activator.CreateInstance(pType) : null;
                        continue;
                    }
                    if (p.HasDefaultValue)
                    {
                        args[i] = FixDefault(p.DefaultValue, pType);
                        continue;
                    }
                    // Required parameter we cannot supply: try an empty list for
                    // collection types, default for value types, null otherwise.
                    object filler;
                    if (TryMakeFiller(pType, out filler)) { args[i] = filler; continue; }
                    buildable = false;
                    break;
                }

                if (!buildable) continue;

                try
                {
                    object result = method.Invoke(target, args);
                    if (outValues != null)
                    {
                        for (int i = 0; i < pars.Length; i++)
                        {
                            if (pars[i].IsOut || pars[i].ParameterType.IsByRef)
                                outValues[pars[i].Name] = args[i];
                        }
                    }
                    return result;
                }
                catch (TargetInvocationException tie)
                {
                    last = tie.InnerException ?? tie;
                }
                catch (Exception ex)
                {
                    last = ex;
                }
            }

            throw new InvalidOperationException(
                $"All overloads of {type.FullName}.{methodName} failed." +
                (last != null ? " Last error: " + last.Message : ""), last);
        }

        private static int CountNameMatches(MethodInfo m, Dictionary<string, object> namedArgs)
        {
            int n = 0;
            foreach (var p in m.GetParameters())
            {
                object dummy;
                if (TryMatchArg(p.Name, namedArgs, out dummy)) n++;
            }
            return n;
        }

        // Parameter-name drift observed across karambaCommon builds: 3.1.60519
        // (yak) names LineToBeam/MeshToShell parameters "curves"/"identifiers"
        // where earlier builds used "lines"/"ids". Keys are normalized names.
        private static readonly Dictionary<string, string[]> ParamSynonyms =
            new Dictionary<string, string[]>
            {
                { "curves", new[] { "lines" } },
                { "lines", new[] { "curves" } },
                { "identifiers", new[] { "ids" } },
                { "ids", new[] { "identifiers" } },
                // 3.1.60921: IsotropicMaterial(.., E, Gip, Gtr, ..) — unmatched,
                // the shear moduli were filled with 0 and the solve went singular.
                { "gip", new[] { "g12" } },
                { "gtr", new[] { "g3" } },
                // GravityLoad(Vector3 force, ..) and CircularHollow(diameter, ..).
                { "force", new[] { "direction" } },
                { "diameter", new[] { "height" } },
            };

        private static bool TryMatchArg(string paramName, Dictionary<string, object> namedArgs,
            out object value)
        {
            value = null;
            if (namedArgs == null) return false;
            string np = NormalizeName(paramName);

            // Exact normalized match first, then known synonyms, then
            // containment either way (e.g. key "width" matches params
            // "lo_width"/"up_width").
            foreach (var kv in namedArgs)
            {
                if (NormalizeName(kv.Key) == np) { value = kv.Value; return true; }
            }
            string[] synonyms;
            if (ParamSynonyms.TryGetValue(np, out synonyms))
            {
                foreach (var kv in namedArgs)
                {
                    string nk = NormalizeName(kv.Key);
                    foreach (var syn in synonyms)
                        if (nk == syn) { value = kv.Value; return true; }
                }
            }
            foreach (var kv in namedArgs)
            {
                string nk = NormalizeName(kv.Key);
                if (nk.Length >= 3 && (np.Contains(nk) || nk.Contains(np)))
                {
                    value = kv.Value;
                    return true;
                }
            }
            return false;
        }

        private static bool TryCoerce(object value, Type targetType, out object coerced)
        {
            coerced = null;
            if (value == null)
                return !targetType.IsValueType;

            if (targetType.IsInstanceOfType(value)) { coerced = value; return true; }

            try
            {
                if (targetType.IsEnum)
                {
                    coerced = value is string s
                        ? Enum.Parse(targetType, s, true)
                        : Enum.ToObject(targetType, value);
                    return true;
                }
                if (value is IConvertible && typeof(IConvertible).IsAssignableFrom(targetType))
                {
                    coerced = Convert.ChangeType(value, targetType);
                    return true;
                }
            }
            catch { }
            return false;
        }

        private static object FixDefault(object declared, Type pType)
        {
            if (declared == null && pType.IsValueType && Nullable.GetUnderlyingType(pType) == null)
                return Activator.CreateInstance(pType);
            return declared;
        }

        private static bool TryMakeFiller(Type pType, out object filler)
        {
            filler = null;
            try
            {
                if (pType == typeof(string)) { filler = ""; return true; }
                if (pType.IsValueType) { filler = Activator.CreateInstance(pType); return true; }
                if (pType.IsGenericType)
                {
                    var def = pType.GetGenericTypeDefinition();
                    if (def == typeof(List<>))
                    {
                        filler = Activator.CreateInstance(pType);
                        return true;
                    }
                    if (def == typeof(IReadOnlyList<>) || def == typeof(IEnumerable<>) ||
                        def == typeof(IList<>))
                    {
                        filler = Activator.CreateInstance(
                            typeof(List<>).MakeGenericType(pType.GetGenericArguments()[0]));
                        return true;
                    }
                }
            }
            catch { }
            return false;
        }

        /// <summary>Build a List&lt;T&gt; of a runtime-only element type.</summary>
        private static object MakeList(Type elemType, IEnumerable<object> items)
        {
            var list = (IList)Activator.CreateInstance(typeof(List<>).MakeGenericType(elemType));
            if (items != null)
                foreach (var it in items) list.Add(it);
            return list;
        }

        private static object GetFactory(object toolkit, string propertyName)
        {
            // karambaCommon 3.1: KarambaCommon.Toolkit exposes factory
            // properties Part, Material, CroSec, Load, Support, Model,
            // Algorithms (Karamba.Factories.* instances).
            var prop = toolkit.GetType().GetProperty(propertyName,
                BindingFlags.Public | BindingFlags.Instance);
            if (prop == null)
                throw new InvalidOperationException(
                    "KarambaCommon.Toolkit has no factory property '" + propertyName + "'.");
            return prop.GetValue(toolkit);
        }

        // ── Karamba geometry constructors (Karamba.Geometry namespace) ──────

        private static object NewPoint3(double xM, double yM, double zM)
        {
            // karambaCommon 3.1: Karamba.Geometry.Point3(double x, double y, double z)
            var t = FindType("Karamba.Geometry.Point3");
            return Activator.CreateInstance(t, xM, yM, zM);
        }

        private static object NewVector3(double x, double y, double z)
        {
            // karambaCommon 3.1: Karamba.Geometry.Vector3(double x, double y, double z)
            var t = FindType("Karamba.Geometry.Vector3");
            return Activator.CreateInstance(t, x, y, z);
        }

        private static object NewLine3(object p0, object p1)
        {
            // karambaCommon 3.1: Karamba.Geometry.Line3(Point3 a, Point3 b)
            var t = FindType("Karamba.Geometry.Line3");
            return Activator.CreateInstance(t, p0, p1);
        }

        private static object NewMesh3(Mesh rhinoMesh, double unitScaleToMeters)
        {
            // karambaCommon 3.1: Karamba.Geometry.Mesh3 with
            // AddVertex(double x, double y, double z) / AddVertex(Point3) and
            // AddFace(int a, int b, int c) / AddFace(int a, int b, int c, int d).
            var t = FindType("Karamba.Geometry.Mesh3");
            object mesh3 = Activator.CreateInstance(t);

            var addVertexXYZ = t.GetMethod("AddVertex",
                new[] { typeof(double), typeof(double), typeof(double) });
            var addVertexPt = addVertexXYZ == null
                ? t.GetMethods().FirstOrDefault(m => m.Name == "AddVertex" &&
                    m.GetParameters().Length == 1)
                : null;

            foreach (var v in rhinoMesh.Vertices)
            {
                double x = Units.LenM(v.X, unitScaleToMeters);
                double y = Units.LenM(v.Y, unitScaleToMeters);
                double z = Units.LenM(v.Z, unitScaleToMeters);
                if (addVertexXYZ != null)
                    addVertexXYZ.Invoke(mesh3, new object[] { x, y, z });
                else if (addVertexPt != null)
                    addVertexPt.Invoke(mesh3, new object[] { NewPoint3(x, y, z) });
                else
                    throw new InvalidOperationException("Mesh3.AddVertex not found.");
            }

            var addFace3 = t.GetMethod("AddFace",
                new[] { typeof(int), typeof(int), typeof(int) });
            var addFace4 = t.GetMethod("AddFace",
                new[] { typeof(int), typeof(int), typeof(int), typeof(int) });
            if (addFace3 == null)
                throw new InvalidOperationException("Mesh3.AddFace(int,int,int) not found.");

            foreach (var f in rhinoMesh.Faces)
            {
                if (f.IsQuad && addFace4 != null)
                    addFace4.Invoke(mesh3, new object[] { f.A, f.B, f.C, f.D });
                else if (f.IsQuad)
                {
                    addFace3.Invoke(mesh3, new object[] { f.A, f.B, f.C });
                    addFace3.Invoke(mesh3, new object[] { f.A, f.C, f.D });
                }
                else
                    addFace3.Invoke(mesh3, new object[] { f.A, f.B, f.C });
            }
            return mesh3;
        }

        // ── Public facade ────────────────────────────────────────────────────

        /// <summary>
        /// Build a Karamba model from conditioned geometry and run a first
        /// order (Theory I) analysis. Never throws for Karamba availability
        /// problems; returns Available = false with FailureReason instead.
        /// </summary>
        public static KarambaResults BuildAndAnalyze(KarambaModelSpec spec)
        {
            var res = new KarambaResults();

            string reason;
            if (!IsAvailable(out reason))
            {
                res.Available = false;
                res.FailureReason = reason ?? "api_unavailable: Karamba assemblies not loaded.";
                return res;
            }

            if (spec?.Conditioned == null ||
                (spec.Conditioned.Beams.Count == 0 && spec.Conditioned.Shells.Count == 0))
            {
                res.Available = false;
                res.FailureReason = "api_unavailable: no analyzable geometry after conditioning.";
                return res;
            }

            try
            {
                RunAnalysis(spec, res);
                res.Available = true;
            }
            catch (Exception ex)
            {
                res.Available = false;
                res.FailureReason = "api_failed: " + ex.Message;
            }
            return res;
        }

        private static void RunAnalysis(KarambaModelSpec spec, KarambaResults res)
        {
            var cond = spec.Conditioned;
            double scale = cond.UnitScaleToMeters;
            double tolM = Math.Max(cond.Tolerance * scale, 1e-6);

            MaterialDef matDef;
            if (!MaterialMap.TryGetValue(spec.MaterialName ?? "Steel", out matDef))
            {
                matDef = MaterialMap["Steel"];
                res.Warnings.Add($"Unknown material '{spec.MaterialName}', using Steel S235.");
            }

            // karambaCommon 3.1: KarambaCommon.Toolkit — entry point facade
            // exposing Part/Material/CroSec/Load/Support/Model/Algorithms factories.
            var toolkitType = FindType("KarambaCommon.Toolkit");
            object k3d = Activator.CreateInstance(toolkitType);

            // karambaCommon 3.1: Karamba.Utilities.MessageLogger — collects
            // warnings emitted by the factory methods.
            object logger;
            try
            {
                logger = Activator.CreateInstance(
                    FindType("Karamba.Utilities.MessageLogger", "KarambaCommon.MessageLogger"));
            }
            catch
            {
                logger = null;
                res.Warnings.Add("Karamba MessageLogger unavailable; factory warnings not captured.");
            }

            // ── Material ─────────────────────────────────────────────────────
            // karambaCommon 3.1: Karamba.Factories.FactoryMaterial.IsotropicMaterial(
            //   string family, string name, double E, double G12, double G3,
            //   double gamma, double ft, double fc,
            //   FemMaterial.FlowHypothesis flowHypothesis, double alphaT)
            // Units: the factory takes E/G/ft/fc in kN/m^2 (the GH UI shows
            // kN/cm^2; the table above is kN/cm^2, hence x1e4), gamma in kN/m^3.
            // Verified live (3.1.60921): a 3 m CHS 114.3x4 cantilever deflects
            // ~0.1 m with kN/m^2 and ~1 km with kN/cm^2.
            const double KNcm2ToKNm2 = 1e4;
            var materialFactory = GetFactory(k3d, "Material");
            object material = InvokeNamed(materialFactory, materialFactory.GetType(),
                "IsotropicMaterial",
                new Dictionary<string, object>
                {
                    { "family", matDef.Family },
                    { "name", matDef.Name },
                    { "E", matDef.E * KNcm2ToKNm2 },
                    { "G12", matDef.G12 * KNcm2ToKNm2 },
                    { "G3", matDef.G3 * KNcm2ToKNm2 },
                    { "gamma", matDef.Gamma },
                    { "ft", matDef.Ft * KNcm2ToKNm2 },
                    { "fc", matDef.Fc * KNcm2ToKNm2 },
                    { "alphaT", matDef.AlphaT },
                },
                null);

            // ── Element and node bookkeeping ─────────────────────────────────
            var croSecFactory = GetFactory(k3d, "CroSec");
            var elementGuids = new List<List<string>>();  // parallel to assembled elements
            var nodePoints = new List<Point3d>();          // meters, for supports/loads

            void RegisterNode(Point3d pM)
            {
                foreach (var q in nodePoints)
                    if (q.DistanceTo(pM) <= tolM) return;
                nodePoints.Add(pM);
            }

            // ── Beams: LineToBeam ────────────────────────────────────────────
            var lineObjs = new List<object>();
            var segEnds = new List<Point3d[]>();   // meters, parallel to lineObjs
            var beamIds = new List<object>();
            var beamCroSecs = new List<object>();

            foreach (var beam in cond.Beams)
            {
                // Straighten: Karamba beams are straight; polygonize curved axes.
                var segments = new List<Line>();
                if (beam.Axis.IsLinear(cond.Tolerance))
                {
                    segments.Add(new Line(beam.Axis.PointAtStart, beam.Axis.PointAtEnd));
                }
                else
                {
                    var poly = beam.Axis.ToPolyline(cond.Tolerance, 0.1, 0,
                        beam.Axis.GetLength())?.ToPolyline();
                    if (poly == null)
                    {
                        res.Warnings.Add("A curved beam axis could not be polygonized; skipped. " +
                            "GUIDs: " + string.Join(",", beam.SourceGuids));
                        continue;
                    }
                    segments.AddRange(poly.GetSegments());
                }

                object croSec = BuildBeamCroSec(croSecFactory, beam.Section, material,
                    scale, res.Warnings);

                foreach (var seg in segments)
                {
                    var a = new Point3d(Units.LenM(seg.From.X, scale),
                                        Units.LenM(seg.From.Y, scale),
                                        Units.LenM(seg.From.Z, scale));
                    var b = new Point3d(Units.LenM(seg.To.X, scale),
                                        Units.LenM(seg.To.Y, scale),
                                        Units.LenM(seg.To.Z, scale));
                    if (a.DistanceTo(b) <= tolM) continue;

                    lineObjs.Add(NewLine3(NewPoint3(a.X, a.Y, a.Z), NewPoint3(b.X, b.Y, b.Z)));
                    segEnds.Add(new[] { a, b });
                    beamIds.Add(beam.SourceGuids.FirstOrDefault() ?? "beam");
                    beamCroSecs.Add(croSec);
                    elementGuids.Add(new List<string>(beam.SourceGuids));
                    RegisterNode(a);
                    RegisterNode(b);
                }
            }

            var partFactory = GetFactory(k3d, "Part");
            var builderElements = new List<object>();

            var line3Type = FindType("Karamba.Geometry.Line3");
            var croSecType = FindType("Karamba.CrossSections.CroSec");

            if (lineObjs.Count > 0)
            {
                // karambaCommon 3.1: Karamba.Factories.FactoryPart.LineToBeam(
                //   List<Line3> lines, List<string> ids, List<CroSec> crosecs,
                //   MessageLogger info, out List<Point3> outPoints, ...)
                // Geometry in meters. Returns List<BuilderBeam>.
                var outs = new Dictionary<string, object>();
                var named = new Dictionary<string, object>
                {
                    { "lines", MakeList(line3Type, lineObjs) },
                    { "ids", beamIds.Cast<object>().Select(o => (string)o).ToList() },
                    { "crosecs", MakeList(croSecType, beamCroSecs) },
                };
                if (logger != null) named["info"] = logger;

                object beamsResult = InvokeNamed(partFactory, partFactory.GetType(),
                    "LineToBeam", named, outs);
                foreach (var item in (IEnumerable)beamsResult)
                    builderElements.Add(item);
            }

            // ── Shells: MeshToShell ──────────────────────────────────────────
            if (cond.Shells.Count > 0)
            {
                var mesh3Type = FindType("Karamba.Geometry.Mesh3");
                var meshObjs = new List<object>();
                var shellIds = new List<string>();
                var shellCroSecs = new List<object>();

                foreach (var shell in cond.Shells)
                {
                    meshObjs.Add(NewMesh3(shell.Mesh, scale));
                    shellIds.Add(shell.SourceGuids.FirstOrDefault() ?? "shell");

                    // karambaCommon 3.1: Karamba.Factories.FactoryCroSec.ShellConst(
                    //   double height, double offset, FemMaterial material,
                    //   string name, string family)
                    // height = shell thickness in CENTIMETERS.
                    double thickCm = Units.SectionCm(shell.Section.ShellThickness, scale);
                    if (thickCm <= 0) thickCm = 10.0; // 100 mm fallback
                    object shellSec = InvokeNamed(croSecFactory, croSecFactory.GetType(),
                        "ShellConst",
                        new Dictionary<string, object>
                        {
                            { "height", thickCm },
                            { "material", material },
                            { "name", "ALMOND_SHELL" },
                            { "family", "ALMOND" },
                        },
                        null);
                    shellCroSecs.Add(shellSec);

                    foreach (var v in shell.Mesh.Vertices)
                        RegisterNode(new Point3d(Units.LenM(v.X, scale),
                            Units.LenM(v.Y, scale), Units.LenM(v.Z, scale)));

                    elementGuids.Add(new List<string>(shell.SourceGuids));
                }

                // karambaCommon 3.1: Karamba.Factories.FactoryPart.MeshToShell(
                //   List<Mesh3> meshes, List<string> ids, List<CroSec> crosecs,
                //   MessageLogger info, out List<Point3> outPoints)
                // Geometry in meters. Returns List<BuilderShell>.
                var outs = new Dictionary<string, object>();
                var named = new Dictionary<string, object>
                {
                    { "meshes", MakeList(mesh3Type, meshObjs) },
                    { "ids", shellIds },
                    { "crosecs", MakeList(croSecType, shellCroSecs) },
                };
                if (logger != null) named["info"] = logger;

                object shellsResult = InvokeNamed(partFactory, partFactory.GetType(),
                    "MeshToShell", named, outs);
                foreach (var item in (IEnumerable)shellsResult)
                    builderElements.Add(item);
            }

            if (builderElements.Count == 0)
                throw new InvalidOperationException("No Karamba elements could be built.");

            // ── Supports ─────────────────────────────────────────────────────
            // Declared anchor points win; otherwise all lowest-Z nodes.
            var supportPtsM = new List<Point3d>();
            if (cond.AnchorPoints.Count > 0)
            {
                foreach (var p in cond.AnchorPoints)
                    supportPtsM.Add(new Point3d(Units.LenM(p.X, scale),
                        Units.LenM(p.Y, scale), Units.LenM(p.Z, scale)));
            }
            else if (nodePoints.Count > 0)
            {
                double minZ = nodePoints.Min(p => p.Z);
                supportPtsM.AddRange(nodePoints.Where(p => p.Z <= minZ + tolM));
                res.Warnings.Add($"No anchor points declared; supporting {supportPtsM.Count} " +
                    "lowest-Z node(s).");
            }

            if (supportPtsM.Count == 0)
                throw new InvalidOperationException("No support points could be determined.");

            var supportFactory = GetFactory(k3d, "Support");
            var supportType = FindType("Karamba.Supports.Support");
            var supportObjs = new List<object>();
            var fullyFixed = new List<bool> { true, true, true, spec.FixedRotations, spec.FixedRotations, spec.FixedRotations };
            res.SupportPointsM = supportPtsM.Select(p => new[] {p.X,p.Y,p.Z}).ToList();

            foreach (var p in supportPtsM)
            {
                // karambaCommon 3.1: Karamba.Factories.FactorySupport.Support(
                //   Point3 position, IReadOnlyList<bool> conditions)
                // conditions = Tx,Ty,Tz,Rx,Ry,Rz fixities; fully fixed here.
                object sup = InvokeNamed(supportFactory, supportFactory.GetType(),
                    "Support",
                    new Dictionary<string, object>
                    {
                        { "position", NewPoint3(p.X, p.Y, p.Z) },
                        { "conditions", fullyFixed },
                    },
                    null);
                supportObjs.Add(sup);
            }

            // ── Loads: gravity self weight + imposed point loads (kN) ───────
            var loadFactory = GetFactory(k3d, "Load");
            var loadType = FindType("Karamba.Loads.Load");
            var loadObjs = new List<object>();

            // karambaCommon 3.1: Karamba.Loads.GravityLoad(Vector3 direction)
            // (also reachable via Karamba.Factories.FactoryLoad.GravityLoad).
            // Direction (0,0,-1) = self weight acting downward.
            if (spec.IncludeSelfWeight)
            {
            object gravity;
            try
            {
                gravity = InvokeNamed(loadFactory, loadFactory.GetType(), "GravityLoad",
                    new Dictionary<string, object> { { "direction", NewVector3(0, 0, -1) } },
                    null);
            }
            catch
            {
                var gravityType = FindType("Karamba.Loads.GravityLoad");
                gravity = Activator.CreateInstance(gravityType, NewVector3(0, 0, -1));
            }
            loadObjs.Add(gravity);
            }

            // Imposed load: total ImposedLoadKN split evenly over free
            // (non-support) nodes; if every node is a support, use all nodes.
            var freeNodes = nodePoints
                .Where(p => !supportPtsM.Any(s => s.DistanceTo(p) <= tolM))
                .ToList();
            if (freeNodes.Count == 0) freeNodes = new List<Point3d>(nodePoints);

            if (spec.ImposedLoadKN > 0 && freeNodes.Count > 0)
            {
                res.LoadedPointsM = freeNodes.Select(p => new[] {p.X,p.Y,p.Z}).ToList();
                double perNodeKN = spec.ImposedLoadKN / freeNodes.Count;
                foreach (var p in freeNodes)
                {
                    // karambaCommon 3.1: Karamba.Factories.FactoryLoad.PointLoad(
                    //   Point3 position, Vector3 force, Vector3 moment)
                    // force in kN; -Z = downward.
                    object pl = InvokeNamed(loadFactory, loadFactory.GetType(), "PointLoad",
                        new Dictionary<string, object>
                        {
                            { "position", NewPoint3(p.X, p.Y, p.Z) },
                            { "force", NewVector3(0, 0, -perNodeKN) },
                            { "moment", NewVector3(0, 0, 0) },
                        },
                        null);
                    loadObjs.Add(pl);
                }
            }

            // ── Assemble ─────────────────────────────────────────────────────
            // karambaCommon 3.1: Karamba.Factories.FactoryModel.AssembleModel(
            //   List<BuilderElement> elems, List<Support> supports, List<Load> loads,
            //   out string info, out double mass, out Point3 cog, out string msg,
            //   out bool runtimeWarning, ...)
            // mass out param in KILOGRAMS. Returns Karamba.Models.Model.
            var modelFactory = GetFactory(k3d, "Model");
            var builderElementType = FindType("Karamba.Elements.BuilderElement");
            var assembleOuts = new Dictionary<string, object>();

            object model = InvokeNamed(modelFactory, modelFactory.GetType(), "AssembleModel",
                new Dictionary<string, object>
                {
                    { "elems", MakeList(builderElementType, builderElements) },
                    { "supports", MakeList(supportType, supportObjs) },
                    { "loads", MakeList(loadType, loadObjs) },
                },
                assembleOuts);

            double massKg = 0;
            foreach (var kv in assembleOuts)
            {
                if (kv.Value is double d && NormalizeName(kv.Key).Contains("mass"))
                { massKg = d; break; }
            }

            foreach (var kv in assembleOuts)
            {
                if (kv.Value is string s && !string.IsNullOrWhiteSpace(s))
                    res.Warnings.Add("Karamba assemble: " + s.Trim());
            }

            // ── Analyze (Theory I = first order) ─────────────────────────────
            // karambaCommon 3.1: Karamba.Factories.FactoryAlgorithms.AnalyzeThI(
            //   Model model, out IReadOnlyList<double> outMaxDisp,
            //   out IReadOnlyList<double> outG, out IReadOnlyList<double> outComp,
            //   out string warning)
            // outMaxDisp per load case in METERS. Returns the analyzed Model.
            var algorithms = GetFactory(k3d, "Algorithms");
            var analyzeOuts = new Dictionary<string, object>();
            object analyzed = InvokeNamed(algorithms, algorithms.GetType(), "AnalyzeThI",
                new Dictionary<string, object> { { "model", model } },
                analyzeOuts);
            if (analyzed == null) analyzed = model;

            double maxDispM = 0;
            bool dispFound = false;
            foreach (var kv in analyzeOuts)
            {
                if (!NormalizeName(kv.Key).Contains("disp")) continue;
                var doubles = FlattenDoubles(kv.Value).ToList();
                if (doubles.Count > 0)
                {
                    maxDispM = doubles.Max(Math.Abs);
                    dispFound = doubles.All(d => !double.IsNaN(d) && !double.IsInfinity(d));
                }
                break;
            }
            foreach (var kv in analyzeOuts)
            {
                if (kv.Value is string s && !string.IsNullOrWhiteSpace(s))
                    res.Warnings.Add("Karamba analyze: " + s.Trim());
            }
            if (!dispFound)
                res.Warnings.Add("AnalyzeThI returned no displacement out param; " +
                    "displacement is unavailable.");

            res.MaxDisplacementMM = maxDispM * Units.MetersToMillimeters;
            res.DisplacementAvailable = dispFound && !double.IsNaN(res.MaxDisplacementMM) && !double.IsInfinity(res.MaxDisplacementMM);

            // ── Per-element utilization ──────────────────────────────────────
            var utils = TryUtilizationBeam(analyzed, lineObjs.Count, res.Warnings)
                        ?? TryComputeUtilization(analyzed, res.Warnings);
            if (utils != null && utils.Count > 0)
            {
                int n = Math.Min(utils.Count, elementGuids.Count);
                if (utils.Count != elementGuids.Count)
                    res.Warnings.Add($"Utilization count ({utils.Count}) does not match " +
                        $"element count ({elementGuids.Count}); mapping first {n}.");
                for (int i = 0; i < n; i++)
                {
                    res.PerElementUtilization.Add(new ElementUtilization
                    {
                        SourceGuids = elementGuids[i],
                        Utilization = Math.Abs(utils[i]),
                    });
                }
                res.UtilizationAvailable = utils.Count == elementGuids.Count && utils.All(u => !double.IsNaN(u) && !double.IsInfinity(u));
            }
            else
            {
                res.Warnings.Add("Per-element utilization unavailable from the Karamba API " +
                    "in this build; utilization-based checks fall back to 0.");
            }

            // ── Displacement field (nodes + sampled members) ─────────────────
            // karambaCommon 3.1 can report 0 through AnalyzeThI's max-displacement
            // out param; the nodal field is authoritative whenever it is present.
            try
            {
                ExtractDisplacements(analyzed, segEnds, elementGuids, spec.ReturnGeometry, res);
                if (res.NodeDispM.Count > 0)
                {
                    double nodeMaxM = res.NodeDispM.Max(n => Math.Sqrt(n[3] * n[3] + n[4] * n[4] + n[5] * n[5]));
                    double sampleMaxM = res.Elements.Count > 0
                        ? res.Elements.SelectMany(e => e.SampleDispM).DefaultIfEmpty(new double[3])
                              .Max(d => Math.Sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2])) : 0;
                    double fieldMaxMM = Math.Max(nodeMaxM, sampleMaxM) * Units.MetersToMillimeters;
                    if (!res.DisplacementAvailable || fieldMaxMM > res.MaxDisplacementMM)
                    {
                        res.MaxDisplacementMM = fieldMaxMM;
                        res.DisplacementAvailable = !double.IsNaN(fieldMaxMM) && !double.IsInfinity(fieldMaxMM);
                    }
                }
            }
            catch (Exception ex)
            {
                res.Warnings.Add("Displacement field unavailable: " + ex.Message);
            }
            if (res.UtilizationAvailable && res.Elements.Count > 0)
                for (int i = 0; i < res.Elements.Count && i < res.PerElementUtilization.Count; i++)
                    res.Elements[i].Utilization = res.PerElementUtilization[i].Utilization;

            // Derived stress: max utilization x yield (documented in Units block).
            double maxUtil = res.PerElementUtilization.Count > 0
                ? res.PerElementUtilization.Max(u => u.Utilization) : 0;
            res.MaxStressMPa = maxUtil * matDef.YieldMPa;

            // Reactions from vertical equilibrium (documented in Units block).
            res.ReactionsKN = (spec.IncludeSelfWeight ? massKg * Units.GravityMS2 / 1000.0 : 0) + spec.ImposedLoadKN;
        }

        private static object BuildBeamCroSec(object croSecFactory, SectionSpec section,
            object material, double unitScaleToMeters, List<string> warnings)
        {
            section = section ?? SectionSpec.DefaultBeam(unitScaleToMeters);

            if (section.Shape == "box")
            {
                double hCm = Units.SectionCm(section.Height, unitScaleToMeters);
                double wCm = Units.SectionCm(section.Width, unitScaleToMeters);
                double tCm = Units.SectionCm(section.WallThickness, unitScaleToMeters);
                if (hCm > 0 && wCm > 0)
                {
                    try
                    {
                        // karambaCommon 3.1: Karamba.Factories.FactoryCroSec.Box(
                        //   string name, string family, FemMaterial material,
                        //   double height, double lo_width, double up_width,
                        //   double thickness, ...)  — dimensions in CENTIMETERS.
                        return InvokeNamed(croSecFactory, croSecFactory.GetType(), "Box",
                            new Dictionary<string, object>
                            {
                                { "name", "ALMOND_BOX" },
                                { "family", "ALMOND" },
                                { "material", material },
                                { "height", hCm },
                                { "width", wCm },
                                { "thickness", Math.Max(tCm, 0.1) },
                            },
                            null);
                    }
                    catch (Exception ex)
                    {
                        warnings.Add("Box section failed (" + ex.Message +
                            "); falling back to circular hollow.");
                    }
                }
            }

            double diaCm = Units.SectionCm(section.Diameter, unitScaleToMeters);
            double wallCm = Units.SectionCm(section.WallThickness, unitScaleToMeters);
            if (diaCm <= 0) { diaCm = 11.43; wallCm = 0.4; } // CHS 114.3x4 default

            // karambaCommon 3.1: Karamba.Factories.FactoryCroSec.CircularHollow(
            //   string name, string family, FemMaterial material,
            //   double height, double thickness)
            // height = outer DIAMETER in cm, thickness = wall in cm.
            return InvokeNamed(croSecFactory, croSecFactory.GetType(), "CircularHollow",
                new Dictionary<string, object>
                {
                    { "name", "ALMOND_CHS" },
                    { "family", "ALMOND" },
                    { "material", material },
                    { "height", diaCm },
                    { "thickness", Math.Max(wallCm, 0.1) },
                },
                null);
        }

        private static double[] Xyz(object v)
        {
            if (v == null) return new double[3];
            var t = v.GetType();
            double Get(string n)
            {
                var pr = t.GetProperty(n); if (pr != null) return Convert.ToDouble(pr.GetValue(v));
                var f = t.GetField(n); if (f != null) return Convert.ToDouble(f.GetValue(v));
                return 0;
            }
            return new[] { Get("X"), Get("Y"), Get("Z") };
        }

        private static List<object> AsList(object o)
        {
            var list = new List<object>();
            if (o is IEnumerable seq && !(o is string)) foreach (var x in seq) list.Add(x);
            return list;
        }

        /// <summary>First-load-case vector from an entry that is either a vector or a per-load-case list.</summary>
        private static double[] FirstVector(object entry)
        {
            if (entry is IEnumerable && !(entry is string))
            {
                var l = AsList(entry);
                return l.Count > 0 ? FirstVector(l[0]) : new double[3];
            }
            return Xyz(entry);
        }

        /// <summary>
        /// Nodal translations (and, when requested, displacements sampled along
        /// every beam) from the analysed model, first load case.
        /// </summary>
        private static void ExtractDisplacements(object model, List<Point3d[]> segEnds,
            List<List<string>> elementGuids, bool withMembers, KarambaResults res)
        {
            // karambaCommon 3.1: Karamba.Results.NodeDisplacements.solve(Model model,
            //   string resultSelection, List<int> nodeIndexes, out List<List<Vector3>> trans,
            //   out List<List<Vector3>> rotat, out .. governingLoadCases, out .. Inds,
            //   out List<Point3> positions)  — empty nodeIndexes = all nodes, meters.
            var ndType = FindType("Karamba.Results.NodeDisplacements");
            string selection = null;
            foreach (var sel in new[] { "0", "LC0", "" })
            {
                var nOuts = new Dictionary<string, object>();
                InvokeNamed(null, ndType, "solve", new Dictionary<string, object>
                {
                    { "model", model }, { "resultSelection", sel }, { "nodeIndexes", new List<int>() },
                }, nOuts);
                var positions = AsList(nOuts.TryGetValue("positions", out var po) ? po : null);
                var trans = AsList(nOuts.TryGetValue("trans", out var tr) ? tr : null);
                var rotat = AsList(nOuts.TryGetValue("rotat", out var ro) ? ro : null);
                // Orientation of the nested list differs between builds: [node][lc] or [lc][node].
                List<object> PerNode(List<object> field) => field.Count == positions.Count ? field
                    : (field.Count > 0 ? AsList(field[0]) : new List<object>());
                var perNode = PerNode(trans); var perNodeRot = PerNode(rotat);
                var rows = new List<double[]>();
                for (int i = 0; i < positions.Count && i < perNode.Count; i++)
                {
                    var p = Xyz(positions[i]); var d = FirstVector(perNode[i]);
                    var r = i < perNodeRot.Count ? FirstVector(perNodeRot[i]) : new double[3];
                    rows.Add(new[] { p[0], p[1], p[2], d[0], d[1], d[2], r[0], r[1], r[2] });
                }
                if (rows.Count == 0 || rows.Any(r => r.Skip(3).Any(v => double.IsNaN(v) || double.IsInfinity(v))))
                    continue;
                res.NodeDispM = rows;
                selection = sel;
                break;
            }
            if (selection == null)
            {
                res.Warnings.Add("Nodal displacements are not finite (singular model: check supports and sections).");
                return;
            }
            if (!withMembers || segEnds.Count == 0) return;

            // karambaCommon 3.1: Karamba.Results.BeamDisplacements.solve(Model model,
            //   List<string> elementsIDs, string resultSelection, double maxResultsDistance,
            //   int minResultsIntervals, out List<List<List<Vector3>>> translations, ...,
            //   out List<int> elementInds)  — equally spaced stations along each beam.
            try
            {
            var bdType = FindType("Karamba.Results.BeamDisplacements");
            var bOuts = new Dictionary<string, object>();
            InvokeNamed(null, bdType, "solve", new Dictionary<string, object>
            {
                { "model", model }, { "elementsIDs", new List<string>() }, { "resultSelection", selection },
                { "maxResultsDistance", 0.2 }, { "minResultsIntervals", 10 },
            }, bOuts);
            var bt = AsList(bOuts.TryGetValue("translations", out var bto) ? bto : null);
            var inds = AsList(bOuts.TryGetValue("elementInds", out var eio) ? eio : null)
                .Select(x => x == null ? -1 : Convert.ToInt32(x)).ToList();
            // [elem][station][lc] expected; tolerate [lc][elem][station].
            if (bt.Count == 1 && segEnds.Count > 1) bt = AsList(bt[0]);
            for (int r = 0; r < bt.Count; r++)
            {
                int e = r < inds.Count && inds[r] >= 0 ? inds[r] : r;
                if (e < 0 || e >= segEnds.Count) continue;
                var el = new ElementDeflection
                {
                    SourceGuids = e < elementGuids.Count ? new List<string>(elementGuids[e]) : new List<string>(),
                    StartM = new[] { segEnds[e][0].X, segEnds[e][0].Y, segEnds[e][0].Z },
                    EndM = new[] { segEnds[e][1].X, segEnds[e][1].Y, segEnds[e][1].Z },
                };
                foreach (var st in AsList(bt[r])) el.SampleDispM.Add(FirstVector(st));
                res.Elements.Add(el);
            }
            res.Elements = res.Elements.OrderBy(x => segEnds.FindIndex(sg =>
                sg[0].X == x.StartM[0] && sg[0].Y == x.StartM[1] && sg[0].Z == x.StartM[2] &&
                sg[1].X == x.EndM[0] && sg[1].Y == x.EndM[1] && sg[1].Z == x.EndM[2])).ToList();
            }
            catch (Exception ex)
            {
                res.Warnings.Add("BeamDisplacements.solve failed: " + ex.Message);
            }
            res.GeometryAvailable = res.Elements.Count == segEnds.Count && res.Elements.All(x => x.SampleDispM.Count >= 2);
            if (!res.GeometryAvailable)
            {
                res.Warnings.Add($"Member stations unavailable from BeamDisplacements ({res.Elements.Count}/{segEnds.Count} " +
                    "members); shapes interpolated from nodal translations and rotations (cubic Hermite).");
                res.Elements = HermiteMembers(segEnds, elementGuids, res.NodeDispM, 12);
                res.GeometryAvailable = res.Elements.Count == segEnds.Count;
            }
        }

        /// <summary>
        /// Deflected member shapes from end-node results: transverse displacement
        /// is the cubic Hermite of the end translations with end slopes theta x axis;
        /// exact for prismatic beams without member loads.
        /// </summary>
        private static List<ElementDeflection> HermiteMembers(List<Point3d[]> segEnds,
            List<List<string>> elementGuids, List<double[]> nodes, int intervals)
        {
            double[] Nearest(Point3d p) => nodes.OrderBy(n =>
                (n[0] - p.X) * (n[0] - p.X) + (n[1] - p.Y) * (n[1] - p.Y) + (n[2] - p.Z) * (n[2] - p.Z)).First();
            var list = new List<ElementDeflection>();
            for (int e = 0; e < segEnds.Count; e++)
            {
                Point3d a = segEnds[e][0], b = segEnds[e][1];
                var na = Nearest(a); var nb = Nearest(b);
                var axis = b - a; double len = axis.Length; axis.Unitize();
                var ua = new Vector3d(na[3], na[4], na[5]); var ub = new Vector3d(nb[3], nb[4], nb[5]);
                var sa = na.Length >= 9 ? Vector3d.CrossProduct(new Vector3d(na[6], na[7], na[8]), axis) * len : Vector3d.Zero;
                var sb = nb.Length >= 9 ? Vector3d.CrossProduct(new Vector3d(nb[6], nb[7], nb[8]), axis) * len : Vector3d.Zero;
                var el = new ElementDeflection
                {
                    SourceGuids = e < elementGuids.Count ? new List<string>(elementGuids[e]) : new List<string>(),
                    StartM = new[] { a.X, a.Y, a.Z }, EndM = new[] { b.X, b.Y, b.Z },
                };
                for (int i = 0; i <= intervals; i++)
                {
                    double t = (double)i / intervals, t2 = t * t, t3 = t2 * t;
                    var d = (2 * t3 - 3 * t2 + 1) * ua + (t3 - 2 * t2 + t) * sa
                          + (-2 * t3 + 3 * t2) * ub + (t3 - t2) * sb;
                    el.SampleDispM.Add(new[] { d.X, d.Y, d.Z });
                }
                list.Add(el);
            }
            return list;
        }

        /// <summary>
        /// karambaCommon 3.1 names the beam utilization solver
        /// Karamba.Results.Utilization_Beam.solve(Model model, List&lt;string&gt; retElemIds,
        ///   string resultSelection, int resNum, bool elastDesign, double gammaM0,
        ///   double gammaM1, bool withDetails, out List&lt;List&lt;UtilizationResults_Item&gt;&gt; modelUtil,
        ///   out List&lt;List&lt;int&gt;&gt; modelUtilLCInd, out string msg, out IEnumerable&lt;int&gt; elementInds).
        /// Returns max utilization per beam, or null when unavailable.
        /// </summary>
        private static List<double> TryUtilizationBeam(object model, int nBeams, List<string> warnings)
        {
            if (nBeams == 0) return null;
            Type ut;
            try { ut = FindType("Karamba.Results.Utilization_Beam"); }
            catch { return null; }
            foreach (var ids in new[] { new List<string>(), new List<string> { "" } })
            {
                try
                {
                    var outs = new Dictionary<string, object>();
                    InvokeNamed(null, ut, "solve", new Dictionary<string, object>
                    {
                        { "model", model }, { "retElemIds", ids }, { "resultSelection", "0" },
                        { "resNum", 5 }, { "elastDesign", true }, { "gammaM0", 1.0 }, { "gammaM1", 1.1 },
                        { "withDetails", false },
                    }, outs);
                    var rows = AsList(outs.TryGetValue("modelUtil", out var mu) ? mu : null);
                    if (rows.Count == 0) continue;
                    var vals = new List<double>();
                    foreach (var row in rows)
                    {
                        double best = double.NaN;
                        foreach (var item in AsList(row))
                        {
                            double v = ItemUtilization(item);
                            if (!double.IsNaN(v) && (double.IsNaN(best) || v > best)) best = v;
                        }
                        vals.Add(best);
                    }
                    if (vals.All(double.IsNaN)) continue;
                    return vals.Select(v => double.IsNaN(v) ? 0 : v).ToList();
                }
                catch (Exception ex)
                {
                    warnings.Add("Utilization_Beam.solve failed: " + ex.Message);
                }
            }
            return null;
        }

        /// <summary>Governing utilization of one UtilizationResults_Item (probe numeric "util" members).</summary>
        private static double ItemUtilization(object item)
        {
            if (item == null) return double.NaN;
            if (item is double dd) return dd;
            double best = double.NaN;
            foreach (var m in item.GetType().GetMembers(BindingFlags.Public | BindingFlags.Instance))
            {
                if (!NormalizeName(m.Name).Contains("util")) continue;
                object v = null;
                try
                {
                    if (m is PropertyInfo pi && pi.GetIndexParameters().Length == 0) v = pi.GetValue(item);
                    else if (m is FieldInfo fi) v = fi.GetValue(item);
                }
                catch { }
                foreach (var d in FlattenDoubles(v))
                    if (!double.IsNaN(d) && !double.IsInfinity(d) && (double.IsNaN(best) || Math.Abs(d) > best)) best = Math.Abs(d);
            }
            return best;
        }

        /// <summary>
        /// Best-effort per-element utilization. karambaCommon builds vary in
        /// the exact signature of the utilization solver, so this probes the
        /// known entry point defensively and returns null when nothing works.
        /// </summary>
        private static List<double> TryComputeUtilization(object model, List<string> warnings)
        {
            Type utilType;
            try
            {
                // karambaCommon 3.1: Karamba.Results.Utilization — static
                // solve(...) computes per-element utilization for beams/shells.
                utilType = FindType("Karamba.Results.Utilization",
                    "Karamba.Results.UtilizationOfElements");
            }
            catch (Exception ex)
            {
                warnings.Add("Karamba utilization type not found: " + ex.Message);
                return null;
            }

            var modelType = model.GetType();
            var solveMethods = utilType
                .GetMethods(BindingFlags.Public | BindingFlags.Static)
                .Where(m => string.Equals(m.Name, "solve", StringComparison.OrdinalIgnoreCase))
                .OrderBy(m => m.GetParameters().Length)
                .ToList();

            foreach (var method in solveMethods)
            {
                var pars = method.GetParameters();
                var args = new object[pars.Length];
                bool buildable = true;

                for (int i = 0; i < pars.Length; i++)
                {
                    var p = pars[i];
                    var pType = p.ParameterType.IsByRef
                        ? p.ParameterType.GetElementType() : p.ParameterType;

                    if (p.IsOut || p.ParameterType.IsByRef)
                    {
                        args[i] = pType.IsValueType ? Activator.CreateInstance(pType) : null;
                    }
                    else if (pType.IsAssignableFrom(modelType))
                    {
                        args[i] = model; // the analyzed Karamba.Models.Model
                    }
                    else if (pType == typeof(string))
                    {
                        // Load-case selector; "0" = first load case by convention.
                        args[i] = "0";
                    }
                    else if (typeof(IEnumerable<string>).IsAssignableFrom(pType))
                    {
                        // Element id filter; empty string matches all elements.
                        args[i] = new List<string> { "" };
                    }
                    else if (typeof(IEnumerable<Guid>).IsAssignableFrom(pType))
                    {
                        args[i] = new List<Guid>();
                    }
                    else if (p.HasDefaultValue)
                    {
                        args[i] = FixDefault(p.DefaultValue, pType);
                    }
                    else if (pType.IsValueType)
                    {
                        args[i] = Activator.CreateInstance(pType);
                    }
                    else
                    {
                        object filler;
                        if (TryMakeFiller(pType, out filler)) args[i] = filler;
                        else { buildable = false; break; }
                    }
                }

                if (!buildable) continue;

                try
                {
                    object ret = method.Invoke(null, args);

                    // Utilization may come back as the return value or an out
                    // param: a flat double list or an object exposing one.
                    var fromReturn = FlattenDoubles(ret).ToList();
                    if (fromReturn.Count > 0) return fromReturn;

                    for (int i = 0; i < pars.Length; i++)
                    {
                        if (!pars[i].IsOut && !pars[i].ParameterType.IsByRef) continue;
                        var flat = FlattenDoubles(args[i]).ToList();
                        if (flat.Count > 0) return flat;

                        var nested = ProbeUtilizationObject(args[i]);
                        if (nested != null && nested.Count > 0) return nested;
                    }
                }
                catch
                {
                    // Try the next overload silently; final failure is reported below.
                }
            }

            warnings.Add("Karamba.Results.Utilization.solve could not be invoked with any " +
                "known signature in this karambaCommon build.");
            return null;
        }

        private static List<double> ProbeUtilizationObject(object obj)
        {
            if (obj == null) return null;
            foreach (var prop in obj.GetType().GetProperties(
                BindingFlags.Public | BindingFlags.Instance))
            {
                if (!NormalizeName(prop.Name).Contains("util")) continue;
                try
                {
                    var flat = FlattenDoubles(prop.GetValue(obj)).ToList();
                    if (flat.Count > 0) return flat;
                }
                catch { }
            }
            return null;
        }

        /// <summary>Flatten nested enumerables into doubles (skips strings).</summary>
        private static IEnumerable<double> FlattenDoubles(object value)
        {
            if (value == null) yield break;
            if (value is double d) { yield return d; yield break; }
            if (value is float f) { yield return f; yield break; }
            if (value is int i) { yield return i; yield break; }
            if (value is string) yield break;

            if (value is IEnumerable seq)
            {
                foreach (var item in seq)
                    foreach (var v in FlattenDoubles(item))
                        yield return v;
            }
        }
    }
}
