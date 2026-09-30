"""Generate a World Labs Marble world (gaussian splat) from one image.

python marble.py <image> [--model marble-1.1] [--name "..."] [--prompt "..."]
Reads WLT_API_KEY from C:\\Users\\liang\\Documents\\almond_promo\\.env (never printed).
Writes splat/world.json and splat/world_<res>.spz next to the .env.
"""
import json, sys, time, urllib.request, urllib.error
from pathlib import Path

WORK = Path(r"C:\Users\liang\Documents\almond_promo")
BASE = "https://api.worldlabs.ai/marble/v1"


def key():
    for line in (WORK / '.env').read_text(encoding='utf-8').splitlines():
        if line.strip().startswith('WLT_API_KEY='):
            v = line.split('=', 1)[1].strip().strip('"').strip("'")
            if v: return v
    raise SystemExit('WLT_API_KEY is empty in .env')


def call(method, path, body=None, headers=None):
    url = path if path.startswith('http') else BASE + path
    data = json.dumps(body).encode() if body is not None else None
    h = {'WLT-Api-Key': key(), 'Content-Type': 'application/json'}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            txt = r.read().decode()
            return json.loads(txt) if txt else {}
    except urllib.error.HTTPError as e:
        raise SystemExit(f'HTTP {e.code} on {method} {path}: {e.read().decode()[:800]}')


def upload(img: Path):
    ext = img.suffix.lstrip('.').lower()
    prep = call('POST', '/media-assets:prepare_upload', {'file_name': img.name, 'kind': 'image', 'extension': ext})
    info = prep['upload_info']
    ma = prep.get('media_asset', {})
    asset_id = ma.get('media_asset_id') or ma.get('id') or prep.get('media_asset_id')
    hdrs = dict(info.get('required_headers') or {})
    req = urllib.request.Request(info['upload_url'], data=img.read_bytes(), method=info.get('upload_method', 'PUT'), headers=hdrs)
    with urllib.request.urlopen(req, timeout=300) as r:
        print('upload', r.status)
    return asset_id


def main():
    a = sys.argv[1:]
    img = Path(a[0])
    model = a[a.index('--model') + 1] if '--model' in a else 'marble-1.1'
    name = a[a.index('--name') + 1] if '--name' in a else 'Almond Atelier-07 axon'
    prompt = a[a.index('--prompt') + 1] if '--prompt' in a else None
    out = WORK / ('splat' if '--out' not in a else a[a.index('--out') + 1]); out.mkdir(exist_ok=True)
    asset = upload(img)
    wp = {'type': 'image', 'image_prompt': {'source': 'media_asset', 'media_asset_id': asset}}
    if prompt: wp['text_prompt'] = prompt
    op = call('POST', '/worlds:generate', {'display_name': name, 'model': model, 'world_prompt': wp})
    opid = op.get('operation_id') or op.get('name') or op.get('id')
    print('operation', opid, flush=True)
    t0 = time.time()
    while True:
        st = call('GET', f'/operations/{opid}')
        if st.get('done'):
            break
        print('waiting %ds' % (time.time() - t0), st.get('metadata', {}).get('progress', ''), flush=True)
        time.sleep(20)
    if st.get('error'):
        raise SystemExit('generation failed: ' + json.dumps(st['error']))
    world = st.get('response') or {}
    wid = world.get('id') or world.get('world_id')
    if wid:
        world = call('GET', f'/worlds/{wid}')
        world = world.get('world', world)
    (out / 'world.json').write_text(json.dumps(world, indent=1))
    spz = world['assets']['splats']['spz_urls']
    for res in ('full_res', '500k'):
        if res in spz:
            p = out / f'world_{res}.spz'
            urllib.request.urlretrieve(spz[res], p)
            print('saved', p, p.stat().st_size)
    meta = world['assets']['splats'].get('semantics_metadata')
    print('metadata', meta)
    print('marble url', world.get('world_marble_url') or world.get('marble_url') or '')


if __name__ == '__main__':
    main()
