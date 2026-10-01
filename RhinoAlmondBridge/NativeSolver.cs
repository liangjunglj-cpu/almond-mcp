using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;

namespace RhinoAlmondBridge
{
    /// <summary>
    /// Almond's native structural solver, run out of process: one JSON request on stdin of
    /// <c>almond-mcp solve</c>, one JSON reply on stdout. The panel uses it so the Karamba-free
    /// engine (floor and asset loads, EN 1990 combinations, connections, stability) needs no MCP
    /// client. The command is <c>uvx almond-mcp@&lt;this plugin's version&gt; solve</c> (uv is already
    /// required for the MCP server; the pin keeps the bridge and solver protocol in step), or the
    /// command line in ALMOND_SOLVER_COMMAND for development checkouts. No shell is involved.
    /// </summary>
    internal static class NativeSolver
    {
        internal const int Protocol = 1;
        private const string EnvCommand = "ALMOND_SOLVER_COMMAND";

        internal sealed class Command
        {
            public string File;
            public string Arguments;
            public string Label;
        }

        internal static string PluginVersion
        {
            get
            {
                var asm = typeof(NativeSolver).Assembly;
                var info = asm.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion;
                return string.IsNullOrWhiteSpace(info) ? asm.GetName().Version.ToString(3) : info.Split('+')[0];
            }
        }

        /// <summary>The solver command, or null with a reason when none can be found.</summary>
        internal static Command Resolve(out string reason)
        {
            reason = null;
            string custom = Environment.GetEnvironmentVariable(EnvCommand);
            if (!string.IsNullOrWhiteSpace(custom))
            {
                Split(custom.Trim(), out string file, out string rest);
                return new Command { File = file, Arguments = (rest + " solve").Trim(), Label = custom.Trim() + " solve" };
            }
            string uvx = FindUvx();
            if (uvx == null)
            {
                reason = "uv is not installed (the Almond MCP server needs it too): winget install astral-sh.uv, then restart Rhino.";
                return null;
            }
            // a release plugin pins its own solver version; a development build takes the latest
            string version = PluginVersion;
            string package = version.Contains("-") ? "almond-mcp" : "almond-mcp@" + version;
            return new Command { File = uvx, Arguments = package + " solve", Label = "uvx " + package + " solve" };
        }

        private static string FindUvx()
        {
            var dirs = (Environment.GetEnvironmentVariable("PATH") ?? "").Split(Path.PathSeparator).ToList();
            string home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
            string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            dirs.Add(Path.Combine(home, ".local", "bin"));
            dirs.Add(Path.Combine(home, ".cargo", "bin"));
            dirs.Add(Path.Combine(local, "Microsoft", "WinGet", "Links"));
            foreach (var d in dirs)
            {
                if (string.IsNullOrWhiteSpace(d)) continue;
                try
                {
                    string candidate = Path.Combine(d.Trim().Trim('"'), "uvx.exe");
                    if (File.Exists(candidate)) return candidate;
                }
                catch (ArgumentException) { }
            }
            return null;
        }

        private static void Split(string commandLine, out string file, out string rest)
        {
            if (commandLine.StartsWith("\"", StringComparison.Ordinal))
            {
                int close = commandLine.IndexOf('"', 1);
                file = close > 0 ? commandLine.Substring(1, close - 1) : commandLine.Trim('"');
                rest = close > 0 ? commandLine.Substring(close + 1).Trim() : "";
                return;
            }
            int space = commandLine.IndexOf(' ');
            file = space > 0 ? commandLine.Substring(0, space) : commandLine;
            rest = space > 0 ? commandLine.Substring(space + 1).Trim() : "";
        }

        /// <summary>Run one request. Never throws: failures come back as {"status":"error","message":...}.</summary>
        internal static async Task<JObject> RunAsync(JObject request, int timeoutMs)
        {
            var command = Resolve(out string reason);
            if (command == null) return Error(reason);
            request["protocol"] = Protocol;
            var info = new ProcessStartInfo(command.File, command.Arguments)
            {
                UseShellExecute = false, CreateNoWindow = true, RedirectStandardInput = true,
                RedirectStandardOutput = true, RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8,
            };
            info.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
            info.EnvironmentVariables["PYTHONUTF8"] = "1";
            Process process;
            try { process = Process.Start(info); }
            catch (Exception ex) { return Error("Could not start the native solver (" + command.Label + "): " + ex.Message); }
            using (process)
            {
                var stdout = process.StandardOutput.ReadToEndAsync();
                var stderr = process.StandardError.ReadToEndAsync();
                try
                {
                    byte[] payload = new UTF8Encoding(false).GetBytes(request.ToString(Newtonsoft.Json.Formatting.None));
                    await process.StandardInput.BaseStream.WriteAsync(payload, 0, payload.Length).ConfigureAwait(false);
                    process.StandardInput.Close();
                }
                catch (IOException) { /* the process exited early: its stderr says why */ }
                var done = Task.Run(() => process.WaitForExit(timeoutMs));
                if (!await done.ConfigureAwait(false))
                {
                    try { process.Kill(); } catch { }
                    return Error($"The native solver did not answer within {timeoutMs / 1000} s ({command.Label}). " +
                                 "The first run downloads it; try again once that finishes.");
                }
                string output = await stdout.ConfigureAwait(false);
                string errors = await stderr.ConfigureAwait(false);
                JObject reply = null;
                try { reply = JObject.Parse(output); } catch { }
                if (reply == null)
                {
                    string tail = Tail(errors);
                    return Error("The native solver returned no result (" + command.Label + ", exit " + process.ExitCode + ")." +
                                 (tail.Length > 0 ? " " + tail : ""));
                }
                if ((int?)reply["protocol"] != Protocol)
                    return Error($"Solver protocol mismatch: the plugin speaks {Protocol}, the solver {(string)reply["protocol"] ?? "?"}. " +
                                 "Update almondbridge and almond-mcp together.");
                reply["solver"] = command.Label;
                return reply;
            }
        }

        private static string Tail(string text)
        {
            var lines = (text ?? "").Split('\n').Select(l => l.Trim()).Where(l => l.Length > 0).ToList();
            return string.Join(" ", lines.Skip(Math.Max(0, lines.Count - 3)));
        }

        private static JObject Error(string message) =>
            new JObject { ["protocol"] = Protocol, ["status"] = "error", ["message"] = message };
    }
}
