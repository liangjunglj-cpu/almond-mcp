using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using Rhino;
using Rhino.DocObjects;
using Rhino.Geometry;

namespace RhinoAlmondBridge
{
    public class FurnitureAssetManager
    {
        private readonly string _libraryRoot;
        private readonly string _layerPath;
        private readonly string _blockPrefix;
        private readonly string _assetType;
        private readonly string _displayName;
        private readonly HashSet<string> _allowedExtensions;

        private static readonly HashSet<string> RasterExtensions =
            new HashSet<string>(StringComparer.OrdinalIgnoreCase) { ".png" };

        public FurnitureAssetManager(
            string libraryRoot,
            string layerPath = "IKEA Furniture",
            string blockPrefix = "IKEA",
            string assetType = "ikea_furniture",
            string displayName = "furniture",
            IEnumerable<string> allowedExtensions = null)
        {
            _libraryRoot = Path.GetFullPath(libraryRoot ?? "");
            _layerPath = layerPath;
            _blockPrefix = blockPrefix;
            _assetType = assetType;
            _displayName = displayName;
            _allowedExtensions = new HashSet<string>(
                allowedExtensions ?? new[] { ".skp" },
                StringComparer.OrdinalIgnoreCase
            );
        }

        public FurniturePlacementResult Place(FurniturePlacementRequest request)
        {
            var result = new FurniturePlacementResult
            {
                Status = "error",
                AssetId = request?.AssetId
            };

            if (request == null)
            {
                result.Message = $"{_displayName} request is required.";
                return result;
            }

            string validationError;
            string fullPath = ValidateAssetPath(request.FilePath, out validationError);
            if (fullPath == null)
            {
                result.Message = validationError;
                return result;
            }

            var doc = RhinoDoc.ActiveDoc;
            if (doc == null)
            {
                result.Message = "No active Rhino document.";
                return result;
            }

            uint undoRecord = doc.BeginUndoRecord($"Place {_displayName}");
            try
            {
                string definitionName = BuildDefinitionName(request.AssetId);
                var definition = FindDefinition(doc, definitionName);
                bool definitionCreated = false;

                if (definition == null)
                {
                    definition = RasterExtensions.Contains(Path.GetExtension(fullPath))
                        ? BuildRasterDefinition(doc, fullPath, definitionName, request.Name, request.Metadata)
                        : ImportAsDefinition(doc, fullPath, definitionName, request.Name);
                    definitionCreated = true;
                }

                Point3d position = ReadPosition(request.Position);
                double angleRadians = RhinoMath.ToRadians(request.RotationDegrees);
                Transform transform =
                    Transform.Translation(position.X, position.Y, position.Z) *
                    Transform.Rotation(angleRadians, Vector3d.ZAxis, Point3d.Origin) *
                    Transform.Scale(Point3d.Origin, request.Scale);

                var attributes = BuildInstanceAttributes(doc, request);
                Guid objectId = doc.Objects.AddInstanceObject(definition.Index, transform, attributes);
                if (objectId == Guid.Empty)
                    throw new InvalidOperationException($"Rhino failed to create the {_displayName} block instance.");

                doc.Views.Redraw();
                var placedObject = doc.Objects.FindId(objectId);
                BoundingBox bounds = placedObject?.Geometry?.GetBoundingBox(true) ?? BoundingBox.Empty;

                result.Status = "success";
                result.Message = definitionCreated
                    ? $"{_displayName} imported and placed as a new block definition."
                    : $"{_displayName} placed using the existing block definition.";
                result.ObjectGuid = objectId.ToString();
                result.BlockDefinition = definition.Name;
                result.DefinitionCreated = definitionCreated;
                result.Bounds = BoundsPayload.FromBoundingBox(bounds);
                return result;
            }
            catch (Exception ex)
            {
                result.Message = ex.Message;
                result.ErrorTrace = ex.ToString();
                return result;
            }
            finally
            {
                if (undoRecord != 0)
                    doc.EndUndoRecord(undoRecord);
            }
        }

