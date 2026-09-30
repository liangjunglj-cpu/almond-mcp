// Build-order replay of the finished Atelier-07 model, captured from the live Rhino UI.
// Library assets (layer 14) stay hidden; they are placed in the library section.
var OUT=@"OUTDIR";Directory.CreateDirectory(OUT);
var jpg=System.Drawing.Imaging.ImageCodecInfo.GetImageEncoders().First(c=>c.MimeType=="image/jpeg");
var ep=new System.Drawing.Imaging.EncoderParameters(1);ep.Param[0]=new System.Drawing.Imaging.EncoderParameter(System.Drawing.Imaging.Encoder.Quality,94L);
var screen=new Rectangle(0,0,2560,1600);int frame=0;
Action grab=()=>{var v=doc.Views.ActiveView;v.Redraw();RhinoApp.Wait();System.Threading.Thread.Sleep(30);RhinoApp.Wait();
 using(var bmp=new Bitmap(screen.Width,screen.Height)){using(var g=Graphics.FromImage(bmp))g.CopyFromScreen(0,0,0,0,bmp.Size);bmp.Save(Path.Combine(OUT,string.Format("f_{0:0000}.jpg",frame++)),jpg,ep);}};
Rhino.UI.Panels.OpenPanel(Rhino.UI.PanelIds.Layers);RhinoApp.ClearCommandHistoryWindow();
var all=doc.Objects.GetObjectList(new ObjectEnumeratorSettings{NormalObjects=true,HiddenObjects=true,LockedObjects=true,DeletedObjects=false}).ToArray();
var keepHidden=new HashSet<Guid>(all.Where(o=>o.IsHidden).Select(o=>o.Id));
string[] stages={"01 Envelope","02 Floors","05 Partitions","04 Stair and gallery","11 Architectural details","06 Kitchen","09 Bathroom","08 Study and bedroom","07 Furniture","15 Lighting","10 Objects and graphics"};
int[] steps={4,28,4,22,10,8,6,8,6,6,18};
Func<string,Layer> L=n=>doc.Layers.First(l=>!l.IsDeleted&&l.FullPath=="A07 / "+n);
// start empty: hide every visible object, switch the stage layers + library layer off
foreach(var o in all)if(!o.IsHidden)doc.Objects.Hide(o.Id,true);
foreach(var n in stages.Concat(new[]{"14 Meshy library assets"})){var l=L(n);l.IsVisible=false;l.CommitChanges();}
RhinoApp.WriteLine("Almond ▸ build replay: Atelier-07 urban duplex, 11 construction stages");
for(int i=0;i<10;i++)grab();
for(int s=0;s<stages.Length;s++){
 var lay=L(stages[s]);lay.IsVisible=true;lay.CommitChanges();
 var objs=all.Where(o=>o.Attributes.LayerIndex==lay.Index&&!keepHidden.Contains(o.Id)).ToList();
 Func<RhinoObject,double> key;
 var bb=new Dictionary<Guid,BoundingBox>();foreach(var o in objs)bb[o.Id]=o.Geometry.GetBoundingBox(true);
 if(stages[s]=="02 Floors")key=o=>bb[o.Id].Min.Z*10+bb[o.Id].Center.X+bb[o.Id].Center.Y;
 else if(stages[s]=="04 Stair and gallery")key=o=>bb[o.Id].Center.Z;
 else key=o=>bb[o.Id].Min.Z*3+bb[o.Id].Center.X*0.5;
 objs=objs.OrderBy(key).ToList();
 RhinoApp.WriteLine(string.Format("Almond ▸ stage {0:00}/{1}  {2}  ({3} objects)",s+1,stages.Length,stages[s],objs.Count));
 int n=Math.Min(steps[s],Math.Max(1,objs.Count));
 for(int k=0;k<n;k++){int a=objs.Count*k/n,b=objs.Count*(k+1)/n;for(int j=a;j<b;j++)doc.Objects.Show(objs[j].Id,true);grab();}
 grab();
}
RhinoApp.WriteLine("Almond ▸ shell complete: "+doc.Objects.Count(o=>o.Visible)+" visible objects. Furnishing from the Almond library next.");
for(int i=0;i<12;i++)grab();
log.AppendLine("frames "+frame);
