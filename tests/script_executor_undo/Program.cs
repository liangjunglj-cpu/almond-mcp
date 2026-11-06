using System;
using System.IO;
using System.Reflection;
using System.Runtime.CompilerServices;

namespace AlmondScriptUndoTests
{
    /// <summary>
    /// Boots Rhino in-process (Rhino.Inside) and runs the native Undo regression
    /// cases. RhinoCommon is resolved from the installed Rhino 8, never from the
    /// SDK package, so the tests see the same Undo behaviour the user does.
    /// </summary>
    internal static class Program
    {
        private static readonly string RhinoSystemDir =
            Environment.GetEnvironmentVariable("RHINO_SYSTEM_DIR")
            ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "Rhino 8", "System");

        [STAThread]
        private static int Main()
        {
            if (!File.Exists(Path.Combine(RhinoSystemDir, "RhinoCommon.dll")))
            {
                Console.Error.WriteLine("Rhino 8 not found at " + RhinoSystemDir + " (set RHINO_SYSTEM_DIR).");
                return 2;
            }

            AppDomain.CurrentDomain.AssemblyResolve += (sender, args) =>
            {
                string name = new AssemblyName(args.Name).Name;
                string candidate = Path.Combine(RhinoSystemDir, name + ".dll");
                return File.Exists(candidate) ? Assembly.LoadFrom(candidate) : null;
            };

            try
            {
                return RunInsideRhino();
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine(ex);
                return 1;
            }
        }

        // Separate method: Rhino types must not be JIT-resolved before the resolver is hooked.
        [MethodImpl(MethodImplOptions.NoInlining)]
        private static int RunInsideRhino()
        {
            using (new Rhino.Runtime.InProcess.RhinoCore(new[] { "/nosplash" }, Rhino.Runtime.InProcess.WindowStyle.NoWindow))
            {
                string report = NativeUndoTests.RunAll(out int failures);
                Console.WriteLine(report);
                return failures == 0 ? 0 : 1;
            }
        }
    }
}
