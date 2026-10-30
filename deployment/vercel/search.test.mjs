import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile, stat} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {search} from './search.mjs';
const assets = [
  {id: 1, kind: 'video', name: 'One', caption: 'city', segments: [{id: 11, start: 4, end: 8, caption: 'golden sunset'}]},
  {id: 2, kind: 'image', name: 'SUNSET', caption: 'beach', segments: []},
  {id: 3, kind: 'audio', name: 'Whoosh', transcript: 'café ambience', segments: []},
];
test('keyword search ranks fields and preserves matching shot timestamp', () => {
  const rows = search(assets, 'sunset');
  assert.deepEqual(rows.map(r => r.asset.id), [2, 1]);
  assert.equal(rows[1].hit.start, 4);
});
test('filters, unicode normalization, empty browse and no-match behavior', () => {
  assert.equal(search(assets, 'sunset', 'video').length, 1);
  assert.equal(search(assets, 'CAFE')[0].asset.id, 3);
  assert.equal(search(assets, '').length, 3);
  assert.equal(search(assets, 'astronaut').length, 0);
});
test('exported real catalog has only public fields and valid deployed files', async () => {
  const base = new URL('./public/', import.meta.url);
  const catalog = JSON.parse(await readFile(new URL('catalog/index.json', base), 'utf8'));
  const allowed = new Set(['id', 'kind', 'name', 'caption', 'transcript', 'duration', 'tags', 'media', 'segments', 'thumb', 'license']);
  for (const asset of catalog.assets) {
    assert.ok(Object.keys(asset).every(k => allowed.has(k)));
    for (const ref of [asset.media, asset.thumb, ...asset.segments.map(s => s.thumb)].filter(Boolean)) {
      assert.match(ref, /^catalog\/media\/[a-f0-9]{24}\.[a-z0-9]+$/);
      assert.ok((await stat(fileURLToPath(new URL(ref, base)))).size > 0);
    }
  }
  assert.ok(catalog.assets.length > 0);
  const landing = await readFile(new URL('index.html', base), 'utf8');
  assert.ok(landing.includes('id="demo"'));
  assert.ok(!landing.includes('upload selected files'));
  const script = await readFile(new URL('static-sandbox.mjs', base), 'utf8');
  assert.ok(!script.includes('/api/'));
});
