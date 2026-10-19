using System;
using System.Collections.Generic;
using System.Linq;
using Rhino;
using Rhino.DocObjects;
using Rhino.Geometry;
using RhinoAlmondBridge;

namespace AlmondScriptUndoTests
{
    // Runs the linked production executor against Rhino's real native Undo stack.
    // Invoke from a modeless UI callback in Rhino, not from a command RunCommand.
    public static class NativeUndoTests
    {
        public static string RunAll()
        {
            var lines = new List<string>();

            Run(lines, "successful script is one Undo/Redo operation", doc =>
            {
                var result = Execute(doc, "var id = doc.Objects.AddPoint(Point3d.Origin); return new List<Guid> { id };");
                Check(result.Status == "success", result.Message);
                var id = Guid.Parse(result.Guids.Single());
                Check(Live(doc, id), "Successful script did not create its point.");
                Idle(doc);
                Undo(doc);
                Check(!Live(doc, id) && Count(doc) == 0, "Undo left successful script objects.");
                Check(doc.Layers.FindName("A-WALL") == null, "Layer initialization was outside the script record.");
                Redo(doc);
                Check(Live(doc, id), "Redo did not restore the successful script.");
            });

            Run(lines, "partial creation rolls back and later Delete/Undo/Redo works", doc =>
            {
                Prepare(doc);
                var previous = Seed(doc);
                int before = Count(doc);
                Failed(Execute(doc, "doc.Objects.AddPoint(new Point3d(10, 0, 0)); throw new InvalidOperationException(\"expected\");"));
                Check(Live(doc, previous) && Count(doc) == before, "Rollback changed previous work or left new geometry.");
                DeleteUndoRedo(doc, previous);
            });

            Run(lines, "empty failure preserves previous work and adds no Undo step", doc =>
            {
                Prepare(doc);
                var previous = Seed(doc);
                Failed(Execute(doc, "throw new InvalidOperationException(\"expected\");"));
                Check(Live(doc, previous), "Empty failure undid the previous successful action.");
                Idle(doc);
                Undo(doc);
                Check(!Live(doc, previous), "An empty failure added an extra Undo step.");
                Redo(doc);
                Check(Live(doc, previous), "Previous action lost its Redo.");
            });

            Run(lines, "failed deletion restores the existing object", doc =>
            {
                Prepare(doc);
                var previous = Seed(doc);
                Failed(Execute(doc, "doc.Objects.Delete(new Guid(\"" + previous + "\"), true); throw new InvalidOperationException(\"expected\");"));
                Check(Live(doc, previous), "Failed deletion was not rolled back.");
                Idle(doc);
            });

            Run(lines, "failed attribute edit restores the existing attributes", doc =>
            {
                Prepare(doc);
                var previous = Seed(doc);
                string originalName = doc.Objects.FindId(previous).Attributes.Name;
                Failed(Execute(doc, "var id = new Guid(\"" + previous + "\"); var a = doc.Objects.FindId(id).Attributes.Duplicate(); a.Name = \"temporary\"; doc.Objects.ModifyAttributes(id, a, true); throw new InvalidOperationException(\"expected\");"));
                Check(doc.Objects.FindId(previous).Attributes.Name == originalName, "Failed attribute edit was not rolled back.");
                Idle(doc);
            });

            Run(lines, "reflection invocation failure preserves previous work", doc =>
            {
                Prepare(doc);
                var previous = Seed(doc);
                var result = new ScriptExecutor().Execute("public class Script { public static void Run() {} }", doc);
                Check(result.Status == "runtime_error", "Invalid Run arguments did not fail.");
                Check(Live(doc, previous), "Generic exception recovery undid previous work.");
                Idle(doc);
            });

            Run(lines, "first-call failure rolls back layers and next call recreates them", doc =>
            {
                Failed(Execute(doc, "doc.Objects.AddPoint(Point3d.Origin); throw new InvalidOperationException(\"expected\");"));
                Check(Count(doc) == 0, "First-call failure left geometry.");
                Check(doc.Layers.FindName("A-WALL") == null, "First-call failure left created layers.");
                Idle(doc);
                Prepare(doc);
                Check(doc.Layers.FindName("A-WALL") != null, "Layer initialization stayed incorrectly cached after rollback.");
            });

            Run(lines, "compile error does not initialize layers or history", doc =>
            {
                int layers = doc.Layers.Count;
                var result = new ScriptExecutor().Execute("this is not C#;", doc);
                Check(result.Status == "compile_error", "Expected compilation failure.");
                Check(doc.Layers.Count == layers && Count(doc) == 0, "Compilation failure changed the document.");
                Idle(doc);
            });

            Run(lines, "missing entry point does not initialize layers or history", doc =>
            {
                int layers = doc.Layers.Count;
                var result = new ScriptExecutor().Execute("public class MissingEntry {}", doc);
                Check(result.Status == "error", "Missing Run method was accepted.");
                Check(doc.Layers.Count == layers && Count(doc) == 0, "Entry validation changed the document.");
                Idle(doc);
            });

            Run(lines, "caller-owned record is neither joined nor closed", doc =>
            {
                uint owner = doc.BeginUndoRecord("caller-owned");
                Check(owner != 0, "Could not create caller's record.");
                var previous = doc.Objects.AddPoint(Point3d.Origin);
                var result = Execute(doc, "doc.Objects.AddPoint(new Point3d(10, 0, 0)); return new List<Guid>();");
                Check(result.Status == "error", "Script executed without owning a record.");
                Check(doc.CurrentUndoRecordSerialNumber == owner && doc.UndoRecordingIsActive, "Executor closed caller's record.");
                Check(Count(doc) == 1 && Live(doc, previous), "Rejected script changed caller's document.");
                Check(doc.Layers.FindName("A-WALL") == null, "Rejected script initialized layers.");
                Check(doc.EndUndoRecord(owner), "Could not finish caller's record.");
                Undo(doc);
                Check(!Live(doc, previous), "Caller lost its Undo history.");
            });

            Run(lines, "disabled Undo rejects execution before document changes", doc =>
            {
                doc.UndoRecordingEnabled = false;
                int layers = doc.Layers.Count;
                var result = Execute(doc, "doc.Objects.AddPoint(Point3d.Origin); return new List<Guid>();");
                Check(result.Status == "error", "Script ran with Undo disabled.");
                Check(!doc.UndoRecordingEnabled && Count(doc) == 0 && doc.Layers.Count == layers, "Rejected script changed the document or Undo setting.");
                Idle(doc);
            });

            Run(lines, "empty failure preserves an existing Redo chain", doc =>
            {
                Prepare(doc);
                var previous = Seed(doc);
                Undo(doc);
                Failed(Execute(doc, "throw new InvalidOperationException(\"expected\");"));
                Idle(doc);
                Redo(doc);
                Check(Live(doc, previous), "Empty failure destroyed the existing Redo.");
            });

            Run(lines, "successful no-op preserves an existing Redo chain", doc =>
            {
                Prepare(doc);
                var previous = Seed(doc);
                Undo(doc);
                Prepare(doc);
                Redo(doc);
                Check(Live(doc, previous), "Successful no-op destroyed the existing Redo.");
            });

            Run(lines, "script-closed record cannot roll back earlier work", doc =>
            {
                Prepare(doc);
                var previous = Seed(doc);
                var result = Execute(doc, "doc.EndUndoRecord(doc.CurrentUndoRecordSerialNumber); throw new InvalidOperationException(\"expected\");");
                Check(result.Status == "runtime_error" && result.Message.Contains("protect other work"), "Lost record ownership was not reported.");
                Check(Live(doc, previous), "Executor undid earlier work after losing its record.");
                Idle(doc);
            });

            Run(lines, "script-created replacement record stays under script ownership", doc =>
            {
                Prepare(doc);
                var previous = Seed(doc);
                var result = Execute(doc, "doc.EndUndoRecord(doc.CurrentUndoRecordSerialNumber); doc.BeginUndoRecord(\"replacement\"); doc.Objects.AddPoint(new Point3d(10, 0, 0)); throw new InvalidOperationException(\"expected\");");
                Check(result.Status == "runtime_error" && result.Message.Contains("protect other work"), "Replacement record was not reported.");
                Check(doc.UndoRecordingIsActive && Count(doc) == 2 && Live(doc, previous), "Executor changed or closed the replacement record.");
                Check(doc.EndUndoRecord(doc.CurrentUndoRecordSerialNumber), "Test could not close its replacement record.");
                Undo(doc);
                Check(Count(doc) == 1 && Live(doc, previous), "Replacement record lost its own Undo.");
            });

            Run(lines, "void Run remains supported and undoable", doc =>
            {
                Prepare(doc);
                var result = new ScriptExecutor().Execute("public class Script { public static void Run(RhinoDoc doc) { doc.Objects.AddPoint(Point3d.Origin); } }", doc);
                Check(result.Status == "success" && Count(doc) == 1, "Existing void Run compatibility changed.");
                Idle(doc);
                Undo(doc);
                Check(Count(doc) == 0, "Void Run changes were not undoable.");
            });

            Run(lines, "immediate Redo cannot replay a failed creation", doc =>
            {
                Prepare(doc);
                var previous = Seed(doc);
                Failed(Execute(doc, "doc.Objects.AddPoint(new Point3d(10, 0, 0)); throw new InvalidOperationException(\"expected\");"));
                Check(Count(doc) == 1 && Live(doc, previous), "Failed creation was not rolled back.");
                bool redone = TryRedo(doc);
                Check(!redone && Count(doc) == 1 && Live(doc, previous), "Immediate Redo replayed the failed creation.");
            });

            Run(lines, "immediate Redo cannot replay a failed deletion", doc =>
            {
                Prepare(doc);
                var previous = Seed(doc);
                Failed(Execute(doc, "doc.Objects.Delete(new Guid(\"" + previous + "\"), true); throw new InvalidOperationException(\"expected\");"));
                Check(Live(doc, previous), "Failed deletion was not rolled back.");
                bool redone = TryRedo(doc);
                Check(!redone && Count(doc) == 1 && Live(doc, previous), "Immediate Redo replayed the failed deletion.");
            });

            Run(lines, "immediate Redo cannot replay a failed attribute edit", doc =>
            {
                Prepare(doc);
                var previous = Seed(doc);
                string originalName = doc.Objects.FindId(previous).Attributes.Name;
                Failed(Execute(doc, "var id = new Guid(\"" + previous + "\"); var a = doc.Objects.FindId(id).Attributes.Duplicate(); a.Name = \"temporary\"; doc.Objects.ModifyAttributes(id, a, true); throw new InvalidOperationException(\"expected\");"));
                Check(doc.Objects.FindId(previous).Attributes.Name == originalName, "Failed attribute edit was not rolled back.");
                bool redone = TryRedo(doc);
                Check(!redone && doc.Objects.FindId(previous).Attributes.Name == originalName, "Immediate Redo replayed the failed attribute edit.");
            });

            Run(lines, "immediate Redo cannot replay failed first-call layer initialization", doc =>
            {
                Failed(Execute(doc, "throw new InvalidOperationException(\"expected\");"));
                Check(Count(doc) == 0 && doc.Layers.FindName("A-WALL") == null, "First-call layer initialization was not rolled back.");
                bool redone = TryRedo(doc);
                Check(!redone && Count(doc) == 0 && doc.Layers.FindName("A-WALL") == null, "Immediate Redo replayed failed first-call layer initialization.");
            });

            Run(lines, "nonempty failure preserves two earlier Undo/Redo records", doc =>
            {
                Prepare(doc);
                var first = Seed(doc);
                var second = Seed(doc);
                Failed(Execute(doc, "doc.Objects.AddPoint(new Point3d(10, 0, 0)); throw new InvalidOperationException(\"expected\");"));
                Check(Count(doc) == 2 && Live(doc, first) && Live(doc, second), "Failure changed earlier work.");
                Check(!TryRedo(doc), "Failed script remained available to Redo.");
                Undo(doc);
                Check(Count(doc) == 1 && Live(doc, first) && !Live(doc, second), "First Undo did not remove only the second successful object.");
                Undo(doc);
                Check(Count(doc) == 0 && !Live(doc, first) && !Live(doc, second), "Second Undo did not remove the first successful object.");
                Redo(doc);
                Check(Count(doc) == 1 && Live(doc, first) && !Live(doc, second), "First Redo did not restore only the first successful object.");
                Redo(doc);
                Check(Count(doc) == 2 && Live(doc, first) && Live(doc, second), "Second Redo did not restore only the two successful objects.");
                Check(!TryRedo(doc) && Count(doc) == 2, "Failed geometry survived beyond the earlier successful Redo records.");
            });

            string report = "Rhino " + RhinoApp.Version + "\n" + string.Join("\n", lines);
            int failures = lines.Count(line => line.StartsWith("FAIL "));
            if (failures != 0)
                throw new InvalidOperationException(report + "\n" + failures + " test(s) failed.");

            return report + "\nPASS: " + lines.Count + "/" + lines.Count + " native Undo regression cases.";
        }

