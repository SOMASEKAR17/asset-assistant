import {search} from './search.mjs';
const $ = s => document.querySelector(s);
let assets = [], rows = [], shown = 0;
function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}
function mediaURL(value) {
  if (!/^catalog\/media\/[a-f0-9]{24}\.(mp4|webm|jpg|jpeg|png|webp|mp3|wav)$/.test(value || '')) return '';
  return value;
}
function display(append = false) {
  if (!append) { rows = search(assets, $('#query').value, $('#kind').value); shown = 0; $('#results').replaceChildren(); }
  for (const row of rows.slice(shown, shown + 24)) {
    const a = row.asset, card = el('button', undefined, 'asset-card'); card.type = 'button';
    const thumb = mediaURL(row.hit?.thumb || a.thumb);
    if (thumb) { const img = el('img'); img.src = thumb; img.alt = a.caption || a.name; img.loading = 'lazy'; card.append(img); }
    else card.append(el('div', a.kind.toUpperCase(), 'placeholder'));
    const copy = el('div', undefined, 'asset-copy');
    copy.append(el('strong', a.name), el('small', row.hit?.caption || a.caption || a.kind), el('small', a.kind.toUpperCase() + (row.hit ? ` · ${row.hit.start.toFixed(1)}s` : '')));
    card.append(copy); card.addEventListener('click', () => preview(row)); $('#results').append(card);
  }
  shown = Math.min(shown + 24, rows.length);
  $('#more').hidden = shown >= rows.length;
  $('#status').textContent = `${shown} of ${rows.length} ${$('#query').value.trim() ? 'keyword matches' : 'samples'} shown`;
  if (!rows.length) $('#results').append(el('div', 'No keyword matches. Try a different word or browse all samples. Semantic search is available in the desktop app.', 'empty'));
}
function preview({asset: a, hit}) {
  $('#asset-title').textContent = a.name; $('#preview').replaceChildren(); $('#segments').replaceChildren();
  $('#caption').textContent = hit?.caption || a.caption || '';
  $('#tags').textContent = (a.tags || []).join(' · ');
  $('#licence').textContent = Object.values(a.license || {}).join(' · ') || 'Sample preview only. Confirm the original licence before reuse.';
  const player = el(a.kind === 'image' ? 'img' : a.kind); player.src = mediaURL(a.media);
  if (a.kind === 'image') player.alt = a.caption || a.name;
  else {
    player.controls = true; player.preload = 'metadata'; player.setAttribute('playsinline', '');
    player.addEventListener('loadedmetadata', () => { if (hit) player.currentTime = hit.start; }, {once: true});
    for (const segment of a.segments || []) {
      const button = el('button', `${segment.start.toFixed(1)}s – ${segment.end.toFixed(1)}s`);
      button.addEventListener('click', () => { player.currentTime = segment.start; $('#caption').textContent = segment.caption || a.caption || ''; });
      $('#segments').append(button);
    }
  }
  player.addEventListener('error', () => { $('#caption').textContent = 'This sample could not be played in your browser. Try another sample.'; });
  $('#preview').append(player); $('#detail').showModal();
}
$('#search-form').addEventListener('submit', e => { e.preventDefault(); display(); });
$('#kind').addEventListener('change', () => display());
$('#browse').addEventListener('click', () => { $('#query').value = ''; display(); });
document.querySelectorAll('[data-query]').forEach(b => b.addEventListener('click', () => { $('#query').value = b.dataset.query; display(); }));
$('#more').addEventListener('click', () => display(true));
$('#close').addEventListener('click', () => $('#detail').close());
$('#detail').addEventListener('close', () => { $('#preview').querySelectorAll('video,audio').forEach(p => p.pause()); $('#preview').replaceChildren(); });
try {
  const response = await fetch('catalog/index.json');
  if (!response.ok) throw new Error('Sample index unavailable');
  const catalog = await response.json();
  if (catalog.version !== 1 || !Array.isArray(catalog.assets)) throw new Error('Invalid sample index');
  assets = catalog.assets;
  $('#engine-state').textContent = `${assets.length} samples · Keyword search ready`; display();
} catch {
  $('#engine-state').textContent = 'Sample library unavailable';
  $('#status').textContent = 'Reload to retry, or watch the demo video above.';
}
