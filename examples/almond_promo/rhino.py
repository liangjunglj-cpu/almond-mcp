"""CLI: python rhino.py <script.cs> [KEY=VAL ...]  -- runs a promo C# body via the bridge ('//LIB' pulls in sv_lib.cs)."""
import sys
from pathlib import Path
from bridge import run_cs

HERE = Path(__file__).resolve().parent
if __name__ == '__main__':
    body = (HERE / sys.argv[1]).read_text(encoding='utf-8')
    if body.startswith('//LIB'):
        body = (HERE / 'sv_lib.cs').read_text(encoding='utf-8') + body
    for kv in sys.argv[2:]:
        k, v = kv.split('=', 1)
        body = body.replace(k, v)
    run_cs(body, timeout=1800)