        private static void Run(List<string> lines, string name, Action<RhinoDoc> test)
        {
            using (var doc = RhinoDoc.CreateHeadless(null))
            {
                doc.UndoRecordingEnabled = true;
                try
                {
                    test(doc);
                    Idle(doc);
                    lines.Add("PASS " + name);
                }
                catch (Exception ex)
                {
                    lines.Add("FAIL " + name + ": " + ex);
                }
            }
        }

        private static ScriptResult Execute(RhinoDoc doc, string body)
        {
            string source = "public class Script { public static List<Guid> Run(RhinoDoc doc) { " + body + " } }";
            return new ScriptExecutor().Execute(source, doc);
        }

        private static void Prepare(RhinoDoc doc)
        {
            var result = Execute(doc, "return new List<Guid>();");
            Check(result.Status == "success", result.Message);
            Idle(doc);
        }

        private static Guid Seed(RhinoDoc doc)
        {
            uint sn = doc.BeginUndoRecord("previous successful point");
            Check(sn != 0, "Could not start seed record.");
            var id = doc.Objects.AddPoint(Point3d.Origin);
            Check(id != Guid.Empty && doc.EndUndoRecord(sn), "Could not finish seed record.");
            return id;
        }

        private static void Failed(ScriptResult result)
        {
            Check(result.Status == "runtime_error" && result.Message == "expected", "Unexpected failure result: " + result.Message);
            Check(result.Guids.Count == 0, "Failure returned stale object IDs.");
        }

