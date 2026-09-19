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
        internal static byte[] ReadArchive(string route)
        {
            string url = ArchiveUrl;
            return _archive.ReadVerified(route);
        }

        internal static string ArchiveUrl
        {
            get
            {
                if (_archive == null)
                {
                    string directory = Path.Combine(Path.GetDirectoryName(typeof(AlmondLibraryCommand).Assembly.Location), "archive");
                    var server = new ArchiveHttpServer(directory);
                    try { server.Start(); } catch { server.Dispose(); throw; }
                    _archive = server;
                }
                return _archive.Url;
            }
        }

        internal static void OpenBrowser(string url = null)
        {
            var uri = new Uri(url ?? ArchiveUrl);
            if (uri.Scheme != Uri.UriSchemeHttp && uri.Scheme != Uri.UriSchemeHttps) return;
            Process.Start(new ProcessStartInfo(uri.AbsoluteUri) { UseShellExecute = true });
        }

        protected override Result RunCommand(RhinoDoc doc, RunMode mode)
        {
            try
            {
                // Start before opening so a missing bundle produces a useful command error.
                string url = ArchiveUrl;
                Rhino.UI.Panels.OpenPanel(AlmondLibraryPanel.PanelId, true);
                RhinoApp.WriteLine("Almond Library panel opened. Drag its tab to dock it beside your viewport.");
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

    public class AlmondLibraryBrowserCommand : Command
    {
        public override string EnglishName => "AlmondLibraryBrowser";

        protected override Result RunCommand(RhinoDoc doc, RunMode mode)
        {
            try { AlmondLibraryCommand.OpenBrowser(); return Result.Success; }
            catch (Exception ex) { RhinoApp.WriteLine("AlmondLibraryBrowser: {0}", ex.Message); return Result.Failure; }
        }
    }
}
