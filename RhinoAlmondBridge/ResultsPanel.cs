using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using Eto.Forms;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using Rhino;
using Rhino.Commands;

namespace RhinoAlmondBridge
{
    /// <summary>The latest analysis record, shared by the Structure workspace and the Results panel.</summary>
    internal static class AnalysisResults
    {
        internal static JObject Latest { get; private set; }
        internal static event Action<JObject> Changed;

        internal static void Publish(JObject report)
        {
            Latest = (JObject)report.DeepClone();
            Changed?.Invoke(Latest);
        }

        internal static void Open(RhinoDoc doc)
        {
            string url = AlmondLibraryCommand.ArchiveUrl;     // starts the archive host if needed
            Guid results = AlmondResultsPanel.PanelId, almond = AlmondLibraryPanel.PanelId;
            // first time: dock as a tab beside the Almond panel (both icons in the same strip), not floating
            Guid bar = !Rhino.UI.Panels.IsPanelVisible(results) && Rhino.UI.Panels.IsPanelVisible(almond)
                ? Rhino.UI.Panels.PanelDockBar(almond) : Guid.Empty;
            if (bar != Guid.Empty) Rhino.UI.Panels.OpenPanel(bar, results, true);
            else Rhino.UI.Panels.OpenPanel(results, true);
        }

        /// <summary>The member table as CSV (invariant culture, one row per member).</summary>
        internal static string MembersCsv(JObject report)
        {
            var members = report?["result"]?["members"] as JArray;
            if (members == null || members.Count == 0) throw new InvalidOperationException("This result has no member table. Run the native engine.");
            string[] cols = { "id", "role", "layer", "section", "material", "length_m", "elements", "utilization", "status",
                "governing_check", "governing_combination", "cross_section_utilization", "buckling_utilization", "slenderness", "chi",
                "max_stress_mpa", "n_tension_kn", "n_compression_kn", "v_max_kn", "m_max_knm", "t_max_knm",
                "max_displacement_mm", "deflection_mm", "deflection_ratio", "pinned_start", "pinned_end", "source_guids" };
            var sb = new StringBuilder();
            sb.AppendLine(string.Join(",", cols));
            foreach (JObject m in members)
            {
                sb.AppendLine(string.Join(",", cols.Select(c => {
                    JToken v = c == "pinned_start" ? m["pinned_ends"]?["start"] : c == "pinned_end" ? m["pinned_ends"]?["end"]
                        : c == "source_guids" ? new JValue(string.Join(" ", (m["source_guids"] as JArray ?? new JArray()).Select(g => (string)g))) : m[c];
                    if (v == null || v.Type == JTokenType.Null) return "";
                    string s = v.Type == JTokenType.Float ? ((double)v).ToString("R", CultureInfo.InvariantCulture)
                        : v.Type == JTokenType.Boolean ? ((bool)v ? "yes" : "no") : v.ToString();
                    return s.IndexOfAny(new[] { ',', '"', '\n', '\r' }) >= 0 ? "\"" + s.Replace("\"", "\"\"") + "\"" : s;
                })));
            }
            return sb.ToString();
        }
    }

    // A second dockable panel: every member's results, wide enough for a table.
    [Guid("6a3f0d9e-4c1b-4f57-9a62-2c8e5f1d7b44")]
    public class AlmondResultsPanel : Panel
    {
        public static Guid PanelId => typeof(AlmondResultsPanel).GUID;
        private readonly Panel _body = new Panel();
        private readonly string _session = Guid.NewGuid().ToString("N");
        private WebView _view;
        private Uri _archive;
        private bool _ready, _disposed;

        public AlmondResultsPanel()
        {
            MinimumSize = new Eto.Drawing.Size(320, 240);
            Content = _body;
            AnalysisResults.Changed += Push;
            RhinoApp.AppSettingsChanged += ThemeChanged;
            Load();
        }

        protected override void Dispose(bool disposing)
        {
            _disposed = true;
            if (disposing) { AnalysisResults.Changed -= Push; RhinoApp.AppSettingsChanged -= ThemeChanged; }
            base.Dispose(disposing);
        }

        private void Push(JObject report)
        {
            Application.Instance.AsyncInvoke(() => {
                if (_disposed || !_ready || _view == null) return;
                _view.ExecuteScript("window.almondResultsReceive && window.almondResultsReceive(" +
                    (report == null ? "null" : JsonConvert.SerializeObject(report, new JsonSerializerSettings { StringEscapeHandling = StringEscapeHandling.EscapeHtml })) + ");");
            });
        }

