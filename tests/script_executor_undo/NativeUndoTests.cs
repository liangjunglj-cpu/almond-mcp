using System;
using System.Collections.Generic;
using System.Linq;
using Rhino;
using Rhino.DocObjects;
using Rhino.Geometry;
using RhinoAlmondBridge;

namespace AlmondScriptUndoTests
{
    /// <summary>
    /// Drives the production ScriptExecutor against Rhino's real Undo stack in
    /// disposable headless documents, outside any Rhino command (the bridge's
    /// situation). Every case ends by checking that no Undo record or operation
    /// was left active, which is the leak behind issue #35.
    /// </summary>
    public static class NativeUndoTests
    {
        public static string RunAll(out int failures)
        {
            var lines = new List<string>();

            Case(lines, "successful script is one Undo step and comes back on Redo", doc =>
            {
                var result = Execute(doc, "var id = doc.Objects.AddPoint(Point3d.Origin); return new List<Guid> { id };");
                Check(result.Status == "success", "status: " + result.Status + " " + result.Message);
                var id = Guid.Parse(result.Guids.Single());
                Check(Live(doc, id), "script did not create its point");
                Idle(doc);
                Undo(doc);
                Check(!Live(doc, id), "Undo left the script's point");
                Check(doc.Layers.FindName("A-WALL") == null, "layer initialisation was outside the script's record");
                Redo(doc);
                Check(Live(doc, id), "Redo did not restore the script");
            });

            Case(lines, "failed script that made changes is rolled back; later Delete / Undo / Redo work", doc =>
            {
                Warm(doc);
                var previous = Seed(doc);
                Failed(Execute(doc, "doc.Objects.AddPoint(new Point3d(10, 0, 0)); throw new InvalidOperationException(\"expected\");"));
                Check(Live(doc, previous) && Count(doc) == 1, "rollback touched previous work or left new geometry");
                Idle(doc);                      // the mechanism 1 leak: recording left active after Undo()
                DeleteUndoRedo(doc, previous);  // what the reporter saw: Delete works, Undo says nothing to undo
            });

            Case(lines, "failed script that made no changes does not undo the previous action", doc =>
            {
                Warm(doc);
                var previous = Seed(doc);
                Failed(Execute(doc, "throw new InvalidOperationException(\"expected\");"));
                Check(Live(doc, previous), "empty failure undid the previous successful action (mechanism 2)");
                Idle(doc);
                Undo(doc);
                Check(!Live(doc, previous), "empty failure added an Undo step of its own");
                Redo(doc);
                Check(Live(doc, previous), "previous action lost its Redo");
            });

            Case(lines, "empty failure keeps an existing Redo chain", doc =>
            {
                Warm(doc);
                var previous = Seed(doc);
                Undo(doc);
                Failed(Execute(doc, "throw new InvalidOperationException(\"expected\");"));
                Idle(doc);
                Redo(doc);
                Check(Live(doc, previous), "empty failure destroyed the existing Redo");
            });

            Case(lines, "failed deletion is restored", doc =>
            {
                Warm(doc);
                var previous = Seed(doc);
                Failed(Execute(doc, "doc.Objects.Delete(new Guid(\"" + previous + "\"), true); throw new InvalidOperationException(\"expected\");"));
                Check(Live(doc, previous), "failed deletion was not rolled back");
                Idle(doc);
            });

            Case(lines, "Redo cannot replay a rolled-back script", doc =>
            {
                Warm(doc);
                var previous = Seed(doc);
                Failed(Execute(doc, "doc.Objects.AddPoint(new Point3d(10, 0, 0)); throw new InvalidOperationException(\"expected\");"));
                Check(!TryRedo(doc) && Count(doc) == 1 && Live(doc, previous), "Redo replayed the failed script");
            });

            Case(lines, "rollback preserves two earlier Undo/Redo steps", doc =>
            {
                Warm(doc);
                var first = Seed(doc);
                var second = Seed(doc);
                Failed(Execute(doc, "doc.Objects.AddPoint(new Point3d(10, 0, 0)); throw new InvalidOperationException(\"expected\");"));
                Check(Count(doc) == 2, "failure changed earlier work");
                Undo(doc);
                Check(Live(doc, first) && !Live(doc, second), "first Undo did not remove only the second object");
                Undo(doc);
                Check(Count(doc) == 0, "second Undo did not remove the first object");
                Redo(doc);
                Redo(doc);
                Check(Live(doc, first) && Live(doc, second) && Count(doc) == 2, "Redo did not restore both objects");
            });

            Case(lines, "first-call failure rolls back the AIA layers and the next call recreates them", doc =>
            {
                Failed(Execute(doc, "doc.Objects.AddPoint(Point3d.Origin); throw new InvalidOperationException(\"expected\");"));
                Check(Count(doc) == 0 && doc.Layers.FindName("A-WALL") == null, "first-call failure left geometry or layers");
                Idle(doc);
                Warm(doc);
                Check(doc.Layers.FindName("A-WALL") != null, "layers were not recreated after rollback");
            });

            Case(lines, "compile error and missing entry point leave document and history untouched", doc =>
            {
                int layers = doc.Layers.Count;
                uint next = doc.NextUndoRecordSerialNumber;
                Check(new ScriptExecutor().Execute("this is not C#;", doc).Status == "compile_error", "compile error not reported");
                Check(new ScriptExecutor().Execute("public class S { public static int Nope() { return 1; } }", doc).Status == "error", "missing Run not reported");
                Check(doc.Layers.Count == layers && Count(doc) == 0 && doc.NextUndoRecordSerialNumber == next, "document or history changed");
                Idle(doc);
            });

            Case(lines, "script that closes the record itself is left alone", doc =>
            {
                Warm(doc);
                var previous = Seed(doc);
                var result = Execute(doc, "doc.EndUndoRecord(doc.CurrentUndoRecordSerialNumber); throw new InvalidOperationException(\"expected\");");
                Check(result.Status == "runtime_error", "failure not reported");
                Check(Live(doc, previous), "executor undid earlier work after losing its record");
                Idle(doc);
            });

            Case(lines, "void Run is still accepted and undoable", doc =>
            {
                Warm(doc);
                var result = new ScriptExecutor().Execute("public class Script { public static void Run(RhinoDoc doc) { doc.Objects.AddPoint(Point3d.Origin); } }", doc);
                Check(result.Status == "success" && Count(doc) == 1, "void Run failed");
                Idle(doc);
                Undo(doc);
                Check(Count(doc) == 0, "void Run changes were not undoable");
            });

            failures = lines.Count(l => l.StartsWith("FAIL "));
            return "Rhino " + RhinoApp.Version + "\n" + string.Join("\n", lines) +
                   "\n" + (lines.Count - failures) + "/" + lines.Count + " native Undo cases passed.";
        }

