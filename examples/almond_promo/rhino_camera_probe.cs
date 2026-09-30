var vp=doc.Views.ActiveView.ActiveViewport;double l,r,b,t,n,f;vp.GetFrustum(out l,out r,out b,out t,out n,out f);
var ci=System.Globalization.CultureInfo.InvariantCulture;
log.AppendLine(string.Format(ci,"frustum l={0} r={1} b={2} t={3} n={4} hfov={5} vfov={6}",l,r,b,t,n,2*Math.Atan(r/n)*180/Math.PI,2*Math.Atan(t/n)*180/Math.PI));
log.AppendLine(string.Format(ci,"loc {0} dir {1} up {2} target {3} size {4}",vp.CameraLocation,vp.CameraDirection,vp.CameraUp,vp.CameraTarget,vp.Size));
var hid=doc.Objects.GetObjectList(new ObjectEnumeratorSettings{HiddenObjects=true,NormalObjects=false}).Select(o=>o.Id.ToString()).ToArray();
File.WriteAllText(@"C:\Users\liang\Documents\almond_promo\rhino_hidden_ids.txt",string.Join("\n",hid));log.AppendLine("hidden "+hid.Length);
