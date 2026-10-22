const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const desk = window.caaDesktop || null;
const FPS = 25;
const VIDEO_OK = [".mp4", ".webm", ".m4v", ".mov"];
const IMAGE_OK = [".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif"];
const AUDIO_OK = [".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".opus"];
const KINDS = ["video", "image", "audio", "template"];
const KIND_LABEL = { video: "Videos", image: "Images", audio: "Sounds", template: "Templates" };
const KIND_ONE = { video: "Video", image: "Image", audio: "Sound", template: "Template" };
const TOP_CHOICES = [5, 10, 20, 50];
const DETAIL_LABELS = [["subjects", "Subjects"], ["setting", "Setting"], ["actions", "Action"], ["shot_type", "Shot"], ["camera_motion", "Camera"], ["mood", "Mood"], ["colors", "Colours"], ["on_screen_text", "Text on screen"], ["background", "Background"], ["kind", "Type"], ["energy", "Energy"], ["instruments", "Instruments"], ["good_for", "Good for"]];
const EXAMPLES = ["punchy whoosh", "trees in the wind", "green screen fire", "calm music", "clips from last week"];
const GENERIC = new Set(["video", "clip", "footage", "b-roll", "landscape", "horizontal", "image", "photo", "still", "audio", "sound", "short", "one-shot", "sfx", "hd", "4k", "portrait", "vertical", "square", "9:16", "template", "tall", "loud", "quiet", "soft", "dark", "bright", "low", "texture", "noisy", "tonal", "long", "music", "keyable", "chroma key"]);

const ICON = {
  close: '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg>',
  folder: '<svg viewBox="0 0 24 24"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>',
  drive: '<svg viewBox="0 0 24 24"><path d="M8 4h8l5 9-4 7H7l-4-7z"/><path d="M8 4l9 16M16 4 7 20M3 13h18"/></svg>',
  inbox: '<svg viewBox="0 0 24 24"><path d="M3 13l3-8h12l3 8v6H3z"/><path d="M3 13h5l1 3h6l1-3h5"/></svg>',
  left: '<svg viewBox="0 0 24 24"><path d="M15 5l-7 7 7 7"/></svg>',
  right: '<svg viewBox="0 0 24 24"><path d="M9 5l7 7-7 7"/></svg>',
};

const state = {
  view: "home",
  kind: null,
  q: "",
  tab: "all",
  gs: false,
  plan: null,
  groups: {},
  cards: [],
  selected: null,
  detail: null,
  folders: [],
  status: null,
  lastIndexed: -1,
  seq: 0,
  feat: { items: [], i: 0, intro: "" },
  topN: 10,
  results: [],
  similar: null,
  webCache: {},
  lic: null,
  licFilter: "all",
  broll: { topic: "", script: "", seconds: 60, research: true, data: null, loading: false },
};
const webStore = [];
const KIND_WORD = { video: "videos", image: "photos", audio: "sounds", template: "templates" };
const PLAN_LENGTHS = [[30, "30 s short"], [60, "1 min"], [180, "3 min"], [600, "10 min"]];

async function api(path, opts = {}) {
  const init = { ...opts, headers: { "Content-Type": "application/json", ...(opts.headers || {}) } };
  if (init.body && typeof init.body !== "string") init.body = JSON.stringify(init.body);
  const r = await fetch(path, init);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `${r.status} ${r.statusText}`);
  return data;
}

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const ext = (n) => { const i = n.lastIndexOf("."); return i >= 0 ? n.slice(i).toLowerCase() : ""; };

function tc(sec, fps = FPS) {
  const total = Math.round(Math.max(0, Number(sec) || 0) * fps);
  const parts = [Math.floor(total / fps / 3600), Math.floor(total / fps / 60) % 60, Math.floor(total / fps) % 60, total % fps];
  return parts.map((n) => String(n).padStart(2, "0")).join(":");
}

function clock(sec) {
  const t = Math.max(0, Number(sec) || 0);
  if (t < 10) return `${t.toFixed(1)} s`;
  return `${Math.floor(t / 60)}:${String(Math.round(t % 60)).padStart(2, "0")}`;
}

function toast(msg) {
  const el = $("#toast");
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => (el.hidden = true), 2600);
}

function pillText(r, hit) {
  if (hit?.jump) return `at ${clock(hit.start)}`;
  if (r.kind === "video" && hit && hit.end > hit.start) return clock(hit.end - hit.start);
  if ((r.kind === "video" || r.kind === "audio") && r.duration) return clock(r.duration);
  return "";
}

function cardHTML(r, opts = {}) {
  const i = state.cards.push(r) - 1;
  const hit = r.hits?.[0];
  const flags = [];
  if (r.green_screen) flags.push('<span class="flag key">Keyable</span>');
  if (r.has_alpha) flags.push('<span class="flag alpha">Alpha</span>');
  const pill = pillText(r, hit);
  const contain = r.kind === "image" && r.has_alpha ? "contain" : "";
  const img = r.thumb ? `<img src="${r.thumb}" alt="" loading="lazy">` : `<span class="ext">${esc(ext(r.name) || "no preview")}</span>`;
  const sub = hit?.caption || r.caption || (r.tags || []).filter((t) => !GENERIC.has(t)).slice(0, 5).join(", ") || "Described from file name only";
  const meta = [];
  if (opts.kind) meta.push(KIND_ONE[r.kind] || r.kind);
  if (hit?.jump) meta.push(`Jumps to ${tc(hit.start)}`);
  else if (r.kind === "video" && hit && hit.start > 0.5) meta.push(`Shot at ${tc(hit.start)}`);
  if (r.captured_at && r.captured_src && r.captured_src !== "file date") meta.push(fmtWhen(r.captured_at));
  if (r.kind === "image" && r.width) meta.push(`${r.width}×${r.height}`);
  if (r.kind === "template") meta.push(ext(r.name).slice(1).toUpperCase());
  return `<article class="card" role="button" tabindex="0" data-i="${i}" aria-label="${esc(r.name)}">
    <div class="thumb brackets ${r.kind === "audio" ? "audio" : ""} ${contain}">${img}<div class="flags">${flags.join("")}</div>${pill ? `<span class="pill">${pill}</span>` : ""}</div>
    <div class="card-title" title="${esc(r.path)}">${opts.rank ? `<b class="rank">${String(opts.rank).padStart(2, "0")}</b>` : ""}${esc(r.name)}</div>
    <p class="card-sub">${esc(sub)}</p>
    ${meta.length ? `<div class="card-meta">${meta.map((m) => `<span>${esc(m)}</span>`).join("")}</div>` : ""}
  </article>`;
}

function wireCards(root = $("#view")) {
  $$(".card", root).forEach((card) => {
    const i = Number(card.dataset.i);
    card.addEventListener("click", () => openAsset(i));
    card.addEventListener("keydown", (e) => { if (e.key === "Enter") openAsset(i); });
  });
}

function sectionHTML(title, items, { count = null, more = null, limit = 8, four = false } = {}) {
  if (!items.length) return "";
  return `<section class="section">
    <div class="section-head"><h2>${esc(title)}</h2>${count != null ? `<span class="count">${count}</span>` : ""}${more ? `<button class="link" data-more="${esc(more)}">View all</button>` : ""}</div>
    <div class="row${four ? " four" : ""}">${items.slice(0, limit).map((r) => cardHTML(r)).join("")}</div>
  </section>`;
}

function wireMore(root = $("#view")) {
  $$("[data-more]", root).forEach((b) => b.addEventListener("click", () => {
    const [mode, kind] = b.dataset.more.split(":");
    if (mode === "kind") go("kind", kind);
    else { state.tab = kind; runSearch(); }
  }));
}

function setNav() {
  $$(".nav-item[data-view]").forEach((b) => {
    const on = b.dataset.view === state.view && (state.view !== "kind" || b.dataset.kind === state.kind);
    if (on) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
  });
}

function go(view, kind = null) {
  state.view = view;
  state.kind = kind;
  if (view !== "search") {
    state.q = "";
    $("#q").value = "";
    state.tab = "all";
  }
  setNav();
  render();
  $("#view").scrollTop = 0;
}

function render() {
  state.cards = [];
  if (state.view === "home") return renderHome();
  if (state.view === "kind") return renderKind();
  if (state.view === "search") return renderSearch();
  if (state.view === "settings") return renderSettings();
  if (state.view === "plan") return renderPlan();
  if (state.view === "licences") return renderLicences();
}

async function copyText(text, msg = "Copied") {
  try {
    await navigator.clipboard.writeText(text);
  } catch (_) {
    const t = document.createElement("textarea");
    t.value = text;
    document.body.appendChild(t);
    t.select();
    document.execCommand("copy");
    t.remove();
  }
  toast(msg);
}

function licBadges(lic) {
  if (!lic) return '<span class="lic none">Not checked</span>';
  const out = [];
  if (lic.commercial_ok === false) out.push('<span class="lic bad">Not for commercial use</span>');
  else if (lic.commercial_ok === true && lic.attribution_required === false) out.push('<span class="lic ok">Free to use, no credit</span>');
  else if (lic.commercial_ok === true) out.push('<span class="lic ok">Free to use</span>');
  if (lic.attribution_required === true) out.push('<span class="lic warn">Credit needed</span>');
  if (lic.commercial_ok == null) out.push('<span class="lic check">Check the item</span>');
  if (lic.status === "not_found" || lic.status === "unverified") out.push('<span class="lic check">Not verified</span>');
  return out.join("");
}

function webOffHTML() {
  const tv = state.status?.tavily || {};
  return `<p class="web-note">${esc(tv.why_off || "Web search is off.")} <button class="inline-link" data-goto="settings">Open settings</button></p>`;
}

