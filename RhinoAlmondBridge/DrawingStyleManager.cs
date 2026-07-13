using System;
using System.Collections.Generic;
using System.Drawing;
using Newtonsoft.Json;
using Rhino;
using Rhino.DocObjects;

namespace RhinoAlmondBridge
{
    public class DrawingStyleManager
    {
        public DrawingStyleResult Apply(DrawingStyleRequest request)
        {
            var result = new DrawingStyleResult
            {
                Status = "error",
                RecipeId = request?.RecipeId,
                Layers = new List<DrawingLayerResult>()
            };
            if (request?.Layers == null || request.Layers.Count == 0)
            {
                result.Message = "Drawing recipe must contain at least one layer.";
                return result;
            }
            var doc = RhinoDoc.ActiveDoc;
            if (doc == null)
            {
                result.Message = "No active Rhino document.";
                return result;
            }

            uint undoRecord = doc.BeginUndoRecord("Apply Almond drawing style");
            try
            {
                foreach (var specification in request.Layers)
                {
                    if (string.IsNullOrWhiteSpace(specification.Path))
                        throw new ArgumentException("Drawing layer path cannot be empty.");

                    int layerIndex = EnsureLayerPath(doc, specification.Path);
                    var layer = doc.Layers[layerIndex];
                    layer.Color = ReadColor(specification.Color, Color.Black);
                    layer.PlotColor = ReadColor(specification.PlotColor, layer.Color);
                    layer.PlotWeight = Math.Max(0.0, specification.PlotWeightMm);
                    layer.LinetypeIndex = EnsureLinetype(doc, specification.Linetype);
                    if (!doc.Layers.Modify(layer, layerIndex, true))
                        throw new InvalidOperationException(
                            $"Rhino failed to update drawing layer {specification.Path}."
                        );

                    result.Layers.Add(new DrawingLayerResult
                    {
                        Path = specification.Path,
                        Role = specification.Role,
                        LayerIndex = layerIndex,
                        PlotWeightMm = layer.PlotWeight,
                        Linetype = layer.LinetypeIndex < 0
                            ? "Continuous"
                            : doc.Linetypes[layer.LinetypeIndex]?.Name ?? "Continuous"
                    });
                }
                doc.Views.Redraw();
                result.Status = "success";
                result.Message = $"Applied {result.Layers.Count} drawing layers.";
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

        private static int EnsureLayerPath(RhinoDoc doc, string path)
        {
            string[] parts = path.Split(
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
                    throw new InvalidOperationException($"Could not create layer {path}.");
                parentId = doc.Layers[currentIndex].Id;
            }
            return currentIndex;
        }

        private static int EnsureLinetype(RhinoDoc doc, string requestedName)
        {
            string name = string.IsNullOrWhiteSpace(requestedName)
                ? "Continuous"
                : requestedName.Trim();
            // Default linetypes (Continuous, ByLayer, ByParent) do not
            // enumerate in the linetype table, and table index 0 is not
            // Continuous in Rhino 8 (verified live: index 0 was "Hidden").
            // FindName resolves defaults correctly; Continuous has index -1,
            // which Rhino treats as the continuous default on a layer.
            var existing = doc.Linetypes.FindName(name);
            if (existing != null)
                return existing.Index;
            if (string.Equals(name, "Continuous", StringComparison.OrdinalIgnoreCase))
                return -1;

            var created = new Linetype { Name = name };
            if (name.IndexOf("DashDot", StringComparison.OrdinalIgnoreCase) >= 0)
            {
                created.AppendSegment(8.0, true);
                created.AppendSegment(3.0, false);
                created.AppendSegment(1.0, true);
                created.AppendSegment(3.0, false);
            }
            else
            {
                created.AppendSegment(6.0, true);
                created.AppendSegment(3.0, false);
            }
            int index = doc.Linetypes.Add(created);
            if (index < 0)
                throw new InvalidOperationException($"Could not create linetype {name}.");
            return index;
        }

        private static Color ReadColor(int[] values, Color fallback)
        {
            if (values == null || values.Length != 3)
                return fallback;
            return Color.FromArgb(
                Math.Max(0, Math.Min(255, values[0])),
                Math.Max(0, Math.Min(255, values[1])),
                Math.Max(0, Math.Min(255, values[2]))
            );
        }
    }

    public class DrawingStyleRequest
    {
        [JsonProperty("recipe_id")]
        public string RecipeId { get; set; }

        [JsonProperty("layers")]
        public List<DrawingLayerSpecification> Layers { get; set; }
    }

    public class DrawingLayerSpecification
    {
        [JsonProperty("path")]
        public string Path { get; set; }

        [JsonProperty("role")]
        public string Role { get; set; }

        [JsonProperty("color")]
        public int[] Color { get; set; }

        [JsonProperty("plot_color")]
        public int[] PlotColor { get; set; }

        [JsonProperty("plot_weight_mm")]
        public double PlotWeightMm { get; set; }

        [JsonProperty("linetype")]
        public string Linetype { get; set; }
    }

    public class DrawingStyleResult
    {
        [JsonProperty("status")]
        public string Status { get; set; }

        [JsonProperty("message")]
        public string Message { get; set; }

        [JsonProperty("recipe_id")]
        public string RecipeId { get; set; }

        [JsonProperty("layers")]
        public List<DrawingLayerResult> Layers { get; set; }

        [JsonProperty("error_trace")]
        public string ErrorTrace { get; set; }
    }

    public class DrawingLayerResult
    {
        [JsonProperty("path")]
        public string Path { get; set; }

        [JsonProperty("role")]
        public string Role { get; set; }

        [JsonProperty("layer_index")]
        public int LayerIndex { get; set; }

        [JsonProperty("plot_weight_mm")]
        public double PlotWeightMm { get; set; }

        [JsonProperty("linetype")]
        public string Linetype { get; set; }
    }
}
