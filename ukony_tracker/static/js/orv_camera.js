// Stream lifetime and in-memory resizing, independent of batch processing.
(function () {
  window.OrvCamera = function (root, addPhoto, notice) {
    const video = root.querySelector('#orv-video');
    const view = root.querySelector('#orv-viewfinder');
    const shutter = root.querySelector('#orv-shutter');
    const fallback = root.querySelector('#orv-fallback');
    const startButton = root.querySelector('#orv-camera');
    const autoButton = root.querySelector('#orv-auto');
    const debugLine = root.querySelector('#orv-debug');
    let stream, opening, generation = 0, dead = false, capturing = false, lastInfo = null;
    // Hands-free capture (2.10): photographs a card held still in the guide.
    let debug = false;
    try { debug = new URLSearchParams(location.search).get('ladeni') === '1'; } catch (_) {}
    let autoOn = true;
    try { autoOn = localStorage.getItem('ukony_orv_auto') !== '0'; } catch (_) {}
    const auto = window.OrvAuto && window.OrvAutoCore ? window.OrvAuto.create({
      video, crop: visibleCrop, debug, jsqrUrl: (root.dataset || {}).jsqr || null,
      canFire: () => !!stream && !capturing && !shutter.hidden && !shutter.disabled,
      onTick: paint,
      onFire: info => capture({zachyt: info.zachyt, auto: true}),
    }) : null;
    function visibleCrop() {
      // The viewfinder shows the video with object-fit: cover; photos and the
      // auto-capture look at exactly that part.
      const aspect = view.clientWidth / view.clientHeight || 16 / 9;
      const w = video.videoWidth, h = video.videoHeight;
      const cw = Math.min(w, h * aspect), ch = Math.min(h, w / aspect);
      return {x: (w - cw) / 2, y: (h - ch) / 2, w: cw, h: ch};
    }
    function paint(info) {
      lastInfo = info;
      if (view.dataset) view.dataset.auto = info.locked ? 'lock' : '';
      if (view.style && view.style.setProperty) view.style.setProperty('--orv-hold', String(info.progress || 0));
      if (debug && debugLine) {
        debugLine.hidden = false;
        debugLine.textContent = window.OrvAuto.zachyt(info.armed ? 'ceka' : 'hotovo', info) +
          (info.qr ? ' qr=' + info.qr : '') + ' ' + auto.qrKind();
      }
    }
    function showAuto() {
      if (!autoButton) return;
      autoButton.hidden = !auto || !stream;
      if (auto) autoButton.setAttribute('aria-pressed', autoOn ? 'true' : 'false');
    }
    function toggleAuto() {
      if (!auto) return;
      autoOn = !autoOn;
      try { localStorage.setItem('ukony_orv_auto', autoOn ? '1' : '0'); } catch (_) {}
      auto.setEnabled(autoOn);
      if (!autoOn && view.dataset) view.dataset.auto = '';
      showAuto();
    }
    function flash(isAuto) {
      if (!view.classList) return;
      view.classList.remove('is-shot');
      void view.offsetWidth; // restart the animation
      view.classList.add('is-shot');
      if (isAuto && typeof navigator !== 'undefined' && navigator.vibrate) {
        try { navigator.vibrate(20); } catch (_) {}
      }
    }
    function release(s) { if (s) s.getTracks().forEach(t => t.stop()); }
    function stop() {
      generation++;
      if (auto) auto.stop();
      release(stream);
      stream = null;
      video.pause();
      video.srcObject = null;
      view.hidden = shutter.hidden = true;
      shutter.disabled = true;
      startButton.hidden = false;
      if (view.dataset) view.dataset.auto = '';
      showAuto();
    }
    async function start() {
      if (dead || stream || opening) return;
      const gen = generation;
      startButton.disabled = true;
      opening = (async function () {
        try {
          if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) throw Error('camera');
          const s = await navigator.mediaDevices.getUserMedia({audio: false, video: {
            facingMode: {ideal: 'environment'}, width: {ideal: 1920}, height: {ideal: 1080}
          }});
          if (dead || generation !== gen || document.hidden) { release(s); return; }
          stream = s;
          video.srcObject = s;
          view.hidden = false;
          await video.play();
          if (dead || generation !== gen) return;
          fallback.hidden = startButton.hidden = true;
          shutter.hidden = false;
          shutter.disabled = false;
          notice('');
          if (auto) { auto.setEnabled(autoOn); auto.start(); }
          showAuto();
        } catch (_) {
          if (dead || generation !== gen) return;
          stop();
          fallback.hidden = false;
          notice('Kamera není dostupná. Použijte „Vyfotit techničák“ nebo galerii.');
        }
      })();
      try { await opening; } finally { opening = null; startButton.disabled = false; }
    }
    function frameCanvas(source, width, height, aspect) {
      // Match object-fit:cover in the landscape viewfinder, including a phone
      // whose camera supplies a portrait frame. Gallery imports keep all pixels.
      const cropWidth = aspect ? Math.min(width, height * aspect) : width;
      const cropHeight = aspect ? Math.min(height, width / aspect) : height;
      const scale = Math.min(1, 1800 / Math.max(cropWidth, cropHeight));
      const canvas = document.createElement('canvas');
      canvas.width = Math.max(1, Math.round(cropWidth * scale));
      canvas.height = Math.max(1, Math.round(cropHeight * scale));
      canvas.getContext('2d').drawImage(source, (width - cropWidth) / 2, (height - cropHeight) / 2,
        cropWidth, cropHeight, 0, 0, canvas.width, canvas.height);
      return canvas;
    }
    function toJpeg(canvas) {
      return new Promise((resolve, reject) => canvas.toBlob(
        blob => blob ? resolve(blob) : reject(Error('image')), 'image/jpeg', .85));
    }
    async function jpeg(source, width, height, aspect) {
      return toJpeg(frameCanvas(source, width, height, aspect));
    }
    // meta: {zachyt, auto} from the auto-capture, null for the shutter. The QR
    // sent with the photo is read from the photo itself, never from an earlier
    // frame, so it cannot belong to another card.
    async function capture(meta) {
      const isAuto = !!(meta && meta.auto);
      if (capturing || !stream || !video.videoWidth) { if (isAuto && auto) auto.release(); return; }
      capturing = true;
      const gen = generation;
      const zachyt = meta ? meta.zachyt : (window.OrvAuto ? window.OrvAuto.zachyt('rucne', lastInfo) : 'rucne');
      let id = 0, qr = null;
      try {
        const aspect = view.clientWidth / view.clientHeight || 16 / 9;
        const canvas = frameCanvas(video, video.videoWidth, video.videoHeight, aspect);
        if (auto) qr = await auto.verify(canvas, canvas.width, canvas.height);
        const blob = await toJpeg(canvas);
        if (!dead && gen === generation) {
          id = addPhoto(blob, {qr, zachyt, auto: isAuto}) || 0;
          if (id) flash(isAuto);
        }
      } catch (_) { notice('Fotku se nepodařilo pořídit. Zkuste to znovu.'); }
      finally {
        capturing = false;
        // Tell the auto-capture which card is now in the batch.
        if (auto && isAuto) { if (id) auto.commit(id); else auto.release(); }
        else if (auto && id) auto.manual(id, qr);
      }
    }
    function onVisibility() { if (document.hidden) stop(); }
    startButton.addEventListener('click', start);
    shutter.addEventListener('click', () => capture(null));
    if (autoButton) autoButton.addEventListener('click', toggleAuto);
    document.addEventListener('visibilitychange', onVisibility);
    window.addEventListener('pagehide', stop);
    return {start, stop, jpeg, forget: id => { if (auto) auto.forget(id); }, destroy: function () {
      dead = true;
      stop();
      document.removeEventListener('visibilitychange', onVisibility);
      window.removeEventListener('pagehide', stop);
    }};
  };
  window.OrvFile = async function (file, camera) {
    // Keep HEIC when the browser cannot decode it; server converts in memory.
    const url = URL.createObjectURL(file);
    try {
      const img = new Image();
      img.src = url;
      // A decode that never settles must not lock the gallery: after 6 s send
      // the original file, the server converts it anyway.
      const late = new Promise((_, reject) => setTimeout(() => reject(Error('slow')), 6000));
      await Promise.race([img.decode(), late]);
      return await Promise.race([camera.jpeg(img, img.naturalWidth, img.naturalHeight), late]);
    } catch (_) { return file; }
    finally { URL.revokeObjectURL(url); }
  };
})();
