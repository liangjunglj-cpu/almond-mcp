// Prepare the library section: Almond panel on the library page, library layer on with its
// instances still hidden, snaps off; report screen targets for every library instance.
RhinoApp.RunScript("_AlmondLibrary", false);
var lay=doc.Layers.First(l=>!l.IsDeleted&&l.FullPath=="A07 / 14 Meshy library assets");lay.IsVisible=true;lay.CommitChanges();
Rhino.ApplicationSettings.ModelAidSettings.Osnap=false;Rhino.ApplicationSettings.ModelAidSettings.GridSnap=false;Rhino.ApplicationSettings.ModelAidSettings.Ortho=false;Rhino.ApplicationSettings.ModelAidSettings.Planar=false;
var view=doc.Views.ActiveView;var vp=view.ActiveViewport;var r=view.ScreenRectangle;
var sb=new StringBuilder("[");bool first=true;
foreach(var o in doc.Objects.GetObjectList(new ObjectEnumeratorSettings{HiddenObjects=true,NormalObjects=true,LayerIndexFilter=lay.Index}).OfType<InstanceObject>()){
 var p=o.InsertionPoint;var c=vp.WorldToClient(p);var bb=o.Geometry.GetBoundingBox(true);
 var xf=o.InstanceXform;double rot=Math.Atan2(xf.M10,xf.M00)*180/Math.PI;
 sb.Append((first?"":",")+string.Format(System.Globalization.CultureInfo.InvariantCulture,
  "{{\"id\":\"{0}\",\"asset\":\"{1}\",\"x\":{2:0},\"y\":{3:0},\"z\":{4:0},\"sx\":{5:0},\"sy\":{6:0},\"rot\":{7:0.0},\"hidden\":{8},\"topz\":{9:0}}}",
  o.Id,o.Attributes.GetUserString("Almond.AssetId"),p.X,p.Y,p.Z,r.X+c.X,r.Y+c.Y,rot,o.IsHidden?"true":"false",bb.Max.Z));first=false;}
sb.Append("]");File.WriteAllText(@"C:\Users\liang\Documents\almond_promo\lib_targets.json",sb.ToString());
doc.Views.Redraw();log.AppendLine("screen "+r+" "+sb.ToString().Length);
