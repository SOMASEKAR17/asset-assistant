const stop = new Set('a an the of in on at to for and or with is it something'.split(' '));
export function tokens(text) {
  return String(text || '').normalize('NFKD').replace(/\p{M}/gu, '').toLowerCase().match(/[\p{L}\p{N}]+/gu) || [];
}
function words(value) { return new Set(tokens(value)); }
function score(terms, fields) {
  return fields.reduce((total, [text, weight]) => {
    const set = words(text);
    return total + terms.reduce((sum, term) => sum + (set.has(term) ? weight : 0), 0);
  }, 0);
}
export function search(assets, query = '', kind = '') {
  const terms = [...new Set(tokens(query).filter(t => !stop.has(t)))];
  return assets.filter(a => !kind || a.kind === kind).map(asset => {
    const base = score(terms, [[asset.name, 4], [(asset.tags || []).join(' '), 3], [asset.caption, 2], [asset.transcript, 1]]);
    let best = null, bestScore = 0;
    for (const segment of asset.segments || []) {
      const rank = score(terms, [[segment.caption, 2], [(segment.tags || []).join(' '), 3], [segment.transcript, 1]]);
      if (rank > bestScore) { best = segment; bestScore = rank; }
    }
    return {asset, hit: best, score: base + bestScore};
  }).filter(row => !terms.length || row.score > 0)
    .sort((a, b) => b.score - a.score || a.asset.id - b.asset.id);
}
