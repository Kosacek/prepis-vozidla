// Poslední report techničáku, uložený v zařízení — dá se k němu vrátit i po
// zavření okna. Fotky jen jako malé náhledy (původní fotky se nikam neukládají).
(function (root) {
  const KEY = 'ukony_orv_posledni';
  const MAX_AGE_MS = 14 * 24 * 3600 * 1000;
  const THUMB_PX = 240;

  function thumb(photo) {
    if (photo.thumb) return Promise.resolve(photo.thumb);
    if (!photo.url || typeof Image === 'undefined') return Promise.resolve('');
    return new Promise(resolve => {
      const img = new Image();
      img.onload = () => {
        try {
          const scale = Math.min(1, THUMB_PX / Math.max(img.naturalWidth, img.naturalHeight));
          const canvas = document.createElement('canvas');
          canvas.width = Math.round(img.naturalWidth * scale);
          canvas.height = Math.round(img.naturalHeight * scale);
          canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
          resolve(canvas.toDataURL('image/jpeg', 0.7));
        } catch (_) { resolve(''); }
      };
      img.onerror = () => resolve('');
      img.src = photo.url;
    });
  }

  function write(record) {
    try { root.localStorage.setItem(KEY, JSON.stringify(record)); return true; } catch (_) { return false; }
  }

  async function save(photos) {
    const done = photos.filter(p => p.result);
    if (!done.length) return;
    for (const p of done) p.thumb = await thumb(p);
    const items = done.map(p => ({thumb: p.thumb || '', result: p.result, upraveno: !!p.upraveno}));
    const at = Date.now();
    // Plné úložiště → aspoň výsledky bez náhledů.
    if (!write({at, items})) write({at, items: items.map(i => ({...i, thumb: ''}))});
  }

  function load(now = Date.now()) {
    try {
      const record = JSON.parse(root.localStorage.getItem(KEY) || 'null');
      if (!record || !Array.isArray(record.items) || !record.items.length) return null;
      if (typeof record.at !== 'number' || now - record.at > MAX_AGE_MS) return null;
      if (!record.items.every(i => i && i.result && typeof i.result.stav === 'string')) return null;
      return record;
    } catch (_) { return null; }
  }

  function label(at, now = new Date()) {
    const d = new Date(at);
    const time = d.getHours() + ':' + String(d.getMinutes()).padStart(2, '0');
    const sameDay = d.toDateString() === now.toDateString();
    return (sameDay ? 'Dnes' : d.getDate() + '. ' + (d.getMonth() + 1) + '.') + ' ' + time;
  }

  const api = {KEY, save, load, label, thumb};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.OrvLast = api;
})(typeof window !== 'undefined' ? window : globalThis);
