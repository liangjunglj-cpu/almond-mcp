using System;
using System.Diagnostics;
using System.IO;
using Rhino;
using Rhino.Commands;

namespace RhinoAlmondBridge
{
    /// <summary>
    /// Rhino command: AlmondMCPStart
    /// Spawns the MCP Python server (uv run server.py) as a background process,
    /// so users never need to open a terminal.
    /// </summary>
    public class AlmondMCPStartCommand : Command
    {
        public override string EnglishName => "AlmondMCPStart";

        private static Process _serverProcess;

        protected override Result RunCommand(RhinoDoc doc, RunMode mode)
        {
            if (_serverProcess != null && !_serverProcess.HasExited)
            {
                RhinoApp.WriteLine("AlmondMCP: Server is already running (PID {0}).", _serverProcess.Id);
                return Result.Success;
            }

            // Find server.py relative to plugin DLL location
            string pluginDir = Path.GetDirectoryName(typeof(AlmondMCPStartCommand).Assembly.Location);
            string serverPy = FindServerScript(pluginDir);

            if (serverPy == null)
            {
                RhinoApp.WriteLine("AlmondMCP: ERROR — Cannot find server.py.");
                RhinoApp.WriteLine("AlmondMCP: Searched in: {0}", pluginDir);
                RhinoApp.WriteLine("AlmondMCP: Place server.py in the same folder as the plugin DLL,");
                RhinoApp.WriteLine("           or in the parent mcp-rhino-plugin folder.");
                return Result.Failure;
            }

            string serverDir = Path.GetDirectoryName(serverPy);
            RhinoApp.WriteLine("AlmondMCP: Starting MCP server from: {0}", serverPy);

            try
            {
                var psi = new ProcessStartInfo
                {
                    FileName = "uv",
                    Arguments = "run server.py",
                    WorkingDirectory = serverDir,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                };

                _serverProcess = Process.Start(psi);

                // Async read output so it doesn't block
                _serverProcess.OutputDataReceived += (s, e) =>
                {
                    if (!string.IsNullOrEmpty(e.Data))
                        RhinoApp.InvokeOnUiThread(new Action(() =>
                            RhinoApp.WriteLine("AlmondMCP Server: {0}", e.Data)));
                };
                _serverProcess.ErrorDataReceived += (s, e) =>
                {
                    if (!string.IsNullOrEmpty(e.Data))
                        RhinoApp.InvokeOnUiThread(new Action(() =>
                            RhinoApp.WriteLine("AlmondMCP Server [err]: {0}", e.Data)));
                };

                _serverProcess.BeginOutputReadLine();
                _serverProcess.BeginErrorReadLine();

                RhinoApp.WriteLine("AlmondMCP: Server started (PID {0}).", _serverProcess.Id);
                RhinoApp.WriteLine("AlmondMCP: Bridge listener on port 5000 — Server connected via MCP.");
                RhinoApp.WriteLine("AlmondMCP: Type 'AlmondMCPStop' to shut down the server.");
            }
            catch (Exception ex)
            {
                RhinoApp.WriteLine("AlmondMCP: Failed to start server — {0}", ex.Message);
                RhinoApp.WriteLine("AlmondMCP: Ensure 'uv' is installed and on your PATH.");
                return Result.Failure;
            }

            return Result.Success;
        }

        /// <summary>
        /// Searches for server.py in the plugin directory and parent directories.
        /// </summary>
        private string FindServerScript(string startDir)
        {
            // Check in the same directory as the DLL
            string candidate = Path.Combine(startDir, "server.py");
            if (File.Exists(candidate)) return candidate;

            // Check parent directory (typical structure: RhinoAlmondBridge/bin/Release/ → mcp-rhino-plugin/)
            string dir = startDir;
            for (int i = 0; i < 4; i++)
            {
                dir = Path.GetDirectoryName(dir);
                if (dir == null) break;
                candidate = Path.Combine(dir, "server.py");
                if (File.Exists(candidate)) return candidate;
            }

            return null;
        }

        /// <summary>
        /// Called by AlmondMCPStopCommand to kill the server process.
        /// </summary>
        public static void StopServer()
        {
            if (_serverProcess != null && !_serverProcess.HasExited)
            {
                try
                {
                    _serverProcess.Kill();
                    _serverProcess.WaitForExit(3000);
                    RhinoApp.WriteLine("AlmondMCP: Server stopped.");
                }
                catch (Exception ex)
                {
                    RhinoApp.WriteLine("AlmondMCP: Error stopping server — {0}", ex.Message);
                }
            }
            else
            {
                RhinoApp.WriteLine("AlmondMCP: Server is not running.");
            }
            _serverProcess = null;
        }
    }

    /// <summary>
    /// Rhino command: AlmondMCPStop
    /// Gracefully shuts down the background MCP server process.
    /// </summary>
    public class AlmondMCPStopCommand : Command
    {
        public override string EnglishName => "AlmondMCPStop";

        protected override Result RunCommand(RhinoDoc doc, RunMode mode)
        {
            AlmondMCPStartCommand.StopServer();
            return Result.Success;
        }
    }

    /// <summary>
    /// Rhino command: AlmondMCPStatus
    /// Reports the current status of the bridge and MCP server.
    /// </summary>
    public class AlmondMCPStatusCommand : Command
    {
        public override string EnglishName => "AlmondMCPStatus";

        protected override Result RunCommand(RhinoDoc doc, RunMode mode)
        {
            RhinoApp.WriteLine("=== AlmondMCP Status ===");
            RhinoApp.WriteLine("Bridge:  Port 5000 (active since plugin load)");

            // Check if server process is alive
            var serverField = typeof(AlmondMCPStartCommand)
                .GetField("_serverProcess", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Static);
            var proc = serverField?.GetValue(null) as Process;

            if (proc != null && !proc.HasExited)
                RhinoApp.WriteLine("Server:  Running (PID {0})", proc.Id);
            else
                RhinoApp.WriteLine("Server:  Not running. Type 'AlmondMCPStart' to launch.");

            return Result.Success;
        }
    }
}