        private string ValidateAssetPath(string filePath, out string error)
        {
            error = null;
            if (string.IsNullOrWhiteSpace(filePath))
            {
                error = $"{_displayName} file path is required.";
                return null;
            }

            string fullPath = Path.GetFullPath(filePath);
            string rootWithSeparator = _libraryRoot.TrimEnd(
                Path.DirectorySeparatorChar,
                Path.AltDirectorySeparatorChar
            ) + Path.DirectorySeparatorChar;

            if (!fullPath.StartsWith(rootWithSeparator, StringComparison.OrdinalIgnoreCase))
            {
                error = $"{_displayName} file is outside its configured library.";
                return null;
            }
            if (!_allowedExtensions.Contains(Path.GetExtension(fullPath)))
            {
                error = $"Only indexed {_displayName} files with extensions " +
                    $"{string.Join(", ", _allowedExtensions.OrderBy(e => e))} are supported.";
                return null;
            }
            if (!File.Exists(fullPath))
            {
                error = $"{_displayName} file does not exist.";
                return null;
            }
            return fullPath;
        }

        private InstanceDefinition ImportAsDefinition(
            RhinoDoc doc,
            string filePath,
            string definitionName,
            string description)
        {
            string extension = Path.GetExtension(filePath);
            var beforeIds = new HashSet<Guid>(doc.Objects.Select(obj => obj.Id));
            string escapedPath = filePath.Replace("\"", "\"\"");
            bool imported = RhinoApp.RunScript($"_-Import \"{escapedPath}\" _Enter", false);
            if (!imported)
                throw new InvalidOperationException($"Rhino's {extension} importer did not complete.");

            var importedObjects = doc.Objects
                .Where(obj => !beforeIds.Contains(obj.Id) && !obj.IsDeleted)
                .ToList();
            if (importedObjects.Count == 0)
                throw new InvalidOperationException($"{extension} import created no Rhino objects.");

            try
            {
                var geometry = new List<GeometryBase>();
                var attributes = new List<ObjectAttributes>();
                BoundingBox bounds = BoundingBox.Empty;
                bool hasBounds = false;

                foreach (var importedObject in importedObjects)
                {
                    GeometryBase duplicate = importedObject.Geometry?.Duplicate();
                    if (duplicate == null)
                        continue;
                    geometry.Add(duplicate);
                    attributes.Add(importedObject.Attributes.Duplicate());

                    BoundingBox objectBounds = duplicate.GetBoundingBox(true);
                    if (objectBounds.IsValid)
                    {
                        if (!hasBounds)
                        {
                            bounds = objectBounds;
                            hasBounds = true;
                        }
                        else
                        {
                            bounds.Union(objectBounds);
                        }
                    }
                }

                if (geometry.Count == 0 || !hasBounds)
                    throw new InvalidOperationException($"Imported {extension} file contained no usable geometry.");

                var basePoint = new Point3d(bounds.Center.X, bounds.Center.Y, bounds.Min.Z);
                int definitionIndex = doc.InstanceDefinitions.Add(
                    definitionName,
                    description ?? $"Indexed {_displayName}",
                    basePoint,
                    geometry,
                    attributes
                );
                if (definitionIndex < 0)
                    throw new InvalidOperationException($"Rhino failed to create the {_displayName} block definition.");

                return doc.InstanceDefinitions[definitionIndex];
            }
            finally
            {
                foreach (var importedObject in importedObjects)
                    doc.Objects.Delete(importedObject.Id, true);
            }
        }

