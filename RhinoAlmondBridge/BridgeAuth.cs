using System;
using System.IO;
using System.Security.Cryptography;
using System.Text;

namespace RhinoAlmondBridge
{
    /// <summary>
    /// Per-session bridge token. The bridge executes C# for its clients, so a loopback port alone is not
    /// enough: any local process (any user's, on a shared PC) could connect. Each Rhino session issues a
    /// random 256-bit token, written to the user's own data folder (%LOCALAPPDATA%\Almond\bridge.token,
    /// readable by that user only by the folder's default ACL), and every request must carry it as
    /// "token". The Almond MCP server and `almond-mcp doctor` read the file (or ALMOND_BRIDGE_TOKEN).
    /// </summary>
    public static class BridgeAuth
    {
        private static string _token;

        public static string TokenPath => Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Almond", "bridge.token");

        /// <summary>New token for this session, written atomically once the port is bound.</summary>
        public static void Issue()
        {
            var bytes = new byte[32];
            using (var rng = RandomNumberGenerator.Create()) rng.GetBytes(bytes);
            _token = BitConverter.ToString(bytes).Replace("-", "").ToLowerInvariant();
            string path = TokenPath;
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            string temp = path + ".tmp";
            File.WriteAllText(temp, _token, new UTF8Encoding(false));
            if (File.Exists(path)) File.Replace(temp, path, null);
            else File.Move(temp, path);
        }

        /// <summary>Remove the token file if it is still this session's (another Rhino may have replaced it).</summary>
        public static void Revoke()
        {
            try
            {
                string path = TokenPath;
                if (_token != null && File.Exists(path) && File.ReadAllText(path).Trim() == _token) File.Delete(path);
            }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
            _token = null;
        }

        /// <summary>Constant-time comparison with this session's token.</summary>
        public static bool Verify(string candidate)
        {
            string expected = _token;
            if (expected == null || candidate == null) return false;
            var a = Encoding.ASCII.GetBytes(expected);
            var b = Encoding.ASCII.GetBytes(candidate);
            int diff = a.Length ^ b.Length;
            for (int i = 0; i < a.Length; i++)
                diff |= a[i] ^ (i < b.Length ? b[i] : 0);
            return diff == 0;
        }
    }
}
