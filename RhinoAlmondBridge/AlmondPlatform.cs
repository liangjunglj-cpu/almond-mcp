using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;

namespace RhinoAlmondBridge
{
    /// <summary>
    /// The few places where Windows and macOS differ. On Windows every member returns what the plugin used
    /// before it gained a macOS build, so Windows behaviour is unchanged.
    /// </summary>
    internal static class AlmondPlatform
    {
        internal static bool IsWindows => RuntimeInformation.IsOSPlatform(OSPlatform.Windows);
        internal static bool IsMac => RuntimeInformation.IsOSPlatform(OSPlatform.OSX);

        /// <summary>
        /// Almond's per-user data folder, the one <c>almond_mcp.paths.user_data_dir</c> uses: %LOCALAPPDATA%\Almond on
        /// Windows, ~/Library/Application Support/Almond on macOS. Spelled out for macOS because .NET's
        /// SpecialFolder.LocalApplicationData there is ~/.local/share before .NET 8, so the bridge and the MCP server
        /// would disagree about where the session token lives.
        /// </summary>
        internal static string UserDataDir
        {
            get
            {
                if (IsMac)
                    return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
                        "Library", "Application Support", "Almond");
                return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Almond");
            }
        }

        /// <summary>Show a folder in Explorer (Windows) or Finder (macOS).</summary>
        internal static void OpenFolder(string dir)
        {
            if (IsWindows) Process.Start("explorer.exe", "\"" + dir + "\"");
            else
            {
                var info = new ProcessStartInfo(IsMac ? "open" : "xdg-open") { UseShellExecute = false };
#if NETFRAMEWORK
                info.Arguments = "\"" + dir + "\"";
#else
                info.ArgumentList.Add(dir);
#endif
                Process.Start(info)?.Dispose();
            }
        }

        /// <summary>One-line install hint for uv on this platform.</summary>
        internal static string InstallUvHint => IsWindows ? "winget install astral-sh.uv" : "brew install uv";
    }
}