function webCardHTML(it) {
  const i = webStore.push(it) - 1;
  const img = it.thumb ? `<img class="web-img" src="${esc(it.thumb)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : "";
  return `<article class="card web-card">
    <a class="thumb brackets ${it.kind === "audio" ? "audio" : ""}" href="${esc(it.url)}" target="_blank" rel="noopener" title="Open on ${esc(it.site_name)}">${img}<span class="ext">${esc(it.site_name)}</span><span class="pill site">${esc(it.site_name)}</span></a>
    <div class="card-title" title="${esc(it.url)}">${esc(it.title)}</div>
    <div class="lics">${it.item ? licBadges(it.licence) : ""}</div>
    <div class="web-actions">${it.item ? `<button class="btn btn-primary btn-sm" data-save="${i}">Save to Inbox</button>` : '<span class="muted">A search page, not one item</span>'}<a class="btn btn-ghost btn-sm" href="${esc(it.url)}" target="_blank" rel="noopener">Open page</a></div>
  </article>`;
}

function wireWeb(root) {
  $$("[data-save]", root).forEach((b) => b.addEventListener("click", () => saveWeb(b)));
  $$("img.web-img", root).forEach((img) => img.addEventListener("error", () => img.remove(), { once: true }));
  $$("[data-goto]", root).forEach((b) => b.addEventListener("click", () => go(b.dataset.goto)));
}

function webResultHTML(data, kind) {
  if (data.off) return webOffHTML();
  const where = (data.sites || []).join(", ");
  if (!data.items.length) return `<p class="web-note">No free ${KIND_WORD[kind] || "assets"} found on ${esc(where)}.</p>`;
  return `<p class="web-note">Found on ${esc(where)} through Tavily. The badge shows each site's usual licence; it is read from the item's own page when you save it.</p><div class="row web-row">${data.items.map(webCardHTML).join("")}</div>`;
}

async function fillWeb(slot, q, kind) {
  if (!slot) return;
  const key = `${q}|${kind}`;
  if (state.webCache[key]) {
    slot.innerHTML = webResultHTML(state.webCache[key], kind);
    wireWeb(slot);
    return;
  }
  if (!state.status?.tavily?.enabled) {
    slot.innerHTML = webOffHTML();
    wireWeb(slot);
    return;
  }
  slot.innerHTML = `<p class="web-note"><i class="sq pulse"></i>Looking for free ${KIND_WORD[kind] || "assets"} on Pexels, Pixabay, Mixkit${kind === "audio" ? ", Freesound" : kind === "image" ? ", Unsplash" : ""}…</p>`;
  try {
    const data = await api(`/api/web/search?${new URLSearchParams({ q, kind })}`);
    if (!data.off) state.webCache[key] = data;
    slot.innerHTML = webResultHTML(data, kind);
  } catch (err) {
    slot.innerHTML = `<p class="web-note bad">${esc(err.message)}</p>`;
  }
  wireWeb(slot);
}

async function saveWeb(btn) {
  const it = webStore[Number(btn.dataset.save)];
  if (!it) return;
  btn.disabled = true;
  btn.textContent = "Saving…";
  try {
    const r = await api("/api/web/save", { method: "POST", body: { url: it.url, kind: it.kind } });
    btn.textContent = "Saved";
    btn.classList.replace("btn-primary", "btn-ghost");
    const lic = r.licence || {};
    toast(`Saved ${r.name} to your Inbox (${lic.licence || "licence saved"}). Indexing it now.`);
    refreshStatus(true);
  } catch (err) {
    btn.disabled = false;
    btn.textContent = "Save to Inbox";
    toast(err.message);
  }
}

function webKindFor() {
  if (state.tab !== "all") return state.tab === "template" ? "template" : state.tab;
  const k = state.plan?.kind;
  return k && k !== "any" ? k : "video";
}

async function openById(aid, hit = null) {
  try {
    const d = await api(`/api/assets/${aid}`);
    const seg = (hit && d.segments.find((s) => s.id === hit.segment_id)) || d.segments[0] || null;
    const h = hit || (seg ? { segment_id: seg.id, start: seg.start, end: seg.end, caption: seg.caption, thumb: seg.thumb_url } : null);
    const r = { asset_id: aid, name: d.asset.name, kind: d.asset.kind, thumb: seg?.thumb_url || null, hits: h ? [h] : [] };
    state.detail = { ...d, result: r, hit: h };
    renderDrawer();
  } catch (err) {
    toast(err.message);
  }
}

function heroSuggestions(rows) {
  const counts = new Map();
  for (const k of KINDS) for (const r of rows[k] || []) for (const t of r.tags || []) if (!GENERIC.has(t) && t.length > 2) counts.set(t, (counts.get(t) || 0) + 1);
  const top = [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([t]) => t).slice(0, 3);
  return top.length >= 2 ? top : EXAMPLES.slice(0, 3);
}

function marqueeHTML(words) {
  const run = words.map((w) => `<span>${esc(w)}</span>`).join("");
  return `<div class="marquee" aria-hidden="true"><div class="track">${run}${run}</div></div>`;
}

function heroHTML(key, title, words, foot) {
  return `<section class="hero" data-home="${esc(key)}">
    <i class="sq c-tl"></i><i class="sq c-tr"></i><i class="sq c-br"></i>
    <h1 class="sr-only">${esc(title)}</h1>
    ${marqueeHTML(words)}
    <div class="hero-foot"><i class="sq"></i>${foot.map((f) => `<span class="label">${esc(f)}</span>`).join("")}</div>
  </section>`;
}

function featuredItems(data) {
  const seen = new Set();
  const out = [];
  for (const r of [data.hero, ...(data.rows.video || []), ...(data.rows.image || [])]) {
    const sid = r?.hits?.[0]?.segment_id;
    if (!r || !sid || !r.thumb || seen.has(r.asset_id)) continue;
    seen.add(r.asset_id);
    out.push({ ...r, poster: r.poster || `/api/poster/${sid}` });
  }
  return out.slice(0, 8);
}

function stageHTML() {
  const { items, i } = state.feat;
  if (!items.length) return `<div class="hg-cell hg-stage brackets"><div class="stage-empty">Frames from your videos and photos show up here once they are indexed.</div></div>`;
  const r = items[i];
  return `<button class="hg-cell hg-stage brackets" id="stage" aria-label="Open ${esc(r.name)}"><img src="${r.poster}" alt=""><span class="stage-cap"><span>${esc(r.name)}</span><b>Open</b></span></button>`;
}

function sideHTML() {
  const { items, i } = state.feat;
  const n = items.length;
  const next = n > 1 ? items[(i + 1) % n] : null;
  const tile = next
    ? `<button class="tile brackets" id="tileNext" aria-label="Show ${esc(next.name)}"><img src="${next.thumb}" alt=""></button><div class="side-note" title="${esc(next.name)}">Next: ${esc(next.name)}</div>`
    : `<div class="tile brackets"></div><div class="side-note">${n ? "Add more footage to browse here" : ""}</div>`;
  return `<div class="hg-cell hg-side">${tile}
    <div class="side-foot"><span class="label">Featured ${n ? `${i + 1}/${n}` : "0/0"}</span><button class="arrow" id="featPrev" aria-label="Previous" ${n > 1 ? "" : "disabled"}>${ICON.left}</button><button class="arrow" id="featNext" aria-label="Next" ${n > 1 ? "" : "disabled"}>${ICON.right}</button></div>
  </div>`;
}

function renderHeroGrid() {
  const grid = $("#heroGrid");
  if (!grid) return;
  grid.innerHTML = state.feat.intro + stageHTML() + sideHTML();
  $$("[data-q]", grid).forEach((b) => b.addEventListener("click", () => searchFor(b.dataset.q)));
  $("#heroSearch")?.addEventListener("click", () => { $("#q").focus(); $("#q").select(); });
  const r = state.feat.items[state.feat.i];
  $("#stage")?.addEventListener("click", () => openAsset(r._i));
  $("#featPrev")?.addEventListener("click", () => moveFeature(-1));
  $("#featNext")?.addEventListener("click", () => moveFeature(1));
  $("#tileNext")?.addEventListener("click", () => moveFeature(1));
}

function moveFeature(d) {
  const n = state.feat.items.length;
  if (n < 2) return;
  state.feat.i = (state.feat.i + d + n) % n;
  renderHeroGrid();
}

async function renderHome() {
  const view = $("#view");
  if (!state.folders.length) return renderOnboarding();
  let data;
  try {
    data = await api("/api/home?limit=8");
  } catch (err) {
    view.innerHTML = `<div class="empty"><h1>The engine is not responding</h1><p>${esc(err.message)}</p></div>`;
    return;
  }
  if (state.view !== "home") return;
  state.cards = [];
  const lib = data.library;
  const sug = heroSuggestions(data.rows);
  const busy = state.status && state.status.indexer.state !== "idle";
  const nf = state.folders.length;
  const heroText = lib.indexed
    ? `${lib.indexed} assets across ${nf} folder${nf === 1 ? "" : "s"}. Describe a shot, a sound or a template and it comes up at the exact second.`
    : busy ? "Building your index. Search works as soon as the first files are done." : "No assets indexed yet. Add a folder with footage, sounds or templates.";
  const items = featuredItems(data);
  const keep = state.feat.items[state.feat.i]?.asset_id;
  items.forEach((r) => (r._i = state.cards.push(r) - 1));
  const at = items.findIndex((r) => r.asset_id === keep);
  state.feat = {
    items,
    i: at >= 0 ? at : 0,
    intro: `<div class="hg-cell hg-intro"><p class="lead">${esc(heroText)}</p><div><button class="btn btn-primary" id="heroSearch">Search your library</button></div><div class="chips">${sug.map((x) => `<button class="chip" data-q="${esc(x)}">${esc(x)}</button>`).join("")}</div></div>`,
  };
  if (!$('#view > .hero[data-home="library"]')) {
    view.innerHTML = `${heroHTML("library", "Find any shot by describing it", ["Find any shot", "Any sound", "Any template", "Any moment"], ["Describe it", "Find it", "Use it"])}<div id="homeBody"></div>`;
  }
  $("#homeBody").innerHTML = `<section class="hero-grid" id="heroGrid"></section>
    <section class="strip">${KINDS.map((k) => `<button data-kind="${k}"><b>${lib.kinds[k] || 0}</b><span>${KIND_LABEL[k]}</span></button>`).join("")}</section>
    ${sectionHTML("Recent videos", data.rows.video, { count: lib.kinds.video || 0, more: "kind:video", limit: 4, four: true })}
    ${sectionHTML("Sounds", data.rows.audio, { count: lib.kinds.audio || 0, more: "kind:audio", limit: 4, four: true })}
    ${sectionHTML("Images", data.rows.image, { count: lib.kinds.image || 0, more: "kind:image", limit: 4, four: true })}
    ${sectionHTML("Templates", data.rows.template, { count: lib.kinds.template || 0, more: "kind:template", limit: 4, four: true })}`;
  renderHeroGrid();
  $$(".strip [data-kind]").forEach((b) => b.addEventListener("click", () => go("kind", b.dataset.kind)));
  wireCards($("#homeBody"));
  wireMore();
}

function renderOnboarding() {
  $("#view").innerHTML = `${heroHTML("onboarding", "Point me at your assets", ["Point me at your assets", "Footage", "Sounds", "Templates"], ["Private", "Local first"])}
    <section class="hero-grid">
      <div class="hg-cell hg-intro"><p class="lead">Add the folders where you keep footage, photos, music, sound effects and templates, including your Google Drive for desktop folder. Files stay where they are; the index stays on this computer.</p><div><button class="btn btn-primary" id="heroAdd">Add folder</button></div></div>
      <div class="hg-cell hg-stage brackets"><div class="stage-empty"><div class="stage-steps"><div><b>1</b>Add a folder</div><div><b>2</b>It indexes in the background</div><div><b>3</b>Describe what you need</div></div></div></div>
      <div class="hg-cell hg-side"><div class="tile brackets"></div><div class="side-note">Nothing indexed yet</div><div class="side-foot"><span class="label">Featured 0/0</span><button class="arrow" disabled aria-label="Previous">${ICON.left}</button><button class="arrow" disabled aria-label="Next">${ICON.right}</button></div></div>
    </section>`;
  $("#heroAdd").addEventListener("click", addFolderFlow);
}

async function renderKind() {
  const kind = state.kind;
  const view = $("#view");
  const total = state.status?.library?.kinds?.[kind] || 0;
  const params = new URLSearchParams({ kind, limit: "240", status: "indexed" });
  try {
    const data = await api(`/api/assets?${params}`);
    if (state.view !== "kind" || state.kind !== kind) return;
    state.cards = [];
    let rows = data.results;
    if (state.gs) rows = rows.filter((r) => r.green_screen);
    const toggle = kind === "video" || kind === "image" ? `<label class="tab-toggle"><input type="checkbox" id="gsKind" ${state.gs ? "checked" : ""}>Green screen only</label>` : "";
    view.innerHTML = `<div class="view-head"><h1>${KIND_LABEL[kind]}</h1><span class="count">${total} indexed</span>${toggle}</div>
      ${rows.length ? `<div class="row">${rows.map((r) => cardHTML(r)).join("")}</div>` : `<div class="empty"><h1>No ${KIND_LABEL[kind].toLowerCase()} yet</h1><p>Add a folder that contains ${KIND_LABEL[kind].toLowerCase()}, or wait for indexing to finish.</p></div>`}`;
    const gs = $("#gsKind");
    if (gs) gs.addEventListener("change", (e) => { state.gs = e.target.checked; renderKind(); });
    wireCards();
  } catch (err) {
    toast(err.message);
  }
}

function describePlan(plan, data) {
  if (!plan) return "";
  const hard = [];
  if (plan.kind && plan.kind !== "any") hard.push(plan.audio_kind === "sfx" ? "sound effects" : plan.audio_kind === "music" ? "music" : KIND_LABEL[plan.kind]?.toLowerCase());
  if (plan.max_duration) hard.push(`under ${plan.max_duration} s`);
  if (plan.min_duration) hard.push(`over ${plan.min_duration} s`);
  if (plan.orientation) hard.push(plan.orientation);
  if (plan.green_screen) hard.push("keyable footage");
  const pw = plan.when;
  const when = pw ? (pw.note ? `<b>${esc(pw.note)}</b>` : `Recorded <b>${esc(pw.label)}</b>`) : "";
  const alt = pw?.alt && pw.alt_hits ? ` <button class="inline-link" data-alt="${esc(pw.alt.query)}">Did you mean ${esc(pw.alt.date_label)}? ${pw.alt_hits} file${pw.alt_hits === 1 ? "" : "s"}</button>` : "";
  const ch = data.channels || {};
  const by = [ch.meaning ? "meaning" : "", ch.text ? "keywords" : "", ch.visual ? "look" : ""].filter(Boolean);
  const kw = (plan.keywords || []).slice(0, 6).join(", ");
  const how = plan.source === "nemotron" && kw
    ? `Nemotron expanded this to <b>${esc(kw)}</b>`
    : by.length ? `Matched on this computer by <b>${by.join(", ").replace(/, ([^,]*)$/, " and $1")}</b>` : "";
  const parts = [when, how].filter(Boolean).join(". ");
  return `${parts}${hard.length ? `. Only ${esc(hard.join(", "))}` : ""}. <span>${data.took_ms} ms</span>${alt}`;
}

function fmtWhen(ts) {
  return new Date(ts * 1000).toLocaleString(undefined, { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" });
}

function searchFor(text) {
  $("#q").value = text;
  state.tab = "all";
  runSearch();
}

let searchTimer = null;
async function runSearch() {
  const q = $("#q").value.trim();
  if (!q) {
    if (state.view === "search") go("home");
    return;
  }
  const seq = ++state.seq;
  state.q = q;
  state.similar = null;
  state.view = "search";
  setNav();
  const params = new URLSearchParams({ q, limit: String(state.topN) });
  if (state.tab !== "all") params.set("kind", state.tab);
  if (state.gs) params.set("gs", "1");
  try {
    const data = await api(`/api/search?${params}`);
    if (seq !== state.seq) return;
    state.plan = data.plan;
    state.results = data.results.slice(0, state.topN);
    state.took = data.took_ms;
    state.lastData = data;
    renderSearch(data);
  } catch (err) {
    toast(`Search failed: ${err.message}`);
  }
}

function topHTML() {
  return `<div class="topn" role="group" aria-label="How many results to show"><span>Show top</span>${TOP_CHOICES.map((c) => `<button data-top="${c}" aria-pressed="${state.topN === c}">${c}</button>`).join("")}</div>`;
}

async function setTopN(n) {
  state.topN = n;
  api("/api/settings", { method: "POST", body: { top_results: n } }).catch(() => {});
  if (state.view === "settings") return renderSettings();
  if (state.similar) return findSimilar(state.similar.sid, state.similar.name);
  runSearch();
}

function renderSearch(data = state.lastData || { took_ms: state.took || 0 }) {
  const view = $("#view");
  state.cards = [];
  const results = state.results || [];
  const n = results.length;
  const sim = state.similar;
  const tabs = sim ? "" : ["all", ...KINDS].map((k) => `<button class="tab" role="tab" data-tab="${k}" aria-selected="${state.tab === k}">${k === "all" ? "All" : KIND_LABEL[k]}${state.tab === k ? `<span class="n">${n}</span>` : ""}</button>`).join("");
  const gsToggle = sim ? "" : `<label class="tab-toggle"><input type="checkbox" id="gsSearch" ${state.gs ? "checked" : ""}>Green screen only</label>`;
  const head = sim ? "Looks like" : data.fallback && n ? "No exact match for" : n < state.topN ? `${n} match${n === 1 ? "" : "es"} for` : `Top ${state.topN} for`;
  const plan = sim ? `The ${n} closest matches by look and meaning, best first. Worked out on this computer.` : describePlan(state.plan, data);
  const body = n
    ? `<div class="row">${results.map((r, i) => cardHTML(r, { rank: i + 1, kind: state.tab === "all" })).join("")}</div>`
    : `<div class="empty"><h1>Nothing matches “${esc(state.q)}”</h1><p>Try fewer or broader words, or turn off Green screen only.</p><div class="suggest">${EXAMPLES.map((x) => `<button class="chip">${esc(x)}</button>`).join("")}</div></div>`;
  const wk = webKindFor();
  const tv = state.status?.tavily || {};
  const cached = state.webCache[`${state.q}|${wk}`];
  const web = sim ? "" : `<section class="section web-sec"><div class="section-head"><h2>Free on the web</h2><span class="count">${esc(KIND_WORD[wk] || "assets")} you can use</span>${!n || cached || !tv.enabled ? "" : `<button class="link" id="webGo">Look for free ${esc(KIND_WORD[wk])}</button>`}</div><div class="web-slot" id="webSlot">${!n || cached ? "" : tv.enabled ? `<p class="web-note">Missing a shot? Search Pexels, Pixabay and Mixkit for free ${esc(KIND_WORD[wk])} with one Tavily request.</p>` : webOffHTML()}</div></section>`;
  view.innerHTML = `<div class="q-head"><span class="label"><i class="sq"></i>${head}</span><h1 class="q-text">“${esc(sim ? sim.name : state.q)}”</h1><p class="plan">${plan}</p></div>
    <div class="tabs" role="tablist">${tabs}<div class="tabs-right">${topHTML()}${gsToggle}</div></div>
    ${body}${web}`;
  if (!sim && (!n || cached)) fillWeb($("#webSlot"), state.q, wk);
  else wireWeb(view);
  $("#webGo")?.addEventListener("click", (e) => { e.currentTarget.remove(); fillWeb($("#webSlot"), state.q, wk); });
  $$(".tab", view).forEach((t) => t.addEventListener("click", () => { state.tab = t.dataset.tab; runSearch(); }));
  $$("[data-top]", view).forEach((b) => b.addEventListener("click", () => setTopN(Number(b.dataset.top))));
  $("#gsSearch")?.addEventListener("change", (e) => { state.gs = e.target.checked; runSearch(); });
  $$(".suggest button", view).forEach((b) => b.addEventListener("click", () => searchFor(b.textContent)));
  $$("[data-alt]", view).forEach((b) => b.addEventListener("click", () => searchFor(b.dataset.alt)));
  wireCards();
}

const ROLE_LABELS = [["vision", "Shots and images"], ["omni", "Sounds (audio input)"], ["fast", "Fast text (search expansion, sounds)"], ["agent", "Agent"], ["reasoning", "B-roll planning"]];
const DATE_ORDERS = [["auto", "Windows setting"], ["DMY", "Day first: 6/9/26 = 6 Sep"], ["MDY", "Month first: 6/9/26 = 9 Jun"], ["YMD", "Year first: 26/9/6"]];

function keyField(name, id, label, help, extra = "") {
  const info = state.cfg?.secrets?.[name] || {};
  const where = info.source === "app" ? "Saved securely on this computer (system keychain)" : info.source === "environment" ? "Read from an environment variable or .env file" : "Not set";
  return `<div class="field"><label for="${id}">${label}</label>
    <div class="field-row"><input class="input" type="password" id="${id}" autocomplete="off" spellcheck="false" placeholder="${info.set ? `Saved (${esc(info.hint)}). Type a new key to replace it` : "Paste your key"}">${extra}${info.source === "app" ? `<button type="button" class="btn btn-ghost btn-sm" data-clear="${name}">Remove</button>` : ""}</div>
    <span class="field-note">${where}. ${help}</span></div>`;
}

function keysPanel() {
  const cfg = state.cfg || {};
  const models = cfg.models || {};
  const overrides = cfg.env_overrides || [];
  return `<section class="panel">
    <h2>Keys &amp; connections</h2>
    <p>Your own API keys and connection settings. Keys are stored in the system keychain and never shown again in full. Environment variables and .env files still work; keys saved here take priority.</p>
    <form class="keys" id="keysForm" autocomplete="off">
      ${keyField("NEBIUS_API_KEY", "kNebius", "Nebius Token Factory API key", "Used to describe new files with Nemotron.", '<button type="button" class="btn btn-ghost btn-sm" id="testKey">Test</button>')}
      <span class="field-note" id="testNote" hidden></span>
      ${keyField("TAVILY_API_KEY", "kTavily", "Tavily API key", "Finds free stock on the web, reads the licence of downloaded files and researches b-roll plans. Used only when you ask.")}
      <div class="field"><label for="kInbox">Inbox folder</label><input class="input" id="kInbox" value="${esc(cfg.inbox_dir || "")}" spellcheck="false"><span class="field-note">Free assets you save from the web go here with their licence. The folder is added to your library on the first save.</span></div>
      <div class="field"><label for="kUrl">Token Factory URL</label><input class="input" id="kUrl" value="${esc(cfg.tokenfactory_base_url || "")}" spellcheck="false"><span class="field-note">OpenAI-compatible endpoint. Leave empty for the default.</span></div>
      <div class="field"><label for="kDate">Date order in searches</label><select class="input" id="kDate">${DATE_ORDERS.map(([v, l]) => `<option value="${v}" ${(cfg.date_order || "auto") === v ? "selected" : ""}>${l}</option>`).join("")}</select><span class="field-note">How a date like 6/9/26 is read. Either-way dates are still checked both ways.</span></div>
      <div class="field"><label for="kFfmpeg">FFmpeg folder</label><input class="input" id="kFfmpeg" value="${esc(cfg.ffmpeg_dir || "")}" placeholder="Found automatically" spellcheck="false"><span class="field-note">${cfg.ffmpeg_path ? `Using ${esc(cfg.ffmpeg_path)}` : '<span class="bad">FFmpeg not found</span>'}. Set a folder containing ffmpeg.exe and ffprobe.exe to override.</span></div>
      <div class="field"><label>Nemotron models</label><div class="model-grid">${ROLE_LABELS.map(([k, l]) => `<label class="model-field"><span>${l}</span><input class="input" data-role="${k}" value="${esc(models[k] || "")}" list="modelList" spellcheck="false" placeholder="none"></label>`).join("")}</div><datalist id="modelList"></datalist><span class="field-note">Model IDs on your Token Factory account. Test the key to load the list.</span></div>
      <div class="field"><label>Data folder</label><span class="field-static">${esc(cfg.home || "")}</span>${overrides.length ? `<span class="field-note">Set by environment variables, which take priority: ${esc(overrides.join(", "))}</span>` : ""}</div>
      <div class="field-actions"><button class="btn btn-primary" type="submit">Save</button></div>
    </form>
  </section>`;
}

async function saveKeys(extra = {}) {
  const body = { tokenfactory_base_url: $("#kUrl").value.trim(), date_order: $("#kDate").value, ffmpeg_dir: $("#kFfmpeg").value.trim(), inbox_dir: $("#kInbox").value.trim(), models: {}, ...extra };
  if ($("#kNebius").value.trim()) body.nebius_api_key = $("#kNebius").value.trim();
  if ($("#kTavily").value.trim()) body.tavily_api_key = $("#kTavily").value.trim();
  $$("[data-role]").forEach((i) => (body.models[i.dataset.role] = i.value.trim()));
  state.cfg = await api("/api/settings", { method: "POST", body });
  return state.cfg;
}

function wireKeys() {
  $("#keysForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await saveKeys();
      toast("Saved");
      await refreshStatus(true);
      renderSettings();
    } catch (err) {
      toast(err.message);
    }
  });
  $$("[data-clear]").forEach((b) => b.addEventListener("click", async () => {
    try {
      state.cfg = await api("/api/settings", { method: "POST", body: { [b.dataset.clear.toLowerCase()]: "" } });
      toast("Key removed");
      await refreshStatus(true);
      renderSettings();
    } catch (err) {
      toast(err.message);
    }
  }));
  $("#testKey").addEventListener("click", async () => {
    const note = $("#testNote");
    note.hidden = false;
    note.textContent = "Checking…";
    try {
      if ($("#kNebius").value.trim() || $("#kUrl").value.trim() !== (state.cfg?.tokenfactory_base_url || "")) await saveKeys();
      const r = await api("/api/models");
      if (r.error) {
        note.innerHTML = `<span class="bad">${/not set/i.test(r.error) ? "Paste your Nebius API key first." : `Could not connect: ${esc(r.error)}`}</span>`;
        return;
      }
      $("#modelList").innerHTML = (r.available || []).map((m) => `<option value="${esc(m)}">`).join("");
      const nv = (r.available || []).filter((m) => /nemotron/i.test(m)).length;
      note.innerHTML = `<span class="ok">Connected.</span> ${(r.available || []).length} models on your account, ${nv} Nemotron. Pick models below or keep the defaults.`;
      refreshStatus(true);
    } catch (err) {
      note.innerHTML = `<span class="bad">${esc(err.message)}</span>`;
    }
  });
}

async function renderSettings() {
  try {
    state.cfg = await api("/api/settings");
  } catch (_) {}
  const st = state.status || (await refreshStatus(true));
  if (state.view !== "settings") return;
  const n = st?.nemotron || {};
  const models = n.models || {};
  const folderRows = state.folders.map((f) => `<div class="folder">
      <span class="folder-icon">${f.kind === "drive-desktop" ? ICON.drive : f.kind === "inbox" ? ICON.inbox : ICON.folder}</span>
      <div style="min-width:0"><div class="folder-name">${esc(f.path.split(/[\\/]/).filter(Boolean).pop() || f.path)}</div><div class="folder-path">${esc(f.path)}</div>
      <div class="folder-stats">${f.indexed} of ${f.assets} indexed${f.errors ? `, <span class="bad">${f.errors} failed</span>` : ""}${f.kind === "drive-desktop" ? ", Google Drive" : ""}${f.kind === "inbox" ? ", Inbox for free assets from the web" : ""}</div></div>
      <div class="folder-actions"><button class="btn btn-ghost btn-sm" data-act="rescan" data-id="${f.id}">Rescan</button><button class="btn btn-danger btn-sm" data-act="remove" data-id="${f.id}">Remove</button></div>
    </div>`).join("") || '<p class="folder-stats">No folders yet.</p>';
  const emb = st?.embedder?.state === "ready" ? `<span class="ok">On</span> (${esc(st.embedder.name)})` : st?.embedder?.state === "loading" ? "Loading" : '<span class="bad">Off</span>: no matching by look';
  const sm = st?.semantic || {};
  const sem = sm.state === "ready" ? `<span class="ok">On</span> (${esc(sm.name)}, ${sm.vectors} shots)` : sm.state === "loading" ? "Loading the model" : '<span class="bad">Off</span>: keywords and look only';
  const asr = st?.transcriber?.state === "ready" ? `<span class="ok">On</span> (${esc(st.transcriber.name)})` : esc(st?.transcriber?.state || "off");
  const topRow = `<div class="topn topn-panel" role="group" aria-label="How many results to show"><span>Show top</span>${TOP_CHOICES.map((c) => `<button data-top="${c}" aria-pressed="${state.topN === c}">${c}</button>`).join("")}<span class="topn-note">results, best match first</span></div>`;
  const roleLine = (k, label) => `<dt>${label}</dt><dd>${models[k] ? esc(models[k]) : '<span class="bad">none on your account</span>'}</dd>`;
  $("#view").innerHTML = `<div class="view-head"><h1>Settings</h1><span class="count">Folders and privacy</span></div>
    <div class="settings">
      <section class="panel">
        <h2>Folders</h2>
        <p>New and changed files in these folders are indexed automatically. Removing a folder only removes it from the index.</p>
        <div class="folders">${folderRows}</div>
        <form class="add-row" id="addForm"><input class="input" id="folderPath" placeholder="${desk ? "Leave empty to browse, or paste a path" : "Paste a folder path, e.g. D:\\Footage or G:\\My Drive\\Assets"}" aria-label="Folder path"><button class="btn btn-primary" type="submit">Add folder</button></form>
      </section>
      <section class="panel">
        <h2>Privacy</h2>
        <p>Your files never leave this computer in either mode, and searches run here too.</p>
        <div class="choices">
          <label class="choice"><input type="radio" name="privacy" value="local" ${n.privacy_mode === "local" ? "checked" : ""}><span><b>Local only</b>Nothing leaves this computer. New files are described by local analysis only, so search relies on file names, sound analysis, look and transcripts. Web features are off.</span></label>
          <label class="choice"><input type="radio" name="privacy" value="standard" ${n.privacy_mode !== "local" ? "checked" : ""}><span><b>Standard</b>A few small keyframes per shot go to Nemotron on Nebius Token Factory, once per file, so every shot gets a description. Searches stay on this computer. Search words, file names and b-roll topics go to Tavily only when you use a web feature.</span></label>
        </div>
      </section>
      ${keysPanel()}
      <section class="panel">
        <h2>Search</h2>
        <p>Searches run on this computer: by meaning, keywords and look. How many results to show can also be changed above the results.</p>
        ${topRow}
        <label class="switch"><input type="checkbox" id="nemoSearch" ${state.cfg?.nemotron_search ? "checked" : ""}><span><b>Also ask Nemotron to expand each search</b>Adds about a second and one small API call per search. It is used automatically while meaning search is unavailable.</span></label>
      </section>
      <section class="panel">
        <h2>Engine</h2>
        <p>What is running on this computer and which NVIDIA models your Token Factory account provides.</p>
        <dl class="facts">
          <dt>Meaning search</dt><dd>${sem}</dd>
          <dt>Visual search</dt><dd>${emb}</dd>
          <dt>Speech transcripts</dt><dd>${asr}</dd>
          <dt>Nemotron</dt><dd>${n.enabled ? `<span class="ok">On</span>, ${n.calls || 0} calls this session${n.cached ? `, ${n.cached} answered from cache` : ""}` : n.has_key ? "Off (Local only mode)" : '<span class="bad">No Nebius API key. Add it under Keys &amp; connections</span>'}</dd>
          <dt>Tavily</dt><dd>${st?.tavily?.enabled ? `<span class="ok">On</span>, ${st.tavily.calls || 0} requests this session${st.tavily.cached ? `, ${st.tavily.cached} from cache` : ""}${st.tavily.credits ? `, ${st.tavily.credits} credits` : ""}` : esc(st?.tavily?.why_off || "Off")}</dd>
          <dt>Describing</dt><dd>Up to ${state.cfg?.caption_workers || 8} shots at a time, ${state.cfg?.index_workers || 2} files at a time</dd>
          ${roleLine("vision", "Shots and images")}
          ${roleLine("omni", "Sounds (audio input)")}
          ${roleLine("fast", "Search expansion (optional)")}
          ${roleLine("agent", "Agent")}
          ${roleLine("reasoning", "B-roll planning")}
          ${n.last_error ? `<dt>Last error</dt><dd class="bad">${esc(n.last_error)}</dd>` : ""}
          ${st?.tavily?.last_error ? `<dt>Last Tavily error</dt><dd class="bad">${esc(st.tavily.last_error)}</dd>` : ""}
        </dl>
      </section>
    </div>`;
  $("#addForm").addEventListener("submit", (e) => { e.preventDefault(); addFolder($("#folderPath").value); });
  $$("[data-act]").forEach((b) => b.addEventListener("click", () => folderAction(b.dataset.act, b.dataset.id)));
  $$('input[name="privacy"]').forEach((r) => r.addEventListener("change", () => setPrivacy(r.value)));
  $$("[data-top]", $("#view")).forEach((b) => b.addEventListener("click", () => setTopN(Number(b.dataset.top))));
  wireKeys();
  $("#nemoSearch").addEventListener("change", async (e) => {
    try {
      state.cfg = await api("/api/settings", { method: "POST", body: { nemotron_search: e.target.checked } });
      toast(e.target.checked ? "Searches will also be expanded by Nemotron" : "Searches now stay on this computer");
    } catch (err) {
      toast(err.message);
    }
  });
}

const LIC_FILTERS = [["all", "All"], ["credit", "Credit needed"], ["noncommercial", "Not commercial"], ["check", "Check the item"], ["unchecked", "Not checked"]];

function licMatches(it, f) {
  const l = it.licence;
  if (f === "credit") return !!l?.attribution_required;
  if (f === "noncommercial") return l?.commercial_ok === false;
  if (f === "check") return !!l && l.commercial_ok == null;
  if (f === "unchecked") return !l;
  return true;
}

function creditsText(items) {
  const lines = items.filter((i) => i.licence?.credit && i.licence.attribution_required !== false).map((i) => i.licence.credit);
  const extra = items.filter((i) => i.licence?.credit && i.licence.attribution_required === false).map((i) => i.licence.credit);
  return [...new Set([...lines, ...extra])].join("\n");
}

async function renderLicences() {
  const view = $("#view");
  let data;
  try {
    data = await api("/api/licences");
  } catch (err) {
    return toast(err.message);
  }
  if (state.view !== "licences") return;
  state.lic = data;
  const sm = data.summary;
  const au = data.audit || {};
  const running = au.state === "running";
  const unchecked = data.items.filter((i) => !i.checked).length;
  const tv = state.status?.tavily || {};
  const rows = data.items.filter((i) => licMatches(i, state.licFilter));
  const cell = (n, label, f) => `<button data-lf="${f}" aria-pressed="${state.licFilter === f}"><b>${n}</b><span>${label}</span></button>`;
  const progress = running
    ? `<div class="lic-progress"><span class="st-label"><i class="sq pulse"></i>Checking ${au.done + 1 > au.total ? au.total : au.done + 1} of ${au.total}</span><span class="st-file">${esc(au.current || "")}</span><span class="st-bar"><i style="width:${au.total ? Math.round((au.done / au.total) * 100) : 0}%"></i></span></div>`
    : au.finished_at ? `<p class="web-note">Last check found ${au.found} of ${au.total} source pages${au.error ? `. Last problem: ${esc(au.error)}` : ""}.</p>` : "";
  const rowHTML = (it) => {
    const l = it.licence;
    const src = it.source_url || l?.source_url;
    return `<div class="lic-row">
      <button class="lic-name" data-open="${it.asset_id}" title="${esc(it.path)}"><span class="lic-kind">${esc(KIND_ONE[it.kind] || it.kind)}</span>${esc(it.name)}</button>
      <span class="lic-site">${esc(l?.site_name || (it.site ? it.site[0].toUpperCase() + it.site.slice(1) : ""))}${it.guess ? "?" : ""}</span>
      <div class="lics">${licBadges(l)}${l ? `<span class="lic-name-small">${esc(l.licence)}</span>` : ""}</div>
      <div class="lic-credit">${l?.credit ? esc(l.credit) : l?.note ? `<span class="muted">${esc(l.note)}</span>` : ""}</div>
      <div class="lic-actions">${l?.credit ? `<button class="btn btn-ghost btn-sm" data-copy="${it.asset_id}">Copy</button>` : ""}${src ? `<a class="btn btn-ghost btn-sm" href="${esc(src)}" target="_blank" rel="noopener">Page</a>` : ""}${tv.enabled && l?.method !== "you" ? `<button class="btn btn-ghost btn-sm" data-check="${it.asset_id}">${l ? "Recheck" : "Check"}</button>` : ""}</div>
    </div>`;
  };
  view.innerHTML = `<div class="view-head"><h1>Licences</h1><span class="count">${sm.files} files from free sites</span></div>
    <p class="lede">Files saved from the web, and files whose names show they came from Pexels, Pixabay, Mixkit, Unsplash or Freesound. Tavily finds each file's page and the licence is read from it, so you know what needs a credit before you publish.</p>
    <div class="strip lic-strip">${cell(sm.files, "Files", "all")}${cell(sm.credit_needed, "Credit needed", "credit")}${cell(sm.not_commercial, "Not commercial", "noncommercial")}${cell(sm.unclear, "Check the item", "check")}${cell(sm.files - sm.checked, "Not checked", "unchecked")}</div>
    <div class="tabs"><span class="tab tab-static">${rows.length} shown</span><div class="tabs-right lic-tools">
      <button class="btn btn-ghost btn-sm" id="copyCredits">Copy credits</button>
      ${tv.enabled ? `<button class="btn btn-primary btn-sm" id="checkAll" ${running || !unchecked ? "disabled" : ""}>${running ? "Checking…" : unchecked ? `Check ${unchecked} file${unchecked === 1 ? "" : "s"}` : "All checked"}</button>` : ""}
    </div></div>
    ${!tv.enabled ? `<div class="lic-off">${webOffHTML()}</div>` : ""}
    ${progress ? `<div class="lic-off">${progress}</div>` : ""}
    ${rows.length ? `<div class="lic-list">${rows.map(rowHTML).join("")}</div>` : `<div class="empty"><h1>${sm.files ? "Nothing in this group" : "No files from free sites yet"}</h1><p>${sm.files ? "Pick another group above." : "Save free assets from search results, or add a folder of stock downloads. Files named like pexels-…-5698420.jpg or 123456__user__name.wav are recognised."}</p></div>`}`;
  $$("[data-lf]", view).forEach((b) => b.addEventListener("click", () => { state.licFilter = b.dataset.lf; renderLicences(); }));
  $$("[data-open]", view).forEach((b) => b.addEventListener("click", () => openById(Number(b.dataset.open))));
  $$("[data-copy]", view).forEach((b) => b.addEventListener("click", () => copyText(data.items.find((i) => i.asset_id === Number(b.dataset.copy)).licence.credit, "Credit copied")));
  $$("[data-check]", view).forEach((b) => b.addEventListener("click", async () => {
    b.disabled = true;
    b.textContent = "Checking…";
    try {
      await api("/api/licences/check", { method: "POST", body: { asset_id: Number(b.dataset.check) } });
    } catch (err) {
      toast(err.message);
    }
    renderLicences();
  }));
  wireWeb(view);
  $("#copyCredits").addEventListener("click", () => {
    const text = creditsText(rows);
    if (!text) return toast("No credit lines yet. Check the files first.");
    copyText(text, `Copied ${text.split("\n").length} credit line${text.includes("\n") ? "s" : ""} for your video description`);
  });
  $("#checkAll")?.addEventListener("click", async () => {
    try {
      await api("/api/licences/check", { method: "POST", body: {} });
    } catch (err) {
      return toast(err.message);
    }
    renderLicences();
  });
  if (running) setTimeout(() => state.view === "licences" && renderLicences(), 1200);
}

function matchHTML(m) {
  return `<button class="mini" data-mopen="${m.asset_id}" data-sid="${m.segment_id ?? ""}" data-start="${m.start ?? 0}" data-end="${m.end ?? 0}" title="${esc(m.caption || m.name)}">
    <span class="thumb ${m.kind === "audio" ? "audio" : ""}">${m.thumb ? `<img src="${m.thumb}" alt="" loading="lazy">` : `<span class="ext">${esc(ext(m.name))}</span>`}${m.kind === "video" && m.tc ? `<span class="pill">${esc(m.tc.split("–")[0])}</span>` : ""}</span>
    <span class="mini-name">${esc(m.name)}</span></button>`;
}

function planText(p) {
  const out = [p.title, p.hook ? `Hook: ${p.hook}` : "", ""];
  p.beats.forEach((b, i) => {
    out.push(`${i + 1}. ${b.line || b.shot}${b.seconds ? ` (${b.seconds} s)` : ""}`);
    if (b.shot) out.push(`   Shot: ${b.shot}`);
    out.push(`   Use: ${b.matches.length ? b.matches.map((m) => `${m.name}${m.kind === "video" && m.tc ? ` ${m.tc}` : ""}`).join("; ") : "nothing in the library yet"}`);
  });
  if (p.facts.length) out.push("", "Facts:", ...p.facts.map((f) => `- ${f.fact}${f.source ? ` (${f.source.url})` : ""}`));
  if (p.sources.length) out.push("", "Sources:", ...p.sources.map((s) => `- ${s.title}: ${s.url}`));
  return out.join("\n");
}

function planResultHTML(p) {
  const total = p.beats.length;
  const by = [p.model ? `Planned by ${p.model.split("/").pop()}` : "Split from your text (Nemotron unavailable)", p.researched ? `${p.sources.length} web sources through Tavily` : p.research_error ? `no web research: ${p.research_error}` : "no web research"];
  const beats = p.beats.map((b, i) => `<li class="beat${b.gap ? " gap" : ""}">
      <span class="beat-n">${String(i + 1).padStart(2, "0")}</span>
      <div class="beat-main">
        ${b.line ? `<p class="beat-line">“${esc(b.line)}”</p>` : ""}
        ${b.shot ? `<p class="beat-shot"><b>Shot</b>${esc(b.shot)}</p>` : ""}
        <p class="beat-meta">${b.seconds ? `<span>${b.seconds} s</span>` : ""}<span>Searched “${esc(b.search)}”</span>${b.why ? `<span>${esc(b.why)}</span>` : ""}</p>
        ${b.matches.length ? `<div class="beat-matches">${b.matches.map(matchHTML).join("")}</div>` : `<div class="beat-gap"><span>Nothing in your library for this beat.</span><button class="btn btn-ghost btn-sm" data-bweb="${i}">Find free ${esc(KIND_WORD[b.kind] || "videos")}</button></div><div class="web-slot" id="bw${i}"></div>`}
      </div>
    </li>`).join("");
  const facts = p.facts.length ? `<section class="section"><div class="section-head"><h2>Facts to use</h2><span class="count">from the research</span></div><ul class="plan-facts">${p.facts.map((f) => `<li>${esc(f.fact)}${f.source ? ` <a href="${esc(f.source.url)}" target="_blank" rel="noopener">[${f.source.n}]</a>` : ""}</li>`).join("")}</ul></section>` : "";
  const sources = p.sources.length ? `<section class="section"><div class="section-head"><h2>Sources</h2><span class="count">${p.sources.length} pages</span></div><ol class="plan-sources">${p.sources.map((s) => `<li><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title)}</a><span>${esc(new URL(s.url).hostname.replace(/^www\./, ""))}</span></li>`).join("")}</ol></section>` : "";
  return `<div class="q-head"><span class="label"><i class="sq"></i>B-roll plan</span><h1 class="q-text">${esc(p.title)}</h1>
      ${p.hook ? `<p class="plan">Hook: <b>${esc(p.hook)}</b></p>` : ""}
      <p class="plan"><b>${p.covered} of ${total}</b> beats have footage in your library${p.gaps ? `, ${p.gaps} to fill` : ""}. ${esc(by.join(", "))}. <span>${(p.took_ms / 1000).toFixed(1)} s</span></p></div>
    <div class="tabs"><span class="tab tab-static">${total} beats, about ${Math.round(p.beats.reduce((a, b) => a + (b.seconds || 0), 0))} s</span><div class="tabs-right lic-tools"><button class="btn btn-ghost btn-sm" id="copyPlan">Copy plan</button></div></div>
    <ol class="beats">${beats}</ol>${facts}${sources}`;
}

async function runPlan() {
  const b = state.broll;
  b.topic = $("#pTopic").value.trim();
  b.script = $("#pScript").value.trim();
  b.seconds = Number($("#pLen").value);
  b.research = $("#pResearch")?.checked ?? false;
  if (!b.topic && !b.script) return toast("Type a topic or paste a script");
  b.loading = true;
  b.data = null;
  renderPlan();
  const t0 = Date.now();
  const tick = setInterval(() => { const el = $("#planTimer"); if (el) el.textContent = `${Math.round((Date.now() - t0) / 1000)} s`; }, 500);
  try {
    b.data = await api("/api/broll", { method: "POST", body: { topic: b.topic, script: b.script, seconds: b.seconds, research: b.research } });
  } catch (err) {
    toast(err.message);
  } finally {
    clearInterval(tick);
    b.loading = false;
    if (state.view === "plan") renderPlan();
  }
}

function renderPlan() {
  const view = $("#view");
  const b = state.broll;
  const tv = state.status?.tavily || {};
  const nm = state.status?.nemotron || {};
  const who = nm.enabled ? `Nemotron (${esc((nm.models?.reasoning || "reasoning model").split("/").pop())})` : "a simple split of your script, because Nemotron is off";
  view.innerHTML = `<div class="view-head"><h1>B-roll plan</h1><span class="count">Research, beats, and the shots you already have</span></div>
    <form class="plan-form" id="planForm" autocomplete="off">
      <div class="field"><label for="pTopic">Topic</label><input class="input" id="pTopic" value="${esc(b.topic)}" placeholder="How coffee gets from the farm to your cup"></div>
      <div class="field"><label for="pScript">Script (optional)</label><textarea class="input" id="pScript" rows="4" placeholder="Paste your script or voice-over. Each beat will follow your own lines.">${esc(b.script)}</textarea></div>
      <div class="plan-row">
        <div class="field"><label for="pLen">Length</label><select class="input" id="pLen">${PLAN_LENGTHS.map(([v, l]) => `<option value="${v}" ${b.seconds === v ? "selected" : ""}>${l}</option>`).join("")}</select></div>
        <label class="switch plan-switch"><input type="checkbox" id="pResearch" ${b.research && tv.enabled ? "checked" : ""} ${tv.enabled ? "" : "disabled"}><span><b>Research the topic on the web</b>${tv.enabled ? "One Tavily search. Facts come with their sources." : esc(tv.why_off || "Tavily is off.")}</span></label>
        <button class="btn btn-primary" type="submit" ${b.loading ? "disabled" : ""}>${b.loading ? "Planning…" : "Plan b-roll"}</button>
      </div>
      <p class="web-note">Beats are written by ${who}, then each shot is searched in your library on this computer.</p>
    </form>
    <div id="planOut">${b.loading ? `<p class="web-note plan-wait"><i class="sq pulse"></i>${b.research && tv.enabled ? "Researching with Tavily, then planning" : "Planning"}… <span id="planTimer">0 s</span></p>` : b.data ? planResultHTML(b.data) : ""}</div>`;
  $("#planForm").addEventListener("submit", (e) => { e.preventDefault(); runPlan(); });
  const out = $("#planOut");
  $$("[data-mopen]", out).forEach((m) => m.addEventListener("click", () => {
    const sid = m.dataset.sid ? Number(m.dataset.sid) : null;
    openById(Number(m.dataset.mopen), sid ? { segment_id: sid, start: Number(m.dataset.start), end: Number(m.dataset.end) } : null);
  }));
  $$("[data-bweb]", out).forEach((btn) => btn.addEventListener("click", () => {
    const i = Number(btn.dataset.bweb);
    const beat = b.data.beats[i];
    btn.remove();
    fillWeb($(`#bw${i}`), beat.search, beat.kind === "audio" ? "audio" : beat.kind === "image" ? "image" : "video");
  }));
  $("#copyPlan")?.addEventListener("click", () => copyText(planText(b.data), "Plan copied"));
}

