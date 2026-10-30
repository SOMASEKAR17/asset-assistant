const $ = selector => document.querySelector(selector);
let offset = 0, activeController, detailController, selectedSegment, selectedPrefix = '/api', sessionInfo, jobsTimer;
async function api(path, signal) {
  const response = await fetch(path, {signal});
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.error || `Request failed (${response.status}). Please try again.`);
  }
  return response.json();
}
function element(tag, text, className) {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (className) el.className = className;
  return el;
}
function render(rows, append = false) {
  if (!append) $('#results').replaceChildren();
  for (const row of rows) {
    const card = element('button', undefined, 'asset-card');
    card.type = 'button';
    if (row.thumb) {
      const img = element('img'); img.src = row.thumb; img.alt = row.caption || row.name; img.loading = 'lazy';
      img.addEventListener('error', () => img.replaceWith(element('div', row.kind.toUpperCase(), 'placeholder')), {once: true});
      card.append(img);
    } else card.append(element('div', row.kind.toUpperCase(), 'placeholder'));
    const copy = element('div', undefined, 'asset-copy');
    copy.append(element('strong', row.name), element('small', row.caption || row.kind), element('small', (row.hits?.[0]?.tc || '') + '  ' + row.kind.toUpperCase()));
    card.append(copy); card.addEventListener('click', () => openAsset(row)); $('#results').append(card);
  }
}
async function load(append = false) {
  activeController?.abort(); activeController = new AbortController();
  const controller = activeController;
  $('#more').hidden = true;
  if (!append) offset = 0;
  $('#status').textContent = 'Searching the sample library…';
  const query = $('#query').value.trim();
  const params = new URLSearchParams({kind: $('#kind').value, offset: String(offset)});
  if (query) params.set('q', query);
  try {
    const prefix = $('#library-scope').value === 'private' ? '/api/private' : '/api';
    if (prefix === '/api/private') await ensureSession();
    const data = await api(`${prefix}/${query ? 'search' : 'assets'}?${params}`, controller.signal);
    const rows = data.results || [];
    rows.forEach(row => { row.apiPrefix = prefix; });
    render(rows, append); offset += rows.length;
    $('#status').textContent = query ? `${rows.length} results for “${query}”` : `${offset} ${prefix === '/api/private' ? 'private' : 'sample'} assets shown`;
    if (!rows.length && !append) {
      $('#results').append(element('div', query ? 'No matching assets. Try another description or browse all assets.' : prefix === '/api/private' ? 'Upload files above. They will appear here after processing.' : 'The sample library is being prepared. Come back soon to explore cleared footage, photos and sounds.', 'empty'));
    }
    $('#more').hidden = Boolean(query) || !data.has_more;
  } catch (error) {
    if (error.name === 'AbortError') return;
    $('#status').textContent = error.message;
    if (!append) $('#results').replaceChildren(element('div', 'The sandbox is temporarily unavailable. You can retry using Search or Browse all assets.', 'empty'));
  }
}
async function openAsset(row) {
  detailController?.abort(); detailController = new AbortController();
  const controller = detailController;
  const dialog = $('#detail');
  $('#asset-title').textContent = row.name;
  $('#preview').replaceChildren(); $('#segments').replaceChildren();
  $('#caption').textContent = 'Loading preview…'; $('#tags').textContent = ''; $('#licence').textContent = ''; $('#similar').hidden = true;
  const selectedHit = row.hits?.[0];
  selectedPrefix = row.apiPrefix || '/api';
  if (!dialog.open) dialog.showModal();
  try {
    const data = await api(`${selectedPrefix}/assets/${row.asset_id}`, controller.signal);
    if (!dialog.open) return;
    const asset = data.asset;
    let player;
    if (asset.kind === 'video' || asset.kind === 'audio') {
      player = element(asset.kind); player.controls = true; player.preload = 'metadata'; player.src = data.media_url;
      player.addEventListener('loadedmetadata', () => { if (selectedHit?.start) player.currentTime = selectedHit.start; }, {once: true});
      player.addEventListener('error', () => $('#caption').textContent = 'This sample format cannot be previewed in your browser. Try another asset.');
    } else if (asset.kind === 'image') {
      player = element('img'); player.src = data.media_url; player.alt = asset.caption || asset.name;
    } else player = element('p', 'Template preview is available in the desktop app.');
    $('#preview').append(player);
    $('#caption').textContent = selectedHit?.caption || asset.caption || 'No description available.';
    $('#tags').textContent = (asset.tags || []).join(' · ');
    $('#licence').textContent = asset.license ? `Licence: ${typeof asset.license === 'string' ? asset.license : JSON.stringify(asset.license)}` : selectedPrefix === '/api/private' ? 'Your private upload. Confirm you have the rights needed before reuse.' : 'Sample supplied by the site owner. Preview does not grant reuse rights.';
    selectedSegment = selectedHit?.segment_id || data.segments[0]?.id;
    $('#similar').hidden = !selectedSegment;
    for (const segment of data.segments) {
      if (asset.kind !== 'video') break;
      const button = element('button', `${segment.start.toFixed(1)}s – ${segment.end.toFixed(1)}s`);
      button.addEventListener('click', () => { player.currentTime = segment.start; selectedSegment = segment.id; $('#caption').textContent = segment.caption || asset.caption || ''; });
      $('#segments').append(button);
    }
  } catch (error) { if (error.name !== 'AbortError') $('#caption').textContent = error.message; }
}
$('#search-form').addEventListener('submit', event => { event.preventDefault(); load(); });
$('#kind').addEventListener('change', () => load());
$('#browse').addEventListener('click', () => { $('#query').value = ''; load(); });
document.querySelectorAll('[data-query]').forEach(button => button.addEventListener('click', () => { $('#query').value = button.dataset.query; load(); }));
$('#more').addEventListener('click', () => load(true));
$('#close').addEventListener('click', () => $('#detail').close());
$('#detail').addEventListener('close', () => { detailController?.abort(); $('#preview').replaceChildren(); });
$('#similar').addEventListener('click', async () => {
  const sid = selectedSegment; $('#detail').close(); activeController?.abort();
  activeController = new AbortController(); const controller = activeController; $('#more').hidden = true;
  $('#status').textContent = 'Finding similar assets…';
  try { const data = await api(`${selectedPrefix}/similar/${sid}`, controller.signal); const rows = data.results || []; rows.forEach(row => { row.apiPrefix = selectedPrefix; }); render(rows); $('#status').textContent = `${rows.length} similar assets`; if (!rows.length) $('#results').append(element('div', 'No similar samples yet. Try another asset.', 'empty')); }
  catch (error) { if (error.name !== 'AbortError') $('#status').textContent = error.message; }
});
api('/api/status').then(data => { $('#engine-state').textContent = data.meaning ? 'Meaning search ready' : 'Keyword search ready · models may still be loading'; }).catch(() => { $('#engine-state').textContent = 'Connection unavailable'; });
load();

