using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using Rhino;

namespace RhinoAlmondBridge
{
    /// <summary>
    /// TCP Server that listens for incoming requests from the MCP server.
    /// Supported request types:
    ///   {"type": "execute", "script": "C# code..."}
    ///   {"type": "validate", "guids": [...], "structure_type": "beam", ...}
    ///   {"type": "run_definition", "capsule_id": "...", "manifest_path": "...", ...}
    ///   {"type": "export_glb", "guids": [...], "output_path": "..."}
    ///   {"type": "place_furniture", "asset_id": "...", "file_path": "...", ...}
    ///   {"type": "place_drawing_asset", "asset_id": "...", "file_path": "...", ...}
    ///   {"type": "import_hatch_patterns", "file_path": "..."}
    ///   {"type": "apply_drawing_style", "recipe_id": "...", "layers": [...]}
    /// Runs on a background thread, marshals execution to Rhino UI thread.
    /// </summary>
    public class BridgeServer
    {
        private readonly int _port;
        private Thread _listenerThread;
        private volatile bool _running;
        private StructuralValidator _validator;
        private GhDefinitionRunner _definitionRunner;
        private FurnitureAssetManager _furnitureManager;
        private FurnitureAssetManager _drawingAssetManager;
        private DrawingStyleManager _drawingStyleManager;

        public BridgeServer(int port = 5000)
        {
            _port = port;
        }

        public void Start()
        {
            if (_running) return;
            _running = true;

            // Resolve the Grasshopper library directory from environment or default
            string libDir = Environment.GetEnvironmentVariable("RHINO_MCP_LIBRARY_DIR")
                ?? FindLibraryDirectory();
            string capsuleDir = Environment.GetEnvironmentVariable("RHINO_MCP_CAPSULE_DIR")
                ?? FindCapsuleDirectory();
            _validator = new StructuralValidator(libDir, capsuleDir);
            _definitionRunner = new GhDefinitionRunner(libDir, capsuleDir);
            string furnitureDir = Environment.GetEnvironmentVariable("RHINO_MCP_FURNITURE_DIR")
                ?? FindFurnitureDirectory();
            _furnitureManager = new FurnitureAssetManager(furnitureDir);
            string drawingAssetDir = Environment.GetEnvironmentVariable("RHINO_MCP_DRAWING_ASSET_DIR")
                ?? FindDrawingAssetDirectory();
            _drawingAssetManager = new FurnitureAssetManager(
                drawingAssetDir,
                "ALMOND-DRAW::ASSETS",
                "DRAWING",
                "drawing_asset",
                "drawing asset",
                new[] { ".skp", ".3dm", ".dwg", ".dxf", ".svg", ".png" }
            );
            _drawingStyleManager = new DrawingStyleManager();

            _listenerThread = new Thread(ListenLoop)
            {
                IsBackground = true,
                Name = "AlmondBridge_Listener"
            };
            _listenerThread.Start();
        }

