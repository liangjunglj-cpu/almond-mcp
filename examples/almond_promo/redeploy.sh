#!/bin/sh
# Swap in a fresh dev bridge build: clean test geometry, close Rhino, copy the .rhp, relaunch, load Grasshopper/Karamba.
cd "$(dirname "$0")"
P="$APPDATA/McNeel/Rhinoceros/packages/8.0/almondbridge/0.6.1-dev"
B="../../RhinoAlmondBridge/bin/Release/net48/RhinoAlmondBridge.dll"
timeout 60 python -c "
from bridge import run_cs
run_cs('''foreach (var nm in new[]{\"SV_TEST\",\"A07 / 16 Structure\"}) { var l = doc.Layers.FindName(nm); if (l != null) foreach (var o in doc.Objects.FindByLayer(l)) doc.Objects.Delete(o, true); } doc.Modified = false; log.Append(\"clean\");''')
" || exit 1
python -c "
import ctypes, time, shot
for h, _ in shot.rhino_hwnd(): ctypes.windll.user32.PostMessageW(h, 0x0010, 0, 0)
"
for i in $(seq 1 60); do tasklist | grep -qi "Rhino.exe" || break; sleep 1; done
tasklist | grep -qi "Rhino.exe" && { echo "Rhino did not exit"; exit 1; }
cp "$B" "$P/RhinoAlmondBridge.rhp" && echo copied
powershell -NoProfile -Command "Start-Process 'C:\Program Files\Rhino 8\System\Rhino.exe' -ArgumentList '\"C:\Users\liang\Documents\almond_promo\rhino\A07-promo.3dm\"'"
for i in $(seq 1 90); do python -c "import socket; socket.create_connection(('127.0.0.1',5000),2).close()" 2>/dev/null && break; sleep 2; done
sleep 6
timeout 120 python -c "
from bridge import run_cs
run_cs('''var gh = RhinoApp.GetPlugInObject(\"Grasshopper\"); gh.GetType().GetMethod(\"LoadEditor\").Invoke(gh, null); gh.GetType().GetMethod(\"HideEditor\").Invoke(gh, null);
log.Append(\"ready \" + typeof(RhinoAlmondBridge.BridgeServer).Assembly.Location + \" \" + File.GetLastWriteTime(typeof(RhinoAlmondBridge.BridgeServer).Assembly.Location));''')
"