async function folderAction(act, id) {
  try {
    if (act === "rescan") {
      const r = await api(`/api/folders/${id}/rescan`, { method: "POST" });
      toast(r.queued ? `Rescanning: ${r.queued} new or changed files` : "Everything is up to date");
    } else {
      await api(`/api/folders/${id}`, { method: "DELETE" });
      toast("Removed from the library. Your files were not touched.");
    }
    await refreshStatus(true);
    if (state.view === "settings") renderSettings();
  } catch (err) {
    toast(err.message);
  }
}

async function setPrivacy(mode) {
  try {
    await api("/api/settings", { method: "POST", body: { privacy_mode: mode } });
    toast(mode === "local" ? "Local only: nothing leaves this computer" : "Standard: Nemotron describes new files");
    await refreshStatus();
  } catch (err) {
    toast(err.message);
  }
}

async function addFolderFlow() {
  if (desk) {
    const p = await desk.pickFolder();
    if (p) addFolder(p);
    return;
  }
  go("settings");
  setTimeout(() => $("#folderPath")?.focus(), 50);
}

async function addFolder(path) {
  let p = (path || "").trim();
  if (!p && desk) p = ((await desk.pickFolder()) || "").trim();
  if (!p) return toast("Paste a folder path first");
  try {
    const r = await api("/api/folders", { method: "POST", body: { path: p } });
    toast(r.queued ? `Added. Indexing ${r.queued} files.` : "Added. No new files to index.");
    state.lastIndexed = -1;
    await refreshStatus(true);
    if (state.view === "settings") renderSettings();
    else if (state.view === "home") renderHome();
  } catch (err) {
    toast(err.message);
  }
}

