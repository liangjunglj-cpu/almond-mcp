using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;

namespace RhinoAlmondBridge
{
    // A loopback-only file server for the immutable, allowlisted archive payload.
    // TcpListener avoids HttpListener URL reservations/admin rights on Windows.
    // No Rhino dependencies: the exact host can be integration-tested standalone.
    internal sealed class ArchiveHttpServer : IDisposable
    {
        private readonly string _root;
        private readonly Dictionary<string, JObject> _routes = new Dictionary<string, JObject>(StringComparer.Ordinal);
        private TcpListener _listener;
        private volatile bool _running;
        public string Url { get; private set; }

        public ArchiveHttpServer(string directory)
        {
            _root = Path.GetFullPath(directory).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            var manifest = JObject.Parse(File.ReadAllText(Path.Combine(_root, "bundle.json"), Encoding.UTF8));
            if ((int?)manifest["schema_version"] != 1) throw new InvalidDataException("Unsupported archive bundle.");
            foreach (var route in ((JObject)manifest["routes"]).Properties())
            {
                if (!route.Name.StartsWith("/", StringComparison.Ordinal) || route.Name.Contains(".."))
                    throw new InvalidDataException("Invalid archive route.");
                var entry = (JObject)route.Value;
                Resolve((string)entry["path"]);
                _routes.Add(route.Name, entry);
            }
            if (!_routes.ContainsKey("/api/catalogue") || !_routes.ContainsKey("/"))
                throw new InvalidDataException("Incomplete archive bundle.");
        }

        private string Resolve(string relative)
        {
            if (string.IsNullOrWhiteSpace(relative) || Path.IsPathRooted(relative))
                throw new InvalidDataException("Invalid archive file path.");
            string path = Path.GetFullPath(Path.Combine(_root, relative.Replace('/', Path.DirectorySeparatorChar)));
            if (!path.StartsWith(_root, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("Archive file escapes the bundle.");
            // Do not follow links/junctions, including ones changed after startup.
            for (string current = path; current != null && current.Length >= _root.TrimEnd(Path.DirectorySeparatorChar).Length; current = Path.GetDirectoryName(current))
                if ((File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0)
                    throw new InvalidDataException("Archive links are not allowed.");
            return path;
        }

        public void Start()
        {
            if (_running) return;
            _listener = new TcpListener(IPAddress.Loopback, 0);
            _listener.Start(16);
            Url = "http://127.0.0.1:" + ((IPEndPoint)_listener.LocalEndpoint).Port + "/";
            _running = true;
            Task.Run(() => AcceptLoop());
        }

        private async Task AcceptLoop()
        {
            while (_running)
            {
                try
                {
                    var client = await _listener.AcceptTcpClientAsync().ConfigureAwait(false);
                    _ = Task.Run(() => Respond(client));
                }
                catch (ObjectDisposedException) { break; }
                catch (SocketException) { if (!_running) break; }
            }
        }

        private void Respond(TcpClient client)
        {
            using (client)
            {
                try
                {
                    client.ReceiveTimeout = 5000;
                    client.SendTimeout = 5000;
                    using (var stream = client.GetStream())
                    {
                        var header = new List<byte>();
                        while (header.Count < 16384)
                        {
                            int value = stream.ReadByte();
                            if (value < 0) return;
                            header.Add((byte)value);
                            int n = header.Count;
                            if (n >= 4 && header[n-4] == 13 && header[n-3] == 10 && header[n-2] == 13 && header[n-1] == 10) break;
                        }
                        if (header.Count >= 16384) { Send(stream, 431, "Headers too large", null, false); return; }
                        string[] lines = Encoding.ASCII.GetString(header.ToArray()).Split(new[] { "\r\n" }, StringSplitOptions.None);
                        string[] request = lines[0].Split(' ');
                        if (request.Length != 3 || !request[1].StartsWith("/", StringComparison.Ordinal))
                        { Send(stream, 400, "Bad request", null, false); return; }
                        bool head = request[0] == "HEAD";
                        if (request[0] != "GET" && !head) { Send(stream, 405, "Method not allowed", null, false); return; }
                        string host = null;
                        foreach (string line in lines)
                            if (line.StartsWith("Host:", StringComparison.OrdinalIgnoreCase))
                            {
                                if (host != null) { Send(stream, 400, "Bad request", null, head); return; }
                                host = line.Substring(5).Trim();
                            }
                        if (host != new Uri(Url).Authority) { Send(stream, 403, "Forbidden", null, head); return; }
                        string route = request[1].Split('?')[0];
                        if (!_routes.TryGetValue(route, out JObject entry)) { Send(stream, 404, "Not found", null, head); return; }
                        byte[] data = File.ReadAllBytes(Resolve((string)entry["path"]));
                        string hash;
                        using (var sha = SHA256.Create()) hash = BitConverter.ToString(sha.ComputeHash(data)).Replace("-", "").ToLowerInvariant();
                        if (hash != (string)entry["sha256"]) { Send(stream, 409, "Archive file changed; reinstall this release", null, head); return; }
                        string download = request[1].EndsWith("?download=1", StringComparison.Ordinal) ? Path.GetFileName((string)entry["path"]) : null;
                        Send(stream, 200, "OK", data, head, (string)entry["mime"], download);
                    }
                }
                catch (IOException) { /* A closing browser may cancel pending transfers. */ }
                catch (SocketException) { }
                catch (InvalidDataException) { }
                catch (UnauthorizedAccessException) { }
            }
        }

        private static void Send(Stream stream, int status, string message, byte[] payload, bool head, string mime = "text/plain; charset=utf-8", string download = null)
        {
            byte[] body = payload ?? Encoding.UTF8.GetBytes(message);
            string headers = "HTTP/1.1 " + status + " " + message + "\r\nContent-Type: " + mime
                + "\r\nContent-Length: " + body.Length + "\r\nConnection: close\r\nCache-Control: no-cache\r\n"
                + "X-Content-Type-Options: nosniff\r\nReferrer-Policy: no-referrer\r\n"
                + "Content-Security-Policy: default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; worker-src 'self' blob:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'\r\n";
            if (download != null) headers += "Content-Disposition: attachment; filename*=UTF-8''" + Uri.EscapeDataString(download) + "\r\n";
            byte[] bytes = Encoding.ASCII.GetBytes(headers + "\r\n");
            stream.Write(bytes, 0, bytes.Length);
            if (!head) stream.Write(body, 0, body.Length);
        }

        public void Dispose()
        {
            _running = false;
            _listener?.Stop();
        }
    }
}
