# Native script Undo regression cases

Regression runner for issue #35 (Undo broken after a script error). It links the
production `RhinoAlmondBridge/ScriptExecutor.cs`, boots Rhino in-process
(Rhino.Inside, no window) and drives the executor against Rhino's real Undo
stack in disposable headless documents, outside any Rhino command, which is the
context the bridge runs scripts in. It never touches the active document of a
running Rhino and installs nothing.

Requirements: Rhino 8 installed and licensed on this machine, a .NET SDK.
Rhino may be open at the same time. Not part of CI (CI has no Rhino).

```powershell
dotnet run --project tests/script_executor_undo -c Release
```

Exit code 0 means every case passed; the report lists each case as PASS/FAIL.

To see the cases catch the original bugs, point the runner at a pre-fix copy of
the executor (its `Execute` needs the explicit-document overload the tests call):

```powershell
dotnet build tests/script_executor_undo -c Release -p:ExecutorSource=C:\path\to\OldScriptExecutor.cs
```

## What the cases pin down

Two Rhino behaviours outside a command, both reproduced on Rhino 8.34 before the fix:

1. `RhinoDoc.Undo()` opens an Undo record of its own that only the command loop
   would close. The executor's rollback after a failed script left it open, so
   recording stayed active forever: a later Delete succeeded but Ctrl+Z reported
   nothing to undo until Rhino was restarted. Every case ends by checking that no
   record or Undo/Redo operation is active, and the manual Delete / Undo / Redo
   case is the reporter's reproduction.
2. Rhino discards an empty record when it is closed. A failed script that
   changed nothing therefore had nothing to undo, and the executor's `Undo()`
   undid the user's previous action instead. Rhino announces the discard through
   `Command.UndoRedo` with `IsPurgeRecord`; the executor watches the close for it.

Also covered: Redo cannot replay a rolled-back script; earlier Undo/Redo steps
survive a rollback; a compile error or missing entry point leaves document and
history untouched; the AIA layers are created inside the script's record; a
script that closes the record itself is left alone; `void Run` still works.