async function openAsset(i) {
  const r = state.cards[i];
  if (!r) return;
  $$(".card[aria-selected]").forEach((c) => c.removeAttribute("aria-selected"));
  $(`.card[data-i="${i}"]`)?.setAttribute("aria-selected", "true");
  try {
    const d = await api(`/api/assets/${r.asset_id}`);
    state.detail = { ...d, result: r, hit: r.hits?.[0] || null };
    renderDrawer();
    api("/api/feedback", { method: "POST", body: { action: "preview", asset_id: r.asset_id, segment_id: r.hits?.[0]?.segment_id, query: state.q } }).catch(() => {});
  } catch (err) {
    toast(err.message);
  }
}

function screenHTML(a, r, hit) {
  const e = ext(a.name);
  const src = `/api/media/${a.id}`;
  if (a.kind === "video" && VIDEO_OK.includes(e)) return `<div class="screen"><video id="player" src="${src}" controls playsinline preload="metadata"></video><span class="tc-live" id="liveTc">${tc(hit?.start || 0)}</span></div>`;
  if (a.kind === "image" && IMAGE_OK.includes(e)) return `<div class="screen"><img src="${src}" alt="${esc(a.caption || a.name)}"></div>`;
  if (a.kind === "audio") {
    const wave = r.thumb ? `<img src="${r.thumb}" alt="">` : "";
    const player = AUDIO_OK.includes(e) ? `<audio id="player" src="${src}" controls preload="metadata"></audio>` : "";
    return `<div class="screen audio">${wave}${player}<span class="tc-live" id="liveTc">${tc(0)}</span></div>`;
  }
  return `<div class="screen">${r.thumb ? `<img src="${r.thumb}" alt="">` : `<span class="ext">No preview for ${esc(e)}</span>`}</div>`;
}