        private string FindLibraryDirectory()
        {
            string directory = Path.GetDirectoryName(typeof(BridgeServer).Assembly.Location);
            for (int i = 0; i < 6 && directory != null; i++)
            {
                string candidate = Path.Combine(directory, "Grasshopperfiles");
                if (Directory.Exists(candidate)) return candidate;
                directory = Path.GetDirectoryName(directory);
            }

            return Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),
                "Almond",
                "Grasshopperfiles"
            );
        }

        private string FindFurnitureDirectory()
        {
            string directory = Path.GetDirectoryName(typeof(BridgeServer).Assembly.Location);
            for (int i = 0; i < 6 && directory != null; i++)
            {
                string candidate = Path.Combine(directory, "IkeaFurniturefiles");
                if (Directory.Exists(candidate)) return candidate;
                directory = Path.GetDirectoryName(directory);
            }

            return Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),
                "Almond",
                "mcp-rhino-plugin",
                "IkeaFurniturefiles"
            );
        }

        private string FindCapsuleDirectory()
        {
            string directory = Path.GetDirectoryName(typeof(BridgeServer).Assembly.Location);
            for (int i = 0; i < 6 && directory != null; i++)
            {
                string candidate = Path.Combine(directory, "capsules");
                if (Directory.Exists(candidate)) return candidate;
                directory = Path.GetDirectoryName(directory);
            }

            return Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),
                "Almond",
                "mcp-rhino-plugin",
                "capsules"
            );
        }

        private string FindDrawingAssetDirectory()
        {
            string directory = Path.GetDirectoryName(typeof(BridgeServer).Assembly.Location);
            for (int i = 0; i < 6 && directory != null; i++)
            {
                string candidate = Path.Combine(directory, "DrawingAssetfiles");
                if (Directory.Exists(candidate)) return candidate;
                directory = Path.GetDirectoryName(directory);
            }

            return Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),
                "Almond",
                "mcp-rhino-plugin",
                "DrawingAssetfiles"
            );
        }

        public void Stop()
        {
            _running = false;
        }

        private void ListenLoop()
        {
            var listener = new TcpListener(IPAddress.Loopback, _port);

            try
            {
                listener.Start();
            }
            catch (Exception ex)
            {
                RhinoApp.WriteLine($"RhinoAlmondBridge: Failed to bind port {_port}: {ex.Message}");
                _running = false;
                return;
            }

            listener.Server.ReceiveTimeout = 1000;

            while (_running)
            {
                try
                {
                    if (!listener.Pending())
                    {
                        Thread.Sleep(100);
                        continue;
                    }

                    using (var client = listener.AcceptTcpClient())
                    using (var stream = client.GetStream())
                    {
                        // Read length-prefixed message: 4-byte big-endian length + payload
                        var headerBytes = ReadExact(stream, 4);
                        if (headerBytes == null) continue;

                        int msgLength = (headerBytes[0] << 24) | (headerBytes[1] << 16) |
                                        (headerBytes[2] << 8) | headerBytes[3];

                        var payloadBytes = ReadExact(stream, msgLength);
                        if (payloadBytes == null) continue;

                        string json = Encoding.UTF8.GetString(payloadBytes);

                        // Route based on request type
                        string responseJson = null;
                        var resetEvent = new ManualResetEventSlim(false);

                        RhinoApp.InvokeOnUiThread(new Action(() =>
                        {
                            responseJson = HandleRequest(json);
                            resetEvent.Set();
                        }));

                        // Wait up to 60 seconds (validation can take longer than
                        // scripts); run_definition requests may declare a larger
                        // timeout_s, honored here with a small grace margin.
                        double waitSeconds = 60;
                        try
                        {
                            var peek = JObject.Parse(json);
                            double? requested = peek.Value<double?>("timeout_s");
                            if (requested.HasValue && requested.Value > 0)
                                waitSeconds = Math.Max(waitSeconds, requested.Value + 10);
                        }
                        catch { /* malformed JSON is reported by HandleRequest */ }

                        if (!resetEvent.Wait(TimeSpan.FromSeconds(waitSeconds)))
                        {
                            var timeout = new { status = "error", message = $"Execution timed out ({waitSeconds:F0}s)." };
                            responseJson = JsonConvert.SerializeObject(timeout);
                        }

                        // Send length-prefixed response
                        byte[] respBytes = Encoding.UTF8.GetBytes(responseJson);
                        byte[] respHeader = new byte[4];
                        respHeader[0] = (byte)((respBytes.Length >> 24) & 0xFF);
                        respHeader[1] = (byte)((respBytes.Length >> 16) & 0xFF);
                        respHeader[2] = (byte)((respBytes.Length >> 8) & 0xFF);
                        respHeader[3] = (byte)(respBytes.Length & 0xFF);

                        stream.Write(respHeader, 0, 4);
                        stream.Write(respBytes, 0, respBytes.Length);
                        stream.Flush();
                    }
                }
                catch (Exception ex)
                {
                    if (_running)
                        RhinoApp.WriteLine($"RhinoAlmondBridge: Connection error: {ex.Message}");
                }
            }

            listener.Stop();
        }

        /// <summary>
        /// Routes a JSON request to the appropriate handler based on the "type" field.
        /// </summary>
        private string HandleRequest(string json)
        {
            try
            {
                var jobj = JObject.Parse(json);
                string requestType = jobj.Value<string>("type") ?? "execute";

                switch (requestType.ToLower())
                {
                    case "place_furniture":
                        RhinoApp.WriteLine("RhinoAlmondBridge: Placing indexed IKEA furniture...");
                        var furnitureRequest = jobj.ToObject<FurniturePlacementRequest>();
                        var furnitureResult = _furnitureManager.Place(furnitureRequest);
                        return JsonConvert.SerializeObject(furnitureResult);

                    case "place_drawing_asset":
                        RhinoApp.WriteLine("RhinoAlmondBridge: Placing indexed drawing asset...");
                        var drawingAssetRequest = jobj.ToObject<FurniturePlacementRequest>();
                        var drawingAssetResult = _drawingAssetManager.Place(drawingAssetRequest);
                        return JsonConvert.SerializeObject(drawingAssetResult);

                    case "import_hatch_patterns":
                        RhinoApp.WriteLine("RhinoAlmondBridge: Importing hatch patterns...");
                        string hatchFilePath = jobj.Value<string>("file_path") ?? "";
                        var hatchResult = _drawingAssetManager.ImportHatchPatterns(hatchFilePath);
                        return JsonConvert.SerializeObject(hatchResult);

                    case "apply_drawing_style":
                        RhinoApp.WriteLine("RhinoAlmondBridge: Applying drawing layer style...");
                        var drawingStyleRequest = jobj.ToObject<DrawingStyleRequest>();
                        var drawingStyleResult = _drawingStyleManager.Apply(drawingStyleRequest);
                        return JsonConvert.SerializeObject(drawingStyleResult);

                    case "export_glb":
                        RhinoApp.WriteLine("RhinoAlmondBridge: Exporting linked GLB...");
                        var exportRequest = jobj.ToObject<GlbExportRequest>();
                        var exportResult = new GlbExporter().Export(exportRequest);
                        return JsonConvert.SerializeObject(exportResult);

                    case "run_definition":
                        RhinoApp.WriteLine("RhinoAlmondBridge: Running capsule definition...");
                        return HandleRunDefinition(jobj);

                    case "validate":
                        RhinoApp.WriteLine("RhinoAlmondBridge: Running structural validation...");
                        var valRequest = jobj.ToObject<ValidationRequest>();
                        var valResult = _validator.Validate(valRequest);
                        RhinoApp.WriteLine($"RhinoAlmondBridge: Validation {valResult.Status}: {valResult.Verdict}");
                        return JsonConvert.SerializeObject(valResult);

                    case "execute":
                    default:
                        string script = jobj.Value<string>("script") ?? "";
                        var executor = new ScriptExecutor();
                        var execResult = executor.Execute(script);
                        return JsonConvert.SerializeObject(execResult);
                }
            }
            catch (Exception ex)
            {
                var error = new { status = "error", message = ex.Message, error_trace = ex.ToString() };
                return JsonConvert.SerializeObject(error);
            }
        }

        /// <summary>
        /// Handles {"type": "run_definition", "capsule_id": "...",
        ///          "manifest_path": "...", "inputs": {...},
        ///          "seed": 42, "timeout_s": 60}
        /// and answers with the exact payload contract from IMPLEMENTATION_PLAN.md:
        /// {"status": "ok|error", "capsule_id": "...", "outputs": {...},
        ///  "baked_guids": [], "analysis_method": "api|template|rule_based",
        ///  "confidence": "high|medium|low", "warnings": [], "error": null}
        /// </summary>
        private string HandleRunDefinition(JObject jobj)
        {
            string capsuleId = jobj.Value<string>("capsule_id");
            string manifestPath = jobj.Value<string>("manifest_path");
            var inputs = jobj["inputs"] as JObject;
            int? seed = jobj.Value<int?>("seed");
            double timeoutS = jobj.Value<double?>("timeout_s") ?? 60.0;

            string Respond(string status, string cid, Dictionary<string, object> outputs,
                List<string> bakedGuids, string method, string confidence,
                List<string> warnings, string error)
            {
                return JsonConvert.SerializeObject(new
                {
                    status = status,
                    capsule_id = cid,
                    outputs = outputs ?? new Dictionary<string, object>(),
                    baked_guids = bakedGuids ?? new List<string>(),
                    analysis_method = method,
                    confidence = confidence,
                    warnings = warnings ?? new List<string>(),
                    error = error,
                });
            }

            // Resolve the manifest: explicit path wins, else look up by capsule_id.
            if (string.IsNullOrEmpty(manifestPath) && !string.IsNullOrEmpty(capsuleId))
                manifestPath = _definitionRunner.FindManifestPath(capsuleId);

            if (string.IsNullOrEmpty(manifestPath))
            {
                return Respond("error", capsuleId, null, null, "template", "medium", null,
                    $"No manifest found for capsule_id '{capsuleId}' and no manifest_path given.");
            }

            // Manifest confidence drives the reported method/confidence pair:
            // api → high, template → medium, rule_based → low.
            string loadError;
            var manifest = GhDefinitionRunner.LoadManifest(manifestPath, out loadError);
            string analysisMethod = manifest?.Confidence ?? "template";
            string confidenceLevel =
                analysisMethod == "api" ? "high" :
                analysisMethod == "rule_based" ? "low" : "medium";

            if (manifest == null)
            {
                return Respond("error", capsuleId, null, null, analysisMethod,
                    confidenceLevel, null, loadError);
            }

            var runResult = _definitionRunner.Run(manifestPath, inputs, timeoutS, seed);

            return Respond(
                runResult.Status == "ok" ? "ok" : "error",
                runResult.CapsuleId ?? manifest.CapsuleId ?? capsuleId,
                runResult.Outputs,
                runResult.BakedGuids,
                analysisMethod,
                confidenceLevel,
                runResult.Warnings,
                runResult.Error);
        }

        /// <summary>
        /// Read exactly 'count' bytes from the stream, blocking until all bytes arrive.
        /// </summary>
        private byte[] ReadExact(NetworkStream stream, int count)
        {
            byte[] buffer = new byte[count];
            int offset = 0;
            while (offset < count)
            {
                int read = stream.Read(buffer, offset, count - offset);
                if (read == 0) return null; // Connection closed
                offset += read;
            }
            return buffer;
        }
    }
}
