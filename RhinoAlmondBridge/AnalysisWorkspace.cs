using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using Rhino;
using Rhino.Commands;
using Rhino.DocObjects;
using Rhino.Geometry;
using Rhino.Input;
using Rhino.Input.Custom;
using Environment = System.Environment;

namespace RhinoAlmondBridge
{
    internal sealed class AnalysisWorkspace
    {
        private readonly Action<JObject> _send;
        private List<string> _ids = new List<string>();
        private uint _document;
        private string _fingerprint;
        private JObject _report;
        private string _reportFingerprint;
        private static Action<RhinoDoc> _pending;
        internal static bool Busy { get; private set; }
        // a native solve runs out of process after the Rhino command has returned
        internal static bool Solving { get; private set; }
        internal AnalysisWorkspace(Action<JObject> send) { _send=send; }
        internal void Request(string action, string json)
        {
            var doc = RhinoDoc.ActiveDoc;
            if (Solving && action!="status") { SendError("The native solver is still running."); return; }
            if (Busy || LibraryPlacement.Busy || doc == null || doc.InCommand(false)>0)
            { SendError("Finish the current Rhino command first."); return; }
            AnalysisSettings settings;
            try { settings=AnalysisSettings.Parse(json); }
            catch(Exception ex) { SendError(ex.Message); return; }
            Busy=true;
            Eto.Forms.Application.Instance.AsyncInvoke(() => {
                try {
                    _pending = target => Execute(target,action,settings);
                    RhinoApp.RunScript("_AlmondAnalysisAction",false);
                }
                catch(Exception ex) { SendError(ex.Message); }
                finally { _pending=null;Busy=false; }
            });
        }
        internal static Result Run(RhinoDoc doc)
        {
            var action=_pending;_pending=null;
            if(action==null) return Result.Cancel;
            action(doc); return Result.Success;
        }
        private void SendError(string text) => _send(new JObject {["kind"]="error",["message"]=text,["stale"]=true});
        private void Execute(RhinoDoc doc,string action,AnalysisSettings settings)
        {
            try
            {
                if(action=="status") { Status(); return; }
                if(action=="clear_view") {
                    StructureView.Handle(new JObject {["clear"]=true});
                    _send(new JObject {["kind"]="notice",["message"]="Viewport overlay cleared."});
                    return;
                }
                if(action=="capture") { Capture(doc,settings);return; }
                if(action=="results") {
                    AnalysisResults.Open(doc);
                    _send(new JObject {["kind"]="notice",["message"]="Full results opened in the Almond Results panel."});
                    return;
                }
                if (_ids.Count==0 || doc.RuntimeSerialNumber!=_document || Fingerprint(doc)!=_fingerprint)
                    throw new InvalidOperationException("The model changed or no model is selected. Capture the current Rhino selection again.");
                if(action=="analyze" && settings.Engine=="native") { AnalyzeNative(doc,settings); return; }
                if(action=="analyze")
                {
                    var request=new ValidationRequest {Guids=_ids.ToList(),StructureType=settings.Structure,Material=settings.Material,
                        LoadKN=settings.LoadKN,RequireKaramba=true,IncludeSelfWeight=settings.SelfWeight,FixedRotations=settings.FixedRotations,
                        ExplicitSupports=settings.ExplicitSupports,BeamDiameterMM=settings.DiameterMM,BeamWallMM=settings.WallMM};
                    var snapshot=Snapshot(doc);
                    var validator=new StructuralValidator(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"Almond","Grasshopperfiles"));
                    var result=validator.Validate(request);
                    _report=new JObject {["schema_version"]=1,["kind"]="result",["created_at"]=DateTime.UtcNow.ToString("o"),
                        ["document_serial"]=_document,["geometry_fingerprint"]=_fingerprint,["object_ids"]=new JArray(_ids),
                        ["settings"]=settings.ToJson(),["model"]=snapshot,["result"]=JObject.FromObject(result),
                        ["limits"]="First-order analysis of the stated idealisation. L/250 is an indicative screen, not project-specific code verification."};
                    _reportFingerprint=_fingerprint;
                    AnalysisResults.Publish(_report);
                    _send((JObject)_report.DeepClone());
                    return;
                }
                if(_report==null || _reportFingerprint!=_fingerprint)
                    throw new InvalidOperationException("Run analysis on this selection first.");
                if(action=="highlight")
                {
                    var worst=_report["result"]?["worst_member_guids"] as JArray;
                    if(worst==null || worst.Count==0) throw new InvalidOperationException("No mapped utilization results to highlight.");
                    doc.Objects.UnselectAll();
                    foreach(string id in worst) if(Guid.TryParse(id,out Guid guid)) doc.Objects.Select(guid);
                    doc.Views.Redraw();
                    _send(new JObject {["kind"]="notice",["message"]="Highest-utilization members selected in Rhino."});
                }
                else if(action=="export")
                {
                    var dialog=new Eto.Forms.SaveFileDialog {Title="Save Almond analysis record",FileName="almond-analysis.json"};
                    dialog.Filters.Add(new Eto.Forms.FileFilter("Analysis JSON",".json"));
                    bool saved=dialog.ShowDialog(Rhino.UI.RhinoEtoApp.MainWindow)==Eto.Forms.DialogResult.Ok;
                    if(saved) File.WriteAllText(dialog.FileName,_report.ToString(Formatting.Indented));
                    _send(new JObject {["kind"]="notice",["message"]=saved ? "Analysis record saved." : "Export cancelled."});
                }
            }
            catch(Exception ex) { SendError(ex.Message); }
        }
        private void Status()
        {
            bool karamba=KarambaAdapter.IsAvailable(out string reason);
            var command=NativeSolver.Resolve(out string missing);
            _send(new JObject {["kind"]="status",["available"]=karamba,["message"]=karamba ?
                "Karamba detected. Solver and licence checked when analysis runs." : "Karamba is unavailable in this Rhino session.",["detail"]=reason,
                ["native"]=command==null ? new JObject {["available"]=false,["detail"]=missing} :
                    new JObject {["checking"]=true,["detail"]=command.Label}});
            if(command==null) return;
            // a ping also fetches the solver on first use, so the first analysis starts quickly
            Task.Run(async () => {
                var reply=await NativeSolver.RunAsync(new JObject {["ping"]=true},300000).ConfigureAwait(false);
                bool ok=(string)reply["status"]=="ok";
                Eto.Forms.Application.Instance.AsyncInvoke(() => _send(new JObject {["kind"]="native_status",["available"]=ok,
                    ["version"]=reply["version"],["design_codes"]=reply["design_codes"],
                    ["detail"]=ok ? (string)reply["solver"] : (string)reply["message"]}));
            });
        }

