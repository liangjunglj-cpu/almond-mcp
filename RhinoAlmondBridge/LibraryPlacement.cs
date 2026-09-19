using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using Rhino;
using Rhino.Commands;
using Rhino.DocObjects;
using Rhino.Geometry;
using Rhino.Input;
using Rhino.Input.Custom;

namespace RhinoAlmondBridge
{
    internal static class LibraryPlacement
    {
        [DllImport("user32.dll")] private static extern bool ReleaseCapture();
        [DllImport("user32.dll")] private static extern short GetAsyncKeyState(int key);
        private static bool LeftDown => (GetAsyncKeyState(1) & 0x8000) != 0;
        internal static string PendingId;
        internal static bool PendingDrag;
        internal static bool PendingLight;
        internal static bool Busy;

        internal static void Request(string id, bool drag, bool light)
        {
            if (Busy || AnalysisWorkspace.Busy) return;
            var doc = RhinoDoc.ActiveDoc;
            if (doc == null || doc.InCommand(false) > 0)
            {
                RhinoApp.WriteLine("Finish the current Rhino command before placing a library model.");
                return;
            }
            Busy = true;
            Eto.Forms.Application.Instance.AsyncInvoke(() =>
            {
                try
                {
                    if (drag && !LeftDown) return;
                    PendingId = id; PendingDrag = drag; PendingLight = light;
                    // Fixed plugin command, never a script or command supplied by a web page.
                    RhinoApp.RunScript("_AlmondPlaceLibraryAsset", false);
                }
                catch (Exception ex) { RhinoApp.WriteLine("Almond placement: {0}", ex.Message); }
                finally { PendingId = null; Busy = false; }
            });
        }

