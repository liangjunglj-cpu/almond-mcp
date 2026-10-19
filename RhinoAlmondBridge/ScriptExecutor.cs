using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Newtonsoft.Json;
using Rhino;
using Rhino.Commands;
using Rhino.DocObjects;
using Rhino.Geometry;

namespace RhinoAlmondBridge
{
    /// <summary>
    /// Compiles and executes C# RhinoCommon scripts at runtime using Roslyn.
    /// Owns an Undo record and rolls back retained records on failure.
    /// </summary>
    public class ScriptExecutor
    {
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
            return Execute(csharpCode, RhinoDoc.ActiveDoc);
        }

        // Keep one document throughout execution; also allows native headless tests.
        internal ScriptResult Execute(string csharpCode, RhinoDoc doc)
        {
            var result = new ScriptResult { Status = "success" };

            if (doc == null)
            {
                result.Status = "error";
                result.Message = "No active Rhino document.";
                return result;
            }

            // Validate before creating layers or touching the Undo/Redo history.
            Assembly assembly;
            try
            {
                assembly = CompileScript(WrapScript(csharpCode));
            }
            catch (Exception ex)
            {
                result.Status = "compile_error";
                result.Message = ex.Message;
                result.ErrorTrace = ex.ToString();
                return result;
            }

            MethodInfo runMethod;
            try
            {
                var entryType = assembly.GetTypes()
                    .FirstOrDefault(t => t.GetMethod("Run", BindingFlags.Public | BindingFlags.Static) != null);

                if (entryType == null)
                {
                    result.Status = "error";
                    result.Message = "Script must contain a class with: public static List<Guid> Run(RhinoDoc doc)";
                    return result;
                }

                runMethod = entryType.GetMethod("Run", BindingFlags.Public | BindingFlags.Static);
            }
            catch (Exception ex)
            {
                SetRuntimeError(result, ex);
                return result;
            }

            uint undoSn = doc.BeginUndoRecord("MCP C# Script Execution");
            if (undoSn == 0)
            {
                result.Status = "error";
                result.Message = "Cannot start an Undo record. Finish the active command or Undo/Redo operation and ensure Undo recording is enabled before retrying.";
                return result;
            }

            try
            {
                EnsureAiaLayers(doc);
                var invokeResult = runMethod.Invoke(null, new object[] { doc });

                // Collect GUIDs
                if (invokeResult is List<Guid> guids)
                {
                    result.Guids = guids.Select(g => g.ToString()).ToList();

                    if (guids.Count > 0)
                        AddScaleDimensions(doc, guids);
                }
            }
            catch (TargetInvocationException ex)
            {
                // The actual exception is in InnerException
                SetRuntimeError(result, ex.InnerException ?? ex);
            }
            catch (Exception ex)
            {
                SetRuntimeError(result, ex);
            }

            try
            {
                FinishUndoRecord(doc, undoSn, result.Status != "success");
            }
            catch (Exception ex)
            {
                ReportUndoError(result, ex);
            }
            finally
            {
                // Never close a record opened by the script or another caller.
                try
                {
                    if (OwnsUndoRecord(doc, undoSn) && !doc.EndUndoRecord(undoSn))
                        throw new InvalidOperationException("Could not close the script's Undo record.");
                }
                catch (Exception ex)
                {
                    ReportUndoError(result, ex);
                }
            }

            // A display failure must not roll back an already completed script.
            try
            {
                doc.Views.Redraw();
            }
            catch (Exception ex)
            {
                RhinoApp.WriteLine($"RhinoAlmondBridge: Redraw error: {ex.Message}");
            }

            return result;
        }

        private static bool OwnsUndoRecord(RhinoDoc doc, uint undoSn)
        {
            return undoSn != 0 && doc.UndoRecordingIsActive &&
                doc.CurrentUndoRecordSerialNumber == undoSn;
        }

        private static void FinishUndoRecord(RhinoDoc doc, uint undoSn, bool rollback)
        {
            if (!OwnsUndoRecord(doc, undoSn))
                throw new InvalidOperationException("The script changed its Undo record. Automatic rollback was skipped to protect other work.");

            bool purged = false;
            int ownerThreadId = System.Environment.CurrentManagedThreadId;
            uint nextUndoSn = doc.NextUndoRecordSerialNumber;
            EventHandler<UndoRedoEventArgs> onUndoRedo = (sender, e) =>
            {
                if (System.Environment.CurrentManagedThreadId == ownerThreadId &&
                    e.UndoSerialNumber == undoSn && e.IsPurgeRecord)
                    purged = true;
            };

            // Rhino discards empty records during EndUndoRecord and reports their
            // serial via IsPurgeRecord. Undoing after that would undo earlier work.
            // Observe only this synchronous close; no custom marker is needed,
            // so an empty failure also preserves an existing Redo history.
            Command.UndoRedo += onUndoRedo;
            try
            {
                if (!doc.EndUndoRecord(undoSn))
                    throw new InvalidOperationException("Could not close the script's Undo record.");
            }
            finally
            {
                Command.UndoRedo -= onUndoRedo;
            }

            if (!rollback || purged)
                return;

            if (doc.UndoRecordingIsActive || doc.UndoActive || doc.RedoActive ||
                doc.NextUndoRecordSerialNumber != nextUndoSn)
                throw new InvalidOperationException("Undo state changed while closing the script's record. Automatic rollback was skipped to protect other work.");

            try
            {
                if (!doc.Undo())
                    throw new InvalidOperationException("Rhino could not undo the failed script's record.");
            }
            finally
            {
                // Modeless Undo starts its own record. No Rhino command will end
                // it for us; leaving it open keeps UndoActive true indefinitely.
                if (doc.UndoRecordingIsActive)
                {
                    if (!OwnsUndoRecord(doc, nextUndoSn))
                        throw new InvalidOperationException("Undo recovery encountered another active record and left it under its owner's control.");
                    if (!doc.EndUndoRecord(nextUndoSn))
                        throw new InvalidOperationException("Could not close the rollback Undo record.");
                }

                if (doc.UndoActive || doc.RedoActive)
                    throw new InvalidOperationException("Rhino still reports an active Undo/Redo operation after recovery.");
            }
        }

        private static void SetRuntimeError(ScriptResult result, Exception ex)
        {
            result.Status = "runtime_error";
            result.Message = ex.Message;
            result.ErrorTrace = ex.ToString();
            result.Guids.Clear();
        }

        private static void ReportUndoError(ScriptResult result, Exception ex)
        {
            if (result.Status == "success")
            {
                SetRuntimeError(result, ex);
                return;
            }

            result.Message += " Undo recovery: " + ex.Message;
            result.ErrorTrace += "\nUndo recovery: " + ex;
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
        /// Creates missing AIA Standard Layers in the current script's Undo record.
        /// </summary>
        private void EnsureAiaLayers(RhinoDoc doc)
        {
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
