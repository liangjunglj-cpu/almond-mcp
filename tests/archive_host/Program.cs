using System;
using System.Threading;
using System.IO;
using Newtonsoft.Json;
using RhinoAlmondBridge;

class Program
{
    static void Main(string[] args)
    {
        if (args[0] == "--settings")
        {
            try { Console.WriteLine(AnalysisSettings.Parse(File.ReadAllText(args[1])).ToJson().ToString(Formatting.None)); }
            catch(Exception ex) { Console.Error.WriteLine(ex.Message); Environment.ExitCode=1; }
            return;
        }
        if (args[0] == "--package")
        {
            Console.WriteLine(NativeSolver.PackageFor(args[1]));
            return;
        }
        if (args[0] == "--solve")
        {
            // the panel's process boundary: request file -> almond-mcp solve -> reply on stdout
            var reply = NativeSolver.RunAsync(Newtonsoft.Json.Linq.JObject.Parse(File.ReadAllText(args[1])), 120000).GetAwaiter().GetResult();
            Console.OutputEncoding = new System.Text.UTF8Encoding(false);
            Console.WriteLine(reply.ToString(Formatting.None));
            return;
        }
        if (args[0] == "--mesh")
        {
            try
            {
                var mesh = ArchiveMeshData.Decode(File.ReadAllBytes(args[1]), args[2]);
                Console.WriteLine(JsonConvert.SerializeObject(mesh));
            }
            catch (Exception ex) { Console.Error.WriteLine(ex.Message); Environment.ExitCode = 1; }
            return;
        }
        using (var server = new ArchiveHttpServer(args[0]))
        {
            server.Start();
            Console.WriteLine(server.Url);
            Console.Out.Flush();
            if (args.Length > 1 && args[1] == "--serve") new ManualResetEvent(false).WaitOne();
            else Console.ReadLine();
        }
    }
}