        // Export on the UI thread, solve out of process, draw and report back on the UI thread.
        private void AnalyzeNative(RhinoDoc doc,AnalysisSettings settings)
        {
            var model=JObject.Parse(StructureModelExport.Handle(new JObject {["guids"]=new JArray(_ids)}));
            if((string)model["status"]!="ok") throw new InvalidOperationException((string)model["message"] ?? "Could not export the structural model.");
            if(settings.ExplicitSupports && !((model["anchor_points"] as JArray)?.Count>0))
                throw new InvalidOperationException("Include Rhino point objects at the supports in the selection, or let Almond use the lowest nodes.");
            var request=new JObject {["model"]=model,["settings"]=settings.SolverSettings()};
            if(settings.AssetLoads)
                request["placements"]=JObject.Parse(AssetPlacementExport.Handle(new JObject()))["placements"] ?? new JArray();
            var snapshot=Snapshot(doc);
            string fingerprint=_fingerprint; uint serial=_document;
            Solving=true;
            _send(new JObject {["kind"]="progress",["message"]="Solving with Almond's native engine…"});
            Task.Run(async () => {
                JObject reply;
                try { reply=await NativeSolver.RunAsync(request,300000).ConfigureAwait(false); }
                catch(Exception ex) { reply=new JObject {["status"]="error",["message"]=ex.Message}; }
                Eto.Forms.Application.Instance.AsyncInvoke(() => FinishNative(reply,settings,snapshot,fingerprint,serial));
            });
        }

        private void FinishNative(JObject reply,AnalysisSettings settings,JObject snapshot,string fingerprint,uint serial)
        {
            Solving=false;
            try
            {
                if(fingerprint!=_fingerprint || serial!=_document)
                    throw new InvalidOperationException("The selection changed while solving. Run the analysis again.");
                if(!(reply["validation"] is JObject validation))
                    throw new InvalidOperationException((string)reply["message"] ?? "The native solver returned no result.");
                var native=new JObject {["solver"]=reply["solver"],["version"]=reply["version"],["view"]=settings.View,
                    ["drawn"]=false,["message"]=reply["message"],["buckling"]=reply["buckling"]};
                if(reply["draw"] is JObject draw)
                {
                    var shown=JObject.Parse(StructureView.HandleDraw(draw));
                    if((string)shown["status"]=="error") native["draw_error"]=(string)shown["message"];
                    else native["drawn"]=true;
                }
                _report=new JObject {["schema_version"]=1,["kind"]="result",["created_at"]=DateTime.UtcNow.ToString("o"),
                    ["document_serial"]=_document,["geometry_fingerprint"]=_fingerprint,["object_ids"]=new JArray(_ids),
                    ["settings"]=settings.ToJson(),["model"]=snapshot,["result"]=validation,["native"]=native,
                    ["limits"]="Linear-elastic 3D frame analysis of the stated idealisation with EN 1990 combinations and an EN 1993-1-1 "+
                        "stability screen. A design aid: it does not replace project-specific verification by an engineer."};
                _reportFingerprint=_fingerprint;
                AnalysisResults.Publish(_report);
                _send((JObject)_report.DeepClone());
            }
            catch(Exception ex) { SendError(ex.Message); }
        }

