using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Newtonsoft.Json;
using Rhino;
using Rhino.DocObjects;
using Rhino.FileIO;
using Rhino.Geometry;

namespace RhinoAlmondBridge
{
    public class GlbExportRequest
    {
        [JsonProperty("guids")]
        public List<string> Guids { get; set; } = new List<string>();

        [JsonProperty("output_path")]
        public string OutputPath { get; set; }
    }

    public class GlbExporter
    {
        public object Export(GlbExportRequest request)
        {
            var doc = RhinoDoc.ActiveDoc;
            if (doc == null)
                return Error("No active Rhino document.");
            if (request?.Guids == null || request.Guids.Count == 0)
                return Error("No Rhino object GUIDs were supplied.");
            if (string.IsNullOrWhiteSpace(request.OutputPath))
                return Error("No GLB output path was supplied.");

            string outputPath = Path.GetFullPath(request.OutputPath);
            if (!string.Equals(Path.GetExtension(outputPath), ".glb", StringComparison.OrdinalIgnoreCase))
                return Error("The export path must end in .glb.");
            if (outputPath.Contains("\""))
                return Error("The export path contains an unsupported quote character.");

            var objects = new List<RhinoObject>();
            foreach (string value in request.Guids.Distinct(StringComparer.OrdinalIgnoreCase))
            {
                if (!Guid.TryParse(value, out Guid id))
                    return Error($"Invalid Rhino object GUID: {value}");
                var obj = doc.Objects.FindId(id);
                if (obj == null || obj.IsDeleted)
                    return Error($"Rhino object was not found: {value}");
                objects.Add(obj);
            }

            Directory.CreateDirectory(Path.GetDirectoryName(outputPath));
            if (File.Exists(outputPath))
                File.Delete(outputPath);

            var previouslySelected = doc.Objects
                .GetSelectedObjects(false, false)
                .Select(obj => obj.Id)
                .ToList();

            try
            {
                doc.Objects.UnselectAll();
                foreach (var obj in objects)
                    obj.Select(true);
                doc.Views.Redraw();

                var options = new FileGltfWriteOptions
                {
                    MapZToY = true,
                    ExportMaterials = true,
                    ExportTextureCoordinates = true,
                    ExportVertexNormals = true,
                    ExportVertexColors = true,
                    ExportOpenMeshes = true,
                    UseDisplayColorForUnsetMaterials = true
                };
                bool commandSucceeded = doc.ExportSelected(outputPath, options.ToDictionary());
                if (!commandSucceeded || !File.Exists(outputPath))
                    return Error("Rhino GLB export failed. Confirm that Rhino 8's glTF exporter is available.");

                var bounds = BoundingBox.Empty;
                foreach (var obj in objects)
                    bounds.Union(obj.Geometry.GetBoundingBox(true));

                return new
                {
                    status = "success",
                    output_path = outputPath,
                    size_bytes = new FileInfo(outputPath).Length,
                    document_path = doc.Path ?? "",
                    document_serial = doc.RuntimeSerialNumber,
                    units = doc.ModelUnitSystem.ToString(),
                    object_guids = objects.Select(obj => obj.Id.ToString()).ToList(),
                    bounds = bounds.IsValid
                        ? new
                        {
                            min = new[] { bounds.Min.X, bounds.Min.Y, bounds.Min.Z },
                            max = new[] { bounds.Max.X, bounds.Max.Y, bounds.Max.Z }
                        }
                        : null
                };
            }
            finally
            {
                doc.Objects.UnselectAll();
                foreach (Guid id in previouslySelected)
                    doc.Objects.FindId(id)?.Select(true);
                doc.Views.Redraw();
            }
        }

        private static object Error(string message)
        {
            return new { status = "error", message };
        }
    }
}
