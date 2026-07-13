using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Newtonsoft.Json;
using Rhino;
using Rhino.DocObjects;
using Rhino.Geometry;

namespace RhinoAlmondBridge
{
    /// <summary>
    /// Compiles and executes C# RhinoCommon scripts at runtime using Roslyn.
    /// Wraps all execution in an Undo block for atomic rollback on failure.
    /// </summary>
    public class ScriptExecutor
    {
        private static bool _aiaLayersCreated = false;

        /// <summary>
        /// Compiles the provided C# source code using Roslyn, executes it within Rhino,
        /// and returns the result including any created GUIDs or error traces.
        /// </summary>
        /// <param name="csharpCode">
        /// A complete C# script. It must define a class with a static Run method:
        ///   public static List&lt;Guid&gt; Run(RhinoDoc doc)
        /// The Run method should create geometry and return a list of GUIDs.
        /// </param>
        public ScriptResult Execute(string csharpCode)
        {
            var result = new ScriptResult { Status = "success" };

            EnsureAiaLayers();

            // Wrap the user's code in a namespace and using statements if not already present
            string fullSource = WrapScript(csharpCode);

            // Compile
            Assembly assembly;
            try
            {
                assembly = CompileScript(fullSource);
            }
            catch (Exception ex)
            {
                result.Status = "compile_error";
                result.Message = ex.Message;
                result.ErrorTrace = ex.ToString();
                return result;
            }

            // Execute within an Undo block
            var doc = RhinoDoc.ActiveDoc;
            uint undoSn = doc.BeginUndoRecord("MCP C# Script Execution");

            try
            {
                // Find the Run method
                var entryType = assembly.GetTypes()
                    .FirstOrDefault(t => t.GetMethod("Run", BindingFlags.Public | BindingFlags.Static) != null);

                if (entryType == null)
                {
                    result.Status = "error";
                    result.Message = "Script must contain a class with: public static List<Guid> Run(RhinoDoc doc)";
                    doc.EndUndoRecord(undoSn);
                    return result;
                }

                var runMethod = entryType.GetMethod("Run", BindingFlags.Public | BindingFlags.Static);
                var invokeResult = runMethod.Invoke(null, new object[] { doc });

                // Collect GUIDs
                if (invokeResult is List<Guid> guids)
                {
                    result.Guids = guids.Select(g => g.ToString()).ToList();

                    if (guids.Count > 0)
                        AddScaleDimensions(doc, guids);
                }

                doc.EndUndoRecord(undoSn);
                doc.Views.Redraw();
            }
            catch (TargetInvocationException ex)
            {
                // The actual exception is in InnerException
                var inner = ex.InnerException ?? ex;
                doc.EndUndoRecord(undoSn);
                doc.Undo();

                result.Status = "runtime_error";
                result.Message = inner.Message;
                result.ErrorTrace = inner.ToString();
            }
            catch (Exception ex)
            {
                doc.EndUndoRecord(undoSn);
                doc.Undo();

                result.Status = "runtime_error";
                result.Message = ex.Message;
                result.ErrorTrace = ex.ToString();
            }

            return result;
        }

        /// <summary>
        /// Wraps raw C# code in necessary using statements if they're not already present.
        /// </summary>
        private string WrapScript(string code)
        {
            // If the code already has 'using' statements, assume it's complete
            if (code.TrimStart().StartsWith("using "))
                return code;

            return $@"
using System;
using System.Collections.Generic;
using System.Linq;
using Rhino;
using Rhino.Geometry;
using Rhino.DocObjects;
using Rhino.Input;
using Rhino.Commands;

{code}
";
        }

