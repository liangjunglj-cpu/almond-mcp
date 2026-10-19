# Native script Undo regression tests

These tests link the production `ScriptExecutor.cs` and exercise Rhino's native
Undo stack in disposable headless documents. They do not install a plugin,
save a model, or edit the active document. Rhino 8 and a .NET SDK are required.

Build from the repository root:

```powershell
dotnet build RhinoAlmondBridge/RhinoAlmondBridge.csproj -c Release
dotnet build tests/script_executor_undo/ScriptExecutorUndoTests.csproj -c Release
```

With Almond loaded in Rhino 8, run the following Python snippet once. Replace
the DLL path with the full path in your checkout. The queued callback runs after
the launching command returns: running the tests inside a Rhino command could
hide the modeless Undo-record leak this suite checks.

```python
import Rhino
from System import Action
from System.Reflection import Assembly
from Eto.Forms import Application

assembly = Assembly.LoadFrom(
    r"C:\path\to\almond-mcp\tests\script_executor_undo\bin\Release\net48\AlmondScriptUndoTests.dll"
)

def run():
    test_type = assembly.GetType("AlmondScriptUndoTests.NativeUndoTests")
    try:
        report = test_type.GetMethod("RunAll").Invoke(None, None)
        Rhino.RhinoApp.WriteLine(report)
    except Exception as error:
        Rhino.RhinoApp.WriteLine(str(error))

Application.Instance.AsyncInvoke(Action(run))
```

The suite checks successful Undo/Redo, partial creation/deletion/attribute
rollback, both exception paths, empty failures with previous Undo and Redo
history, first-call layer rollback, validation failures, unavailable or
caller-owned recording, lost record ownership, and existing `void Run`
compatibility. Every normal exit must leave Undo, Redo, and recording inactive.
The test's manual Undo/Redo helper checks that condition before doing its own
native bookkeeping, so it cannot hide a leaked executor record.

Rhino discards an empty record synchronously during `EndUndoRecord`, reporting
`Command.UndoRedo` with `IsPurgeRecord` for that record's serial. The executor
observes only that close and skips Undo for discarded records. A custom Undo
marker is deliberately unnecessary: adding one would turn an empty failure into
a history edit and discard an existing Redo chain.