        private static bool Live(RhinoDoc doc, Guid id)
        {
            var obj = doc.Objects.FindId(id);
            return obj != null && !obj.IsDeleted;
        }

        private static int Count(RhinoDoc doc)
        {
            return doc.Objects.GetObjectList(ObjectType.AnyObject).Count();
        }

        private static void Idle(RhinoDoc doc)
        {
            Check(!doc.UndoActive && !doc.RedoActive && !doc.UndoRecordingIsActive &&
                doc.CurrentUndoRecordSerialNumber == 0, "Undo/Redo operation or record was left active.");
        }

        private static void Undo(RhinoDoc doc) { UndoOrRedo(doc, false); }
        private static void Redo(RhinoDoc doc) { UndoOrRedo(doc, true); }

        private static void UndoOrRedo(RhinoDoc doc, bool redo)
        {
            // These are modeless native calls as well. Check BEFORE cleanup so
            // the test cannot hide a record leaked by the production executor.
            Idle(doc);
            uint sn = doc.NextUndoRecordSerialNumber;
            try
            {
                Check(redo ? doc.Redo() : doc.Undo(), redo ? "Redo failed." : "Undo failed.");
            }
            finally
            {
                if (doc.UndoRecordingIsActive && doc.CurrentUndoRecordSerialNumber == sn)
                    Check(doc.EndUndoRecord(sn), "Could not finish the test's Undo/Redo.");
            }
            Idle(doc);
        }