        private static void Case(List<string> lines, string name, Action<RhinoDoc> test)
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
                    lines.Add("FAIL " + name + ": " + ex.Message);
                }
            }
        }

        private static ScriptResult Execute(RhinoDoc doc, string body)
        {
            string source = "public class Script { public static List<Guid> Run(RhinoDoc doc) { " + body + " } }";
            return new ScriptExecutor().Execute(source, doc);
        }

        /// <summary>A successful no-op script, so the AIA layers exist before the case proper.</summary>
        private static void Warm(RhinoDoc doc)
        {
            var result = Execute(doc, "return new List<Guid>();");
            Check(result.Status == "success", "warm-up failed: " + result.Message);
            Idle(doc);
        }

        /// <summary>A previous successful user action: one point in its own Undo record.</summary>
        private static Guid Seed(RhinoDoc doc)
        {
            uint sn = doc.BeginUndoRecord("previous successful point");
            Check(sn != 0, "could not start seed record");
            var id = doc.Objects.AddPoint(Point3d.Origin);
            Check(id != Guid.Empty && doc.EndUndoRecord(sn), "could not finish seed record");
            return id;
        }

        private static void Failed(ScriptResult result)
        {
            Check(result.Status == "runtime_error" && result.Message == "expected", "unexpected result: " + result.Status + " " + result.Message);
            Check(result.Guids.Count == 0, "failure returned stale object ids");
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

        /// <summary>No Undo/Redo operation and no record may be open between actions.</summary>
        private static void Idle(RhinoDoc doc)
        {
            Check(!doc.UndoActive && !doc.RedoActive && !doc.UndoRecordingIsActive && doc.CurrentUndoRecordSerialNumber == 0,
                "an Undo/Redo operation or record was left active (UndoActive=" + doc.UndoActive +
                " RedoActive=" + doc.RedoActive + " recording=" + doc.UndoRecordingIsActive + " sn=" + doc.CurrentUndoRecordSerialNumber + ")");
        }

        private static void Undo(RhinoDoc doc) { Check(UndoOrRedo(doc, false), "Undo reported nothing to undo"); }
        private static void Redo(RhinoDoc doc) { Check(UndoOrRedo(doc, true), "Redo reported nothing to redo"); }
        private static bool TryRedo(RhinoDoc doc) { return UndoOrRedo(doc, true); }

        /// <summary>
        /// What Ctrl+Z / Ctrl+Y do, as modeless calls. Checks the idle state BEFORE its
        /// own bookkeeping so it cannot hide a record leaked by the executor.
        /// </summary>
        private static bool UndoOrRedo(RhinoDoc doc, bool redo)
        {
            Idle(doc);
            uint sn = doc.NextUndoRecordSerialNumber;
            bool done;
            try
            {
                done = redo ? doc.Redo() : doc.Undo();
            }
            finally
            {
                if (doc.UndoRecordingIsActive && doc.CurrentUndoRecordSerialNumber == sn)
                    Check(doc.EndUndoRecord(sn), "could not finish the test's own Undo/Redo record");
            }
            Idle(doc);
            return done;
        }

        /// <summary>The reporter's reproduction: a manual Delete, then Undo, then Redo.</summary>
        private static void DeleteUndoRedo(RhinoDoc doc, Guid id)
        {
            uint sn = doc.BeginUndoRecord("later manual deletion");
            Check(sn != 0, "later Delete could not start its own Undo record (recording still active)");
            Check(doc.Objects.Delete(id, true) && doc.EndUndoRecord(sn), "later Delete failed");
            Check(!Live(doc, id), "Delete left the point");
            Undo(doc);
            Check(Live(doc, id), "Undo did not restore the deleted point");
            Redo(doc);
            Check(!Live(doc, id), "Redo did not delete the point again");
        }

        private static void Check(bool condition, string message)
        {
            if (!condition)
                throw new InvalidOperationException(message);
        }
    }
}
