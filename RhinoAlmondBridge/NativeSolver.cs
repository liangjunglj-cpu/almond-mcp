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
            string package = PackageFor(PluginVersion);
            return new Command { File = uvx, Arguments = package + " solve", Label = "uvx " + package + " solve" };
        }

        /// <summary>
        /// The uvx package for a plugin version. A release (0.7.0) or Yak prerelease (0.7.0-rc.1) pins its PyPI twin
        /// (almond-mcp@0.7.0, almond-mcp@0.7.0rc1): unpinned, uvx would resolve the latest stable release, which can
        /// predate this bridge's solver protocol. A development build (0.6.1-dev) takes the latest.
        /// </summary>
        internal static string PackageFor(string version)
        {
            var m = System.Text.RegularExpressions.Regex.Match(version ?? "", @"^(\d+\.\d+\.\d+)(?:-(alpha|beta|rc)\.(\d+))?$");
            if (!m.Success) return "almond-mcp";
            if (!m.Groups[2].Success) return "almond-mcp@" + m.Groups[1].Value;
            string tag = m.Groups[2].Value == "alpha" ? "a" : m.Groups[2].Value == "beta" ? "b" : "rc";
            return "almond-mcp@" + m.Groups[1].Value + tag + m.Groups[3].Value;
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
            // uv trusts only its bundled certificates by default. Behind security software or a proxy that inspects HTTPS
            // (common in offices) the first-run download then fails with "invalid peer certificate: UnknownIssuer".
            // Use the Windows certificate store instead, unless the user has chosen a setting of their own.
            if (!info.EnvironmentVariables.ContainsKey("UV_NATIVE_TLS") && !info.EnvironmentVariables.ContainsKey("UV_SYSTEM_CERTS"))
                info.EnvironmentVariables["UV_NATIVE_TLS"] = "1";
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
