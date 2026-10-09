const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');

function cameraEnv(getUserMedia) {
  const elements = new Map();
  const events = {};
  const captured = [];
  const notices = [];
  let stopped = 0;
  const stream = {getTracks: () => [{stop: () => stopped++}]};
  function element(id) {
    if (!elements.has(id)) elements.set(id, {hidden: true, disabled: false, handlers: {},
      videoWidth: 3840, videoHeight: 2160, pause() {}, play: async () => {},
      addEventListener(name, fn) { this.handlers[name] = fn; }});
    return elements.get(id);
  }
  const document = {hidden: false,
    addEventListener: (name, fn) => { events[name] = fn; },
    removeEventListener: name => { delete events[name]; },
    createElement() {
      const canvas = {getContext: () => ({drawImage() {}}),
        toBlob(fn, type, quality) { fn({width: canvas.width, height: canvas.height, type, quality}); }};
      return canvas;
    }};
  const window = {addEventListener: (name, fn) => { events[name] = fn; },
    removeEventListener: name => { delete events[name]; }};
  vm.runInNewContext(fs.readFileSync(require.resolve('../static/js/orv_camera.js'), 'utf8'), {
    window, document, navigator: {mediaDevices: {getUserMedia}}, URL, Image: function () {}
  });
  const camera = window.OrvCamera({querySelector: element}, blob => captured.push(blob), text => notices.push(text));
  return {camera, stream, element, events, captured, notices, document, stopped: () => stopped};
}

test('late permission after close releases the stream and repeated start opens once', async () => {
  let resolve, calls = 0;
  const e = cameraEnv(() => { calls++; return new Promise(r => { resolve = r; }); });
  const opening = e.camera.start();
  await e.camera.start();
  e.camera.stop();
  resolve(e.stream);
  await opening;
  assert.equal(calls, 1);
  assert.equal(e.stopped(), 1);
  assert.equal(e.element('#orv-video').srcObject, null);
  assert.equal(e.element('#orv-viewfinder').hidden, true);
  e.camera.destroy();
});

test('permission denial offers both native capture and a reusable camera button', async () => {
  const e = cameraEnv(async () => { throw Error('denied'); });
  await e.camera.start();
  assert.equal(e.element('#orv-fallback').hidden, false);
  assert.equal(e.element('#orv-camera').disabled, false);
  assert.ok(e.notices.at(-1).includes('galerii'));
  e.camera.destroy();
});

test('capture resizes landscape frames and pagehide releases active camera', async () => {
  let e;
  e = cameraEnv(async options => {
    assert.equal(options.video.facingMode.ideal, 'environment');
    return e.stream;
  });
  await e.camera.start();
  await e.element('#orv-shutter').handlers.click();
  assert.deepEqual(e.captured, [{width: 1800, height: 1013, type: 'image/jpeg', quality: .85}]);
  e.events.pagehide();
  assert.equal(e.stopped(), 1);
  assert.equal(e.element('#orv-shutter').hidden, true);
  e.camera.destroy();
  assert.deepEqual(Object.keys(e.events), []);
});

test('leaving the tab releases camera; destroy also invalidates a pending permission', async () => {
  let resolve;
  const e = cameraEnv(() => new Promise(r => { resolve = r; }));
  const opening = e.camera.start();
  e.document.hidden = true;
  e.events.visibilitychange();
  e.camera.destroy();
  resolve(e.stream);
  await opening;
  assert.equal(e.stopped(), 1);
  assert.equal(e.element('#orv-video').srcObject, null);
});

test('portrait camera output is cropped to the landscape viewfinder; gallery stays whole', async () => {
  let e;
  e = cameraEnv(async () => e.stream);
  const video = e.element('#orv-video');
  video.videoWidth = 1080; video.videoHeight = 1920;
  await e.camera.start();
  await e.element('#orv-shutter').handlers.click();
  assert.equal(e.captured[0].width, 1080);
  assert.equal(e.captured[0].height, 608);
  const gallery = await e.camera.jpeg({}, 1080, 1920);
  assert.equal(gallery.width, 1013);
  assert.equal(gallery.height, 1800);
  e.camera.destroy();
});
