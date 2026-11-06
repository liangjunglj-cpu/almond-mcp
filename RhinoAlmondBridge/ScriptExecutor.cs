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
    /// Each script runs inside one Undo record so that Ctrl+Z removes the whole
    /// script, and a script that throws is rolled back.
    ///
    /// The executor is called from the bridge's UI-thread callback, outside any
    /// Rhino command, which is what makes the Undo bookkeeping delicate: Rhino's
    /// command loop normally closes records for us, and here nothing does.
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

        /// <summary>Same as <see cref="Execute(string)"/> on an explicit document (headless tests).</summary>
        internal ScriptResult Execute(string csharpCode, RhinoDoc doc)
        {
            var result = new ScriptResult { Status = "success" };

            if (doc == null)
            {
                result.Status = "error";
                result.Message = "No active Rhino document.";
                return result;
            }

            // Compile and locate the entry point before touching the document, so a
            // script that cannot run leaves no trace in the Undo history.
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

            var entryType = assembly.GetTypes()
                .FirstOrDefault(t => t.GetMethod("Run", BindingFlags.Public | BindingFlags.Static) != null);
            if (entryType == null)
            {
                result.Status = "error";
                result.Message = "Script must contain a class with: public static List<Guid> Run(RhinoDoc doc)";
                return result;
            }
            var runMethod = entryType.GetMethod("Run", BindingFlags.Public | BindingFlags.Static);

            // One record for everything the script does, including the layers it may
            // need. 0 means Rhino is already recording for someone else (or recording
            // is off): then the script's changes join that record and we own nothing.
            uint undoSn = doc.BeginUndoRecord("MCP C# Script Execution");
            bool failed = false;
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
                failed = true;
                SetRuntimeError(result, ex.InnerException ?? ex);
            }
            catch (Exception ex)
            {
                failed = true;
                SetRuntimeError(result, ex);
            }
            finally
            {
                if (undoSn != 0)
                    CloseUndoRecord(doc, undoSn, rollback: failed);
            }

            doc.Views.Redraw();
            return result;
        }

        private static void SetRuntimeError(ScriptResult result, Exception ex)
        {
            result.Status = "runtime_error";
            result.Message = ex.Message;
            result.ErrorTrace = ex.ToString();
            result.Guids.Clear();   // rolled back, so nothing to report
        }

        /// <summary>
        /// Closes the script's Undo record and, on failure, undoes it. Two Rhino
        /// behaviours outside a command have to be handled explicitly (issue #35):
        ///
        /// 1. Rhino discards a record that recorded nothing when it is closed. If the
        ///    failed script changed nothing, there is nothing to undo, and calling
        ///    Undo() anyway would undo the user's previous action instead. Rhino
        ///    announces the discard through Command.UndoRedo with IsPurgeRecord, so
        ///    the close is watched for that.
        /// 2. RhinoDoc.Undo() opens an Undo record for the undo operation itself.
        ///    Inside a command the command loop closes it; here nothing would, so
        ///    recording stays active forever, every later action (a Delete, the next
        ///    script) is swallowed into that open record, and Ctrl+Z reports there is
        ///    nothing to undo until Rhino is restarted. The record is closed by hand,
        ///    as McNeel recommends.
        /// </summary>
        private static void CloseUndoRecord(RhinoDoc doc, uint undoSn, bool rollback)
        {
            if (doc.CurrentUndoRecordSerialNumber != undoSn)
            {
                // The script ended or replaced the record itself; it is not ours to
                // close or undo any more.
                RhinoApp.WriteLine("RhinoAlmondBridge: script changed the Undo record; automatic rollback skipped.");
                return;
            }

            bool purged = false;
            EventHandler<UndoRedoEventArgs> watchPurge = (sender, e) =>
            {
                if (e.IsPurgeRecord && e.UndoSerialNumber == undoSn)
                    purged = true;
            };

            Command.UndoRedo += watchPurge;
            try
            {
                doc.EndUndoRecord(undoSn);
            }
            finally
            {
                Command.UndoRedo -= watchPurge;
            }

            if (!rollback || purged)
                return;

            try
            {
                bool wasRecording = doc.UndoRecordingIsActive;
                if (!doc.Undo())
                {
                    RhinoApp.WriteLine("RhinoAlmondBridge: could not undo the failed script; its partial changes remain.");
                    return;
                }
                if (!wasRecording && doc.UndoRecordingIsActive)
                    doc.EndUndoRecord(doc.CurrentUndoRecordSerialNumber);

                // The undone partial script is now on the Redo stack; Ctrl+Y must not
                // bring half a model back.
                doc.ClearRedoRecords();
            }
            catch (Exception ex)
            {
                RhinoApp.WriteLine($"RhinoAlmondBridge: Undo recovery error: {ex.Message}");
            }
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
        /// Creates the AIA standard layers that are missing from the document. Runs
        /// inside the script's Undo record, so a rolled-back first script does not
        /// leave the layers behind (and recreates them next time).
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