        /// <summary>
        /// Compiles a C# source string into an in-memory assembly using Roslyn.
        /// References RhinoCommon and standard .NET assemblies.
        /// </summary>
        private Assembly CompileScript(string source)
        {
            var syntaxTree = CSharpSyntaxTree.ParseText(source);

            // Gather references: mscorlib, System, System.Core, RhinoCommon, etc.
            var references = new List<MetadataReference>();

            // Add core .NET references
            var trustedAssemblies = AppDomain.CurrentDomain.GetAssemblies()
                .Where(a => !a.IsDynamic && !string.IsNullOrEmpty(a.Location))
                .Select(a => a.Location)
                .Distinct();

            foreach (var loc in trustedAssemblies)
            {
                try
                {
                    references.Add(MetadataReference.CreateFromFile(loc));
                }
                catch { /* Skip assemblies that can't be referenced */ }
            }

            var compilation = CSharpCompilation.Create(
                assemblyName: $"MCPScript_{Guid.NewGuid():N}",
                syntaxTrees: new[] { syntaxTree },
                references: references,
                options: new CSharpCompilationOptions(
                    OutputKind.DynamicallyLinkedLibrary,
                    optimizationLevel: OptimizationLevel.Release
                )
            );

            using (var ms = new MemoryStream())
            {
                var emitResult = compilation.Emit(ms);

                if (!emitResult.Success)
                {
                    var errors = emitResult.Diagnostics
                        .Where(d => d.Severity == DiagnosticSeverity.Error)
                        .Select(d => d.ToString())
                        .ToList();

                    throw new InvalidOperationException(
                        $"C# compilation failed with {errors.Count} error(s):\n" +
                        string.Join("\n", errors));
                }

                ms.Seek(0, SeekOrigin.Begin);
                return Assembly.Load(ms.ToArray());
            }
        }

        /// <summary>
        /// Creates AIA Standard Layers once per Rhino session.
        /// </summary>
        private void EnsureAiaLayers()
        {
            if (_aiaLayersCreated) return;

            var doc = RhinoDoc.ActiveDoc;
            if (doc == null) return;

            var layers = new Dictionary<string, System.Drawing.Color>
            {
                { "A-WALL", System.Drawing.Color.Black },
                { "A-STRC", System.Drawing.Color.Red },
                { "A-GLAZ", System.Drawing.Color.Cyan }
            };

            foreach (var kvp in layers)
            {
                if (doc.Layers.FindName(kvp.Key) == null)
                {
                    var layer = new Layer { Name = kvp.Key, Color = kvp.Value };
                    doc.Layers.Add(layer);
                }
            }

            _aiaLayersCreated = true;
        }

        /// <summary>
        /// Adds an aligned dimension line spanning the bounding box of created geometry.
        /// </summary>
        private void AddScaleDimensions(RhinoDoc doc, List<Guid> guids)
        {
            var bbox = BoundingBox.Empty;

            foreach (var guid in guids)
            {
                var obj = doc.Objects.FindId(guid);
                if (obj?.Geometry != null)
                    bbox.Union(obj.Geometry.GetBoundingBox(true));
            }

            if (!bbox.IsValid) return;

            try
            {
                var pt0 = bbox.Min;
                var pt1 = new Point3d(bbox.Max.X, bbox.Min.Y, bbox.Min.Z);
                var plane = Plane.WorldXY;
                plane.Origin = pt0;

                var dim = LinearDimension.Create(
                    AnnotationType.Aligned,
                    doc.DimStyles.Current,
                    plane, plane.XAxis, pt0, pt1, pt0, 0
                );

                if (dim != null)
                    doc.Objects.AddLinearDimension(dim);
            }
            catch (Exception ex)
            {
                RhinoApp.WriteLine($"RhinoAlmondBridge: Dimension error: {ex.Message}");
            }
        }
    }

    /// <summary>
    /// Result object sent back to the MCP server after script execution.
    /// </summary>
    public class ScriptResult
    {
        [JsonProperty("status")]
        public string Status { get; set; } = "success";

        [JsonProperty("message")]
        public string Message { get; set; } = "";

        [JsonProperty("guids")]
        public List<string> Guids { get; set; } = new List<string>();

        [JsonProperty("error_trace")]
        public string ErrorTrace { get; set; }
    }
}
