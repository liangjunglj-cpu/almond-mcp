using Rhino;
using Rhino.PlugIns;

namespace RhinoAlmondBridge
{
    /// <summary>
    /// RhinoAlmondBridge Plugin - MCP Bridge for AI-driven C# RhinoCommon script execution.
    /// Automatically starts a TCP listener on Rhino startup to receive and compile
    /// C# scripts from the MCP server.
    /// </summary>
    public class RhinoAlmondBridgePlugin : PlugIn
    {
        private BridgeServer _server;

        public static RhinoAlmondBridgePlugin Instance { get; private set; }

        public RhinoAlmondBridgePlugin()
        {
            Instance = this;
        }

        // Load at startup so the TCP listener is available without the user
        // running any command first (Rhino's default is load-when-needed,
        // which would leave a fresh install silent until AlmondMCPStart).
        public override PlugInLoadTime LoadTime => PlugInLoadTime.AtStartup;

        protected override LoadReturnCode OnLoad(ref string errorMessage)
        {
            RhinoApp.WriteLine("RhinoAlmondBridge: Loading MCP Bridge plugin...");

            _server = new BridgeServer(port: 5000);
            _server.Start();

            RhinoApp.WriteLine("RhinoAlmondBridge: TCP listener started on port 5000.");
            RhinoApp.WriteLine("RhinoAlmondBridge: Ready to receive C# scripts from MCP server.");

            return LoadReturnCode.Success;
        }

        protected override void OnShutdown()
        {
            _server?.Stop();
            RhinoApp.WriteLine("RhinoAlmondBridge: Plugin shut down.");
            base.OnShutdown();
        }
    }
}