        private static void DeleteUndoRedo(RhinoDoc doc, Guid id)
        {
            Idle(doc);
            uint sn = doc.BeginUndoRecord("later manual deletion");
            Check(sn != 0, "Later Delete could not start an Undo record.");
            Check(doc.Objects.Delete(id, true) && doc.EndUndoRecord(sn), "Later Delete failed.");
            Check(!Live(doc, id), "Delete left the point live.");
            Undo(doc);
            Check(Live(doc, id), "Later Undo did not restore the deleted point.");
            Redo(doc);
            Check(!Live(doc, id), "Later Redo did not delete the point again.");
        }

        private static bool TryRedo(RhinoDoc doc)
        {
            Idle(doc);
            uint sn = doc.NextUndoRecordSerialNumber;
            bool redone;
            try
            {
                // Do not make another edit before this call: an edit would clear
                // Redo itself and hide a failed script left by the executor.
                redone = doc.Redo();
            }
            finally
            {
                if (doc.UndoRecordingIsActive && doc.CurrentUndoRecordSerialNumber == sn)
                    Check(doc.EndUndoRecord(sn), "Could not finish the test's immediate Redo.");
            }
            Idle(doc);
            return redone;
        }

        private static void Check(bool condition, string message)
        {
            if (!condition)
                throw new InvalidOperationException(message);
        }
    }
}