function describeHTML(a, seg) {
  const own = seg && seg.caption;
  const text = own ? seg.caption : a.caption;
  const det = own ? seg.details : seg?.details || null;
  const rows = det ? DETAIL_LABELS.filter(([k]) => det[k] && (!Array.isArray(det[k]) || det[k].length)).map(([k, label]) => `<dt>${label}</dt><dd>${esc(Array.isArray(det[k]) ? det[k].join(", ") : det[k])}</dd>`).join("") : "";
  const multi = a.kind === "video" && (state.detail?.segments?.length || 0) > 1;
  const title = own && multi ? `Shot ${seg.idx + 1} at ${tc(seg.start)}` : "Description";
  if (!text && !rows) {
    const why = a.captioned_by ? "Nemotron did not return a description for this file." : "Not described yet. In Standard mode with a Token Factory key, Nemotron describes new files.";
    return `<div class="d-section desc" id="dDesc"><h3>${title}</h3><p class="muted">${why}</p></div>`;
  }
  return `<div class="d-section desc" id="dDesc"><h3>${title}</h3>${text ? `<p class="d-caption">${esc(text)}</p>` : ""}${rows ? `<dl class="d-details">${rows}</dl>` : ""}</div>`;
}

function licenceHTML(a, guess) {
  const lic = a.license && Object.keys(a.license).length ? a.license : null;
  if (lic) {
    const when = lic.checked_at ? new Date(lic.checked_at * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "";
    const how = { "page + nemotron": "read from the page by Nemotron", page: "read from the page", "site default": "the site's usual licence", "file name": "guessed from the file name", you: "set by you" }[lic.method] || lic.method || "";
    const name = lic.terms_url ? `<a href="${esc(lic.terms_url)}" target="_blank" rel="noopener">${esc(lic.licence)}</a>` : esc(lic.licence);
    return `<div class="d-section lic-block"><h3>Licence</h3><div class="lics">${licBadges(lic)}</div>
      <dl class="d-details"><dt>Licence</dt><dd>${name}</dd>
      ${lic.source_url ? `<dt>Source</dt><dd><a href="${esc(lic.source_url)}" target="_blank" rel="noopener">${esc(lic.site_name || "Open page")}</a></dd>` : ""}
      ${lic.credit ? `<dt>Credit</dt><dd>${esc(lic.credit)} <button class="inline-link" id="dCopyCredit">Copy</button></dd>` : ""}
      ${lic.note ? `<dt>Note</dt><dd>${esc(lic.note)}</dd>` : ""}
      <dt>Checked</dt><dd>${esc([how, when].filter(Boolean).join(", "))}</dd></dl>
      ${lic.method !== "you" ? '<div class="actions"><button class="btn btn-ghost btn-sm" id="dRecheck">Check again</button></div>' : ""}</div>`;
  }
  if (guess) {
    return `<div class="d-section lic-block"><h3>Licence</h3><p class="muted">The file name looks like a ${esc(guess.site_name)} download${guess.guess ? " (not certain)" : ""}. Tavily can find its page and read the licence.</p><div class="actions"><button class="btn btn-ghost btn-sm" id="dRecheck">Find the licence</button></div></div>`;
  }
  return "";
}

async function recheckLicence(aid) {
  const b = $("#dRecheck");
  if (b) { b.disabled = true; b.textContent = "Checking…"; }
  try {
    const r = await api("/api/licences/check", { method: "POST", body: { asset_id: aid } });
    if (state.detail?.asset.id === aid) {
      state.detail.asset.license = r.licence;
      renderDrawer();
    }
    toast(r.licence.status === "found" ? `Found on ${r.licence.site_name}: ${r.licence.licence}` : r.licence.note || "Checked");
    if (state.view === "licences") renderLicences();
  } catch (err) {
    if (b) { b.disabled = false; b.textContent = "Find the licence"; }
    toast(err.message);
  }
}

function renderDrawer() {
  const { asset: a, segments, result: r, hit } = state.detail;
  const d = $("#drawer");
  d.hidden = false;
  const facts = [["Type", `${KIND_ONE[a.kind] || a.kind} (${a.ext})`]];
  if (a.duration) facts.push(["Length", tc(a.duration)]);
  if (a.width) facts.push(["Size", `${a.width}×${a.height}${a.fps ? `, ${a.fps} fps` : ""}`]);
  if (a.green_screen) facts.push(["Keying", "Green screen detected"]);
  if (a.has_alpha) facts.push(["Alpha", "Transparent background"]);
  if (a.captured_at) facts.push([a.captured_src === "file date" ? "File date" : "Recorded", `${fmtWhen(a.captured_at)}${a.captured_src && a.captured_src !== "file date" ? ` (from ${a.captured_src})` : ""}`]);
  if (a.device) facts.push(["Camera", a.device]);
  facts.push(["Described by", a.captioned_by ? a.captioned_by.split("/").pop() : "Local analysis only"]);
  facts.push(["File", a.path]);
  const seg = segments.find((s) => hit && s.id === hit.segment_id) || segments.find((s) => s.caption) || segments[0] || null;
  const shots = a.kind === "video" && segments.length > 1
    ? `<div class="d-section"><h3>${segments.length} shots</h3><div class="shots">${segments.map((s) => `<button class="shot ${seg && s.id === seg.id ? "on" : ""}" data-sid="${s.id}" title="${esc(s.caption || "")}"><div class="thumb">${s.thumb_url ? `<img src="${s.thumb_url}" alt="" loading="lazy">` : ""}<span class="pill">${tc(s.start)}</span></div></button>`).join("")}</div></div>`
    : "";
  d.innerHTML = `<div class="drawer-top drag"><span class="label"><i class="sq"></i>${esc(KIND_ONE[a.kind] || a.kind)}</span><button class="icon-btn no-drag" id="dClose" aria-label="Close">${ICON.close}</button></div>
    <div class="drawer-body">
      ${screenHTML(a, r, hit)}
      <h2 class="d-title">${esc(a.name)}</h2>
      ${describeHTML(a, seg)}
      <div class="actions">
        <button class="btn btn-primary" id="dReveal">Show in folder</button>
        <button class="btn btn-ghost" id="dLike">Good pick</button>
        <button class="btn btn-danger" id="dNot">Not this</button>
        ${hit ? '<button class="btn btn-ghost" id="dSimilar">Find similar</button>' : ""}
      </div>
      ${licenceHTML(a, state.detail.source_guess)}
      ${shots}
      <div class="d-section"><h3>Tags</h3><div class="tags">${(a.tags || []).slice(0, 24).map((t) => `<button class="tag" data-tag="${esc(t)}">${esc(t)}</button>`).join("")}</div></div>
      ${a.transcript ? `<div class="d-section"><h3>Speech</h3><p class="transcript">${esc(a.transcript)}</p></div>` : ""}
      <dl class="facts">${facts.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}${a.lat != null ? `<dt>Location</dt><dd>${a.lat.toFixed(5)}, ${a.lon.toFixed(5)} <a class="map-link" href="https://www.openstreetmap.org/?mlat=${a.lat}&mlon=${a.lon}#map=16/${a.lat}/${a.lon}" target="_blank" rel="noopener">Open map</a></dd>` : ""}</dl>
    </div>`;
  wirePlayer(hit);
  $("#dClose").onclick = closeDrawer;
  $("#dLike").onclick = () => feedback("like", "Noted. Picks like this will rank higher.");
  $("#dNot").onclick = notThis;
  $("#dReveal").onclick = () => {
    feedback("use");
    api(`/api/assets/${a.id}/reveal`, { method: "POST" }).catch((e) => toast(e.message));
  };
  const sim = $("#dSimilar");
  if (sim) sim.onclick = () => findSimilar(state.detail.hit.segment_id, a.name);
  $("#dRecheck")?.addEventListener("click", () => recheckLicence(a.id));
  $("#dCopyCredit")?.addEventListener("click", () => copyText(a.license.credit, "Credit copied"));
  $$(".tag", d).forEach((b) => b.addEventListener("click", () => searchFor(b.dataset.tag)));
  $$(".shot", d).forEach((b) => b.addEventListener("click", () => {
    const sg = segments.find((s) => s.id === Number(b.dataset.sid));
    state.detail.hit = { segment_id: sg.id, start: sg.start, end: sg.end, caption: sg.caption, thumb: sg.thumb_url };
    $$(".shot", d).forEach((x) => x.classList.toggle("on", x === b));
    $("#dDesc").outerHTML = describeHTML(a, sg);
    wirePlayer(state.detail.hit);
  }));
}

function wirePlayer(hit) {
  const p = $("#player");
  const live = $("#liveTc");
  if (!p) return;
  const start = hit?.start || 0;
  const end = hit?.end || 0;
  let loop = state.detail.asset.kind === "video" && end > start && !hit?.jump;
  const seek = () => { try { p.currentTime = start; } catch (_) {} };
  if (p.readyState >= 1) seek();
  else p.addEventListener("loadedmetadata", seek, { once: true });
  p.ontimeupdate = () => {
    if (live) live.textContent = tc(p.currentTime);
    if (loop && p.currentTime >= end) p.currentTime = start;
  };
  p.onseeking = () => { if (loop && (p.currentTime < start - 0.2 || p.currentTime > end + 0.2)) loop = false; };
  if (state.detail.asset.kind === "video") p.play().catch(() => {});
}

function closeDrawer() {
  $("#player")?.pause();
  const d = $("#drawer");
  d.hidden = true;
  d.innerHTML = "";
  state.detail = null;
  $$(".card[aria-selected]").forEach((c) => c.removeAttribute("aria-selected"));
}

async function feedback(action, msg) {
  const d = state.detail;
  if (!d) return;
  await api("/api/feedback", { method: "POST", body: { action, asset_id: d.asset.id, segment_id: d.hit?.segment_id, query: state.q } }).catch(() => {});
  if (msg) toast(msg);
}

async function notThis() {
  await feedback("dismiss");
  const id = state.detail.asset.id;
  closeDrawer();
  if (state.view === "search") {
    state.results = state.results.filter((r) => r.asset_id !== id);
    renderSearch();
  }
  toast("Hidden. It will rank lower next time.");
}

async function findSimilar(sid, name) {
  try {
    const data = await api(`/api/similar/${sid}?limit=${state.topN}`);
    closeDrawer();
    state.view = "search";
    state.similar = { sid, name };
    state.q = name;
    $("#q").value = "";
    state.tab = "all";
    state.results = data.results.slice(0, state.topN);
    state.plan = null;
    setNav();
    renderSearch({ took_ms: 0 });
  } catch (err) {
    toast(err.message);
  }
}

function renderStatus(st) {
  const p = st.indexer;
  const n = st.nemotron;
  const el = $("#status");
  const total = p.done + p.failed + p.queued;
  const busy = p.state !== "idle";
  const mode = n.enabled ? "on" : n.privacy_mode === "local" ? "local" : "off";
  const label = n.enabled ? "Nemotron on" : n.privacy_mode === "local" ? "Local only" : "Nemotron off";
  const nf = state.folders.length;
  el.className = `status ${mode}`;
  if (busy) {
    const pct = total ? Math.round(((p.done + p.failed) / total) * 100) : 0;
    const cur = p.state === "scanning" ? "Looking for new files" : p.current || "Looking for new files";
    el.innerHTML = `<div class="st-top"><span class="st-label"><i class="sq pulse"></i>${p.state === "scanning" ? "Scanning" : "Indexing"}</span>${total ? `<span class="st-count">${Math.min(p.done + p.failed + 1, total)} / ${total}</span>` : ""}</div><span class="st-file" title="${esc(cur)}">${esc(cur)}</span><span class="st-bar"><i style="width:${pct}%"></i></span>`;
  } else {
    const sub = !nf ? "Add a folder to start" : `${st.library.indexed} assets in ${nf} folder${nf === 1 ? "" : "s"}${mode === "off" ? ", no API key" : ""}`;
    el.innerHTML = `<span class="st-label"><i class="sq"></i>${label}</span><span class="st-sub">${esc(sub)}</span>`;
  }
  const dot = $("#railDot");
  dot.className = `rail-dot ${mode}${busy ? " busy" : ""}`;
  dot.title = busy ? "Indexing" : label;
  for (const k of KINDS) {
    const c = $(`[data-count="${k}"]`);
    if (c) c.textContent = st.library.kinds[k] || "";
  }
  const banner = $("#banner");
  if (p.blocker) {
    banner.hidden = false;
    banner.innerHTML = `<span><b>${esc(p.blocker.message)}</b> ${p.blocker.files || ""} files are waiting. Install it with <code>winget install --id Gyan.FFmpeg -e --source winget</code>.</span><button class="btn btn-ghost btn-sm" id="recheck">Check again</button>`;
    $("#recheck").onclick = async () => {
      const r = await api("/api/rescan", { method: "POST" }).catch((e) => toast(e.message));
      const st2 = await refreshStatus(true);
      toast(st2?.indexer?.blocker ? "FFmpeg still not found. Install it, then press Check again." : `FFmpeg found. Indexing ${r?.queued ?? 0} files.`);
    };
  } else {
    banner.hidden = true;
  }
}

async function rescanAll() {
  try {
    const r = await api("/api/rescan", { method: "POST" });
    toast(r.queued ? `Rescanning: ${r.queued} new or changed files` : "Everything is up to date");
    await refreshStatus(true);
  } catch (err) {
    toast(err.message);
  }
}

async function refreshStatus(withFolders = false) {
  try {
    const st = await api("/api/status");
    state.status = st;
    const changed = st.library.indexed !== state.lastIndexed;
    if (changed || withFolders || !state.folders.length) state.folders = (await api("/api/folders")).folders;
    renderStatus(st);
    if (changed && state.lastIndexed !== -1 && !state.detail) {
      if (state.view === "home") renderHome();
      else if (state.view === "kind") renderKind();
    }
    state.lastIndexed = st.library.indexed;
    return st;
  } catch (err) {
    $("#status").className = "status off";
    $("#status").innerHTML = `<span class="st-label"><i class="sq"></i>Engine not responding</span><span class="st-sub">Retrying every few seconds</span>`;
    $("#railDot").className = "rail-dot";
    return null;
  }
}

async function poll() {
  const st = await refreshStatus();
  const busy = st && (st.indexer.state !== "idle" || st.embedder.state === "loading");
  setTimeout(poll, busy ? 1200 : 5000);
}

function wireDesktop() {
  if (!desk) return;
  $("#traffic").hidden = false;
  if (desk.openLog) {
    $("#railLog").hidden = false;
    $("#railLog").addEventListener("click", () => desk.openLog());
  }
  $("#tlClose").addEventListener("click", () => desk.close());
  $("#tlMin").addEventListener("click", () => desk.minimize());
  $("#tlMax").addEventListener("click", () => desk.toggleMaximize());
  desk.onWindowState?.((s) => $("#app").classList.toggle("blurred", s && s.focused === false));
  $$(".drag").forEach((el) => el.addEventListener("dblclick", (e) => {
    if (e.target.closest("button, input, form, .no-drag")) return;
    desk.toggleMaximize();
  }));
}

function wire() {
  $("#searchForm").addEventListener("submit", (e) => { e.preventDefault(); clearTimeout(searchTimer); state.tab = "all"; runSearch(); });
  $("#q").addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => { state.tab = "all"; runSearch(); }, 350);
  });
  $$(".nav-item[data-view]").forEach((b) => b.addEventListener("click", () => go(b.dataset.view, b.dataset.kind || null)));
  $("#navShortcuts").addEventListener("click", () => $("#shortcuts").showModal());
  $("#topAdd").addEventListener("click", addFolderFlow);
  $(".logo").addEventListener("click", () => go("home"));
  $("#clearSearch").addEventListener("click", () => { $("#q").value = ""; go("home"); });
  $("#railRescan").addEventListener("click", rescanAll);
  document.addEventListener("keydown", (e) => {
    const typing = ["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName);
    if (e.key === "/" && !typing) { e.preventDefault(); $("#q").focus(); $("#q").select(); }
    else if (e.key === "Escape") {
      if (state.detail) closeDrawer();
      else if (typing && $("#q").value) { $("#q").value = ""; go("home"); }
      else if (typing) document.activeElement.blur();
    }
  });
  wireDesktop();
}

async function init() {
  wire();
  setNav();
  try {
    state.cfg = await api("/api/settings");
    if (state.cfg.top_results) state.topN = Number(state.cfg.top_results);
  } catch (_) {}
  await refreshStatus(true);
  render();
  setTimeout(poll, 1500);
}

init();