        internal static Result Place(RhinoDoc doc, string id, bool drag, bool light)
        {
            var catalogue = JObject.Parse(Encoding.UTF8.GetString(AlmondLibraryCommand.ReadArchive("/api/catalogue")));
            var record = catalogue["assets"].OfType<JObject>().SingleOrDefault(a => (string)a["id"] == id);
            if (record == null || (string)record["kind"] != "model" || (string)record["format"] != "glb" || (bool?)record["available"] != true)
                throw new InvalidDataException("Only installed generated models can be placed.");
            if (doc.ModelUnitSystem == UnitSystem.None || doc.ModelUnitSystem == UnitSystem.CustomUnits)
                throw new InvalidDataException("Set standard document units before placing a model.");
            double scale = RhinoMath.UnitScale(UnitSystem.Millimeters, doc.ModelUnitSystem);
            var dims = record["dimensions_mm"];
            var bounds = new BoundingBox(-(double)dims["width"]*scale/2, -(double)dims["depth"]*scale/2, 0,
                (double)dims["width"]*scale/2, (double)dims["depth"]*scale/2, (double)dims["height"]*scale);
            Point3d point;
            using (var get = new GetPoint())
            {
                get.SetCommandPrompt(drag ? "Release in a viewport to place; Esc cancels" : "Pick model insertion point; Esc cancels");
                get.EnableTransparentCommands(false);
                get.DynamicDraw += (s,e) =>
                {
                    var box = new BoundingBox(bounds.Min + (Vector3d)e.CurrentPoint, bounds.Max + (Vector3d)e.CurrentPoint);
                    e.Display.DrawBox(box, Color.FromArgb(233,68,43), 2);
                };
                if (drag)
                {
                    // Transfer the held pointer from Edge to Rhino's native point getter.
                    // A timed getter also cancels a release outside all viewports.
                    if (!LeftDown) return Result.Cancel;
                    ReleaseCapture();
                    get.SetWaitDuration(150);
                }
                RhinoApp.SetFocusToMainWindow(doc);
                GetResult result;
                do { result = get.Get(drag); }
                while (drag && result == GetResult.Timeout && LeftDown);
                if (result != GetResult.Point || get.View() == null) return Result.Cancel;
                point = get.Point();
            }
            string modelRoute = (string)record["model"];
            byte[] bytes = AlmondLibraryCommand.ReadArchive(modelRoute);
            string sourceHash = Hash(bytes);
            if (!string.Equals(sourceHash, (string)record["metadata"]["sha256"], StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("Model checksum disagrees with its catalogue record.");
            var materialLibrary = JObject.Parse(Encoding.UTF8.GetString(AlmondLibraryCommand.ReadArchive("/api/materials")));
            string materialId = (string)record["metadata"]["render_material_id"];
            var recipe = materialLibrary["materials"].OfType<JObject>().Single(m => (string)m["material_id"] == materialId);
            string revision = Hash(Encoding.UTF8.GetBytes(sourceHash + record.ToString(Formatting.None) + recipe.ToString(Formatting.None) + (light ? "light20k" : "original") + ":1"));
            string definitionName = "Almond::" + id + "::" + revision.Substring(0,12) + "::" + doc.ModelUnitSystem;
            var definition = doc.InstanceDefinitions.Find(definitionName);
            string baseName = definitionName;
            int conflict = 0;
            // Editing an existing block must not cause a later placement to silently
            // reuse altered geometry while claiming the original source fingerprint.
            while (definition != null && !MatchesGeometry(definition))
            {
                if (++conflict > 1000) throw new InvalidOperationException("Too many modified library blocks.");
                definitionName = baseName + "::" + conflict;
                definition = doc.InstanceDefinitions.Find(definitionName);
            }
            int definitionIndex = definition?.Index ?? -1;
            bool created = false;
            try
            {
                if (definitionIndex < 0)
                {
                    var decoded = ArchiveMeshData.Decode(bytes, id);
                    var geometry = new List<GeometryBase>();
                    var attributes = new List<ObjectAttributes>();
                    try
                    {
                        int originalFaces = decoded.TriangleCount, placedFaces = 0;
                        int materialIndex = MaterialIndex(doc, materialId, recipe);
                        foreach (var part in decoded.Parts)
                        {
                            if (part.Material != "ALMOND::" + materialId) throw new InvalidDataException("Unexpected model material.");
                            var mesh = new Mesh();
                            geometry.Add(mesh);
                            foreach (var v in part.Vertices) mesh.Vertices.Add(v[0],v[1],v[2]);
                            for(int i=0;i<part.Indices.Length;i+=3) mesh.Faces.AddFace(part.Indices[i],part.Indices[i+1],part.Indices[i+2]);
                            if (part.Normals != null)
                                foreach (var n in part.Normals) mesh.Normals.Add((float)n[0],(float)n[1],(float)n[2]);
                            else mesh.Normals.ComputeNormals();
                            if (light && originalFaces > 20000)
                            {
                                int target = Math.Max(4, (int)(20000d * mesh.Faces.Count / originalFaces));
                                if (!mesh.Reduce(target, true, 5, true)) throw new InvalidOperationException("Mesh reduction failed; try Original detail.");
                                mesh.Normals.ComputeNormals();
                            }
                            mesh.Compact();
                            if (!mesh.IsValid) throw new InvalidDataException("Invalid mesh after conversion.");
                            placedFaces += mesh.Faces.Count;
                            attributes.Add(new ObjectAttributes { MaterialIndex = materialIndex, MaterialSource = ObjectMaterialSource.MaterialFromObject,
                                LayerIndex = 0, Name = (string)record["name"] });
                        }
                        var local = BoundingBox.Empty;
                        foreach (var g in geometry) local.Union(g.GetBoundingBox(true));
                        var anchor = new Point3d((local.Min.X+local.Max.X)/2, (local.Min.Y+local.Max.Y)/2, local.Min.Z);
                        var transform = Transform.Scale(Point3d.Origin, scale) * Transform.Translation(-(Vector3d)anchor);
                        foreach (var g in geometry) g.Transform(transform);
                        // Keep derivation and source evidence inside the saved Rhino document.
                        var derivation = new JObject {
                            ["schema_version"]=1, ["source_sha256"]=sourceHash, ["source_triangle_count"]=originalFaces,
                            ["placed_triangle_count"]=placedFaces, ["detail"]=light ? "light" : "original",
                            ["method"]=placedFaces < originalFaces ? "Rhino Mesh.Reduce; target 20000 triangles; accuracy 5; normalized; compacted" : "Original indexed mesh; compacted",
                            ["geometry_sha256"]=MeshHash(geometry.Cast<Mesh>()), ["rhino_version"]=RhinoApp.Version.ToString(),
                            ["anchor"]="bottom_center", ["document_units"]=doc.ModelUnitSystem.ToString(),
                            ["local_dimensions_mm"]=new JArray(local.Max.X-local.Min.X,local.Max.Y-local.Min.Y,local.Max.Z-local.Min.Z),
                            ["limitations"]=placedFaces < originalFaces ? "Approximate display mesh; fine features can change. Original source and drawings retained." : "Original geometry; document units and bottom-centre anchor applied."
                        };
                        var meta = new JObject { ["record"]=record.DeepClone(), ["passport"]=decoded.Passport.DeepClone(), ["derivation"]=derivation };
                        foreach (var a in attributes) SetMetadata(a,id,meta);
                        definitionIndex = doc.InstanceDefinitions.Add(definitionName, meta.ToString(Formatting.None), Point3d.Origin, geometry, attributes);
                        if (definitionIndex < 0) throw new InvalidOperationException("Could not create the model block.");
                        created = true;
                    }
                    finally { foreach (var g in geometry) g.Dispose(); }
                }
                definition = doc.InstanceDefinitions[definitionIndex];
                var instanceAttributes = new ObjectAttributes { Name = (string)record["name"], LayerIndex = doc.Layers.CurrentLayerIndex };
                SetMetadata(instanceAttributes,id,JObject.Parse(definition.Description));
                Guid placed = doc.Objects.AddInstanceObject(definitionIndex, Transform.Translation((Vector3d)point), instanceAttributes);
                if (placed == Guid.Empty) throw new InvalidOperationException("Could not place the model.");
                doc.Objects.Select(placed);
                doc.Views.Redraw();
                RhinoApp.WriteLine("Placed {0} as a shared {1} block. Undo removes this placement.", record["name"], light ? "light" : "original");
                return Result.Success;
            }
            catch
            {
                if (created) doc.InstanceDefinitions.Delete(definitionIndex, true, true);
                throw;
            }
        }
        private static void SetMetadata(ObjectAttributes a, string id, JObject meta)
        {
            a.SetUserString("almond.asset_id",id);
            a.SetUserString("almond.asset_type","generated_asset");
            a.SetUserString("almond.metadata",meta.ToString(Formatting.None));
            a.SetUserString("almond:asset_id",id);
            a.SetUserString("almond:passport",meta["passport"].ToString(Formatting.None));
            a.SetUserString("almond:derivation",meta["derivation"].ToString(Formatting.None));
            a.SetUserString("almond:source_record",meta["record"].ToString(Formatting.None));
            a.SetUserString("almond:license","CC-BY-4.0");
            a.SetUserString("almond:attribution","Almond generated asset library");
        }
        private static int MaterialIndex(RhinoDoc doc, string id, JObject recipe)
        {
            string name = "ALMOND::" + id + "::" + Hash(Encoding.UTF8.GetBytes(recipe.ToString(Formatting.None))).Substring(0,12);
            var existing = doc.Materials.FirstOrDefault(m => !m.IsDeleted && m.Name == name);
            if (existing != null) return existing.Index;
            var rgb = recipe["base_color"];
            var material = new Material { Name = name, DiffuseColor = Color.FromArgb((int)rgb[0],(int)rgb[1],(int)rgb[2]) };
            material.ToPhysicallyBased();
            material.PhysicallyBased.BaseColor = new Rhino.Display.Color4f(material.DiffuseColor);
            material.PhysicallyBased.Metallic = (double)recipe["metallic"];
            material.PhysicallyBased.Roughness = (double)recipe["roughness"];
            material.PhysicallyBased.Opacity = (double)recipe["opacity"];
            material.SetUserString("almond:material_id",id);
            return doc.Materials.Add(material);
        }
        private static string MeshHash(IEnumerable<Mesh> meshes)
        {
            using (var stream = new MemoryStream())
            using (var writer = new BinaryWriter(stream))
            {
                foreach (var mesh in meshes)
                {
                    writer.Write(mesh.Vertices.Count); writer.Write(mesh.Faces.Count);
                    foreach (var v in mesh.Vertices) { writer.Write(v.X); writer.Write(v.Y); writer.Write(v.Z); }
                    foreach (var f in mesh.Faces) { writer.Write(f.A); writer.Write(f.B); writer.Write(f.C); writer.Write(f.D); }
                }
                writer.Flush();
                return Hash(stream.ToArray());
            }
        }
        private static bool MatchesGeometry(InstanceDefinition definition)
        {
            try
            {
                var meta = JObject.Parse(definition.Description);
                var objects = definition.GetObjects();
                return objects.Length > 0 && objects.All(o => o.Geometry is Mesh) &&
                    (string)meta["derivation"]?["geometry_sha256"] == MeshHash(objects.Select(o => (Mesh)o.Geometry));
            }
            catch { return false; }
        }
        private static string Hash(byte[] bytes)
        {
            using (var sha = SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-","").ToLowerInvariant();
        }
    }

    public sealed class AlmondPlaceLibraryAssetCommand : Command
    {
        public override string EnglishName => "AlmondPlaceLibraryAsset";
        protected override Result RunCommand(RhinoDoc doc, RunMode mode)
        {
            string id = LibraryPlacement.PendingId;
            if (id == null) { RhinoApp.WriteLine("Use Place or drag a model from AlmondLibrary."); return Result.Cancel; }
            LibraryPlacement.PendingId = null;
            try { return LibraryPlacement.Place(doc,id,LibraryPlacement.PendingDrag,LibraryPlacement.PendingLight); }
            catch (Exception ex) { RhinoApp.WriteLine("Almond placement: {0}",ex.Message); return Result.Failure; }
        }
    }
}
