"""Export Atelier 07's analysis geometry through the Almond export script and cache it."""
import json, sys, time
from pathlib import Path
here = Path(__file__).parent
sys.path.insert(0, str(here)); sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from bridge import run
from almond_mcp.environment import rhino

LAYERS = ["A07 / 01 Envelope", "A07 / 02 Floors", "A07 / 03 Facade", "A07 / 04 Stair and gallery", "A07 / 05 Partitions",
          "A07 / 06 Kitchen", "A07 / 07 Furniture", "A07 / 08 Study and bedroom", "A07 / 09 Bathroom",
          "A07 / 12 Roof / hide for cutaway", "A07 / 13 Urban context"]
ids_file = here / "ids.json"
run(r'''using System; using System.Collections.Generic; using System.IO; using System.Linq; using Rhino; using Rhino.DocObjects;
public class Script { public static List<Guid> Run(RhinoDoc doc) {
  var want = new HashSet<string>(new[] { ''' + ", ".join(json.dumps(l) for l in LAYERS) + r''' });
  var es = new ObjectEnumeratorSettings { HiddenObjects = true, LockedObjects = true };
  var ids = doc.Objects.GetObjectList(es).Where(o => want.Contains(doc.Layers[o.Attributes.LayerIndex].FullPath)).Select(o => "\"" + o.Id + "\"");
  File.WriteAllText(@"''' + str(ids_file) + r'''", "[" + string.Join(",", ids) + "]");
  return new List<Guid>();
}}''')
ids = json.loads(ids_file.read_text())
t0 = time.time()
out = here / "export.json"
run(rhino.export_script(ids, str(out)), timeout=900)
data = json.loads(out.read_text(encoding="utf-8"))
tris = sum(len(o["faces"]) // 3 for o in data["objects"])
print(len(ids), "objects requested,", len(data["objects"]), "exported,", tris, "triangles,", round(time.time() - t0, 1), "s, units", data["units"], "missing", len(data["missing"]), "skipped", len(data["skipped"]))
