const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');

function cameraEnv(getUserMedia, options = {}) {
  const elements = new Map();
  const events = {};
  const captured = [];
  const notices = [];
  let stopped = 0;
  const stream = {getTracks: () => [{stop: () => stopped++}]};
  function element(id) {
    if (!elements.has(id)) elements.set(id, {hidden: true, disabled: false, handlers: {},
      videoWidth: 3840, videoHeight: 2160, pause() {}, play: async () => {},
      setAttribute(name, value) { this[name] = value; },
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
    removeEventListener: name => { delete events[name]; }, ...options.window};
  vm.runInNewContext(fs.readFileSync(require.resolve('../static/js/orv_camera.js'), 'utf8'), {
    window, document, navigator: {mediaDevices: {getUserMedia}}, URL, Image: function () {},
    fetch: options.fetch
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

test('phone cameras require a quad and send at most one idle diagnostic per three seconds', async () => {
  let settings;
  const requests = [];
  const driver = {start() {}, stop() {}, setEnabled() {}};
  const window = {matchMedia: () => ({matches: true}), OrvAutoCore: {},
    OrvAuto: {create: options => { settings = options; return driver; }}};
  const fetch = async (url, init) => requests.push({url, method: init.method, body: JSON.parse(init.body)});
  const e = cameraEnv(async () => e.stream, {window, fetch});
  await e.camera.start();
  assert.equal(settings.params.requireQuad, true);
  const sample = {motion: 20, sharp: 4083, edges: 0.2, quad: true, stable: true, qr: null, reason: 'hold'};
  for (const t of [0, 125, 2999, 3000, 3001, 5999]) settings.onTick({...sample, t});
  assert.deepEqual(requests, [{url: '/ukony/orv-sken/log', method: 'POST',
    body: {m: 20, s: 4083, e: 0.2, quad: 1, stable: 1, qr: null, reason: 'hold'}}]);
  settings.onTick({...sample, t: 6000, fire: true});
  settings.onTick({...sample, t: 6500});
  assert.equal(requests.length, 1);
  settings.onTick({...sample, t: 9000, reason: 'captured'});
  assert.equal(requests.length, 2);
  assert.equal(requests[1].body.reason, 'captured');
  e.camera.destroy();
});
