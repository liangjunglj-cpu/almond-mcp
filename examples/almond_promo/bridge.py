"""Send C# scripts to the running Almond bridge (127.0.0.1:5000)."""
import json, socket, sys
from pathlib import Path

WORK = Path(r"C:\Users\liang\Documents\almond_promo")


def execute(source, timeout=120, quiet=False):
    payload = json.dumps({'type': 'execute', 'script': source, 'timeout_s': timeout}).encode()
    with socket.create_connection(('127.0.0.1', 5000), timeout=30) as s:
        s.settimeout(timeout + 15)
        s.sendall(len(payload).to_bytes(4, 'big') + payload)

        def exact(n):
            out = b''
            while len(out) < n:
                chunk = s.recv(n - len(out))
                if not chunk:
                    raise RuntimeError('Almond connection closed')
                out += chunk
            return out
        reply = json.loads(exact(int.from_bytes(exact(4), 'big')))
    if not quiet:
        print(json.dumps(reply)[:4000], flush=True)
    if reply.get('status') != 'success':
        raise SystemExit('bridge error: ' + json.dumps(reply)[:2000])
    return reply


def run_cs(body, usings='', timeout=120, quiet=False):
    """Wrap a method body (with access to `doc` and a `log` StringBuilder) as a bridge script.
    Whatever is appended to `log` comes back through RhinoApp output in the reply."""
    src = ('using System;using System.IO;using System.Linq;using System.Text;using System.Collections.Generic;'
           'using System.Drawing;using Rhino;using Rhino.Geometry;using Rhino.DocObjects;using Rhino.Display;'
           'using Rhino.Render;' + usings +
           '\npublic class Script{public static List<Guid> Run(RhinoDoc doc){var log=new StringBuilder();\n'
           + body +
           '\nFile.WriteAllText(@"' + str(WORK / 'bridge_log.txt') + '",log.ToString());return new List<Guid>();}}')
    execute(src, timeout=timeout, quiet=True)
    text = (WORK / 'bridge_log.txt').read_text(encoding='utf-8')
    if not quiet:
        print(text)
    return text


if __name__ == '__main__':
    run_cs(Path(sys.argv[1]).read_text(encoding='utf-8'), timeout=int(sys.argv[2]) if len(sys.argv) > 2 else 120)
