using System;
using System.Threading;
using RhinoAlmondBridge;

class Program
{
    static void Main(string[] args)
    {
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
