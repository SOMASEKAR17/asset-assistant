async function configure() {
  try {
    const response = await fetch('config.json');
    if (!response.ok) throw new Error('Configuration unavailable');
    const config = await response.json();
    const safe = value => {
      if (!value) return null;
      const url = new URL(value, location.href);
      return url.protocol === 'https:' || (url.origin === location.origin && ['http:', 'https:'].includes(url.protocol)) ? url.href : null;
    };
    const download = document.querySelector('#download');
    if (download && safe(config.downloadUrl)) {
      download.href = safe(config.downloadUrl);
      download.removeAttribute('aria-disabled');
      document.querySelector('#download-note').textContent = 'Download the installer, then open it on Windows. This release is unsigned; Windows may show a publisher warning.';
    }
    const checksum = document.querySelector('#checksum');
    if (checksum && safe(config.checksumUrl)) { checksum.href = safe(config.checksumUrl); checksum.hidden = false; }
    document.querySelectorAll('[data-sandbox]').forEach(a => { if (safe(config.sandboxUrl)) a.href = safe(config.sandboxUrl); });
    const note = document.querySelector('#release-note');
    if (note) note.textContent = `Windows 64-bit · v${config.version} · ${config.downloadSize}`;
  } catch (error) { console.warn(error.message); }
}
configure();
