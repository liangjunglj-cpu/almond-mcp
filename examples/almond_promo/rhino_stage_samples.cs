// Per build stage: sample object names/ids/types in the same order the replay revealed them (for the metadata ticker).
string[] stages={"01 Envelope","02 Floors","05 Partitions","04 Stair and gallery","11 Architectural details","06 Kitchen","09 Bathroom","08 Study and bedroom","07 Furniture","15 Lighting","10 Objects and graphics"};
var sb=new StringBuilder("[");
for(int s=0;s<stages.Length;s++){
 var lay=doc.Layers.FindByFullPath("A07 / "+stages[s],-1);
 var objs=doc.Objects.GetObjectList(new ObjectEnumeratorSettings{HiddenObjects=true,NormalObjects=true,LayerIndexFilter=lay}).ToList();
 var pick=objs.Where(o=>!string.IsNullOrEmpty(o.Attributes.Name)).GroupBy(o=>o.Attributes.Name).Select(g=>g.First()).Take(10).ToList();
 sb.Append(s>0?",":"").Append("[");
 for(int i=0;i<pick.Count;i++){var o=pick[i];var bb=o.Geometry.GetBoundingBox(true);
  sb.Append(i>0?",":"").Append(string.Format(System.Globalization.CultureInfo.InvariantCulture,"{{\"id\":\"{0}\",\"name\":\"{1}\",\"type\":\"{2}\",\"src\":\"{3}\",\"dx\":{4:0},\"dy\":{5:0},\"dz\":{6:0}}}",
   o.Id,o.Attributes.Name.Replace("\"","'"),o.ObjectType,o.Attributes.GetUserString("Almond.Source")??"",bb.Diagonal.X,bb.Diagonal.Y,bb.Diagonal.Z));}
 sb.Append("]");}
sb.Append("]");File.WriteAllText(@"C:\Users\liang\Documents\almond_promo\stage_samples.json",sb.ToString());log.Append("ok");
