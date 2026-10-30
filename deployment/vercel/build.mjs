// Allowlist-only static build: no Python, raw databases, user uploads or secrets.
import {mkdir, readFile, writeFile, copyFile, cp, rm, stat, realpath} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const here = path.dirname(fileURLToPath(import.meta.url));
const site = path.resolve(here, '../site');
const output = path.join(here, 'public');
const catalog = JSON.parse(await readFile(path.join(here, 'catalog/index.json'), 'utf8'));
if (catalog.version !== 1 || !catalog.assets?.length) throw new Error('Run python deployment/export_static.py before building.');
await rm(output, {recursive: true, force: true});
await mkdir(path.join(output, 'catalog/media'), {recursive: true});
for (const name of ['styles.css', 'site.js']) await copyFile(path.join(site, name), path.join(output, name));
await cp(path.join(site, 'fonts'), path.join(output, 'fonts'), {recursive: true});
await mkdir(path.join(output, 'media'));
for (const name of ['demo.mp4', 'demo-poster.jpg']) await copyFile(path.join(site, 'media', name), path.join(output, 'media', name));
for (const name of ['sandbox.html', 'search.mjs', 'static-sandbox.mjs']) await copyFile(path.join(here, name), path.join(output, name));
const config = JSON.parse(await readFile(path.join(site, 'config.json'), 'utf8'));
await writeFile(path.join(output, 'config.json'), JSON.stringify({
  downloadUrl: config.downloadUrl, checksumUrl: config.checksumUrl,
  sandboxUrl: 'sandbox.html', version: config.version, downloadSize: config.downloadSize,
}, null, 2));
let landing = await readFile(path.join(site, 'index.html'), 'utf8');
landing = landing.replaceAll('Try the live sandbox', 'Try the interactive preview')
  .replaceAll('Open sandbox', 'Open preview').replaceAll('Explore the sandbox', 'Explore the preview');
const start = landing.indexOf('<h3>Sandbox:');
const end = landing.indexOf('</div></section>', start);
if (start < 0 || end < 0) throw new Error('Landing privacy section changed; update static build copy.');
landing = landing.slice(0, start) + '<h3>Interactive preview: a glimpse of the app.</h3><p>This is not a full sandbox. Explore a fixed sample library using keyword matching in your browser. The downloadable desktop app adds semantic search, your own folders, automatic indexing, b-roll planning and licence tools.</p><p class="muted">This preview does not upload files or call AI services. No speed or accuracy comparison has been benchmarked. Watch the video above for a broader walkthrough.</p>' + landing.slice(end);
await writeFile(path.join(output, 'index.html'), landing);
const references = new Set();
for (const a of catalog.assets) {
  references.add(a.media);
  if (a.thumb) references.add(a.thumb);
  for (const s of a.segments) if (s.thumb) references.add(s.thumb);
}
for (const ref of references) {
  if (!/^catalog\/media\/[a-f0-9]{24}\.(mp4|webm|jpg|jpeg|png|webp|mp3|wav)$/.test(ref)) throw new Error('Invalid media reference');
  const source = path.join(here, ref);
  const resolved = await realpath(source);
  const mediaRoot = await realpath(path.join(here, 'catalog/media'));
  if (!resolved.startsWith(mediaRoot + path.sep)) throw new Error('Media escapes catalog');
  if ((await stat(source)).size >= 95 * 1024 * 1024) throw new Error('Sample exceeds 95 MiB');
  await copyFile(source, path.join(output, ref));
}
await copyFile(path.join(here, 'catalog/index.json'), path.join(output, 'catalog/index.json'));
console.log(`Built static Vercel site: ${catalog.assets.length} assets, ${references.size} media files. No backend or API keys required.`);
