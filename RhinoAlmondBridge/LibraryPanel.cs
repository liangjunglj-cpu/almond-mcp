using System;
using System.Runtime.InteropServices;
using Eto.Drawing;
using Eto.Forms;
using Rhino;

namespace RhinoAlmondBridge
{
    // Stable panel identity: Rhino remembers the user's dock position across sessions.
    [Guid("dfe280c6-7e79-4afd-9f3d-729034d5b9b1")]
    public class AlmondLibraryPanel : Panel
    {
        public static Guid PanelId => typeof(AlmondLibraryPanel).GUID;
        private WebView _view;
        private readonly Panel _body = new Panel();
        private Uri _archive;

        public AlmondLibraryPanel()
        {
            MinimumSize = new Size(280, 240);
            var browser = new Button { Text = "Open in browser" };
            browser.Click += (s, e) => OpenExternal(null);
            var reload = new Button { Text = "Reload" };
            reload.Click += (s, e) => { if (_view == null) LoadArchive(); else _view.Reload(); };
            var layout = new DynamicLayout { Padding = new Padding(0), Spacing = new Size(0, 0) };
            layout.AddSeparateRow(browser, null, reload);
            layout.Add(_body, yscale: true);
            Content = layout;
            LoadArchive();
        }

        private void LoadArchive()
        {
            try
            {
                _archive = new Uri(AlmondLibraryCommand.ArchiveUrl);
                var view = new WebView(); // Rhino 8 supplies its Edge WebView2 handler.
                view.DocumentLoading += (s, e) =>
                {
                    if (!e.IsMainFrame || e.Uri == null) return;
                    bool local = e.Uri.Scheme == _archive.Scheme && e.Uri.Authority == _archive.Authority;
                    // Keep the archive in the panel. Downloads and source pages use the browser.
                    if (local && e.Uri.AbsolutePath == "/") return;
                    e.Cancel = true;
                    OpenExternal(e.Uri.AbsoluteUri);
                };
                view.OpenNewWindow += (s, e) => { if (e.Uri != null) OpenExternal(e.Uri.AbsoluteUri); };
                _body.Content = view;
                _view = view;
                view.Url = new Uri(_archive, "?panel=1");
            }
            catch (Exception ex)
            {
                _view?.Dispose();
                _view = null;
                _body.Content = new Label { Text = "The embedded archive could not start. Use Reload or Open in browser.\n\n" + ex.Message, Wrap = WrapMode.Word };
                RhinoApp.WriteLine("Almond Library panel: {0}", ex.Message);
            }
        }

        private void OpenExternal(string url)
        {
            try { AlmondLibraryCommand.OpenBrowser(url); }
            catch (Exception ex) { RhinoApp.WriteLine("Almond Library browser: {0}", ex.Message); }
        }
    }
}
