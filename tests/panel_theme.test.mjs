import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const script = readFileSync(new URL('../almond_mcp/library_ui/panel-theme.js', import.meta.url), 'utf8');
function page(search) {
  const properties = new Map(), classes = new Set();
  const root = {style:{setProperty:(key,value)=>properties.set(key,value)},dataset:{},classList:{add:value=>classes.add(value)}};
  const context = {URLSearchParams,location:{search},document:{documentElement:root},window:{},matchMedia:()=>({matches:false,addEventListener(){}})};
  vm.runInNewContext(script,context);
  return {...context,root,properties,classes};
}
test('desktop archive is unaffected by host styling',()=>{
  const p=page('?theme=dark');
  assert.equal(p.properties.size,0);
  assert.equal(p.classes.size,0);
  assert.equal(p.window.almondThemeReceive,undefined);
});
test('host palette takes precedence over browser preference and updates in place',()=>{
  const p=page('?panel=1&theme=light&palette='+encodeURIComponent(JSON.stringify({paper:'#333333',ink:'#eeeeee',font:'Segoe UI'})));
  assert.equal(p.root.dataset.rhinoTheme,'dark');
  assert.equal(p.properties.get('--paper'),'#333333');
  const originalRoot=p.root;
  p.window.almondThemeReceive({paper:'#f0f0f0',ink:'#202020',font:'Arial'});
  assert.equal(p.root,originalRoot);
  assert.equal(p.root.dataset.rhinoTheme,'light');
  assert.equal(p.properties.get('--ui-font'),'"Arial"');
});
test('invalid host colours and CSS injection cannot escape the palette boundary',()=>{
  const p=page('?panel=1&palette=broken');
  for(const input of [null,[],{paper:'url(https://example.com)',ink:'#fff',font:'x";background:url(x)'},{paper:123,font:{}}]) {
    p.window.almondThemeReceive(input);
    for(const [key,value] of p.properties) if(key!=='--ui-font') assert.match(value,/^#[a-f0-9]{6}$/i);
    assert.equal(p.properties.get('--ui-font'),'"Segoe UI"');
  }
});
test('unreadable custom colours get a readable text/control fallback',()=>{
  const p=page('?panel=1');
  p.window.almondThemeReceive({paper:'#333333',ink:'#333333',field:'#ffffff'});
  assert.equal(p.properties.get('--ink'),'#ffffff');
  assert.equal(p.properties.get('--field'),'#333333');
  assert.notEqual(p.properties.get('--preview'),p.properties.get('--paper'));
});
