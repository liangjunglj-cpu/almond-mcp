using System;
using System.Diagnostics;
using System.IO;
using Rhino;
using Rhino.Commands;

namespace RhinoAlmondBridge
{
    public class AlmondLibraryCommand : Command
    {
        public override string EnglishName => "AlmondLibrary";
        private static ArchiveHttpServer _archive;

        protected override Result RunCommand(RhinoDoc doc, RunMode mode)
        {
            try
            {
                if (_archive == null)
                {
                    string directory = Path.Combine(Path.GetDirectoryName(typeof(AlmondLibraryCommand).Assembly.Location), "archive");
                    var server = new ArchiveHttpServer(directory);
                    try { server.Start(); } catch { server.Dispose(); throw; }
                    _archive = server;
                }
                Process.Start(new ProcessStartInfo(_archive.Url) { UseShellExecute = true });
                RhinoApp.WriteLine("Almond Object Archive: {0}", _archive.Url);
                RhinoApp.WriteLine("47 generated models, drawings and source records. Browsing needs no Python or AI client.");
                return Result.Success;
            }
            catch (Exception ex)
            {
                RhinoApp.WriteLine("AlmondLibrary: {0}", ex.Message);
                RhinoApp.WriteLine("Reinstall the full almondbridge package if its archive folder is missing.");
                return Result.Failure;
            }
        }

        internal static void StopArchive()
        {
            _archive?.Dispose();
            _archive = null;
        }
    }
}