        /// <summary>
        /// Builds a block definition for a transparent raster asset (for
        /// example a PNG entourage cut-out): an upright textured quad with
        /// alpha transparency, bottom-centre anchored at the origin. Physical
        /// size comes from manifest dimensions_mm when present, otherwise from
        /// pixel dimensions at 96 dpi.
        /// </summary>
        private InstanceDefinition BuildRasterDefinition(
            RhinoDoc doc,
            string filePath,
            string definitionName,
            string description,
            JObject metadata)
        {
            double widthMm = 0.0;
            double heightMm = 0.0;
            var dimensions = metadata?["dimensions_mm"] as JObject;
            if (dimensions != null)
            {
                widthMm = dimensions.Value<double?>("width") ?? 0.0;
                heightMm = dimensions.Value<double?>("height") ?? 0.0;
            }

            int pixelWidth;
            int pixelHeight;
            using (var bitmap = new System.Drawing.Bitmap(filePath))
            {
                pixelWidth = bitmap.Width;
                pixelHeight = bitmap.Height;
            }
            if (pixelWidth <= 0 || pixelHeight <= 0)
                throw new InvalidOperationException("Raster asset has invalid pixel dimensions.");

            if (widthMm <= 0.0 && heightMm <= 0.0)
                widthMm = pixelWidth * 25.4 / 96.0;
            if (widthMm <= 0.0)
                widthMm = heightMm * pixelWidth / pixelHeight;
            if (heightMm <= 0.0)
                heightMm = widthMm * pixelHeight / pixelWidth;

            var mesh = new Mesh();
            mesh.Vertices.Add(-widthMm / 2.0, 0.0, 0.0);
            mesh.Vertices.Add(widthMm / 2.0, 0.0, 0.0);
            mesh.Vertices.Add(widthMm / 2.0, 0.0, heightMm);
            mesh.Vertices.Add(-widthMm / 2.0, 0.0, heightMm);
            mesh.TextureCoordinates.Add(0.0, 0.0);
            mesh.TextureCoordinates.Add(1.0, 0.0);
            mesh.TextureCoordinates.Add(1.0, 1.0);
            mesh.TextureCoordinates.Add(0.0, 1.0);
            mesh.Faces.AddFace(0, 1, 2, 3);
            mesh.Normals.ComputeNormals();
            mesh.Compact();

            int materialIndex = doc.Materials.Add();
            if (materialIndex < 0)
                throw new InvalidOperationException("Rhino failed to create the raster material.");
            var material = doc.Materials[materialIndex];
            material.Name = definitionName;
            material.SetBitmapTexture(filePath);
            material.AlphaTransparency = true;
            material.CommitChanges();

            var attributes = new ObjectAttributes
            {
                MaterialIndex = materialIndex,
                MaterialSource = ObjectMaterialSource.MaterialFromObject
            };

            int definitionIndex = doc.InstanceDefinitions.Add(
                definitionName,
                description ?? $"Indexed raster {_displayName}",
                Point3d.Origin,
                new GeometryBase[] { mesh },
                new[] { attributes }
            );
            if (definitionIndex < 0)
                throw new InvalidOperationException($"Rhino failed to create the raster {_displayName} block definition.");

            return doc.InstanceDefinitions[definitionIndex];
        }

        /// <summary>
        /// Imports AutoCAD-style .pat hatch definitions from the controlled
        /// library root into the active document's hatch pattern table.
        /// </summary>
        public HatchPatternImportResult ImportHatchPatterns(string filePath)
        {
            var result = new HatchPatternImportResult
            {
                Status = "error",
                Patterns = new List<string>()
            };

            if (string.IsNullOrWhiteSpace(filePath))
            {
                result.Message = "Hatch pattern file path is required.";
                return result;
            }
            string fullPath = Path.GetFullPath(filePath);
            string rootWithSeparator = _libraryRoot.TrimEnd(
                Path.DirectorySeparatorChar,
                Path.AltDirectorySeparatorChar
            ) + Path.DirectorySeparatorChar;
            if (!fullPath.StartsWith(rootWithSeparator, StringComparison.OrdinalIgnoreCase))
            {
                result.Message = "Hatch pattern file is outside its configured library.";
                return result;
            }
            if (!string.Equals(Path.GetExtension(fullPath), ".pat", StringComparison.OrdinalIgnoreCase))
            {
                result.Message = "Only .pat hatch definition files are supported.";
                return result;
            }
            if (!File.Exists(fullPath))
            {
                result.Message = "Hatch pattern file does not exist.";
                return result;
            }

            var doc = RhinoDoc.ActiveDoc;
            if (doc == null)
            {
                result.Message = "No active Rhino document.";
                return result;
            }

            try
            {
                HatchPattern[] patterns = HatchPattern.ReadFromFile(fullPath, true);
                if (patterns == null || patterns.Length == 0)
                {
                    result.Message = "No hatch patterns were found in the file.";
                    return result;
                }
                int added = 0;
                foreach (var pattern in patterns)
                {
                    if (pattern == null || string.IsNullOrWhiteSpace(pattern.Name))
                        continue;
                    if (doc.HatchPatterns.FindName(pattern.Name) == null)
                    {
                        if (doc.HatchPatterns.Add(pattern) < 0)
                            continue;
                        added++;
                    }
                    result.Patterns.Add(pattern.Name);
                }
                result.Status = "success";
                result.Message = $"Imported {added} new hatch patterns ({result.Patterns.Count} available).";
                return result;
            }
            catch (Exception ex)
            {
                result.Message = ex.Message;
                result.ErrorTrace = ex.ToString();
                return result;
            }
        }

        private static InstanceDefinition FindDefinition(RhinoDoc doc, string name)
        {
            foreach (var definition in doc.InstanceDefinitions)
            {
                if (definition != null &&
                    !definition.IsDeleted &&
                    string.Equals(definition.Name, name, StringComparison.OrdinalIgnoreCase))
                    return definition;
            }
            return null;
        }