async function post(path, body, headers = {}) {
  const response = await fetch(path, {method:'POST', headers:{'X-Upload-Intent':'1', ...headers}, body});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'The request failed. Please try again.');
  return data;
}
async function ensureSession() {
  sessionInfo = await post('/api/private/session');
  $('#session-expiry').textContent = `Your private session expires ${new Date(sessionInfo.expires*1000).toLocaleString()}. Keep this browser's cookies to retain access.`;
  return sessionInfo;
}
async function refreshJobs() {
  try {
    const data = await api('/api/private/jobs');
    $('#upload-jobs').replaceChildren();
    for (const file of data.files) {
      const message = file.status === 'failed' ? 'Could not process this file. Check its format, duration and size.' : file.status;
      $('#upload-jobs').append(element('li', `${file.folder} / ${file.name} — ${message}`));
    }
    if (data.files.some(file => ['receiving','queued','processing'].includes(file.status))) {
      clearTimeout(jobsTimer); jobsTimer = setTimeout(refreshJobs, 5000);
    } else {
      const ready = data.files.filter(file => file.status === 'ready').length;
      const failed = data.files.filter(file => file.status === 'failed').length;
      $('#upload-message').textContent = `${ready} file(s) ready${failed ? `; ${failed} could not be processed` : ''}.`;
      if ($('#library-scope').value === 'private') await load();
    }
  } catch (error) { $('#upload-message').textContent = error.message; }
}
$('#library-scope').addEventListener('change', async () => {
  await load();
  if ($('#library-scope').value === 'private') refreshJobs();
});
$('#upload-form').addEventListener('submit', async event => {
  event.preventDefault();
  const files = [...$('#upload-files').files];
  if (files.some(file => file.size > 50*1024*1024)) { $('#upload-message').textContent = 'Each file must be 50 MB or smaller.'; return; }
  $('#upload-button').disabled = true;
  try {
    await ensureSession();
    let accepted = 0;
    for (const file of files) {
      $('#upload-message').textContent = `Uploading ${file.name} (${accepted+1}/${files.length})…`;
      await post(`/api/private/upload?folder=${encodeURIComponent($('#upload-folder').value.trim())}`, file,
                 {'Content-Type':'application/octet-stream','X-File-Name':encodeURIComponent(file.name)});
      accepted++;
    }
    $('#upload-message').textContent = `${accepted} file(s) queued. Processing may take a few minutes.`;
    $('#library-scope').value = 'private'; $('#upload-files').value = ''; await load();
  } catch (error) { $('#upload-message').textContent = error.message; }
  finally { $('#upload-button').disabled = false; refreshJobs(); }
});
$('#web-form').addEventListener('submit', async event => {
  event.preventDefault(); const button = $('#web-form button'); button.disabled = true;
  $('#web-status').textContent = 'Searching…'; $('#web-results').replaceChildren();
  try {
    await ensureSession();
    const data = await post('/api/cloud/search', JSON.stringify({query:$('#web-query').value.trim()}), {'Content-Type':'application/json'});
    for (const result of data.results) {
      const article = element('article');
      let url;
      try { url = new URL(result.url); } catch { continue; }
      if (!['http:','https:'].includes(url.protocol)) continue;
      const link = element('a', result.title || url.hostname); link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer';
      article.append(link, element('p', result.snippet)); $('#web-results').append(article);
    }
    $('#web-status').textContent = `${data.results.length} web results`;
  } catch (error) { $('#web-status').textContent = error.message; }
  finally { button.disabled = false; }
});
