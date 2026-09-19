using System;
using System.Runtime.InteropServices;
using System.Text.RegularExpressions;
using Eto.Drawing;
using Eto.Forms;
using Rhino;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

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
        private readonly string _session = Guid.NewGuid().ToString("N");
        private bool _ready;
        internal static string StartPage = "home";
        private string _page = StartPage;
        private readonly AnalysisWorkspace _analysis;

        public AlmondLibraryPanel()
        {
            _analysis = new AnalysisWorkspace(reply => {
                if (_ready && _view != null) _view.ExecuteScript("window.almondAnalysisReceive && window.almondAnalysisReceive(" +
                    JsonConvert.SerializeObject(reply,new JsonSerializerSettings{StringEscapeHandling=StringEscapeHandling.EscapeHtml}) + ");");
            });
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
                _ready = false;
                var view = new WebView(); // Rhino 8 supplies its Edge WebView2 handler.
                view.DocumentLoaded += (s, e) => _ready = e.Uri != null && e.Uri.Authority == _archive.Authority && e.Uri.AbsolutePath == "/";
                view.DocumentLoading += (s, e) =>
                {
                    if (!e.IsMainFrame || e.Uri == null) return;
                    bool local = e.Uri.Scheme == _archive.Scheme && e.Uri.Authority == _archive.Authority;
                    if (local && e.Uri.AbsolutePath.StartsWith("/almond-action/", StringComparison.Ordinal))
                    {
                        e.Cancel = true;
                        // The capability exists only in this panel's URL; the HTTP host
                        // has no placement endpoint and continues to accept GET/HEAD only.
                        var action = Regex.Match(e.Uri.AbsolutePath, "^/almond-action/" + _session + "/(drag|place)/(light|original)/(gen-[a-z0-9-]{1,100})$");
                        if (_ready && action.Success)
                            LibraryPlacement.Request(action.Groups[3].Value, action.Groups[1].Value == "drag", action.Groups[2].Value == "light");
                        var analysis = Regex.Match(e.Uri.AbsolutePath,"^/almond-action/"+_session+"/karamba/(status|capture|analyze|highlight|export)$");
                        if (_ready && analysis.Success)
                        {
                            try {
                                string query=e.Uri.Query;
                                if(!query.StartsWith("?data=",StringComparison.Ordinal) || query.Length>12000) return;
                                _analysis.Request(analysis.Groups[1].Value,Uri.UnescapeDataString(query.Substring(6)));
                            } catch(Exception ex) { RhinoApp.WriteLine("Almond analysis: {0}",ex.Message); }
                        }
                        return;
                    }
                    // Keep the archive in the panel. Downloads and source pages use the browser.
                    if (local && e.Uri.AbsolutePath == "/") return;
                    e.Cancel = true;
                    OpenExternal(e.Uri.AbsoluteUri);
                };
                view.OpenNewWindow += (s, e) => { if (e.Uri != null) OpenExternal(e.Uri.AbsoluteUri); };
                _body.Content = view;
                _view = view;
                view.Url = new Uri(_archive, "?panel=1&bridge=" + _session + "#" + _page);
            }
            catch (Exception ex)
            {
                _view?.Dispose();
                _view = null;
                _body.Content = new Label { Text = "The embedded archive could not start. Use Reload or Open in browser.\n\n" + ex.Message, Wrap = WrapMode.Word };
                RhinoApp.WriteLine("Almond Library panel: {0}", ex.Message);
            }
        }
        internal void ShowPage(string page)
        {
            if (page!="home" && page!="library" && page!="karamba") return;
            _page=page;
            if(_ready) _view.ExecuteScript("location.hash="+JsonConvert.SerializeObject(page)+";");
            else if(_view!=null) _view.Url=new Uri(_archive,"?panel=1&bridge="+_session+"#"+page);
        }

        private void OpenExternal(string url)
        {
            try { AlmondLibraryCommand.OpenBrowser(url); }
            catch (Exception ex) { RhinoApp.WriteLine("Almond Library browser: {0}", ex.Message); }
        }
    }
}
