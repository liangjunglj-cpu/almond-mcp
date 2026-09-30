// Dump the Almond metadata actually embedded in the Atelier-07 document (for honest captions).
var sofa=doc.Objects.FindId(new Guid("c0ce6a95-fe48-4b15-828a-760c12c2a1f0")) as InstanceObject;
log.AppendLine("== sofa instance user text");
var us=sofa.Attributes.GetUserStrings();foreach(string k in us.AllKeys)log.AppendLine(k+" = "+(us[k]??"").Replace("\n"," ").Substring(0,Math.Min(160,(us[k]??"").Length)));
var def=sofa.InstanceDefinition;log.AppendLine("== block "+def.Name+" objects "+def.ObjectCount+" desc="+(def.Description??"").Length);
var du=def.GetUserStrings();foreach(string k in du.AllKeys)log.AppendLine("def."+k+" = "+(du[k]??"").Replace("\n"," ").Substring(0,Math.Min(200,(du[k]??"").Length)));
foreach(var o in def.GetObjects().Take(2)){var ou=o.Attributes.GetUserStrings();foreach(string k in ou.AllKeys)log.AppendLine("part."+k+" = "+(ou[k]??"").Replace("\n"," ").Substring(0,Math.Min(200,(ou[k]??"").Length)));
 var m=o.Geometry as Mesh;if(m!=null)log.AppendLine("part mesh faces "+m.Faces.Count);}
log.AppendLine("== doc user text");
for(int i=0;i<doc.Strings.Count;i++){var k=doc.Strings.GetKey(i);var v=doc.Strings.GetValue(i)??"";log.AppendLine(k+" ("+v.Length+" chars) = "+v.Replace("\n"," ").Substring(0,Math.Min(160,v.Length)));}
log.AppendLine("== counts");
var all=doc.Objects.GetObjectList(new ObjectEnumeratorSettings{HiddenObjects=true,NormalObjects=true,LockedObjects=true}).ToArray();
log.AppendLine("objects "+all.Length+" with user text "+all.Count(o=>o.Attributes.GetUserStrings().Count>0));
foreach(var g in all.SelectMany(o=>o.Attributes.GetUserStrings().AllKeys.Cast<string>()).GroupBy(k=>k).OrderByDescending(g=>g.Count()).Take(25))log.AppendLine("key "+g.Key+" x"+g.Count());
log.AppendLine("materials "+doc.Materials.Count(m=>!m.IsDeleted)+" blocks "+doc.InstanceDefinitions.Count(d=>d!=null&&!d.IsDeleted)+" layers "+doc.Layers.Count(l=>!l.IsDeleted)+" lights "+doc.Lights.Count);
// a sample architectural object
var stair=all.FirstOrDefault(o=>o.Attributes.LayerIndex==doc.Layers.FindByFullPath("A07 / 04 Stair and gallery",-1)&&o.Attributes.GetUserStrings().Count>0);
if(stair!=null){log.AppendLine("== stair object "+stair.Attributes.Name);var su=stair.Attributes.GetUserStrings();foreach(string k in su.AllKeys)log.AppendLine(k+" = "+su[k]);}