        private void Capture(RhinoDoc doc,AnalysisSettings settings)
        {
            var selected=doc.Objects.GetSelectedObjects(false,false).ToList();
            if(selected.Count==0)
            {
                using(var get=new GetObject()) {
                    get.SetCommandPrompt("Select structural curves, shell surfaces/meshes, and optional support points");
                    get.GeometryFilter=ObjectType.Curve|ObjectType.Surface|ObjectType.Brep|ObjectType.Mesh|ObjectType.Point;
                    get.SubObjectSelect=false;
                    if(get.GetMultiple(1,200)!=GetResult.Object) {_send(new JObject{["kind"]="notice",["message"]="Selection cancelled."});return;}
                    selected=get.Objects().Select(r=>r.Object()).ToList();
                }
            }
            if(selected.Count>200) throw new InvalidOperationException("Select at most 200 structural objects per study.");
            foreach(var obj in selected) {
                if(obj.Geometry is InstanceReferenceGeometry) throw new InvalidOperationException("Select structural curves or shell geometry. Library blocks are visual models.");
                if(obj.Geometry is Mesh mesh && mesh.Faces.Count>10000) throw new InvalidOperationException("Use a structural shell mesh with at most 10,000 faces.");
                if(obj.Geometry is Brep brep && brep.Faces.Count>200) throw new InvalidOperationException("Simplify the selected surface model before analysis.");
            }
            if(doc.ModelUnitSystem==UnitSystem.None || doc.ModelUnitSystem==UnitSystem.CustomUnits)
                throw new InvalidOperationException("Set standard document units before analysis.");
            _ids=selected.Select(o=>o.Id.ToString()).ToList();_document=doc.RuntimeSerialNumber;_fingerprint=Fingerprint(doc);
            _report=null;_reportFingerprint=null;
            _send(new JObject {["kind"]="capture",["model"]=Snapshot(doc),["settings"]=settings.ToJson()});
        }
        private string Fingerprint(RhinoDoc doc) => doc.ModelUnitSystem + ":" + doc.ModelAbsoluteTolerance.ToString("R",System.Globalization.CultureInfo.InvariantCulture) + ":" +
            string.Join("|",_ids.Select(id => {
                var obj=doc.Objects.FindId(Guid.Parse(id));
                return obj==null ? id+":missing" : id+":"+obj.Geometry.DataCRC(0);
            }));
        private JObject Snapshot(RhinoDoc doc)
        {
            var model=new ModelConditioner().Condition(doc,_ids);
            try
            {
                var segments=new JArray();
                foreach(var beam in model.Beams)
                {
                    var points=new List<Point3d>();
                    if(beam.Axis.TryGetPolyline(out Polyline poly)) points.AddRange(poly);
                    else {
                        double[] t=beam.Axis.DivideByCount(12,true);
                        if(t!=null) points.AddRange(t.Select(x=>beam.Axis.PointAt(x)));
                    }
                    for(int i=1;i<points.Count;i++)
                        segments.Add(new JObject {["a"]=Point(points[i-1],model.UnitScaleToMeters),["b"]=Point(points[i],model.UnitScaleToMeters),
                            ["guids"]=new JArray(beam.SourceGuids),["section_source"]=beam.Section?.Source ?? "default"});
                }
                var shells=new JArray();
                foreach(var shell in model.Shells)
                    foreach(var edge in shell.Mesh.GetNakedEdges() ?? new Polyline[0])
                        shells.Add(new JArray(edge.Select(p=>(JToken)Point(p,model.UnitScaleToMeters))));
                return new JObject {["objects"]=_ids.Count,["beams"]=model.Beams.Count,["shells"]=model.Shells.Count,
                    ["units"]=doc.ModelUnitSystem.ToString(),["segments"]=segments,["shell_outlines"]=shells,
                    ["anchors"]=new JArray(model.AnchorPoints.Select(p=>(JToken)Point(p,model.UnitScaleToMeters))),
                    ["default_sections"]=model.Beams.Count(b=>b.Section?.Source=="default"),
                    ["warnings"]=new JArray(model.Warnings),["geometry_fingerprint"]=_fingerprint};
            }
            finally { foreach(var b in model.Beams)b.Axis.Dispose();foreach(var s in model.Shells)s.Mesh.Dispose(); }
        }
        private static JArray Point(Point3d p,double scale) => new JArray(p.X*scale,p.Y*scale,p.Z*scale);
    }
    public sealed class AlmondAnalysisActionCommand : Command
    {
        public override string EnglishName => "AlmondAnalysisAction";
        protected override Result RunCommand(RhinoDoc doc,RunMode mode) => AnalysisWorkspace.Run(doc);
    }
}
