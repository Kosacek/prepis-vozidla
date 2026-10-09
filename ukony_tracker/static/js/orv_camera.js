// Stream lifetime and in-memory resizing, independent of batch processing.
(function () {
  window.OrvCamera = function (root, addPhoto, notice) {
    const video = root.querySelector('#orv-video');
    const view = root.querySelector('#orv-viewfinder');
    const shutter = root.querySelector('#orv-shutter');
    const fallback = root.querySelector('#orv-fallback');
    const startButton = root.querySelector('#orv-camera');
    let stream, opening, generation = 0, dead = false, capturing = false;
    function release(s) { if (s) s.getTracks().forEach(t => t.stop()); }
    function stop() {
      generation++;
      release(stream);
      stream = null;
      video.pause();
      video.srcObject = null;
      view.hidden = shutter.hidden = true;
      shutter.disabled = true;
      startButton.hidden = false;
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
        } catch (_) {
          if (dead || generation !== gen) return;
          stop();
          fallback.hidden = false;
          notice('Kamera není dostupná. Použijte „Vyfotit techničák“ nebo galerii.');
        }
      })();
      try { await opening; } finally { opening = null; startButton.disabled = false; }
    }
    async function jpeg(source, width, height, aspect) {
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
      return new Promise((resolve, reject) => canvas.toBlob(
        blob => blob ? resolve(blob) : reject(Error('image')), 'image/jpeg', .85));
    }
    async function capture() {
      if (capturing || !stream || !video.videoWidth) return;
      capturing = true;
      const gen = generation;
      try {
        const aspect = view.clientWidth / view.clientHeight || 16 / 9;
        const blob = await jpeg(video, video.videoWidth, video.videoHeight, aspect);
        if (!dead && gen === generation) addPhoto(blob);
      } catch (_) { notice('Fotku se nepodařilo pořídit. Zkuste to znovu.'); }
      finally { capturing = false; }
    }
    function onVisibility() { if (document.hidden) stop(); }
    startButton.addEventListener('click', start);
    shutter.addEventListener('click', capture);
    document.addEventListener('visibilitychange', onVisibility);
    window.addEventListener('pagehide', stop);
    return {start, stop, jpeg, destroy: function () {
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
      await img.decode();
      return await camera.jpeg(img, img.naturalWidth, img.naturalHeight);
    } catch (_) { return file; }
    finally { URL.revokeObjectURL(url); }
  };
})();
