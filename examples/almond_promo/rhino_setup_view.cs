// Cutaway axon for the promo: same state as A07 / 06-cutaway, camera from cameras.json.
foreach(var layer in doc.Layers.Where(l=>!l.IsDeleted)){
 if(layer.Name.Contains("Roof / hide")||layer.Name.Contains("Urban context")||layer.Name=="A07 / 03 Facade"){layer.IsVisible=false;layer.CommitChanges();}}
var all=doc.Objects.GetObjectList(new ObjectEnumeratorSettings{NormalObjects=true,HiddenObjects=true,LockedObjects=true,DeletedObjects=false}).ToArray();
int hid=0;
foreach(var o in all.Where(o=>o.Attributes.Name=="East concrete wall"||o.Attributes.Name=="Full-height linen curtain fold"||o.Attributes.GetUserString("Almond.AssetId")=="gen-tree-deciduous-medium-1")){doc.Objects.Hide(o.Id,true);hid++;}
var mode=DisplayModeDescription.FindByName("Almond | Apartment Day");
var vp=doc.Views.ActiveView.ActiveViewport;vp.DisplayMode=mode;
vp.ChangeToPerspectiveProjection(true,LENS);
vp.SetCameraLocations(new Point3d(6500,4700,2400),new Point3d(18900,-18100,15100));vp.Camera35mmLensLength=LENS;
doc.Lights.Sun.Enabled=true;doc.Lights.Skylight.Enabled=true;
doc.Objects.UnselectAll();doc.Views.Redraw();
var r=doc.Views.ActiveView.ScreenRectangle;
log.AppendLine("hidden "+hid+" vpsize "+vp.Size+" screenrect "+r);
