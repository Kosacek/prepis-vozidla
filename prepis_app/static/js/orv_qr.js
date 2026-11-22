// Reads the ORV number from the QR code on a 2024+ ORV front.
//
// BarcodeDetector where the browser has it (Android Chrome), otherwise the
// vendored jsQR (iOS Safari has no BarcodeDetector), loaded only when needed.
// Only the card guide is searched, so a second card at the edge of the picture
// cannot answer; two different ORV codes in view answer nothing. The QR is
// ~1.2 cm on the card, so the top-right of the guide is read at FULL
// resolution, alternating with the whole guide. No app DOM: žádosti copies
// this file verbatim. A value counts only when it is exactly an ORV number.
(function (root) {
  const ORV = /^[A-Z]{3}[0-9]{6}$/;
  const GUIDE = {x: 0.08, y: 0.06, w: 0.84, h: 0.88};
  const MAX_NATIVE = 1280, MAX_JSQR = 960;
  const DETECT_MS = 800;   // a detector call that hangs must not hold the reader
  const WAIT_MS = 600;     // verify() waits this long for a live read to finish

  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

  function clean(value) {
    return typeof value === 'string' && ORV.test(value) ? value : null;
  }
  // Part of `crop` (source pixels) covered by `rect` (fractions of it).
  function within(crop, rect) {
    return {x: crop.x + crop.w * rect.x, y: crop.y + crop.h * rect.y, w: crop.w * rect.w, h: crop.h * rect.h};
  }
  // Where the QR sits on a card that fills the guide: right half, upper 60 %.
  function topRight(area) {
    return {x: area.x + area.w * 0.5, y: area.y, w: area.w * 0.5, h: area.h * 0.6};
  }
  // One answer from several codes: all valid ones must agree.
  function single(values) {
    const found = Array.from(new Set(values.map(clean).filter(Boolean)));
    return found.length === 1 ? found[0] : null;
  }
  function loadScript(url) {
    return new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = url;
      script.async = true;
      script.onload = () => resolve();
      script.onerror = () => reject(Error('qr-script'));
      document.head.appendChild(script);
    });
  }

  function create(options) {
    const o = options || {};
    const guide = o.guide || GUIDE;
    let detector = null, jsqr = null, preparing = null, busy = false, turn = 0;
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d', {willReadFrequently: true});

    function kind() { return detector ? 'native' : jsqr ? 'jsqr' : 'none'; }
    function prepare() {
      if (!preparing) preparing = (async function () {
        try {
          if (root.BarcodeDetector) {
            const formats = root.BarcodeDetector.getSupportedFormats
              ? await root.BarcodeDetector.getSupportedFormats() : ['qr_code'];
            if (formats.indexOf('qr_code') >= 0) detector = new root.BarcodeDetector({formats: ['qr_code']});
          }
        } catch (_) { detector = null; }
        if (!detector && o.jsqrUrl) {
          try {
            if (!root.jsQR) await loadScript(o.jsqrUrl);
            jsqr = typeof root.jsQR === 'function' ? root.jsQR : null;
          } catch (_) { jsqr = null; }
        }
        return kind();
      })();
      return preparing;
    }
    // Reads `region` of `source` at its own resolution (capped).
    async function read(source, region) {
      const max = detector ? MAX_NATIVE : MAX_JSQR;
      const scale = Math.min(1, max / Math.max(region.w, region.h));
      canvas.width = Math.max(1, Math.round(region.w * scale));
      canvas.height = Math.max(1, Math.round(region.h * scale));
      ctx.drawImage(source, region.x, region.y, region.w, region.h, 0, 0, canvas.width, canvas.height);
      if (detector) {
        const codes = await Promise.race([detector.detect(canvas), sleep(DETECT_MS).then(() => [])]);
        return single((codes || []).map(code => code && code.rawValue));
      }
      const img = ctx.getImageData(0, 0, canvas.width, canvas.height);
      const code = jsqr(img.data, img.width, img.height, {inversionAttempts: 'dontInvert'});
      return single([code && code.data]);
    }
    // Live frames: one region per call, alternating.
    // -> ORV number, null (nothing readable) or undefined (busy / not ready).
    async function decode(source, crop) {
      if (busy || !(detector || jsqr) || !crop || crop.w < 2 || crop.h < 2) return undefined;
      busy = true;
      try {
        const area = within(crop, guide);
        return await read(source, turn++ % 2 === 0 ? topRight(area) : area);
      } catch (_) {
        return null;
      } finally {
        busy = false;
      }
    }
    // The photo itself (a canvas of exactly what is uploaded): both regions;
    // they must not disagree. This is what binds the QR to the photo.
    async function verify(source, width, height) {
      if (!(detector || jsqr) || width < 2 || height < 2) return null;
      for (let waited = 0; busy; waited += 15) {
        if (waited >= WAIT_MS) return null;
        await sleep(15);
      }
      busy = true;
      try {
        const area = within({x: 0, y: 0, w: width, h: height}, guide);
        return single([await read(source, topRight(area)), await read(source, area)]);
      } catch (_) {
        return null;
      } finally {
        busy = false;
      }
    }
    return {prepare, decode, verify, kind};
  }

  const api = {create, clean, topRight, within, single};
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.OrvQr = api;
})(typeof window !== 'undefined' ? window : globalThis);
