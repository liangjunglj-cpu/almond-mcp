using System.Runtime.InteropServices;
using Rhino.PlugIns;

// Permanent plugin ID - Rhino identifies the plugin by this GUID across
// versions and machines. NEVER change it; doing so makes Rhino treat the
// plugin as a different product (duplicate registrations, broken updates).
[assembly: Guid("c337dbb8-394a-4593-9c2b-a3d7cfc91893")]

[assembly: PlugInDescription(DescriptionType.Organization, "LiangJung")]
[assembly: PlugInDescription(DescriptionType.Email, "liangjung.lj@gmail.com")]
[assembly: PlugInDescription(DescriptionType.WebSite, "https://github.com/liangjunglj-cpu/almond-mcp")]
[assembly: PlugInDescription(DescriptionType.UpdateUrl, "https://github.com/liangjunglj-cpu/almond-mcp")]
