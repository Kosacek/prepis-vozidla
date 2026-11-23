/* "Co umí Žádosti" (templates/_novinky.html).
   Phase 1 card -> (3.5 s) -> slides away, sheet underneath.
   data-start: "auto" card then sheet | "hold" card stays (screenshots)
               | "sheet" sheet only, no motion (screenshots).
   data-key present = production: opens once per device (localStorage).
   Absent = preview: always opens. "Verze X ⓘ" = [data-releases-open] opens
   the sheet directly. */
(function () {
  var root = document.getElementById('nv');
  if (!root) return;
  var card = root.querySelector('.nv-card');
  var panel = root.querySelector('.nv-panel');
  var intro = root.querySelector('.nv-intro');
  var sheet = root.querySelector('.nv-sheet');
  var KEY = root.getAttribute('data-key');
  var START = root.getAttribute('data-start') || 'auto';
  var DELAY = 3500;
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var motionStyle = getComputedStyle(root);
  var enterMs = parseFloat(motionStyle.getPropertyValue('--dur-enter'));
  var exitMs = parseFloat(motionStyle.getPropertyValue('--dur-base'));
  var timer = null, opened = false, lockedUntil = 0;

  function seen() { try { return localStorage.getItem(KEY) === '1'; } catch (e) { return true; } }
  function markSeen() { try { localStorage.setItem(KEY, '1'); return true; } catch (e) { return false; } }

  function lockPage(on) { document.documentElement.style.overflow = on ? 'hidden' : ''; }

  // Ignore clicks while the sheet is still sliding in.
  root.addEventListener('click', function (e) {
    if (Date.now() < lockedUntil) { e.preventDefault(); e.stopPropagation(); }
  }, true);

  function toSheet() {
    if (!root.classList.contains('is-open') || root.classList.contains('is-sheet')) return;
    clearTimeout(timer);
    lockedUntil = Date.now() + (reduce ? 0 : enterMs);
    root.classList.add('is-sheet');
    intro.inert = true;
    sheet.inert = false;
    panel.focus({ preventScroll: true });
  }

  function onKey(e) {
    if (e.key === 'Shift' || e.key === 'Control' || e.key === 'Alt' || e.key === 'Meta') return;
    // The page behind has its own shortcuts (Enter steps the form): keep them out.
    e.stopPropagation();
    if (e.key === 'Escape') { e.preventDefault(); close(); }
    else if (e.key === 'Tab') {
      e.preventDefault();
      (sheet.inert ? card : panel).querySelector('.nv-ok').focus();
    }
    else if (e.key === 'Enter' && !(document.activeElement && document.activeElement.tagName === 'BUTTON')) e.preventDefault();
  }
  function open(mode) {
    if (opened) return;
    opened = true;
    root.hidden = false;
    lockPage(true);
    var direct = mode === 'sheet';
    if (direct) root.classList.add('nv-direct');
    if (mode === 'still') root.classList.add('nv-still', 'nv-direct');
    if (mode === 'hold') root.classList.add('nv-hold');
    void root.offsetWidth;
    root.classList.add('is-open');
    window.addEventListener('keydown', onKey, true);
    intro.inert = direct || mode === 'still';
    sheet.inert = !intro.inert;
    if (direct || mode === 'still') {
      root.classList.add('is-sheet');
      panel.focus({ preventScroll: true });
    } else {
      card.focus({ preventScroll: true });
      if (mode !== 'hold') timer = setTimeout(toSheet, DELAY);
    }
  }

  function close() {
    if (!opened) return;
    opened = false;
    clearTimeout(timer);
    lockedUntil = 0;
    root.classList.remove('is-open');
    window.removeEventListener('keydown', onKey, true);
    setTimeout(function () {
      if (opened) return;
      root.hidden = true;
      root.classList.remove('is-sheet', 'nv-direct', 'nv-still', 'nv-hold');
      lockPage(false);
    }, reduce ? 0 : Math.max(enterMs, exitMs));
  }

  root.querySelectorAll('.nv-ok').forEach(function (button) {
    button.addEventListener('click', close);
  });
  root.querySelectorAll('.nv-intro, .nv-sheet').forEach(function (scrim) {
    scrim.addEventListener('click', function (e) {
      if (e.target === scrim) close();
    });
  });

  document.addEventListener('click', function (e) {
    if (e.target.closest && e.target.closest('[data-releases-open]')) {
      e.preventDefault();
      if (opened) return;
      open('sheet');
    }
  });

  // Start.
  var pointers = new Set();
  function startPointer(e) { pointers.add(e.pointerId); }
  function endPointer(e) { pointers.delete(e.pointerId); }
  function clearPointers() { pointers.clear(); }
  function watchPointers(on) {
    var method = on ? 'addEventListener' : 'removeEventListener';
    window[method]('pointerdown', startPointer, true);
    window[method]('pointerup', endPointer, true);
    window[method]('pointercancel', endPointer, true);
    window[method]('blur', clearPointers);
  }
  function autoOpen() {
    if (KEY) {
      if (seen()) { watchPointers(false); return; }
      var dialogOpen = Array.from(document.querySelectorAll('.modal-overlay, .tahak-scrim, dialog[open]'))
        .some(function (dialog) { return getComputedStyle(dialog).display !== 'none'; });
      if (opened || document.hidden || pointers.size || dialogOpen) { setTimeout(autoOpen, 2000); return; }
      watchPointers(false);
      if (!markSeen()) return;
    }
    open(START === 'sheet-still' ? 'still' : START);
  }
  if (KEY && !seen()) watchPointers(true);
  setTimeout(autoOpen, KEY ? 900 : 150);

  window.novinky = { open: open, close: close };
})();
