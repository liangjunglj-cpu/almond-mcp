using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using Newtonsoft.Json.Linq;

namespace RhinoAlmondBridge
{
    // Deliberately bounded static GLB decoder. No Rhino/native dependencies, file
    // references, textures, plugins, scripts or network access. Tested against
    // the independent drafting decoder for every distributed model.
    internal sealed class ArchiveMeshData
    {
        internal sealed class Part
        {
            public double[][] Vertices;
            public double[][] Normals;
            public int[] Indices;
            public string Material;
        }
        public readonly List<Part> Parts = new List<Part>();
        public JObject Passport;
        public int TriangleCount => Parts.Sum(p => p.Indices.Length / 3);
        public double[] Min => Enumerable.Range(0, 3).Select(k => Parts.Min(p => p.Vertices.Min(v => v[k]))).ToArray();
        public double[] Max => Enumerable.Range(0, 3).Select(k => Parts.Max(p => p.Vertices.Max(v => v[k]))).ToArray();
        private JObject _g;
        private byte[] _bin;
        private int _visited;
        private static void Require(bool condition, string message)
        {
            if (!condition) throw new InvalidDataException(message);
        }
        private static bool Finite(double n) => !double.IsNaN(n) && !double.IsInfinity(n);
        public static ArchiveMeshData Decode(byte[] bytes, string assetId)
        {
            Require(bytes.Length >= 28 && bytes.Length <= 100000000, "Invalid GLB size.");
            Require(BitConverter.ToUInt32(bytes, 0) == 0x46546c67 && BitConverter.ToUInt32(bytes, 4) == 2 &&
                BitConverter.ToUInt32(bytes, 8) == bytes.Length, "Invalid GLB header.");
            int offset = 12;
            JObject gltf = null;
            byte[] binary = null;
            while (offset < bytes.Length)
            {
                Require(offset <= bytes.Length - 8, "Truncated GLB chunk.");
                uint length = BitConverter.ToUInt32(bytes, offset), type = BitConverter.ToUInt32(bytes, offset + 4);
                Require(length <= bytes.Length - offset - 8 && length % 4 == 0, "Invalid GLB chunk length.");
                offset += 8;
                if (type == 0x4e4f534a)
                {
                    Require(gltf == null && binary == null, "Duplicate or misplaced GLB JSON.");
                    gltf = JObject.Parse(Encoding.UTF8.GetString(bytes, offset, (int)length));
                }
                else if (type == 0x004e4942)
                {
                    Require(gltf != null && binary == null, "Duplicate or misplaced GLB buffer.");
                    binary = new byte[length];
                    Buffer.BlockCopy(bytes, offset, binary, 0, (int)length);
                }
                else throw new InvalidDataException("Unsupported GLB chunk.");
                offset += (int)length;
            }
            Require(gltf != null && binary != null, "Incomplete GLB.");
            Require(!(gltf["animations"] as JArray)?.Any() ?? true, "Animated models are unsupported.");
            Require(!(gltf["skins"] as JArray)?.Any() ?? true, "Skinned models are unsupported.");
            Require(!(gltf["extensionsRequired"] as JArray)?.Any() ?? true, "Required GLB extensions are unsupported.");
            Require(gltf["buffers"] is JArray buffers && buffers.Count == 1 &&
                buffers[0]["uri"] == null && (int)buffers[0]["byteLength"] <= binary.Length, "External/truncated buffers are unsupported.");
            var passport = gltf["asset"]?["extras"]?["almond"]?["passport"] as JObject;
            Require((string)passport?["asset_id"] == assetId &&
                (string)passport?["coordinate_convention"]?["glb_numeric_units"] == "mm", "Asset identity or millimetre convention is missing.");
            var result = new ArchiveMeshData { _g = gltf, _bin = binary, Passport = passport };
            var scene = gltf["scenes"]?[(int?)gltf["scene"] ?? 0];
            Require(scene?["nodes"] is JArray, "Missing default scene.");
            foreach (int node in scene["nodes"]) result.Visit(node, Identity(), new HashSet<int>());
            Require(result.Parts.Count > 0, "No static mesh geometry.");
            return result;
        }
        private double[][] Accessor(int index, bool vector)
        {
            var a = _g["accessors"][index];
            Require(a["sparse"] == null && !((bool?)a["normalized"] ?? false), "Sparse/normalized accessors are unsupported.");
            int kind = (int)a["componentType"], width = vector ? 3 : 1, count = (int)a["count"];
            Require((string)a["type"] == (vector ? "VEC3" : "SCALAR") &&
                (vector ? kind == 5126 : kind == 5121 || kind == 5123 || kind == 5125), "Unsupported accessor type.");
            var view = _g["bufferViews"][(int)a["bufferView"]];
            Require(((int?)view["buffer"] ?? 0) == 0 && view["extensions"] == null, "Unsupported buffer view.");
            int size = kind == 5121 ? 1 : kind == 5123 ? 2 : 4;
            long start = (long?)view["byteOffset"] ?? 0, viewLength = (long)view["byteLength"];
            long pos = start + ((long?)a["byteOffset"] ?? 0);
            int stride = (int?)view["byteStride"] ?? size * width;
            long end = pos + (long)(count - 1) * stride + width * size;
            Require(count > 0 && count <= 750000 && stride >= size * width && pos >= start &&
                start >= 0 && end <= start + viewLength && end <= _bin.Length, "Invalid accessor bounds.");
            var values = new double[count][];
            for (int i = 0; i < count; i++)
            {
                values[i] = new double[width];
                for (int k = 0; k < width; k++)
                {
                    int at = checked((int)(pos + i * (long)stride + k * size));
                    double value = kind == 5126 ? BitConverter.ToSingle(_bin, at) : kind == 5125 ?
                        BitConverter.ToUInt32(_bin, at) : kind == 5123 ? BitConverter.ToUInt16(_bin, at) : _bin[at];
                    Require(Finite(value), "Non-finite mesh data.");
                    values[i][k] = value;
                }
            }
            return values;
        }
        private void Visit(int index, double[,] parent, HashSet<int> ancestors)
        {
            Require(++_visited <= 10000 && ancestors.Count < 100 && !ancestors.Contains(index), "Cyclic/oversized scene.");
            var node = _g["nodes"][index];
            Require(node["skin"] == null && node["weights"] == null, "Deformed meshes are unsupported.");
            var world = Multiply(parent, NodeMatrix(node));
            if (node["mesh"] != null)
                foreach (var primitive in _g["meshes"][(int)node["mesh"]]["primitives"])
                {
                    Require(((int?)primitive["mode"] ?? 4) == 4 && primitive["targets"] == null &&
                        primitive["extensions"] == null, "Only static triangle primitives are supported.");
                    var vertices = Accessor((int)primitive["attributes"]["POSITION"], true);
                    var indices = primitive["indices"] == null ? Enumerable.Range(0, vertices.Length).ToArray() :
                        Accessor((int)primitive["indices"], false).Select(a => checked((int)a[0])).ToArray();
                    Require(indices.Length % 3 == 0 && indices.All(i => i >= 0 && i < vertices.Length) &&
                        TriangleCount + indices.Length / 3 <= 250000, "Invalid or oversized triangle indices.");
                    var normalId = primitive["attributes"]["NORMAL"];
                    var normals = normalId == null ? null : Accessor((int)normalId, true);
                    Require(normals == null || normals.Length == vertices.Length, "Normal count mismatch.");
                    // Current archive transforms are positive uniform scale + rotation.
                    // Fail closed for shear/reflection/nonuniform scale rather than corrupt normals.
                    double[] lengths = Enumerable.Range(0, 3).Select(k => Math.Sqrt(Enumerable.Range(0, 3).Sum(r => world[r,k]*world[r,k]))).ToArray();
                    Require(lengths[0] > 0 && lengths.All(l => Math.Abs(l-lengths[0]) < lengths[0]*1e-6), "Nonuniform scale is unsupported.");
                    for (int a = 0; a < 3; a++)
                        for (int b = a+1; b < 3; b++)
                            Require(Math.Abs(Enumerable.Range(0,3).Sum(r => world[r,a]*world[r,b])) < lengths[0]*lengths[0]*1e-6, "Shear is unsupported.");
                    double det = world[0,0]*(world[1,1]*world[2,2]-world[1,2]*world[2,1])
                        -world[0,1]*(world[1,0]*world[2,2]-world[1,2]*world[2,0])+world[0,2]*(world[1,0]*world[2,1]-world[1,1]*world[2,0]);
                    Require(det > 0, "Reflected transforms are unsupported.");
                    for (int i = 0; i < vertices.Length; i++)
                    {
                        vertices[i] = Transform(vertices[i], world, false);
                        if (normals != null) normals[i] = Transform(normals[i], world, true);
                    }
                    Parts.Add(new Part { Vertices = vertices, Normals = normals, Indices = indices,
                        Material = (string)_g["materials"]?[(int?)primitive["material"] ?? 0]?["name"] });
                }
            var next = new HashSet<int>(ancestors) { index };
            foreach (int child in node["children"] as JArray ?? new JArray()) Visit(child, world, next);
        }
        private static double[] Transform(double[] p, double[,] m, bool normal)
        {
            var v = Enumerable.Range(0, 3).Select(r => m[r,0]*p[0]+m[r,1]*p[1]+m[r,2]*p[2]+(normal ? 0 : m[r,3])).ToArray();
            if (normal)
            {
                double length = Math.Sqrt(v.Sum(n => n*n));
                Require(length > 0 && Finite(length), "Invalid normal.");
                v = v.Select(n => n/length).ToArray();
            }
            Require(v.All(n => Finite(n) && Math.Abs(n) <= 1e9), "Mesh exceeds supported coordinate range.");
            return new[] { v[0], -v[2], v[1] }; // Y-up mm -> right-handed Z-up mm.
        }
        private static double[,] Identity() => new double[,] {{1,0,0,0},{0,1,0,0},{0,0,1,0},{0,0,0,1}};
        private static double[,] Multiply(double[,] a, double[,] b)
        {
            var c = new double[4,4];
            for (int r=0;r<4;r++) for(int k=0;k<4;k++) for(int i=0;i<4;i++) c[r,k]+=a[r,i]*b[i,k];
            return c;
        }
        private static double[,] NodeMatrix(JToken node)
        {
            var m = Identity();
            if (node["matrix"] is JArray matrix)
            {
                Require(matrix.Count == 16, "Invalid matrix.");
                for(int r=0;r<4;r++) for(int k=0;k<4;k++) m[r,k]=(double)matrix[k*4+r];
            }
            else
            {
                double[] q = (node["rotation"] as JArray)?.Select(x=>(double)x).ToArray() ?? new[]{0d,0d,0d,1d};
                Require(q.Length == 4 && Math.Abs(q.Sum(x=>x*x)-1)<1e-4, "Invalid quaternion.");
                double x=q[0],y=q[1],z=q[2],w=q[3];
                m = new double[,] {{1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w),0},
                    {2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w),0},{2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y),0},{0,0,0,1}};
                for(int k=0;k<3;k++)
                {
                    double scale = (double?)node["scale"]?[k] ?? 1;
                    for(int r=0;r<3;r++) m[r,k]*=scale;
                    m[k,3]=(double?)node["translation"]?[k] ?? 0;
                }
            }
            Require(m.Cast<double>().All(Finite) && m[3,0]==0 && m[3,1]==0 && m[3,2]==0 && m[3,3]==1, "Invalid affine transform.");
            return m;
        }
    }
}