        private ObjectAttributes BuildInstanceAttributes(
            RhinoDoc doc,
            FurniturePlacementRequest request)
        {
            int layerIndex = FindOrCreateLayer(doc, _layerPath);
            var attributes = new ObjectAttributes
            {
                Name = request.Name ?? request.AssetId,
                LayerIndex = layerIndex
            };
            attributes.SetUserString("almond.asset_id", request.AssetId ?? "");
            attributes.SetUserString("almond.asset_type", _assetType);
            attributes.SetUserString("almond.metadata", request.Metadata?.ToString(Formatting.None) ?? "{}");
            return attributes;
        }

        private static int FindOrCreateLayer(RhinoDoc doc, string name)
        {
            string[] parts = (name ?? "Assets").Split(
                new[] { "::" },
                StringSplitOptions.RemoveEmptyEntries
            );
            Guid parentId = Guid.Empty;
            int currentIndex = -1;
            foreach (string rawPart in parts)
            {
                string part = rawPart.Trim();
                currentIndex = -1;
                foreach (var layer in doc.Layers)
                {
                    if (layer != null &&
                        !layer.IsDeleted &&
                        layer.ParentLayerId == parentId &&
                        string.Equals(layer.Name, part, StringComparison.OrdinalIgnoreCase))
                    {
                        currentIndex = layer.Index;
                        break;
                    }
                }
                if (currentIndex < 0)
                {
                    currentIndex = doc.Layers.Add(new Layer
                    {
                        Name = part,
                        ParentLayerId = parentId
                    });
                }
                if (currentIndex < 0)
                    throw new InvalidOperationException($"Rhino failed to create layer {name}.");
                parentId = doc.Layers[currentIndex].Id;
            }
            return currentIndex;
        }

        private static Point3d ReadPosition(double[] position)
        {
            if (position == null || position.Length != 3)
                throw new ArgumentException("position must contain exactly three coordinates.");
            if (position.Any(value => double.IsNaN(value) || double.IsInfinity(value)))
                throw new ArgumentException("position coordinates must be finite.");
            return new Point3d(position[0], position[1], position[2]);
        }

        private string BuildDefinitionName(string assetId)
        {
            string safeId = Regex.Replace(assetId ?? "unknown", @"[^A-Za-z0-9._-]+", "-");
            return $"{_blockPrefix}::{safeId}";
        }
    }

    public class HatchPatternImportResult
    {
        [JsonProperty("status")]
        public string Status { get; set; }

        [JsonProperty("message")]
        public string Message { get; set; }

        [JsonProperty("patterns")]
        public List<string> Patterns { get; set; }

        [JsonProperty("error_trace")]
        public string ErrorTrace { get; set; }
    }

    public class FurniturePlacementRequest
    {
        [JsonProperty("asset_id")]
        public string AssetId { get; set; }

        [JsonProperty("file_path")]
        public string FilePath { get; set; }

        [JsonProperty("name")]
        public string Name { get; set; }

        [JsonProperty("position")]
        public double[] Position { get; set; }

        [JsonProperty("rotation_degrees")]
        public double RotationDegrees { get; set; }

        [JsonProperty("scale")]
        public double Scale { get; set; } = 1.0;

        [JsonProperty("metadata")]
        public JObject Metadata { get; set; }
    }

    public class FurniturePlacementResult
    {
        [JsonProperty("status")]
        public string Status { get; set; }

        [JsonProperty("message")]
        public string Message { get; set; }

        [JsonProperty("asset_id")]
        public string AssetId { get; set; }

        [JsonProperty("object_guid")]
        public string ObjectGuid { get; set; }

        [JsonProperty("block_definition")]
        public string BlockDefinition { get; set; }

        [JsonProperty("definition_created")]
        public bool DefinitionCreated { get; set; }

        [JsonProperty("bounds")]
        public BoundsPayload Bounds { get; set; }

        [JsonProperty("error_trace")]
        public string ErrorTrace { get; set; }
    }

    public class BoundsPayload
    {
        [JsonProperty("min")]
        public double[] Min { get; set; }

        [JsonProperty("max")]
        public double[] Max { get; set; }

        public static BoundsPayload FromBoundingBox(BoundingBox bounds)
        {
            if (!bounds.IsValid)
                return null;
            return new BoundsPayload
            {
                Min = new[] { bounds.Min.X, bounds.Min.Y, bounds.Min.Z },
                Max = new[] { bounds.Max.X, bounds.Max.Y, bounds.Max.Z }
            };
        }
    }
}