        private void ThemeChanged(object sender, EventArgs e)
        {
            Application.Instance.AsyncInvoke(() => {
                if (_disposed || !_ready || _view == null) return;
                _view.ExecuteScript("window.almondThemeReceive && window.almondThemeReceive(" + AlmondLibraryPanel.HostPalette(out var bg) + ");");
                BackgroundColor = _body.BackgroundColor = bg;
            });
        }

        private void Load()
        {
            try
            {
                _archive = new Uri(AlmondLibraryCommand.ArchiveUrl);
                var view = new WebView();
                view.DocumentLoaded += (s, e) => {
                    _ready = e.Uri != null && e.Uri.Authority == _archive.Authority && e.Uri.AbsolutePath == "/results.html";
                    if (_ready) Push(AnalysisResults.Latest);
                };
                view.DocumentLoading += (s, e) => {
                    if (!e.IsMainFrame || e.Uri == null) return;
                    bool local = e.Uri.Scheme == _archive.Scheme && e.Uri.Authority == _archive.Authority;
                    if (local && e.Uri.AbsolutePath == "/results.html") return;
                    e.Cancel = true;
                    var action = Regex.Match(e.Uri.AbsolutePath, "^/almond-action/" + _session + "/results/(select|export_csv|refresh)$");
                    if (local && _ready && action.Success) Act(action.Groups[1].Value, e.Uri.Query);
                    else if (!local) AlmondLibraryCommand.OpenBrowser(e.Uri.AbsoluteUri);
                };
                view.OpenNewWindow += (s, e) => { if (e.Uri != null) AlmondLibraryCommand.OpenBrowser(e.Uri.AbsoluteUri); };
                _body.Content = view;
                _view = view;
                string palette = AlmondLibraryPanel.HostPalette(out var bg);
                BackgroundColor = _body.BackgroundColor = bg;
                view.Url = new Uri(_archive, "results.html?panel=1&bridge=" + _session + "&palette=" + Uri.EscapeDataString(palette));
            }
            catch (Exception ex)
            {
                _body.Content = new Label { Text = "The Almond results page could not start.\n\n" + ex.Message, Wrap = WrapMode.Word };
                RhinoApp.WriteLine("Almond Results panel: {0}", ex.Message);
            }
        }

        private void Notice(string text) =>
            _view?.ExecuteScript("window.almondResultsNotice && window.almondResultsNotice(" + JsonConvert.SerializeObject(text) + ");");

        private void Act(string action, string query)
        {
            try
            {
                if (action == "refresh") { Push(AnalysisResults.Latest); return; }
                if (action == "select")
                {
                    if (query == null || !query.StartsWith("?data=", StringComparison.Ordinal) || query.Length > 40000) return;
                    var ids = JArray.Parse(Uri.UnescapeDataString(query.Substring(6))).Select(t => (string)t).Take(500).ToList();
                    var doc = RhinoDoc.ActiveDoc;
                    if (doc == null) return;
                    doc.Objects.UnselectAll();
                    int found = 0;
                    foreach (var id in ids)
                        if (Guid.TryParse(id, out Guid g) && doc.Objects.Select(g, true)) found++;
                    doc.Views.Redraw();
                    Notice(found == 0 ? "Those members are no longer in the document." : found + " object" + (found == 1 ? "" : "s") + " selected in Rhino.");
                    return;
                }
                if (action == "export_csv")
                {
                    string csv = AnalysisResults.MembersCsv(AnalysisResults.Latest);
                    var dialog = new SaveFileDialog { Title = "Save member results", FileName = "almond-members.csv" };
                    dialog.Filters.Add(new FileFilter("CSV", ".csv"));
                    bool saved = dialog.ShowDialog(Rhino.UI.RhinoEtoApp.MainWindow) == DialogResult.Ok;
                    if (saved) File.WriteAllText(dialog.FileName, csv, new UTF8Encoding(true));   // BOM: Excel reads it as UTF-8
                    Notice(saved ? "Member results saved as CSV." : "Export cancelled.");
                }
            }
            catch (Exception ex) { Notice(ex.Message); }
        }
    }

    public sealed class AlmondResultsCommand : Rhino.Commands.Command
    {
        public override string EnglishName => "AlmondResults";
        protected override Rhino.Commands.Result RunCommand(RhinoDoc doc, RunMode mode)
        {
            try { AnalysisResults.Open(doc); return Rhino.Commands.Result.Success; }
            catch (Exception ex) { RhinoApp.WriteLine("AlmondResults: {0}", ex.Message); return Rhino.Commands.Result.Failure; }
        }
    }
}
